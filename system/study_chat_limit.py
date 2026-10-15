"""Atomic, consent-bound chat allowance; stores counters/leases, never chat text."""
import secrets
import sqlite3
import time

from privacy import ConsentRequired
from study_metrics import metrics_snapshot

MAX_USER_CHAT_MESSAGES = 3
RESERVATION_SECONDS = 15 * 60
CHAT_LIMIT_MESSAGE = ('Du hast die drei Chatnachrichten für diese Umfrage genutzt. '
                      'Du kannst deine Ergebnisse und den Chat weiter ansehen und die Umfrage fortsetzen.')


class ChatMessageLimit(Exception):
    def __init__(self, usage):
        self.usage = usage
        super().__init__(CHAT_LIMIT_MESSAGE if not usage['pending'] else
                         'Deine verbleibenden Chatnachrichten werden gerade verarbeitet. Bitte warte auf die Antwort.')


class ChatReservationExpired(Exception):
    pass


class StudyChatLimit:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS study_chat_reservations (
                    reservation_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL,
                    expires_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS study_chat_reservations_token
                    ON study_chat_reservations(token_hash);
                CREATE TRIGGER IF NOT EXISTS privacy_revoke_chat_reservations
                AFTER UPDATE OF withdrawn_at ON privacy_consents
                WHEN NEW.withdrawn_at IS NOT NULL
                BEGIN DELETE FROM study_chat_reservations WHERE token_hash=NEW.token_hash; END;
                CREATE TRIGGER IF NOT EXISTS privacy_delete_chat_reservations
                AFTER DELETE ON privacy_consents
                BEGIN DELETE FROM study_chat_reservations WHERE token_hash=OLD.token_hash; END;
            ''')

    @staticmethod
    def snapshot(digest, db):
        metrics = metrics_snapshot(digest, db)
        used = metrics.get('successful_chat_count') or 0
        pending = db.execute('''SELECT count(*) FROM study_chat_reservations
            WHERE token_hash=? AND expires_at>?''', (digest, time.time())).fetchone()[0]
        return dict(limit=MAX_USER_CHAT_MESSAGES, used=used, pending=pending,
                    remaining=max(0, MAX_USER_CHAT_MESSAGES - used - pending))

    def reserve(self, digest, db):
        # BEGIN IMMEDIATE serializes the counter check and reservation across
        # processes and across every search session belonging to this consent.
        if not db.in_transaction:
            db.execute('BEGIN IMMEDIATE')
        consent = db.execute('SELECT purpose, withdrawn_at FROM privacy_consents WHERE token_hash=?', (digest,)).fetchone()
        if not consent or consent[0] != 'study' or consent[1] is not None:
            raise ConsentRequired()
        db.execute('DELETE FROM study_chat_reservations WHERE expires_at<=?', (time.time(),))
        usage = self.snapshot(digest, db)
        if usage['remaining'] == 0:
            raise ChatMessageLimit(usage)
        reservation = secrets.token_urlsafe(24)
        db.execute('INSERT INTO study_chat_reservations VALUES (?, ?, ?)',
                   (reservation, digest, time.time() + RESERVATION_SECONDS))
        return reservation

    @staticmethod
    def finish(digest, reservation, db):
        # Runs in the same transaction as the successful-chat metric and session
        # save. A timed-out/crashed request cannot later spend a replaced slot.
        deleted = db.execute('''DELETE FROM study_chat_reservations
            WHERE token_hash=? AND reservation_id=? AND expires_at>?''',
            (digest, reservation, time.time()))
        if deleted.rowcount != 1:
            raise ChatReservationExpired()

    def release(self, reservation):
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute('DELETE FROM study_chat_reservations WHERE reservation_id=?', (reservation,))
