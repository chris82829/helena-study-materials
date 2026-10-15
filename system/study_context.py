"""Versioned enrollment context and minimal, consent-bound study diagnostics.

Configuration is copied at enrollment, never retrofitted. Browser layout is a
coarse UI observation, not a device identity. Progress is advanced only by server
handlers after validating the corresponding action.
"""
import csv
import io
import json
import sqlite3
from datetime import datetime, timezone

from privacy import ConsentRequired

CAPTURE_VERSION = 1
VIEWPORT_MOBILE_MAX_PX = 850
STEPS = ('consent', 'profile', 'first_search', 'chat',
         'questionnaire_started', 'questionnaire_completed')
CONTEXT_FIELDS = ('capture_version', 'study_wave', 'recruitment_batch', 'config_revision',
    'questionnaire_version', 'experiment_id', 'viewport_class', 'viewport_class_last',
    'furthest_step_reached', 'enrolled_at', 'updated_at')


def now_utc():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _exists(db, table):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _active(digest, db):
    row = db.execute('SELECT purpose, withdrawn_at FROM privacy_consents WHERE token_hash=?', (digest,)).fetchone()
    return bool(row and row[0] == 'study' and row[1] is None)


def context_snapshot(digest, db):
    if not _exists(db, 'study_participant_context'):
        return {}
    row = db.execute('SELECT metadata_json FROM study_participant_context WHERE token_hash=?', (digest,)).fetchone()
    return json.loads(row[0]) if row else {}


def _safe(value):
    return "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@')) else value


class StudyContext:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS study_context_config (
                    revision INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                    study_wave TEXT NOT NULL CHECK(study_wave IN ('pretest','main')),
                    recruitment_batch TEXT);
                CREATE TABLE IF NOT EXISTS study_participant_context (
                    token_hash TEXT PRIMARY KEY, metadata_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS study_scoring_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash TEXT NOT NULL,
                    recorded_at TEXT NOT NULL, operation_id TEXT NOT NULL,
                    applied_weights TEXT NOT NULL, scoring_version TEXT NOT NULL,
                    assessment_reused INTEGER NOT NULL CHECK(assessment_reused IN (0,1)));
                CREATE INDEX IF NOT EXISTS study_scoring_calls_participant ON study_scoring_calls(token_hash);
            ''')
            db.execute("INSERT OR IGNORE INTO study_context_config VALUES (1, ?, 'pretest', NULL)", (now_utc(),))
            if _exists(db, 'privacy_consents'):
                for table in ('study_participant_context', 'study_scoring_calls'):
                    db.executescript(f'''
                        CREATE TRIGGER IF NOT EXISTS privacy_revoke_{table}
                        AFTER UPDATE OF withdrawn_at ON privacy_consents
                        WHEN NEW.withdrawn_at IS NOT NULL
                        BEGIN DELETE FROM {table} WHERE token_hash=NEW.token_hash; END;
                        CREATE TRIGGER IF NOT EXISTS privacy_delete_{table}
                        AFTER DELETE ON privacy_consents
                        BEGIN DELETE FROM {table} WHERE token_hash=OLD.token_hash; END;
                    ''')

    def config(self, db=None):
        if db is None:
            with sqlite3.connect(self.path) as connection:
                return self.config(connection)
        row = db.execute('SELECT revision,study_wave,recruitment_batch FROM study_context_config ORDER BY revision DESC LIMIT 1').fetchone()
        return dict(revision=row[0], study_wave=row[1], recruitment_batch=row[2])

    def configure(self, study_wave, recruitment_batch, revision):
        if study_wave not in ('pretest', 'main') or type(revision) is not int:
            raise ValueError('Studienphase oder Konfigurationsversion ist ungültig.')
        if recruitment_batch is not None:
            if not isinstance(recruitment_batch, str) or len(recruitment_batch) > 40:
                raise ValueError('Die Versandwelle muss ein Zeitstempel mit Zeitzone sein.')
            try:
                timestamp = datetime.fromisoformat(recruitment_batch.replace('Z', '+00:00'))
                if timestamp.tzinfo is None:
                    raise ValueError()
                recruitment_batch = timestamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
            except ValueError:
                raise ValueError('Die Versandwelle muss ein Zeitstempel mit Zeitzone sein.') from None
        if study_wave == 'main' and recruitment_batch is None:
            raise ValueError('Bitte für die Hauptstudie den Zeitpunkt der Versandwelle angeben.')
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            current = self.config(db)
            if current['revision'] != revision:
                raise ValueError('Die Konfiguration wurde inzwischen geändert. Bitte neu laden.')
            if (current['study_wave'], current['recruitment_batch']) == (study_wave, recruitment_batch):
                return current
            db.execute('INSERT INTO study_context_config VALUES (?, ?, ?, ?)',
                (revision + 1, now_utc(), study_wave, recruitment_batch))
            return self.config(db)

    def enroll(self, digest, db, *, experiment_id, questionnaire_version):
        if not _active(digest, db):
            raise ConsentRequired()
        current = context_snapshot(digest, db)
        if current:
            return current
        config = self.config(db)
        timestamp = now_utc()
        snapshot = dict(capture_version=CAPTURE_VERSION, study_wave=config['study_wave'],
            recruitment_batch=config['recruitment_batch'], config_revision=config['revision'],
            questionnaire_version=questionnaire_version, experiment_id=experiment_id,
            viewport_class=None, viewport_class_last=None, furthest_step_reached='consent',
            enrolled_at=timestamp, updated_at=timestamp)
        db.execute('INSERT INTO study_participant_context VALUES (?, ?)', (digest, json.dumps(snapshot, sort_keys=True)))
        return snapshot

    def _update(self, digest, db, **values):
        if not _active(digest, db):
            raise ConsentRequired()
        current = context_snapshot(digest, db)
        # Old receipts are not silently classified as this wave/version.
        if not current:
            return {}
        current.update(values, updated_at=now_utc())
        db.execute('UPDATE study_participant_context SET metadata_json=? WHERE token_hash=?',
            (json.dumps(current, sort_keys=True), digest))
        return current

    def viewport(self, digest, viewport_class, db):
        if viewport_class not in ('mobile', 'desktop'):
            raise ValueError('Ungültige Darstellungsart.')
        current = context_snapshot(digest, db)
        return self._update(digest, db, viewport_class=current.get('viewport_class') or viewport_class,
                            viewport_class_last=viewport_class)

    def advance(self, digest, step, db):
        if step not in STEPS:
            raise ValueError('Ungültiger Studienschritt.')
        current = context_snapshot(digest, db)
        prior = current.get('furthest_step_reached')
        if prior and STEPS.index(prior) >= STEPS.index(step):
            return current
        return self._update(digest, db, furthest_step_reached=step)

    def record_scoring(self, digest, evidence, operation_id, db):
        if not _active(digest, db):
            return False
        weights = evidence.get('applied_weights')
        if (not isinstance(weights, list) or len(weights) != 6
                or any(type(weight) is not int or not 0 <= weight <= 100 for weight in weights)
                or sum(weights) != 100 or type(evidence.get('assessment_reused')) is not bool
                or not isinstance(evidence.get('scoring_version'), str)
                or not 1 <= len(evidence['scoring_version']) <= 100):
            raise ValueError('Ungültiger Nachweis der tatsächlichen Bewertungsgewichte.')
        db.execute('''INSERT INTO study_scoring_calls
            (token_hash,recorded_at,operation_id,applied_weights,scoring_version,assessment_reused)
            VALUES (?, ?, ?, ?, ?, ?)''', (digest, now_utc(), operation_id,
                json.dumps(weights, separators=(',', ':')), evidence['scoring_version'],
                int(evidence['assessment_reused'])))
        return True


def participant_contexts(db, *, version=None, wave=None):
    """Include consent-only participants: response-only rows hide early dropout."""
    if not _exists(db, 'study_participant_context'):
        return []
    assignments = {}
    if _exists(db, 'study_assignments'):
        assignments = {row[0]: row[1] for row in db.execute('SELECT token_hash,arm FROM study_assignments')}
    result = []
    for digest, identifier, raw in db.execute('''SELECT c.token_hash,p.participation_id,c.metadata_json
        FROM study_participant_context c JOIN privacy_consents p ON c.token_hash=p.token_hash
        WHERE p.purpose='study' AND p.withdrawn_at IS NULL'''):
        snapshot = json.loads(raw)
        if version and snapshot.get('questionnaire_version') != version:
            continue
        if wave and snapshot.get('study_wave') != wave:
            continue
        result.append(dict(participation_id=identifier, study_arm=assignments.get(digest), **snapshot))
    return sorted(result, key=lambda row: row['enrolled_at'])


def dropout_summary(db, *, version=None, wave=None):
    rows = participant_contexts(db, version=version, wave=wave)
    return dict(enrolled_count=len(rows),
        completed_count=sum(row['furthest_step_reached'] == STEPS[-1] for row in rows),
        furthest_steps={step:sum(row['furthest_step_reached'] == step for row in rows) for step in STEPS},
        groups={arm:sum(row['study_arm'] == arm for row in rows) for arm in ('A', 'B', 'C')},
        without_assignment_count=sum(row['study_arm'] is None for row in rows),
        note='Eingewilligte Teilnahmen inklusive Abbrüchen vor dem ersten Fragebogen; noch aktive Teilnahmen sind nicht automatisch Abbrüche.')


def context_csv(db, *, version=None, wave=None):
    output = io.StringIO(newline='')
    fields = ('participation_id', 'study_arm', *CONTEXT_FIELDS)
    writer = csv.DictWriter(output, fieldnames=fields, delimiter=';')
    writer.writeheader()
    for row in participant_contexts(db, version=version, wave=wave):
        writer.writerow({name:_safe(row.get(name)) for name in fields})
    return '\ufeff' + output.getvalue()


def scoring_csv(db, participation_ids=None):
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(('participation_id','recorded_at_utc','operation_id','applied_weights',
                     'scoring_version','assessment_reused'))
    if _exists(db, 'study_scoring_calls'):
        allowed = set(participation_ids) if participation_ids is not None else None
        for row in db.execute('''SELECT p.participation_id,s.recorded_at,s.operation_id,
            s.applied_weights,s.scoring_version,s.assessment_reused FROM study_scoring_calls s
            JOIN privacy_consents p ON p.token_hash=s.token_hash
            WHERE p.purpose='study' AND p.withdrawn_at IS NULL ORDER BY s.id'''):
            if allowed is None or row[0] in allowed:
                writer.writerow([_safe(value) for value in row])
    return '\ufeff' + output.getvalue()


def metadata_analysis(db, *, version=None, wave=None, arm=None):
    """Cohort diagnostics whose denominator includes consent-only participants."""
    from collections import Counter
    from study_metrics import operation_diagnostics
    rows = [row for row in participant_contexts(db, version=version, wave=wave)
            if not arm or row['study_arm'] == arm]
    by_id = {row['participation_id']:row for row in rows}
    active = {digest:identifier for digest, identifier in db.execute(
        "SELECT token_hash,participation_id FROM privacy_consents WHERE purpose='study' AND withdrawn_at IS NULL")
        if identifier in by_id}
    for digest, identifier in active.items():
        by_id[identifier].update(operation_diagnostics(digest, db))
    errors, weights = Counter(), Counter()
    if _exists(db, 'study_operation_events'):
        for digest, code, stage in db.execute('SELECT token_hash,error_code,error_stage FROM study_operation_events WHERE success=0'):
            if digest in active:
                errors[(code, stage)] += 1
    if _exists(db, 'study_scoring_calls'):
        for digest, vector in db.execute('SELECT token_hash,applied_weights FROM study_scoring_calls'):
            if digest in active:
                weights[vector] += 1
    return dict(participants=rows, participant_count=len(rows),
        step_counts={step:sum(row['furthest_step_reached'] == step for row in rows) for step in STEPS},
        wave_counts={name:sum(row['study_wave'] == name for row in rows) for name in ('pretest','main')},
        viewport_counts={name:sum((row['viewport_class'] or 'unknown') == name for row in rows)
                         for name in ('mobile','desktop','unknown')},
        errors=[dict(error_code=code,error_stage=stage,count=count) for (code,stage),count in sorted(errors.items())],
        scoring=dict(call_count=sum(weights.values()),weight_vectors=[dict(applied_weights=json.loads(vector),count=count)
            for vector,count in sorted(weights.items())]),
        notes=['Die Kohorte umfasst auch Einwilligungen ohne Fragebogenantwort. Noch laufende Teilnahmen sind keine bestätigten Abbrüche.',
               'Fehler können behoben worden sein. Ein Fehlerereignis allein ist kein Ausschlussgrund.',
               'Die Darstellungsart basiert auf dem Layout bei 850 CSS-Pixeln; sie ist keine Geräteidentifikation.'])
