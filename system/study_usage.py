"""Minimal, consent-bound record of personalities actually applied in the study.

Only fixed selection codes are persisted. Editable personality content remains
in the existing ephemeral search session. This is not an interaction event log.
"""
from datetime import datetime, timezone
import json
import sqlite3

from advisor import AdvisorConfig
from persona_mlds import load_templates


CAPTURE_VERSION = 1
SOURCES = {'template', 'custom', 'unknown', 'not_applicable'}
TEMPLATE_IDS = {'career', 'expert'}


def empty_usage():
    """Missing historical metadata means unknown, never 'template by default'."""
    return dict(capture_version=0, initial_source='unknown', initial_template_id=None,
                last_source='unknown', last_template_id=None, ever_custom=None,
                ever_template=None, selection_change_count=None,
                first_applied_at_utc='', last_selection_changed_at_utc='')


def _selection(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump()
    if not isinstance(value, dict) or set(value) != {'source', 'template_id'}:
        raise ValueError('Die Herkunft der KI-Persönlichkeit ist ungültig.')
    source, template_id = value['source'], value['template_id']
    if not isinstance(source, str) or source not in SOURCES or (source == 'template' and
            (not isinstance(template_id, str) or template_id not in TEMPLATE_IDS)):
        raise ValueError('Die Herkunft der KI-Persönlichkeit ist ungültig.')
    if source != 'template' and template_id is not None:
        raise ValueError('Nur unveränderte Vorlagen erhalten eine Vorlagenkennung.')
    return dict(source=source, template_id=template_id)


def normalize_selection(advisor, selection=None, *, arm=None):
    """Validate provenance against the effective advisor before calling the LLM.

    Explicitly choosing customization counts as custom even if the resulting
    values happen to equal a template. A legacy request without a marker stays
    unknown; the neutral comparison condition is always not applicable.
    """
    config = AdvisorConfig.model_validate(
        advisor.model_dump() if isinstance(advisor, AdvisorConfig) else advisor).model_dump()
    if arm == 'A' or (config['mode'] == 'preset' and config['preset'] in ('neutral', 'standard')):
        return dict(source='not_applicable', template_id=None)
    if selection is None:
        return dict(source='unknown', template_id=None)
    selection = _selection(selection)
    if selection['source'] == 'not_applicable':
        raise ValueError('Die gewählte Studienvariante erlaubt eine KI-Persönlichkeit.')
    if selection['source'] == 'template':
        expected = load_templates()[selection['template_id']]['advisor']
        # The list order is part of the stored configuration, as in the editor.
        if config != expected:
            raise ValueError('Die Persönlichkeit wurde gegenüber der Vorlage verändert. Bitte als selbst gestaltet verwenden.')
    return selection


class StudyPersonalityUsage:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS study_personality_usage (
                token_hash TEXT PRIMARY KEY, metadata_json TEXT NOT NULL)''')
            # Also cover deletion through admin bulk actions and future routes.
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='privacy_consents'").fetchone():
                db.executescript('''
                    CREATE TRIGGER IF NOT EXISTS privacy_revoke_personality_usage
                    AFTER UPDATE OF withdrawn_at ON privacy_consents
                    WHEN NEW.withdrawn_at IS NOT NULL
                    BEGIN DELETE FROM study_personality_usage WHERE token_hash=NEW.token_hash; END;
                    CREATE TRIGGER IF NOT EXISTS privacy_delete_personality_usage
                    AFTER DELETE ON privacy_consents
                    BEGIN DELETE FROM study_personality_usage WHERE token_hash=OLD.token_hash; END;
                ''')

    def mark_applied(self, digest, selection, db):
        """Call in the successful session-write transaction, never on UI clicks.

        Repeating a chat or search with the same selection is idempotent for this
        metadata. Only switching source/template updates the last timestamp.
        """
        selection = _selection(selection)
        consent = db.execute('SELECT purpose, withdrawn_at FROM privacy_consents WHERE token_hash=?', (digest,)).fetchone()
        if not consent or consent[0] != 'study' or consent[1] is not None:
            return False
        previous = db.execute('SELECT metadata_json FROM study_personality_usage WHERE token_hash=?', (digest,)).fetchone()
        usage = json.loads(previous[0]) if previous else None
        key = (selection['source'], selection['template_id'])
        if usage and key == (usage['last_source'], usage['last_template_id']):
            return False
        now = datetime.now(timezone.utc).isoformat()
        if usage is None:
            usage = dict(capture_version=CAPTURE_VERSION,
                         initial_source=key[0], initial_template_id=key[1],
                         last_source=key[0], last_template_id=key[1],
                         ever_custom=None if key[0] == 'unknown' else key[0] == 'custom',
                         ever_template=None if key[0] == 'unknown' else key[0] == 'template',
                         selection_change_count=0,
                         first_applied_at_utc=now, last_selection_changed_at_utc=now)
        else:
            def observed(previous, source):
                if previous is True or key[0] == source:
                    return True
                return None if previous is None or key[0] == 'unknown' else False
            usage.update(last_source=key[0], last_template_id=key[1],
                         ever_custom=observed(usage['ever_custom'], 'custom'),
                         ever_template=observed(usage['ever_template'], 'template'),
                         selection_change_count=usage['selection_change_count'] + 1,
                         last_selection_changed_at_utc=now)
        db.execute('''INSERT INTO study_personality_usage VALUES (?, ?)
            ON CONFLICT(token_hash) DO UPDATE SET metadata_json=excluded.metadata_json''',
                   (digest, json.dumps(usage, sort_keys=True, separators=(',', ':'))))
        return True


def usage_snapshot(digest, db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='study_personality_usage'").fetchone():
        return empty_usage()
    row = db.execute('SELECT metadata_json FROM study_personality_usage WHERE token_hash=?', (digest,)).fetchone()
    return json.loads(row[0]) if row else empty_usage()
