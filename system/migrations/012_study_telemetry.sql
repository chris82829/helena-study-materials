-- Additive, idempotent V12 telemetry migration. No historical answers are changed.
CREATE TABLE IF NOT EXISTS track_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN
        ('dwell_justification', 'job_expand', 'job_detail', 'chat_turn')),
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    metadata TEXT NOT NULL,
    capture_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE (token_hash, event_id)
);
CREATE INDEX IF NOT EXISTS idx_track_events_session ON track_events(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_track_events_participant ON track_events(token_hash, event_type);
