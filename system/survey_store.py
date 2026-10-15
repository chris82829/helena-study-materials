"""Survey answers, separate from applicant profiles and chat histories."""
from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, RootModel, create_model, model_validator

from schemas import APIModel

V7_SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition.json').read_text())
V7_SURVEY_FIELDS = [field for group in [V7_SURVEY_DEFINITION['demographics'], *V7_SURVEY_DEFINITION['categories']] for field in group['fields']]
V8_SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition_v8.json').read_text())
V8_SURVEY_FIELDS = [field for group in [V8_SURVEY_DEFINITION['demographics'], *V8_SURVEY_DEFINITION['categories']] for field in group['fields']]
V9_SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition_v9.json').read_text())
V9_SURVEY_FIELDS = [field for group in [V9_SURVEY_DEFINITION['demographics'], *V9_SURVEY_DEFINITION['categories']] for field in group['fields']]
V10_SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition_v10.json').read_text())
V10_SURVEY_FIELDS = [field for group in [V10_SURVEY_DEFINITION['demographics'], *V10_SURVEY_DEFINITION['categories']] for field in group['fields']]
V11_SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition_v11.json').read_text())
V11_SURVEY_FIELDS = [field for group in [V11_SURVEY_DEFINITION['demographics'], *V11_SURVEY_DEFINITION['categories']] for field in group['fields']]
V12_SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition_v12.json').read_text())
V12_SURVEY_FIELDS = [field for group in [V12_SURVEY_DEFINITION['demographics'], *V12_SURVEY_DEFINITION['categories']] for field in group['fields']]
V13_SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition_v13.json').read_text())
V13_SURVEY_FIELDS = [field for group in [V13_SURVEY_DEFINITION['demographics'], *V13_SURVEY_DEFINITION['categories']] for field in group['fields']]
SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition_v14.json').read_text())
SURVEY_VERSION = SURVEY_DEFINITION['version']
SURVEY_FIELDS = [field for group in [SURVEY_DEFINITION['demographics'], *SURVEY_DEFINITION['categories']]
                 for field in group['fields']]
LEGACY_SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition_v3.json').read_text())
LEGACY_SURVEY_FIELDS = [field for group in [LEGACY_SURVEY_DEFINITION['demographics'], *LEGACY_SURVEY_DEFINITION['categories']]
                        for field in group['fields']]
V4_SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition_v4.json').read_text())
V4_SURVEY_FIELDS = [field for group in [V4_SURVEY_DEFINITION['demographics'], *V4_SURVEY_DEFINITION['categories']] for field in group['fields']]
V5_SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition_v5.json').read_text())
V5_SURVEY_FIELDS = [field for group in [V5_SURVEY_DEFINITION['demographics'], *V5_SURVEY_DEFINITION['categories']] for field in group['fields']]
V6_SURVEY_DEFINITION = json.loads(Path(__file__).with_name('survey_definition_v6.json').read_text())
V6_SURVEY_FIELDS = [field for group in [V6_SURVEY_DEFINITION['demographics'], *V6_SURVEY_DEFINITION['categories']] for field in group['fields']]
VERSIONED_FIELDS = {'helena-v4': V4_SURVEY_FIELDS, 'helena-v5': V5_SURVEY_FIELDS, 'helena-v6': V6_SURVEY_FIELDS, 'helena-v7': V7_SURVEY_FIELDS, 'helena-v8': V8_SURVEY_FIELDS, 'helena-v9': V9_SURVEY_FIELDS, 'helena-v10': V10_SURVEY_FIELDS, 'helena-v11': V11_SURVEY_FIELDS, 'helena-v12': V12_SURVEY_FIELDS, 'helena-v13': V13_SURVEY_FIELDS, SURVEY_VERSION: SURVEY_FIELDS}

MISSING_CODES = {'not_used', 'not_assessable', 'not_specified'}


def field_visible(field, answers):
    condition = field.get('visibleIf')
    if not condition:
        return True
    value = answers.get(condition['field'])
    return value in condition['in'] if 'in' in condition else value == condition['equals']


def answer_status(field, answers):
    if not field_visible(field, answers):
        return 'skipped' if answers.get(field.get('visibleIf', {}).get('field')) is not None else 'unanswered'
    value = answers.get(field['name'])
    return value if value in MISSING_CODES else ('no_answer' if field.get('optional') else 'unanswered') if value in (None, '') else 'answered'


def choice_codes(field):
    return field.get('codes', {code: i for i, (code, _) in enumerate(field.get('options', []), 1)
                               if code not in MISSING_CODES})
QUESTIONS = (
    'Wie hilfreich war die Möglichkeit, die vorgeschlagenen Ergebnisse direkt im Chatfenster mit der Persona zu besprechen und iterativ zu verfeinern?',
    'Im Vergleich zu einer klassischen Jobbörse (nur harte Filter): Welchen Mehrwert bietet Ihnen die Kombination aus Job-Karten und maßgeschneiderter KI-Persona?',
    'Würden Sie bei zukünftigen Jobsuchen eine individuell einstellbare KI-Beratung bevorzugen?',
    'Welches konkrete Feedback haben Sie zur Persona-Generierung oder den angezeigten Begründungen?',
)
ADDED_VALUE_LABELS = dict(very_high='Sehr großen Mehrwert', some='Etwas Mehrwert',
                          same='Keinen Unterschied', confusing='Eher verwirrend', worse='Deutlich schlechter')
PREFERENCE_LABELS = dict(definitely_yes='Ja, auf jeden Fall', rather_yes='Eher ja',
                         undecided='Unentschieden', rather_no='Eher nein', definitely_no='Auf keinen Fall')


class LegacySurveySubmission(APIModel):
    submission_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    version: Literal['helena-v1']
    chat_helpfulness: int = Field(ge=1, le=5)
    added_value: Literal['very_high', 'some', 'same', 'confusing', 'worse']
    future_preference: Literal['definitely_yes', 'rather_yes', 'undecided', 'rather_no', 'definitely_no']
    feedback: str = Field(default='', max_length=4000)


Rating = Annotated[int, Field(ge=1, le=10)]


class SurveySubmissionV2(APIModel):
    submission_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    version: Literal['helena-v2']
    age_group: Literal['under_18', '18_20', '21_24', '25_29', '30_39', '40_plus', 'not_specified']
    gender: Literal['female', 'male', 'diverse', 'not_specified']
    education: Literal['bachelor', 'master', 'other_studies', 'doctorate', 'training', 'not_studying', 'not_specified']
    study_field: str = Field(default='', max_length=160)
    search_goal: str = Field(min_length=3, max_length=1000)
    personality_clarity: Rating
    personality_setup: Rating
    personality_consistency: Rating
    chat_helpfulness: Rating
    search_refinement: Rating
    explanation_helpfulness: Rating
    search_ease: Rating
    personality_value: Rating
    future_use: Rating


class SurveySubmission(SurveySubmissionV2):
    version: Literal['helena-v3']
    score_usefulness: Rating
    match_reasons_usefulness: Rating
    personalized_chat_usefulness: Rating
    personalized_search_usefulness: Rating


class ConditionalSurvey(APIModel):
    @model_validator(mode='after')
    def validate_visibility(self):
        answers = self.model_dump()
        for field in VERSIONED_FIELDS[self.version]:
            if 'visibleIf' not in field:
                continue
            value = answers[field['name']]
            if field_visible(field, answers) and value is None:
                raise ValueError(f"Bitte beantworte {field['name']}.")
            if not field_visible(field, answers) and value is not None:
                raise ValueError(f"Die übersprungene Frage {field['name']} muss leer bleiben.")
        return self


def _submission_fields(version):
    fields = dict(submission_id=(str, Field(pattern=r'^[a-f0-9]{32}$')), version=(Literal[version], ...))
    for field in VERSIONED_FIELDS[version]:
        default = ...
        if field['kind'] == 'choice':
            annotation = Literal[tuple(code for code, _ in field['options'])]
        elif field['kind'] == 'scale':
            rating = Annotated[int, Field(ge=field.get('scale', {}).get('min', 1), le=field.get('scale', {}).get('max', 10))]
            annotation = rating | Literal[tuple(code for code, _ in field['nonresponse'])] if field.get('nonresponse') else rating
        else:
            annotation = Annotated[str, Field(min_length=0 if field.get('optional') else field.get('minLength', 1), max_length=field['maxLength'])]
            if field.get('optional'):
                default = ''
        if 'visibleIf' in field:
            annotation = annotation | None
            default = None
        fields[field['name']] = (annotation, default)
    return fields


SurveySubmissionV4 = create_model('SurveySubmissionV4', __base__=ConditionalSurvey, **_submission_fields('helena-v4'))

SurveySubmissionV5 = create_model('SurveySubmissionV5', __base__=ConditionalSurvey, **_submission_fields('helena-v5'))

SurveySubmissionV6 = create_model('SurveySubmissionV6', __base__=ConditionalSurvey, **_submission_fields('helena-v6'))

SurveySubmissionV7 = create_model('SurveySubmissionV7', __base__=ConditionalSurvey, **_submission_fields('helena-v7'))

SurveySubmissionV8 = create_model('SurveySubmissionV8', __base__=ConditionalSurvey, **_submission_fields('helena-v8'))

SurveySubmissionV9 = create_model('SurveySubmissionV9', __base__=ConditionalSurvey, **_submission_fields('helena-v9'))

SurveySubmissionV10 = create_model('SurveySubmissionV10', __base__=ConditionalSurvey, **_submission_fields('helena-v10'))

SurveySubmissionV11 = create_model('SurveySubmissionV11', __base__=ConditionalSurvey, **_submission_fields('helena-v11'))

SurveySubmissionV12 = create_model('SurveySubmissionV12', __base__=ConditionalSurvey, **_submission_fields('helena-v12'))

SurveySubmissionV13 = create_model('SurveySubmissionV13', __base__=ConditionalSurvey, **_submission_fields('helena-v13'))

SurveySubmissionV14 = create_model('SurveySubmissionV14', __base__=ConditionalSurvey, **_submission_fields('helena-v14'))

def _draft_fields(version, model):
    fields = {}
    for field in VERSIONED_FIELDS[version]:
        if field['kind'] == 'text':
            annotation = Annotated[str, Field(max_length=field['maxLength'])]
        else:
            annotation = model.model_fields[field['name']].annotation
        fields[field['name']] = (annotation | None, None)
    return fields


DraftAnswers = create_model('DraftAnswers', __base__=APIModel, **_draft_fields('helena-v4', SurveySubmissionV4))
DraftAnswersV5 = create_model('DraftAnswersV5', __base__=APIModel, **_draft_fields('helena-v5', SurveySubmissionV5))
DraftAnswersV6 = create_model('DraftAnswersV6', __base__=APIModel, **_draft_fields('helena-v6', SurveySubmissionV6))
DraftAnswersV7 = create_model('DraftAnswersV7', __base__=APIModel, **_draft_fields('helena-v7', SurveySubmissionV7))
DraftAnswersV8 = create_model('DraftAnswersV8', __base__=APIModel, **_draft_fields('helena-v8', SurveySubmissionV8))
DraftAnswersV9 = create_model('DraftAnswersV9', __base__=APIModel, **_draft_fields('helena-v9', SurveySubmissionV9))
DraftAnswersV10 = create_model('DraftAnswersV10', __base__=APIModel, **_draft_fields('helena-v10', SurveySubmissionV10))
DraftAnswersV11 = create_model('DraftAnswersV11', __base__=APIModel, **_draft_fields('helena-v11', SurveySubmissionV11))
DraftAnswersV12 = create_model('DraftAnswersV12', __base__=APIModel, **_draft_fields('helena-v12', SurveySubmissionV12))
DraftAnswersV13 = create_model('DraftAnswersV13', __base__=APIModel, **_draft_fields('helena-v13', SurveySubmissionV13))
DraftAnswersV14 = create_model('DraftAnswersV14', __base__=APIModel, **_draft_fields('helena-v14', SurveySubmissionV14))
WaitingField = Literal['previous_participation', 'age_group', 'gender', 'education', 'study_field', 'search_goal', 'personality_customized', 'personality_setup', 'template_selection_ease', 'job_portal_experience', 'ai_chat_experience']


class SurveyDraftV4(APIModel):
    submission_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    version: Literal['helena-v4']
    revision: int = Field(ge=1, le=9007199254740991)
    answers: DraftAnswers
    waiting_answered: list[WaitingField] = Field(default_factory=list, max_length=10)

    @model_validator(mode='after')
    def consistent_draft(self):
        answers = self.answers.model_dump()
        for field in VERSIONED_FIELDS[self.version]:
            if not field_visible(field, answers) and answers[field['name']] is not None:
                raise ValueError('Übersprungene Fragen müssen leer bleiben.')
        return self


class SurveyDraftV5(SurveyDraftV4):
    version: Literal['helena-v5']
    answers: DraftAnswersV5


class SurveyDraftV6(SurveyDraftV4):
    version: Literal['helena-v6']
    answers: DraftAnswersV6


class SurveyDraftV7(SurveyDraftV4):
    version: Literal['helena-v7']
    answers: DraftAnswersV7


class SurveyDraftV8(SurveyDraftV4):
    version: Literal['helena-v8']
    answers: DraftAnswersV8


class SurveyDraftV9(SurveyDraftV4):
    version: Literal['helena-v9']
    answers: DraftAnswersV9

    @model_validator(mode='after')
    def waiting_questions_are_factual(self):
        allowed = {field['name'] for field in VERSIONED_FIELDS[self.version] if field.get('beforeSystem')} | {field['name'] for field in V9_SURVEY_DEFINITION['demographics']['fields']} | {'search_goal'}
        if not set(self.waiting_answered) <= allowed:
            raise ValueError('Während der Wartezeit sind nur Sachangaben vorgesehen.')
        return self


class SurveyDraftV10(SurveyDraftV9):
    version: Literal['helena-v10']
    answers: DraftAnswersV10


class SurveyDraftV11(SurveyDraftV10):
    version: Literal['helena-v11']
    answers: DraftAnswersV11


class SurveyDraftV12(SurveyDraftV11):
    version: Literal['helena-v12']
    answers: DraftAnswersV12


class SurveyDraftV13(SurveyDraftV12):
    version: Literal['helena-v13']
    answers: DraftAnswersV13

    @model_validator(mode='after')
    def active_waiting_fields_only(self):
        allowed={field['name'] for field in VERSIONED_FIELDS[self.version] if field.get('beforeSystem')} | {'search_goal'}
        if not set(self.waiting_answered) <= allowed:
            raise ValueError('Veraltete Angaben für die Wartezeit sind nicht mehr verfügbar.')
        return self


class SurveyDraftV14(SurveyDraftV13):
    version: Literal['helena-v14']
    answers: DraftAnswersV14


class SurveyDraftRequest(RootModel[Annotated[SurveyDraftV14 | SurveyDraftV13 | SurveyDraftV12 | SurveyDraftV11 | SurveyDraftV10 | SurveyDraftV9 | SurveyDraftV8 | SurveyDraftV7 | SurveyDraftV6 | SurveyDraftV5 | SurveyDraftV4, Field(discriminator='version')]]):
    pass


# Compatibility for callers constructing historical v4 drafts directly.
SurveyDraft = SurveyDraftV4


class SurveyRequest(RootModel[Annotated[SurveySubmissionV14 | SurveySubmissionV13 | SurveySubmissionV12 | SurveySubmissionV11 | SurveySubmissionV10 | SurveySubmissionV9 | SurveySubmissionV8 | SurveySubmissionV7 | SurveySubmissionV6 | SurveySubmissionV5 | SurveySubmissionV4 | SurveySubmission | SurveySubmissionV2 | LegacySurveySubmission,
                                        Field(discriminator='version')]]):
    """Historical parsers remain available offline; HTTP routes accept only SURVEY_VERSION."""


class SurveyConflict(Exception):
    pass


def spreadsheet_text(value):
    """Keep user text literal when the CSV is opened in a spreadsheet."""
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


class SurveyStore:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS survey_responses (
                submission_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                answers_json TEXT NOT NULL
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS survey_drafts (
                submission_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                revision INTEGER NOT NULL, answers_json TEXT NOT NULL, waiting_json TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS survey_answer_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id TEXT NOT NULL,
                corrected_at TEXT NOT NULL, reason TEXT NOT NULL, actor TEXT NOT NULL,
                response_status TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL)''')
            from survey_migrations import migrate_v12, migrate_v13, migrate_v14
            migrate_v12(db)
            migrate_v13(db)
            migrate_v14(db)
            db.execute('CREATE INDEX IF NOT EXISTS survey_corrections_response ON survey_answer_corrections(submission_id, id)')
            # Follow every deletion path, including withdrawal and retention cleanup.
            # Promoting a draft retains its history because the completed row exists.
            for table, other in [('survey_responses', 'survey_drafts'), ('survey_drafts', 'survey_responses')]:
                db.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_delete_corrections
                    AFTER DELETE ON {table}
                    WHEN NOT EXISTS (SELECT 1 FROM {other} WHERE submission_id=OLD.submission_id)
                    BEGIN DELETE FROM survey_answer_corrections WHERE submission_id=OLD.submission_id; END''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_draft(self, draft, before_save=None):
        answers = dict(version=draft.version, **draft.answers.model_dump())
        canonical = json.dumps(answers, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        waiting = json.dumps(sorted(set(draft.waiting_answered)))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if before_save:
                before_save(db, draft.submission_id)
            if db.execute('SELECT 1 FROM survey_responses WHERE submission_id=?', (draft.submission_id,)).fetchone():
                return {'saved': True, 'completed': True, 'revision': draft.revision}
            old = db.execute('SELECT * FROM survey_drafts WHERE submission_id=?', (draft.submission_id,)).fetchone()
            if old and (old['revision'] > draft.revision or (old['revision'] == draft.revision and
                (old['answers_json'] != canonical or old['waiting_json'] != waiting))):
                raise SurveyConflict('Ein neuerer Antwortstand ist bereits gespeichert. Bitte lade die Seite neu.')
            if not old or old['revision'] < draft.revision:
                now = datetime.now(timezone.utc).isoformat()
                db.execute("""INSERT INTO survey_drafts VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(submission_id) DO UPDATE SET updated_at=excluded.updated_at,
                    revision=excluded.revision, answers_json=excluded.answers_json, waiting_json=excluded.waiting_json""",
                    (draft.submission_id, now, now, draft.revision, canonical, waiting))
            return {'saved': True, 'completed': False, 'revision': draft.revision}

    def get_draft(self, submission_id):
        with self.connect() as db:
            completed = db.execute('SELECT answers_json FROM survey_responses WHERE submission_id=?', (submission_id,)).fetchone()
            if completed:
                return {'completed': True, 'version': json.loads(completed['answers_json']).get('version')}
            row = db.execute('SELECT * FROM survey_drafts WHERE submission_id=?', (submission_id,)).fetchone()
            if not row:
                return None
            answers = json.loads(row['answers_json'])
            return dict(completed=False, revision=row['revision'], version=answers.pop('version'),
                        answers=answers, waiting_answered=json.loads(row['waiting_json']))

    def save(self, submission: SurveySubmissionV4 | SurveySubmission | SurveySubmissionV2 | LegacySurveySubmission, before_save=None):
        """A repeated request is safe, including after a lost HTTP response."""
        answers = submission.model_dump(exclude={'submission_id'})
        canonical = json.dumps(answers, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if before_save:
                before_save(db, submission.submission_id)
            inserted = db.execute(
                'INSERT INTO survey_responses VALUES (?, ?, ?) ON CONFLICT(submission_id) DO NOTHING',
                (submission.submission_id, datetime.now(timezone.utc).isoformat(), canonical))
            if inserted.rowcount:
                db.execute('DELETE FROM survey_drafts WHERE submission_id=?', (submission.submission_id,))
                return True
            existing = db.execute('SELECT answers_json FROM survey_responses WHERE submission_id = ?',
                                  (submission.submission_id,)).fetchone()
            if existing['answers_json'] != canonical:
                raise SurveyConflict('Diese Teilnahme wurde bereits mit anderen Antworten gespeichert.')
            return False

    def export_csv(self, stream, columns='readable'):
        """Export only the active questionnaire with readable, source-stable columns."""
        from export_columns import export_headers
        from survey_analytics import construct_value
        constructs=SURVEY_DEFINITION.get('constructs', [])
        columns_list=['participation_id','submitted_at_utc','survey_version',
            *[column for field in SURVEY_FIELDS for column in ('v14_'+field['name'],'v14_'+field['name']+'_status')],
            *['v14_'+item['id']+'_mean' for item in constructs]]
        writer=csv.writer(stream,delimiter=';');writer.writerow(export_headers(columns_list,columns))
        with self.connect() as db:
            has_links=db.execute("SELECT 1 FROM sqlite_master WHERE name='privacy_links'").fetchone()
            participation_ids={row[0]:row[1] for row in db.execute("SELECT l.record_id,p.participation_id FROM privacy_links l JOIN privacy_consents p ON p.token_hash=l.token_hash WHERE l.kind='survey'")} if has_links else {}
            for row in db.execute("SELECT * FROM survey_responses WHERE json_extract(answers_json,'$.version')=? ORDER BY created_at,submission_id",(SURVEY_VERSION,)):
                answers=json.loads(row['answers_json'])
                values=[participation_ids.get(row['submission_id'],row['submission_id']),row['created_at'],SURVEY_VERSION]
                for field in SURVEY_FIELDS:
                    status=answer_status(field,answers);value=answers.get(field['name'],'') if status=='answered' else ''
                    if field['kind']=='choice' and status=='answered':value=choice_codes(field)[value]
                    values.extend([value,status])
                values.extend(construct_value(answers,c) for c in constructs)
                writer.writerow([spreadsheet_text(v) if isinstance(v,str) else v for v in values])

    def _export_historical_csv(self, stream, columns='readable'):
        """Server-side export only. The caller opens the file with UTF-8 BOM."""
        writer = csv.writer(stream, delimiter=';')
        from export_columns import export_headers
        technical = ['participation_id', 'submitted_at_utc', 'survey_version',
                     *[field['name'] for field in LEGACY_SURVEY_FIELDS],
                     *['v1_' + name for name in ('chat_helpfulness','added_value','future_preference','feedback')],
                     *[column for version, fields in VERSIONED_FIELDS.items() for field in fields
                       for column in (version[6:]+'_'+field['name'], version[6:]+'_'+field['name']+'_status')]]
        writer.writerow(export_headers(technical, columns))
        count = 0
        with self.connect() as db:
            participation_ids = {}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='privacy_consents'").fetchone():
                participation_ids = dict(db.execute("""SELECT links.record_id, consents.participation_id
                    FROM privacy_links AS links JOIN privacy_consents AS consents
                    ON links.token_hash=consents.token_hash WHERE links.kind='survey'"""))
            for row in db.execute('SELECT * FROM survey_responses ORDER BY created_at, submission_id'):
                answers = json.loads(row['answers_json'])
                if answers['version'] == 'helena-v1':
                    values = [''] * len(LEGACY_SURVEY_FIELDS) + [
                        answers['chat_helpfulness'], ADDED_VALUE_LABELS[answers['added_value']],
                        PREFERENCE_LABELS[answers['future_preference']], spreadsheet_text(answers['feedback'])]
                else:
                    values = []
                    for field in LEGACY_SURVEY_FIELDS:
                        value = answers.get(field['name'], '') if answers['version'] in ('helena-v2','helena-v3') else ''
                        if field['kind'] == 'choice':
                            value = dict(field['options']).get(value, '')
                        elif field['kind'] == 'text':
                            value = spreadsheet_text(value)
                        values.append(value)
                    values += [''] * len(QUESTIONS)
                for version, fields in VERSIONED_FIELDS.items():
                    for field in fields:
                        status = answer_status(field, answers) if answers['version'] == version else 'not_asked'
                        value = answers.get(field['name'], '') if status == 'answered' else ''
                        if field['kind'] == 'choice' and status == 'answered':
                            value = dict(field['options'])[value]
                        values.extend([spreadsheet_text(value) if isinstance(value, str) else value, status])
                writer.writerow([participation_ids.get(row['submission_id'], row['submission_id']), row['created_at'], answers['version'], *values])
                count += 1
        return count
