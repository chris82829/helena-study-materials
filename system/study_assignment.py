"""Transactional A/B/C allocation, retaining historical experiment conditions."""
import secrets
from datetime import datetime, timezone

from privacy import token_hash
from advisor import AdvisorConfig

EXPERIMENT_ID = 'helena-abc-v7'
PREVIOUS_FRAMEWORK_EXPERIMENT_ID = 'helena-abc-v6'
PREVIOUS_QUESTIONNAIRE_EXPERIMENT_ID = 'helena-abc-v5'
PREVIOUS_PERSONALITY_EXPERIMENT_ID = 'helena-abc-v4'
PREVIOUS_CONFERENCE_EXPERIMENT_ID = 'helena-abc-v3'
PREVIOUS_FAIR_EXPERIMENT_ID = 'helena-abc-v2'
PREVIOUS_ABC_EXPERIMENT_ID = 'helena-abc-v1'
AB_EXPERIMENT_ID = 'helena-ab-v2'
LEGACY_EXPERIMENT_ID = 'helena-bc-v1'
LEGACY_TO_CURRENT_ARM = {'B': 'A', 'C': 'B'}
CURRENT_TO_LEGACY_ARM = {current: legacy for legacy, current in LEGACY_TO_CURRENT_ARM.items()}


def personality_policy(experiment_id, arm):
    if experiment_id in (EXPERIMENT_ID, PREVIOUS_FRAMEWORK_EXPERIMENT_ID, PREVIOUS_QUESTIONNAIRE_EXPERIMENT_ID, PREVIOUS_PERSONALITY_EXPERIMENT_ID):
        return {'A': 'unprompted', 'B': 'career_fixed', 'C': 'custom_career'}[arm]
    if arm == 'A':
        return 'standard' if experiment_id in (PREVIOUS_CONFERENCE_EXPERIMENT_ID, PREVIOUS_FAIR_EXPERIMENT_ID) else 'generic'
    # Historical B participants had the full editor. Never silently change the
    # treatment associated with an existing assignment.
    return 'templates' if experiment_id in (PREVIOUS_CONFERENCE_EXPERIMENT_ID, PREVIOUS_FAIR_EXPERIMENT_ID, PREVIOUS_ABC_EXPERIMENT_ID) and arm == 'B' else 'configurable'


def presentation_policy(experiment_id, arm):
    return 'legacy_neutral' if personality_policy(experiment_id, arm) == 'generic' else 'ranked_insights'


class PersonalityPolicyError(ValueError):
    pass


def advisor_for_policy(requested, policy):
    if policy == 'unprompted':
        # The fixed balanced configuration preserves the scoring weights. The LLM
        # layer applies A's separately versioned prompt, which is empty by default.
        from persona_mlds import load_standard_advisor
        return load_standard_advisor()
    if policy in ('career_fixed', 'custom_career'):
        from persona_mlds import load_templates
        career = load_templates()['career']['advisor']
        if policy == 'custom_career':
            # Current C edits the personality only. Keep its ranking weights
            # balanced even when the starting template or a cached client asks
            # for another focus; B and historical templates retain their focus.
            career = {**career, 'focus': 'ausgewogen'}
        if requested == AdvisorConfig().model_dump() or (requested.get('mode', 'preset') == 'preset' and requested.get('preset') in ('neutral', 'standard')):
            return dict(career)
        if policy == 'career_fixed':
            if requested == career:
                return dict(career)
            raise PersonalityPolicyError('In dieser Variante ist der Top-Berufsberater fest eingestellt.')
        # C accepts only an actually self-designed configuration. Old cached
        # frontends may still submit one of the former preset personalities;
        # normalize every such preset to the reviewed career starting point so a
        # stale client cannot silently reintroduce a removed treatment. The
        # ``preset`` field is irrelevant in custom mode, but canonicalizing it
        # keeps the stored MLDS representation stable and auditable.
        if requested.get('mode') == 'preset':
            return dict(career)
        if requested.get('mode') != 'custom':
            raise PersonalityPolicyError(
                'In dieser Variante muss die KI-Suchpersönlichkeit selbst gestaltet werden.'
            )
        return {**requested, 'mode': 'custom', 'preset': 'helena', 'focus': 'ausgewogen'}
    if policy == 'standard':
        from persona_mlds import load_standard_advisor
        return load_standard_advisor()
    if policy == 'generic':
        return dict(NEUTRAL_ADVISOR)
    if policy == 'templates':
        from persona_mlds import load_templates
        templates = load_templates()
        if requested == AdvisorConfig().model_dump() or (requested.get('mode', 'preset') == 'preset' and requested.get('preset') in ('neutral', 'standard')):
            return dict(templates['career']['advisor'])
        for template in templates.values():
            if requested == template['advisor']:
                return dict(template['advisor'])
        raise PersonalityPolicyError('In dieser Variante kannst du Top-Berufsberater oder Fachexperte auswählen. Die Vorlagen sind nicht bearbeitbar.')
    if requested.get('mode', 'preset') == 'preset' and requested.get('preset') in ('neutral', 'standard'):
        return AdvisorConfig().model_dump()
    return requested
NEUTRAL_ADVISOR = dict(mode='preset', preset='neutral', name='HELENA', traits=[], focus='ausgewogen', description='')


class StudyAssignments:
    def __init__(self, surveys, privacy, notice):
        self.surveys, self.privacy, self.notice = surveys, privacy, notice
        with surveys.connect() as db:
            # Serialize startup migrations as well as allocations. Old rows retain
            # their original experiment, group code and allocation timestamp.
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS study_assignments (
                token_hash TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
                arm TEXT NOT NULL CHECK(arm IN ('A','B','C')), assigned_at TEXT NOT NULL,
                prior_exposure INTEGER NOT NULL DEFAULT 0)''')
            schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='study_assignments'").fetchone()['sql']
            if "'A'" not in schema.upper():
                # SQLite cannot alter CHECK constraints in place. Rebuild within
                # this transaction so concurrent workers never see a partial table.
                db.execute('''CREATE TABLE study_assignments_ab_migration (
                    token_hash TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
                    arm TEXT NOT NULL CHECK(arm IN ('A','B','C')), assigned_at TEXT NOT NULL,
                    prior_exposure INTEGER NOT NULL DEFAULT 0)''')
                db.execute('''INSERT INTO study_assignments_ab_migration
                    (token_hash, experiment_id, arm, assigned_at, prior_exposure)
                    SELECT token_hash, experiment_id, arm, assigned_at, prior_exposure
                    FROM study_assignments''')
                db.execute('DROP TABLE study_assignments')
                db.execute('ALTER TABLE study_assignments_ab_migration RENAME TO study_assignments')

    @staticmethod
    def public(row):
        if not row:
            return None
        arm = row['arm']
        if row['experiment_id'] == LEGACY_EXPERIMENT_ID:
            arm = LEGACY_TO_CURRENT_ARM[arm]
        return dict(experiment_id=row['experiment_id'], arm=arm, assigned_at=row['assigned_at'],
                    prior_exposure=bool(row['prior_exposure']),
                    personality_policy=personality_policy(row['experiment_id'], arm),
                    presentation_policy=presentation_policy(row['experiment_id'], arm),
                    questionnaire_arm=row['arm'] if row['experiment_id'] == LEGACY_EXPERIMENT_ID else arm,
                    questionnaire_version=('helena-v14' if row['experiment_id'] == EXPERIMENT_ID else
                                           'helena-v13' if row['experiment_id'] == PREVIOUS_FRAMEWORK_EXPERIMENT_ID else
                                           'helena-v12' if row['experiment_id'] == PREVIOUS_QUESTIONNAIRE_EXPERIMENT_ID else
                                           'helena-v11' if row['experiment_id'] == PREVIOUS_PERSONALITY_EXPERIMENT_ID else
                                           'helena-v10' if row['experiment_id'] == PREVIOUS_CONFERENCE_EXPERIMENT_ID else
                                           'helena-v9' if row['experiment_id'] == PREVIOUS_FAIR_EXPERIMENT_ID else
                                           'helena-v8' if row['experiment_id'] == PREVIOUS_ABC_EXPERIMENT_ID else
                                           'helena-v6' if row['experiment_id'] == LEGACY_EXPERIMENT_ID else 'helena-v7'))

    def get(self, token):
        if not token:
            return None
        with self.surveys.connect() as db:
            row = db.execute('SELECT * FROM study_assignments WHERE token_hash=?', (token_hash(token),)).fetchone()
            return self.public(row)

    def assign(self, token, *, on_assign=None):
        with self.surveys.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            digest = self.privacy.require(token, self.notice, db)
            old = db.execute('SELECT * FROM study_assignments WHERE token_hash=?', (digest,)).fetchone()
            if old:
                assigned = self.public(old)
            else:
                prior = bool(db.execute("SELECT 1 FROM privacy_links WHERE token_hash=? AND kind='chat' LIMIT 1", (digest,)).fetchone())
                db.execute('INSERT INTO study_assignments VALUES (?, ?, ?, ?, ?)',
                           (digest, EXPERIMENT_ID, secrets.choice(('A', 'B', 'C')), datetime.now(timezone.utc).isoformat(), int(prior)))
                assigned = self.public(db.execute('SELECT * FROM study_assignments WHERE token_hash=?', (digest,)).fetchone())
            if on_assign is not None:
                on_assign(digest, assigned, db)
            return assigned

    def advisor(self, token, requested):
        assigned = self.get(token)
        return advisor_for_policy(requested, assigned['personality_policy']) if assigned else requested

    def validate_answers(self, token, version, answers):
        assigned = self.get(token)
        if assigned:
            allowed = ({'helena-v14'} if assigned['experiment_id'] == EXPERIMENT_ID else
                       {'helena-v13'} if assigned['experiment_id'] == PREVIOUS_FRAMEWORK_EXPERIMENT_ID else
                       {'helena-v12'} if assigned['experiment_id'] == PREVIOUS_QUESTIONNAIRE_EXPERIMENT_ID else
                       {'helena-v11'} if assigned['experiment_id'] == PREVIOUS_PERSONALITY_EXPERIMENT_ID else
                       {'helena-v10'} if assigned['experiment_id'] == PREVIOUS_CONFERENCE_EXPERIMENT_ID else
                       {'helena-v9'} if assigned['experiment_id'] == PREVIOUS_FAIR_EXPERIMENT_ID else
                       {'helena-v8'} if assigned['experiment_id'] == PREVIOUS_ABC_EXPERIMENT_ID else
                       {'helena-v6', 'helena-v7'} if assigned['experiment_id'] == LEGACY_EXPERIMENT_ID else {'helena-v7'})
            if version not in allowed:
                raise ValueError('Der Fragebogen passt nicht zu deiner Studienzuordnung. Bitte lade die Umfrage neu.')
        elif version not in ('helena-v6', 'helena-v7', 'helena-v8', 'helena-v9', 'helena-v10', 'helena-v11', 'helena-v12', 'helena-v13', 'helena-v14'):
            return
        expected_arm = assigned['arm'] if assigned else None
        if version == 'helena-v6':
            expected_arm = CURRENT_TO_LEGACY_ARM.get(expected_arm)
        if not assigned or answers.get('study_arm') != expected_arm:
            raise ValueError('Die Studienzuordnung fehlt oder stimmt nicht überein. Bitte lade die Umfrage neu.')
