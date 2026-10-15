"""Versioned consent receipts and withdrawal, without names, IPs or user agents."""
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field
from schemas import APIModel


class ConsentInput(APIModel):
    token: str = Field(pattern=r'^[a-f0-9]{64}$')
    version: str = Field(pattern=r'^[a-f0-9]{64}$')
    accepted: bool
    purpose: Literal['study', 'test_a', 'test_b', 'test_c'] = 'study'


class ConsentRequired(Exception):
    pass


def load_notice(path):
    settings = json.loads(Path(path).read_text())
    required = ('controller', 'retention', 'openai_processing', 'technical_processing')
    configured = all(
        isinstance(settings.get(key), str) and settings[key].strip() for key in required)
    ready = settings.get('approved') is True and configured
    notice = {
        'ready': ready,
        'configuration_complete': configured,
        'title': 'Datenschutz und freiwillige Teilnahme',
        'contact': 'study@example.org',
        'imprint': 'https://example.org/impressum',
        'sections': [
            ['Zweck und Freiwilligkeit', 'HELENA untersucht die Nutzung einer einstellbaren KI-Suchpersönlichkeit im Rahmen der Promotion und weiteren wissenschaftlichen Forschung von Studienleitung zu personalisierten Such- und Empfehlungssystemen, KI-Beratung und deren Nutzbarkeit. Die Teilnahme ist freiwillig. Du kannst ablehnen oder jederzeit ohne Nachteile abbrechen. Die Einwilligung ist die vorgesehene Rechtsgrundlage nach Art. 6 Abs. 1 Buchst. a DSGVO.'],
            ['Verantwortliche Stelle', settings.get('controller') or 'Die verantwortliche Stelle wird vor Freigabe der Studie verbindlich benannt.'],
            ['Welche Daten werden verarbeitet?', 'Die Umfrage erfasst demografische Angaben, dein Suchvorhaben und deine Bewertungen. Zur wissenschaftlichen Nachvollziehbarkeit wird deiner Teilnahme der verwendete technische Systemstand einschließlich Modellversion, Prompt-Variante, Prompt-Revision und Prüfsumme des Basis-Systemprompts zugeordnet; der Prompttext selbst wird nicht in den Umfrageexport aufgenommen und dafür werden keine zusätzlichen Such- oder Chattexte gespeichert. Bei der selbst gestalteten Variante umfasst diese Prüfsumme nicht die anschließend ergänzte persönliche Gestaltung. Zusätzlich wird dokumentiert, ob der feste Top-Berufsberater oder eine selbst gestaltete Persönlichkeit tatsächlich für Suche beziehungsweise Beratung verwendet wurde. Gespeichert werden die erste und letzte verwendete Konfigurationsart, Wechsel zwischen diesen Arten und die Erfassungszeitpunkte; keine individuellen Namen, Eigenschaften oder Freitexthinweise. Historische Teilnahmen können weiterhin eine frühere Vorlagenkennung enthalten. Außerdem werden die Anzahl erfolgreicher und fehlgeschlagener Such-, Neubewertungs- und Chatvorgänge sowie ihre aufsummierten technischen Laufzeiten gespeichert. Diese Zählwerte enthalten keine Texte. Ab diesem Systemstand werden zusätzlich Interaktionsereignisse mit Zeitpunkt und zufälliger Suchsitzungskennung erfasst: die Dauer, während der Stellenbegründungen in einer aktiven Ansicht sichtbar sind, das Öffnen von Begründungen und Stellendetails sowie erfolgreich abgeschlossene Chatnachrichten als Zählwerte. Dazu werden die Stellenkennung, ihre angezeigte Position und bei Betrachtungsereignissen die Dauer gespeichert; keine Inhalte von Suchprofilen oder Chatnachrichten. Die Messung pausiert bei ausgeblendeten Ansichten und Hintergrund-Tabs, ist technisch jedoch nicht lückenlos. Sichtbarkeit belegt nicht, dass du den Text tatsächlich gelesen hast. Ab Fragebogenversion V14 speichern wir außerdem die bei Einwilligung zugeordnete Studienphase (Pretest oder Hauptstudie), den von der Studienleitung eingetragenen Zeitpunkt der Einladungswelle, die grobe Darstellungsklasse (Mobilansicht bis 850 CSS-Pixel oder Desktopansicht) und den weitesten bestätigten Studienschritt. So können wir Abbrüche und Unterschiede zwischen Ansichten beschreiben. Die tatsächlichen sechs Bewertungsgewichte werden je Berechnung protokolliert. Bei technischen Fehlern speichern wir standardisierte Fehlercodes und die betroffene Verarbeitungsphase, keine Fehlermeldungen mit Eingabetext. Der Fragebogen ergänzt eine Selbstauskunft über frühere Teilnahmen, Vertrauen in Empfehlungen und den wahrgenommenen Beratungscharakter. Diese Angaben sind mit deiner Teilnahme-ID verknüpfte pseudonyme Forschungsdaten, keine anonymen Daten; IP-Adressen oder Gerätefingerabdrücke werden dafür nicht erfasst. Diese Ereignisse werden wie die Umfrageantworten der Teilnahme zugeordnet und bei Widerruf oder Löschung ebenfalls entfernt. Persönliche Auswahlfelder bieten „Keine Angabe“. Suchprofil, optionaler Lebenslauftext, KI-Persönlichkeit und Chatnachrichten werden für den Systemtest nur vorübergehend im Arbeitsspeicher verarbeitet. Die Suchsitzung verfällt nach spätestens einer Stunde ohne neue Such- oder Chataktion oder beim Serverneustart; ein Widerruf beendet sie sofort. Suchprofile und Chattexte werden nicht neu in der Studiendatenbank gespeichert. Bitte nutze möglichst das Beispielprofil und gib keine Kontaktdaten, Gesundheitsdaten oder Angaben über andere Personen ein.'],
            ['KI-Verarbeitung', 'Für die Beratung werden Suchprofil, eingegebener Lebenslauftext, Persönlichkeit und relevante Chatnachrichten an die OpenAI-API übermittelt. Demografische Umfrageangaben und Bewertungen werden nicht an das LLM gesendet. ' + (settings.get('openai_processing') or 'Die vertraglichen Bedingungen, Verarbeitungsorte, Übermittlungsgrundlagen, Anbieter-Speicherfristen und Kontoeinstellungen werden vor Freigabe geklärt.')],
            ['Studienvarianten', 'Für diesen Systemtest wirst du zufällig und mit gleicher Wahrscheinlichkeit einer von drei Varianten zugeteilt: A ist das Basissystem ohne wählbare KI-Suchpersönlichkeit. B verwendet einen fest eingestellten Top-Berufsberater. In C gestaltest du die KI-Suchpersönlichkeit auf derselben Berufsberater-Basis selbst. Alle drei Varianten bieten dieselben Such- und Chatfunktionen, sortierte Stellen, Scores und Begründungen auf den Stellenkarten und berücksichtigen dein Suchprofil. Primär wird untersucht, welchen zusätzlichen wahrgenommenen Nutzen und Aufwand die freie Gestaltung gegenüber dem festen Berufsberater verursacht. Bereits vorhandene Zuordnungen aus früheren Studienversionen bleiben mit ihrem bisherigen Funktionsumfang erhalten und werden getrennt gekennzeichnet. Die Zuordnung bleibt für deine Teilnahme erhalten. Variante, Zuordnungszeitpunkt und ein Hinweis auf eine gegebenenfalls bereits vorhandene HELENA-Suchteilnahme werden zusammen mit deinen Antworten für den wissenschaftlichen Vergleich gespeichert.'],
            ['Speicherung und Empfänger', 'Umfrageantworten werden während der Eingabe fortlaufend auf dem Studienserver gespeichert, auch vor dem Abschluss. Wenn du die Umfrage abbrichst, bleiben bereits gespeicherte Teilantworten als unvollständige Teilnahme für die Forschung erhalten, sofern du sie nicht löschen lässt oder deine Einwilligung widerrufst. Ein zufälliger Einwilligungsnachweis ordnet deine Antwort und die Kennung der vorübergehenden Suchsitzung für die Verwaltung der Teilnahme und den Widerruf zu; die Daten sind daher nicht als anonym zu verstehen. Der Nachweis enthält Zeitpunkt und Wortlaut der Einwilligung. ' + (settings.get('retention') or 'Speicherfristen, Löschung, Empfängerkreis und Umgang mit Exporten und Sicherungen werden vor Freigabe festgelegt.')],
            ['Technische Verarbeitung', 'Der Browser speichert für die laufende Teilnahme einen zufälligen Zugangscode und Entwürfe im Sitzungsspeicher. ' + (settings.get('technical_processing') or 'Verbindungsprotokolle, Transportverschlüsselung und technische Speicherfristen werden vor Freigabe dokumentiert.')],
            ['Widerruf und Rechte', 'Über „Datenschutz & Widerruf“ kannst du die Einwilligung jederzeit widerrufen. Die zu dieser Einwilligung gespeicherten Antworten und Suchsitzungen werden dann aus der aktiven Studiendatenbank gelöscht; neue Anfragen werden gesperrt. Bereits erfolgte Verarbeitung bleibt rechtmäßig. Für Exporte, Sicherungen, bereits an OpenAI übermittelte Daten sowie Auskunft, Berichtigung, Löschung, Einschränkung und gegebenenfalls Datenübertragbarkeit wende dich an die Studienleitung. Bewahre deine Teilnahme-ID auf. Wenn du uns diese ID per E-Mail schickst, kann die Studienleitung die zugehörigen Daten finden und deine Löschanfrage bearbeiten.'],
            ['Kontakt und Beschwerde', 'Studienleitung: Studienleitung, study@example.org. Datenschutzkontakt der teilnehmende Hochschule: privacy@example.org. Du kannst dich bei einer Datenschutzaufsichtsbehörde beschweren; für bayerische öffentliche Stellen ist dies der Bayerische Landesbeauftragte für den Datenschutz (www.datenschutz-bayern.de).'],
            ['Empfehlungen', 'Das System bewertet Stellen anhand deines Profils und deiner KI-Suchpersönlichkeit. Es trifft keine Einstellungsentscheidung und übermittelt keine Bewerbung an Arbeitgeber.'],
        ],
        'consent_text': 'Ich habe die Datenschutzhinweise gelesen und willige freiwillig in die dort beschriebene Verarbeitung meiner Angaben für den HELENA-Systemtest und die wissenschaftliche Umfrage einschließlich der OpenAI-Verarbeitung ein. Ich kann meine Einwilligung jederzeit widerrufen.',
    }
    # Operational availability is separate from the wording a participant accepts.
    consent_content = {key: value for key, value in notice.items() if key not in ('ready', 'configuration_complete')}
    notice['version'] = hashlib.sha256(json.dumps(consent_content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return notice


def token_hash(token):
    if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{64}', token):
        raise ConsentRequired()
    return hashlib.sha256(token.encode()).hexdigest()


class PrivacyStore:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS privacy_consents (
                    token_hash TEXT PRIMARY KEY, version TEXT NOT NULL,
                    notice_json TEXT NOT NULL, accepted_at TEXT NOT NULL, withdrawn_at TEXT);
                CREATE TABLE IF NOT EXISTS privacy_consent_history (
                    token_hash TEXT NOT NULL, version TEXT NOT NULL, notice_json TEXT NOT NULL,
                    accepted_at TEXT NOT NULL, PRIMARY KEY(token_hash, version));
                CREATE TABLE IF NOT EXISTS privacy_lifecycle (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS privacy_links (
                    kind TEXT NOT NULL, record_id TEXT NOT NULL, token_hash TEXT NOT NULL,
                    PRIMARY KEY (kind, record_id));
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(privacy_consents)')}
            if 'participation_id' not in columns:
                db.execute('ALTER TABLE privacy_consents ADD COLUMN participation_id TEXT')
            if 'purpose' not in columns:
                db.execute("ALTER TABLE privacy_consents ADD COLUMN purpose TEXT NOT NULL DEFAULT 'study'")
            for (digest,) in db.execute('SELECT token_hash FROM privacy_consents WHERE participation_id IS NULL').fetchall():
                db.execute('UPDATE privacy_consents SET participation_id=? WHERE token_hash=?', (f'HELENA-{uuid.uuid4()}', digest))
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS privacy_participation_id ON privacy_consents(participation_id)')

    def study_status(self, notice, db=None):
        if notice.get('purpose') in ('test_a', 'test_b', 'test_c'):
            configured = notice.get('configuration_complete', False)
            return dict(enabled=configured, closed=False, can_enable=False, updated_at=None)
        if db is None:
            with sqlite3.connect(self.path) as connection:
                return self.study_status(notice, connection)
        lifecycle = dict(db.execute('SELECT key, value FROM privacy_lifecycle'))
        closed = 'closed' in lifecycle
        configured = notice.get('configuration_complete', True)
        enabled = lifecycle.get('participation_enabled', 'true' if notice['ready'] else 'false') == 'true'
        return dict(enabled=enabled and configured and not closed, closed=closed,
                    can_enable=configured and not closed, updated_at=lifecycle.get('participation_updated_at'))

    def set_study_enabled(self, enabled, notice):
        if type(enabled) is not bool:
            raise ValueError('Ungültiger Freigabestatus.')
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            status = self.study_status(notice, db)
            if status['closed']:
                raise ValueError('Die Studie wurde endgültig beendet und kann hier nicht neu gestartet werden.')
            if enabled and not status['can_enable']:
                raise ValueError('Die erforderlichen Angaben in den Datenschutzhinweisen fehlen.')
            db.executemany('INSERT INTO privacy_lifecycle (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           [('participation_enabled', 'true' if enabled else 'false'),
                            ('participation_updated_at', datetime.now(timezone.utc).isoformat())])
            return self.study_status(notice, db)

    def receipt(self, token):
        try:
            digest = token_hash(token)
        except ConsentRequired:
            return None
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT participation_id, accepted_at FROM privacy_consents WHERE token_hash=?', (digest,)).fetchone()
            return {'participation_id': row[0], 'accepted_at': row[1]} if row else None

    def require(self, token, notice, db=None):
        digest = token_hash(token)
        if db is None:
            with sqlite3.connect(self.path) as connection:
                return self.require(token, notice, connection)
        if not self.study_status(notice, db)['enabled']:
            raise ConsentRequired()
        row = db.execute('SELECT version, withdrawn_at, purpose FROM privacy_consents WHERE token_hash=?', (digest,)).fetchone()
        if not row or row[0] != notice['version'] or row[1] or row[2] != notice.get('purpose', 'study'):
            raise ConsentRequired()
        return digest

    def accept(self, body, notice):
        if body.accepted is not True or body.version != notice['version'] or body.purpose != notice.get('purpose', 'study'):
            raise ConsentRequired()
        digest = token_hash(body.token)
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if not self.study_status(notice, db)['enabled']:
                raise ConsentRequired()
            previous = db.execute('SELECT version,notice_json,accepted_at,withdrawn_at,purpose FROM privacy_consents WHERE token_hash=?', (digest,)).fetchone()
            if previous and (previous[3] or previous[4] != body.purpose):
                raise ConsentRequired()
            if previous and previous[0] != notice['version']:
                db.execute('INSERT OR IGNORE INTO privacy_consent_history VALUES (?, ?, ?, ?)', (digest, *previous[:3]))
                db.execute('UPDATE privacy_consents SET version=?,notice_json=?,accepted_at=? WHERE token_hash=?',
                    (notice['version'],json.dumps({**notice,'ready':True},ensure_ascii=False),datetime.now(timezone.utc).isoformat(),digest))
            db.execute('INSERT INTO privacy_consents (token_hash, version, notice_json, accepted_at, participation_id, purpose) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING',
                       (digest, notice['version'], json.dumps({**notice, 'ready': True}, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), f'HELENA-{uuid.uuid4()}', body.purpose))
            self.require(body.token, notice, db)

    def attach(self, token, notice, kind, record_id, db):
        digest = self.require(token, notice, db)
        existing = db.execute('SELECT token_hash FROM privacy_links WHERE kind=? AND record_id=?', (kind, record_id)).fetchone()
        if existing and existing[0] != digest:
            raise ConsentRequired()
        db.execute('INSERT OR IGNORE INTO privacy_links VALUES (?, ?, ?)', (kind, record_id, digest))

    def owns(self, token, kind, record_id):
        digest = token_hash(token)
        with sqlite3.connect(self.path) as db:
            return bool(db.execute('SELECT 1 FROM privacy_links WHERE kind=? AND record_id=? AND token_hash=?',
                                   (kind, record_id, digest)).fetchone())

    def withdraw(self, token):
        return self._withdraw_digest(token_hash(token))

    def _withdraw_digest(self, digest):
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM privacy_consents WHERE token_hash=?', (digest,)).fetchone():
                raise ConsentRequired()
            db.execute('UPDATE privacy_consents SET withdrawn_at=COALESCE(withdrawn_at, ?) WHERE token_hash=?',
                       (datetime.now(timezone.utc).isoformat(), digest))
            chat_ids = [row[0] for row in db.execute("SELECT record_id FROM privacy_links WHERE kind='chat' AND token_hash=?", (digest,))]
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='survey_response_metadata'").fetchone():
                db.execute("DELETE FROM survey_response_metadata WHERE submission_id IN (SELECT record_id FROM privacy_links WHERE kind='survey' AND token_hash=?)", (digest,))
            for kind, table, key in [('survey', 'survey_responses', 'submission_id'), ('survey', 'survey_drafts', 'submission_id'), ('chat', 'chat_sessions', 'id')]:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    continue
                db.execute(f'DELETE FROM {table} WHERE {key} IN (SELECT record_id FROM privacy_links WHERE kind=? AND token_hash=?)', (kind, digest))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='study_assignments'").fetchone():
                db.execute('DELETE FROM study_assignments WHERE token_hash=?', (digest,))
            db.execute('DELETE FROM privacy_links WHERE token_hash=?', (digest,))
            db.execute('DELETE FROM privacy_consent_history WHERE token_hash=?', (digest,))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='study_runs'").fetchone():
                db.execute('DELETE FROM study_runs WHERE token_hash=?', (digest,))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='study_personality_usage'").fetchone():
                db.execute('DELETE FROM study_personality_usage WHERE token_hash=?', (digest,))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_prompt_participant_snapshots'").fetchone():
                db.execute('DELETE FROM system_prompt_participant_snapshots WHERE token_hash=?', (digest,))

        return chat_ids

    def participant_records(self, participation_id):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT token_hash FROM privacy_consents WHERE participation_id=?', (participation_id,)).fetchone()
            if not row:
                return None
            return dict(db.execute('SELECT kind, COUNT(*) FROM privacy_links WHERE token_hash=? GROUP BY kind', (row[0],)).fetchall())

    def delete_participant(self, participation_id):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT token_hash FROM privacy_consents WHERE participation_id=?', (participation_id,)).fetchone()
        if not row:
            raise ConsentRequired()
        return self._withdraw_digest(row[0])

    def closed(self):
        with sqlite3.connect(self.path) as db:
            return bool(db.execute("SELECT 1 FROM privacy_lifecycle WHERE key='closed'").fetchone())

    def end_study(self):
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            study_tokens = "SELECT token_hash FROM privacy_consents WHERE purpose='study'"
            chat_ids = [row[0] for row in db.execute(f"SELECT record_id FROM privacy_links WHERE kind='chat' AND token_hash IN ({study_tokens})")]
            db.execute("INSERT OR IGNORE INTO privacy_lifecycle VALUES ('closed', ?)", (datetime.now(timezone.utc).isoformat(),))
            for table in ('survey_responses', 'survey_drafts', 'survey_response_metadata', 'study_runs', 'study_assignments', 'study_personality_usage', 'system_prompt_participant_snapshots'):
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                    continue
                db.execute(f'DELETE FROM {table}')
            for table in ('privacy_links', 'privacy_consent_history'):
                db.execute(f'DELETE FROM {table} WHERE token_hash IN ({study_tokens})')
            db.execute("DELETE FROM privacy_consents WHERE purpose='study'")
        return chat_ids
