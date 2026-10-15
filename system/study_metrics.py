"""Consent-bound operation totals and bounded diagnostic events without input text."""
import json
import sqlite3

METRICS_CAPTURE_VERSION = 2
OPERATION_KINDS = ('search', 'rerank', 'chat')
ERROR_CODES = frozenset({'llm_unavailable', 'embedding_unavailable', 'session_conflict',
    'chat_reservation_expired', 'client_disconnected', 'validation_error', 'internal_error',
    'consent_required', 'http_error'})
ERROR_STAGES = frozenset({'prefilter', 'persona', 'retrieval', 'rerank', 'chat_plan',
    'search', 'chat', 'session_commit', 'unknown'})


def empty_metrics():
    """Old/missing capture is unknown; zero only describes an observed period."""
    return dict(capture_version=0, **{key: None for kind in OPERATION_KINDS for key in
        (f'successful_{kind}_count', f'failed_{kind}_count', f'{kind}_duration_ms')})


def metrics_snapshot(digest, db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='study_operation_metrics'").fetchone():
        return empty_metrics()
    row = db.execute('SELECT metadata_json FROM study_operation_metrics WHERE token_hash=?', (digest,)).fetchone()
    return json.loads(row[0]) if row else empty_metrics()


class StudyOperationMetrics:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS study_operation_metrics (
                token_hash TEXT PRIMARY KEY, metadata_json TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS study_operation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash TEXT NOT NULL,
                timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                operation_id TEXT, operation_kind TEXT NOT NULL, success INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL, error_code TEXT, error_stage TEXT,
                CHECK(success IN (0,1)), CHECK(duration_ms >= 0))''')
            db.execute('CREATE INDEX IF NOT EXISTS study_operation_events_participant ON study_operation_events(token_hash,id)')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='privacy_consents'").fetchone():
                db.executescript('''
                    CREATE TRIGGER IF NOT EXISTS privacy_revoke_operation_metrics
                    AFTER UPDATE OF withdrawn_at ON privacy_consents
                    WHEN NEW.withdrawn_at IS NOT NULL
                    BEGIN DELETE FROM study_operation_metrics WHERE token_hash=NEW.token_hash; END;
                    CREATE TRIGGER IF NOT EXISTS privacy_revoke_operation_events
                    AFTER UPDATE OF withdrawn_at ON privacy_consents
                    WHEN NEW.withdrawn_at IS NOT NULL
                    BEGIN DELETE FROM study_operation_events WHERE token_hash=NEW.token_hash; END;
                    CREATE TRIGGER IF NOT EXISTS privacy_delete_operation_metrics
                    AFTER DELETE ON privacy_consents
                    BEGIN DELETE FROM study_operation_metrics WHERE token_hash=OLD.token_hash; END;
                    CREATE TRIGGER IF NOT EXISTS privacy_delete_operation_events
                    AFTER DELETE ON privacy_consents
                    BEGIN DELETE FROM study_operation_events WHERE token_hash=OLD.token_hash; END;
                ''')

    @staticmethod
    def snapshot(digest, db):
        return metrics_snapshot(digest, db)

    def record_operation(self, digest, kind, success, duration_ms, db, *, error_code=None, error_stage=None, operation_id=None):
        """Count a finished operation inside the caller's transaction.

        A chat that performs a search/rerank also counts as a chat operation when
        its own request finishes. Durations therefore overlap across kinds and
        must never be summed into a total study/session duration. Validation,
        permission and rate-limit rejections before work starts are not counted.
        No commit occurs here; rollback of the enclosing write also rolls back
        the metric. Every finished attempt is counted, including failed retries.
        """
        if kind not in OPERATION_KINDS or type(success) is not bool or type(duration_ms) is not int or duration_ms < 0:
            raise ValueError('Ungültige aggregierte Operationsmetrik.')
        if success:
            error_code = error_stage = None
        else:
            error_code = error_code if error_code in ERROR_CODES else 'internal_error'
            error_stage = error_stage if error_stage in ERROR_STAGES else 'unknown'
        if operation_id is not None and (not isinstance(operation_id, str)
                or len(operation_id) > 64 or not operation_id.isalnum()):
            raise ValueError('Ungültige Operationskennung.')
        if not db.in_transaction:
            db.execute('BEGIN IMMEDIATE')
        consent = db.execute('SELECT purpose, withdrawn_at FROM privacy_consents WHERE token_hash=?', (digest,)).fetchone()
        if not consent or consent[0] != 'study' or consent[1] is not None:
            return False
        metrics = metrics_snapshot(digest, db)
        if metrics['capture_version'] == 0:
            metrics = {key: 0 for key in empty_metrics()}
            metrics['capture_version'] = METRICS_CAPTURE_VERSION
        counter = f'{"successful" if success else "failed"}_{kind}_count'
        metrics[counter] += 1
        metrics[f'{kind}_duration_ms'] += duration_ms
        db.execute('''INSERT INTO study_operation_metrics VALUES (?, ?)
            ON CONFLICT(token_hash) DO UPDATE SET metadata_json=excluded.metadata_json''',
            (digest, json.dumps(metrics, sort_keys=True, separators=(',', ':'))))
        db.execute('''INSERT INTO study_operation_events
            (token_hash, operation_id, operation_kind, success, duration_ms, error_code, error_stage)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (digest, operation_id, kind, int(success), duration_ms, error_code, error_stage))
        return True


def operation_diagnostics(digest, db):
    """Last outcome per operation, not an automatic statistical exclusion rule.

    A recovered failure never marks a participant terminally failed. A final
    failure is only an unrecovered observed attempt; successful prior exposure
    must still be considered by the analysis rather than excluding every error.
    """
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='study_operation_events'").fetchone():
        return dict(capture_available=False, failed_attempt_count=None, last_error_code=None,
                    last_error_stage=None, last_operation_success=None, unrecovered_operation_kinds=[])
    rows = db.execute('SELECT operation_kind, success, error_code, error_stage FROM study_operation_events WHERE token_hash=? ORDER BY id', (digest,)).fetchall()
    if not rows:
        return dict(capture_available=False, failed_attempt_count=None, last_error_code=None,
                    last_error_stage=None, last_operation_success=None, unrecovered_operation_kinds=[])
    latest = {row[0]:bool(row[1]) for row in rows}
    errors = [row for row in rows if not row[1]]
    return dict(capture_available=True, failed_attempt_count=len(errors),
        last_error_code=errors[-1][2] if errors else None,
        last_error_stage=errors[-1][3] if errors else None,
        last_operation_success=bool(rows[-1][1]),
        unrecovered_operation_kinds=[kind for kind in OPERATION_KINDS if latest.get(kind) is False])


def operation_events_csv(db, participation_ids=None):
    import csv
    import io
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(('participation_id','timestamp_utc','operation_id','operation_kind',
                     'success','duration_ms','error_code','error_stage'))
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='study_operation_events'").fetchone():
        allowed = set(participation_ids) if participation_ids is not None else None
        for row in db.execute("""SELECT p.participation_id,e.timestamp,e.operation_id,e.operation_kind,
            e.success,e.duration_ms,e.error_code,e.error_stage FROM study_operation_events e
            JOIN privacy_consents p ON p.token_hash=e.token_hash
            WHERE p.purpose='study' AND p.withdrawn_at IS NULL ORDER BY e.id"""):
            if allowed is None or row[0] in allowed:
                writer.writerow(["'"+value if isinstance(value,str) and value.startswith(('=','+','-','@')) else value for value in row])
    return '\ufeff' + output.getvalue()
