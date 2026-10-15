"""Production RAM sessions with expiry; legacy SQLite store retained for tests/migration."""
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


class SessionConflict(RuntimeError):
    pass


class SessionStore:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY, state_json TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL)''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, state, before_save=None):
        session_id = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if before_save:
                before_save(db, session_id)
            db.execute('INSERT INTO chat_sessions VALUES (?, ?, 1, ?)',
                       (session_id, json.dumps(state, ensure_ascii=False),
                        datetime.now(timezone.utc).isoformat()))
        return session_id

    def get(self, session_id):
        with self.connect() as db:
            row = db.execute('SELECT state_json, version FROM chat_sessions WHERE id=?',
                             (session_id,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def update(self, session_id, state, version, before_save=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if before_save:
                before_save(db, session_id)
            result = db.execute('''UPDATE chat_sessions SET state_json=?, version=version+1,
                updated_at=? WHERE id=? AND version=?''',
                (json.dumps(state, ensure_ascii=False), datetime.now(timezone.utc).isoformat(),
                 session_id, version))
            if result.rowcount != 1:
                raise SessionConflict('Der Chat wurde parallel geändert. Bitte neu laden.')

    def delete(self, session_id):
        with self.connect() as db:
            return db.execute('DELETE FROM chat_sessions WHERE id=?', (session_id,)).rowcount == 1


class EphemeralSessionStore:
    """Production chat state: RAM only, expires after one hour without activity."""
    def __init__(self, db_path, ttl=3600):
        import threading
        self.db_path, self.ttl = str(db_path), ttl
        self._lock = threading.RLock()
        self._states, self._timers = {}, {}

    def _put(self, session_id, state, version):
        import threading
        if session_id in self._timers:
            self._timers[session_id].cancel()
        # JSON roundtrip prevents callers from mutating the stored snapshot.
        self._states[session_id] = (json.dumps(state, ensure_ascii=False), version)
        timer = threading.Timer(self.ttl, lambda: self._expire(session_id, version))
        timer.daemon = True
        self._timers[session_id] = timer
        timer.start()

    def _expire(self, session_id, version):
        with self._lock:
            if self._states.get(session_id, (None, None))[1] == version:
                self.delete(session_id)

    def create(self, state, before_save=None):
        session_id = secrets.token_urlsafe(32)
        with sqlite3.connect(self.db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            if before_save:
                before_save(db, session_id)
            with self._lock:
                self._put(session_id, state, 1)
        return session_id

    def get(self, session_id):
        with self._lock:
            row = self._states.get(session_id)
            return (json.loads(row[0]), row[1]) if row else None

    def update(self, session_id, state, version, before_save=None):
        with sqlite3.connect(self.db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            if before_save:
                before_save(db, session_id)
            with self._lock:
                if self._states.get(session_id, (None, None))[1] != version:
                    raise SessionConflict('Die Suchsitzung ist abgelaufen oder wurde beendet. Bitte starte neu.')
                self._put(session_id, state, version + 1)

    def delete(self, session_id):
        with self._lock:
            timer = self._timers.pop(session_id, None)
            if timer:
                timer.cancel()
            return self._states.pop(session_id, None) is not None
