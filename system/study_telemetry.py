"""Consent-bound, bounded interaction observations; never profile or chat text.

Client observations are best-effort and are not quality/relevance judgments.
chat_turn is derived only from the authoritative successful-chat metric in the
same transaction as the successful session commit. Its ordinal spans sessions.
"""
import json
import sqlite3
from pathlib import Path
from typing import Literal

from flask import jsonify, request
from pydantic import Field, model_validator

from privacy import ConsentRequired
from schemas import APIModel
from study_metrics import metrics_snapshot

CAPTURE_VERSION = 1
MAX_EVENTS_PER_PARTICIPANT = 10000
MAX_EVENT_DURATION_MS = 60000


class EventMetadata(APIModel):
    job_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    rank: int = Field(ge=1, le=20)
    duration_ms: int | None = Field(default=None, ge=1, le=MAX_EVENT_DURATION_MS)


class ClientTrackEvent(APIModel):
    session_id: str = Field(min_length=32, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    event_id: str = Field(min_length=16, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    event_type: Literal['dwell_justification', 'job_expand', 'job_detail']
    metadata: EventMetadata

    @model_validator(mode='after')
    def require_duration_only_for_dwell(self):
        if (self.event_type == 'dwell_justification') != (self.metadata.duration_ms is not None):
            raise ValueError('Nur Verweildauer-Ereignisse benötigen eine Dauer.')
        return self


class StudyTelemetry:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.executescript((Path(__file__).parent / 'migrations/012_study_telemetry.sql').read_text())
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='privacy_consents'").fetchone():
                db.executescript('''
                    CREATE TRIGGER IF NOT EXISTS privacy_revoke_track_events
                    AFTER UPDATE OF withdrawn_at ON privacy_consents
                    WHEN NEW.withdrawn_at IS NOT NULL
                    BEGIN DELETE FROM track_events WHERE token_hash=NEW.token_hash; END;
                    CREATE TRIGGER IF NOT EXISTS privacy_delete_track_events
                    AFTER DELETE ON privacy_consents
                    BEGIN DELETE FROM track_events WHERE token_hash=OLD.token_hash; END;
                ''')

    @staticmethod
    def _owns_session(digest, session_id, db):
        consent = db.execute('SELECT purpose, withdrawn_at FROM privacy_consents WHERE token_hash=?', (digest,)).fetchone()
        return bool(consent and consent[0] == 'study' and consent[1] is None
                    and db.execute("SELECT 1 FROM privacy_links WHERE kind='chat' AND record_id=? AND token_hash=?",
                                   (session_id, digest)).fetchone())

    def record_event(self, digest, event, db):
        """Caller checks the current notice and job exposure; write under its lock."""
        if not self._owns_session(digest, event.session_id, db):
            raise ConsentRequired()
        if db.execute('SELECT 1 FROM track_events WHERE token_hash=? AND event_id=?', (digest, event.event_id)).fetchone():
            return 'duplicate'
        count = db.execute('SELECT COUNT(*) FROM track_events WHERE token_hash=? AND event_type<>?',
                           (digest, 'chat_turn')).fetchone()[0]
        if count >= MAX_EVENTS_PER_PARTICIPANT:
            return 'limit'
        db.execute('''INSERT INTO track_events
            (token_hash, session_id, event_id, event_type, metadata, capture_version)
            VALUES (?, ?, ?, ?, ?, ?)''', (digest, event.session_id, event.event_id,
                event.event_type, json.dumps(event.metadata.model_dump(exclude_none=True),
                separators=(',', ':'), sort_keys=True), CAPTURE_VERSION))
        return 'recorded'

    def record_chat_turn(self, digest, session_id, db):
        """After the authoritative metric increment; no separate count source."""
        if not self._owns_session(digest, session_id, db):
            return False
        count = metrics_snapshot(digest, db).get('successful_chat_count')
        if type(count) is not int or count < 1:
            return False
        result = db.execute('''INSERT OR IGNORE INTO track_events
            (token_hash, session_id, event_id, event_type, metadata, capture_version)
            VALUES (?, ?, ?, 'chat_turn', ?, ?)''', (digest, session_id,
                f'chat-turn-{count}', json.dumps({'successful_chat_count': count},
                    separators=(',', ':')), CAPTURE_VERSION))
        return result.rowcount == 1


def register_telemetry(app, privacy, surveys, sessions, request_notice, consent_token, test_arm):
    telemetry = StudyTelemetry(surveys.path)
    app.extensions['study_telemetry'] = telemetry

    @app.post('/api/track_event')
    def track_event():
        event = ClientTrackEvent.model_validate(request.get_json())
        # This is a study endpoint; standalone tests never create study records.
        # Requiring a valid purpose-bound receipt prevents spoofed test headers.
        with surveys.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            digest = privacy.require(consent_token(), request_notice(), db)
            if test_arm():
                return jsonify(status='ignored_test'), 200
            if not telemetry._owns_session(digest, event.session_id, db):
                raise ConsentRequired()
            saved = sessions.get(event.session_id)
            if not saved:
                return jsonify(error={'code': 'telemetry_session_expired', 'message': 'Die Suchsitzung ist beendet.'}), 409
            jobs = saved[0].get('jobs', [])
            # Bind events to an actually displayed ranking, never arbitrary IDs
            # or a client-supplied description that could contain personal text.
            if not any(str(job.get('id')) == event.metadata.job_id for job in jobs):
                return jsonify(error={'code': 'telemetry_job_unknown', 'message': 'Die Stelle gehört nicht zur aktuellen Suche.'}), 400
            rank = event.metadata.rank
            if rank > len(jobs) or str(jobs[rank - 1].get('id')) != event.metadata.job_id:
                return jsonify(error={'code': 'telemetry_ranking_changed',
                    'message': 'Die Rangfolge hat sich inzwischen geändert.'}), 409
            status = telemetry.record_event(digest, event, db)
        return jsonify(status=status), 429 if status == 'limit' else 200

    return telemetry


def telemetry_csv(db, participation_ids=None):
    """Flatten fixed event metadata for an authenticated, filter-bound download.

    None exports all consent-bound records; an empty set exports no records.
    No token hashes, authentication credentials, profiles or chat text leave here.
    """
    import csv
    import io

    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['participation_id', 'session_id', 'event_type', 'timestamp_utc',
                     'job_id', 'displayed_rank', 'duration_ms', 'successful_chat_count',
                     'capture_version'])
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='track_events'").fetchone():
        return '\ufeff' + output.getvalue()
    allowed = set(participation_ids) if participation_ids is not None else None
    rows = db.execute('''SELECT p.participation_id, e.session_id, e.event_type,
        e.timestamp, e.metadata, e.capture_version FROM track_events e
        JOIN privacy_consents p ON p.token_hash=e.token_hash
        WHERE p.purpose='study' AND p.withdrawn_at IS NULL ORDER BY e.id''')
    for participation_id, session_id, kind, timestamp, raw_metadata, capture_version in rows:
        if allowed is not None and participation_id not in allowed:
            continue
        metadata = json.loads(raw_metadata)
        def safe(value):
            return "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@')) else value
        writer.writerow([safe(participation_id), safe(session_id), kind, timestamp,
                         safe(metadata.get('job_id', '')), metadata.get('rank', ''),
                         metadata.get('duration_ms', ''), metadata.get('successful_chat_count', ''),
                         capture_version])
    return '\ufeff' + output.getvalue()
