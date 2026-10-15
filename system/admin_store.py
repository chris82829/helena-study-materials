"""Analysis exports, audited answer corrections and explicit deletion."""
import csv
import hashlib
import io
import json
import zipfile
from copy import deepcopy
from datetime import datetime, timezone

from pydantic import Field
from schemas import APIModel
from export_columns import META_TITLES, export_name, export_headers, validate_columns
from study_usage import empty_usage
from study_metrics import empty_metrics, operation_diagnostics
from study_context import context_snapshot
from study_assignment import EXPERIMENT_ID, StudyAssignments
from survey_store import SurveyRequest, SurveyDraftRequest, SurveySubmissionV2, SurveyConflict

from survey_store import SURVEY_VERSION, V13_SURVEY_DEFINITION, V12_SURVEY_DEFINITION, V11_SURVEY_DEFINITION, V10_SURVEY_DEFINITION, V9_SURVEY_DEFINITION, V8_SURVEY_DEFINITION, V7_SURVEY_DEFINITION, V6_SURVEY_DEFINITION, V5_SURVEY_DEFINITION, VERSIONED_FIELDS, V4_SURVEY_DEFINITION, SURVEY_FIELDS, LEGACY_SURVEY_FIELDS, SURVEY_DEFINITION, LEGACY_SURVEY_DEFINITION, choice_codes, answer_status, QUESTIONS, spreadsheet_text, ADDED_VALUE_LABELS, PREFERENCE_LABELS

LEGACY_FIELDS = ['chat_helpfulness','added_value','future_preference','feedback']
META_FIELDS = ['participation_id','submitted_at_utc','survey_version','study_release_ids','openai_models','reasoning_efforts','response_status','last_saved_at_utc','study_arm','experiment_id','assigned_at_utc','prior_exposure','system_prompt_policy','system_prompt_revision','system_prompt_base_sha256','presentation_versions','correction_count','last_corrected_at_utc']
USAGE_FIELDS = list(empty_usage())
META_FIELDS += ['personality_' + key for key in USAGE_FIELDS]
METRIC_FIELDS = list(empty_metrics())
META_FIELDS += ['operations_' + key for key in METRIC_FIELDS]
CONTEXT_EXPORT_FIELDS = ['study_wave','recruitment_batch','viewport_class','viewport_class_last','furthest_step_reached','context_config_revision']
META_FIELDS += CONTEXT_EXPORT_FIELDS
ARM_CODES = {'A': 'V11/V12: Basissystem ohne wählbare KI-Suchpersönlichkeit; V9/V10: Standardberatung; V6–V8: Basisvariante',
             'B': 'V11/V12: fester Top-Berufsberater; V8–V10: Vorlagenauswahl; V6/V7: selbst gestaltbar',
             'C': 'V11/V12: Selbstgestaltung auf Berufsberater-Basis; V8–V10: Vorlagenauswahl und Selbstgestaltung'}
ARM_VERSION_NOTE = ('V12: Drei getrennte Nutzen-Aussagen (usefulness_effective, usefulness_speed, usefulness_overall), jeweils 1–5 mit allen fünf verbalen Zustimmungsankern. Die übrigen Bewertungsfragen bleiben 1–10. Es erfolgt keine automatische Zusammenfassung zu einer ungeprüften Gesamtskala. Fehlende bzw. nicht beurteilbare Items sind leer; primaerwert_v12_vollstaendig_anzahl zählt nur Teilnahmen mit drei numerischen Antworten 1–5. V12 erhebt keine Bewertungsschwerpunkte mehr; historische personalized_search_usefulness-Antworten bleiben versioniert erhalten (deprecated seit V12). Die neue Frage zur Formulierung der Begründungen heißt personality_clarity_explanations und wird nicht mit der historischen Rangfolgenfrage zusammengeführt.\n\nV11 / helena-abc-v4: A ist das Basissystem ohne wählbare KI-Suchpersönlichkeit, B der feste Top-Berufsberater und C ausschließlich Selbstgestaltung auf Basis dieser Berufsberater-Anweisungen. Die konkrete A-Systemprompt-Revision wird separat dokumentiert; ein leerer A-Basisprompt ist an der SHA-256-Prüfsumme des leeren Textes erkennbar und bedeutet unabhängig von seiner positiven Revision, dass keine Systemnachricht gesendet wurde. V10 / helena-abc-v3 übernimmt die fairen Bedingungen von V9 und entfernt fünf Bedienungs-/Einrichtungsfragen. V9 / helena-abc-v2: A ist eine sachliche Standardberatung; B erlaubt feste Vorlagen, C zusätzlich Selbstgestaltung. Alle drei Varianten verwenden Scores, Begründungen und Ranking. V8 / helena-abc-v1: A ist die Basisvariante, B erlaubt unveränderte Vorlagen, '
    'C zusätzlich die Selbstgestaltung. In helena-v6 entsprechen die gespeicherten Originalcodes '
    'B der Anzeige A und C der Anzeige B. V6 zeigte Scores und Begründungen in beiden Gruppen. '
    'In helena-v7 sind Originalcodes und Anzeige A/B identisch; B war dort selbst gestaltbar. '
    'V7 zeigte Scores und Begründungen nur in B, V8 in B und C. '
    'Historisches B wird nicht als neue Vorlagengruppe interpretiert. Fragebogenversion und '
    'experiment_id gemeinsam berücksichtigen; Versionen nicht ungeprüft zusammenfassen.')


def displayed_study_arm(answers):
    """Normalize labels from answer version, never reinterpret a historical B as new B."""
    if answers.get('version') == 'helena-v6':
        return {'B': 'A', 'C': 'B'}.get(answers.get('study_arm'), '')
    if answers.get('version') == 'helena-v7':
        return answers.get('study_arm') if answers.get('study_arm') in ('A', 'B') else ''
    if answers.get('version') in ('helena-v8', 'helena-v9', 'helena-v10', 'helena-v11', 'helena-v12', 'helena-v13', 'helena-v14'):
        return answers.get('study_arm') if answers.get('study_arm') in ARM_CODES else ''
    return ''


def release_presentation(manifest, assignment):
    """A release can serve both current ranked advice and historical generic A."""
    if manifest.get('presentation_policy'):
        if not assignment:
            return 'undocumented'
        if assignment['presentation_policy'] == 'legacy_neutral':
            return manifest.get('historical_neutral_presentation', 'undocumented')
        return manifest['presentation_policy']
    return manifest.get('neutral_presentation', 'undocumented')


class AdminAnswerCorrection(APIModel):
    answers: dict[str, object]
    reason: str = Field(min_length=3, max_length=1000)
    edit_revision: str = Field(pattern=r'^[a-f0-9]{64}$')


def edit_revision(row, correction_id):
    snapshot = [row['submission_id'], row['response_status'], row['answers_json'],
                row['updated_at'], row['source_revision'], correction_id]
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False).encode()).hexdigest()


class AdminSurveyData:
    def __init__(self, surveys, privacy, releases, sessions):
        self.surveys,self.privacy,self.releases,self.sessions=surveys,privacy,releases,sessions

    def records(self):
        releases=self.releases.all()
        with self.surveys.connect() as db:
            rows=db.execute('''SELECT s.*, l.token_hash AS participant_token_hash, p.participation_id, m.metadata_json, u.metadata_json AS personality_usage_json, o.metadata_json AS operation_metrics_json, a.arm, a.experiment_id, a.assigned_at, a.prior_exposure,
                sp.policy AS system_prompt_policy, sp.revision AS system_prompt_revision,
                sp.sha256 AS system_prompt_base_sha256,
                COALESCE(c.correction_count,0) AS correction_count, COALESCE(c.correction_id,0) AS correction_id,
                c.last_corrected_at FROM (
                SELECT submission_id,created_at,created_at AS updated_at,answers_json,'completed' AS response_status,0 AS source_revision FROM survey_responses
                UNION ALL
                SELECT submission_id,created_at,updated_at,answers_json,'in_progress' AS response_status,revision AS source_revision FROM survey_drafts
                WHERE submission_id NOT IN (SELECT submission_id FROM survey_responses)) s
                LEFT JOIN privacy_links l ON l.record_id=s.submission_id AND l.kind='survey'
                LEFT JOIN privacy_consents p ON p.token_hash=l.token_hash
                LEFT JOIN study_assignments a ON a.token_hash=l.token_hash
                LEFT JOIN survey_response_metadata m ON m.submission_id=s.submission_id
                LEFT JOIN study_personality_usage u ON u.token_hash=l.token_hash
                LEFT JOIN study_operation_metrics o ON o.token_hash=l.token_hash
                LEFT JOIN system_prompt_participant_snapshots sp
                    ON sp.token_hash=l.token_hash AND sp.experiment_id=a.experiment_id
                LEFT JOIN (SELECT submission_id, COUNT(*) AS correction_count, MAX(id) AS correction_id,
                    MAX(corrected_at) AS last_corrected_at FROM survey_answer_corrections GROUP BY submission_id) c
                    ON c.submission_id=s.submission_id
                ORDER BY MAX(s.updated_at,COALESCE(c.last_corrected_at,s.updated_at)) DESC, s.submission_id DESC''').fetchall()
            contexts = {row['participant_token_hash']: context_snapshot(row['participant_token_hash'],db) for row in rows}
            diagnostics = {row['participant_token_hash']: operation_diagnostics(row['participant_token_hash'],db) for row in rows}
        result=[]
        for row in rows:
            answers=json.loads(row['answers_json'])
            experiment=answers.get('version') in ('helena-v6', 'helena-v7', 'helena-v8', 'helena-v9', 'helena-v10', 'helena-v11', 'helena-v12', 'helena-v13', 'helena-v14')
            prompt_experiment = experiment and row['experiment_id'] in (EXPERIMENT_ID, 'helena-abc-v4', 'helena-abc-v5', 'helena-abc-v6')
            assignment=StudyAssignments.public(row) if experiment and row['experiment_id'] and row['arm'] else None
            metadata=json.loads(row['metadata_json']) if row['metadata_json'] else {}
            context = (metadata.get('study_context') if row['response_status']=='completed' else None) or contexts.get(row['participant_token_hash'],{})
            ids=metadata.get('release_ids',[])
            usage=(json.loads(row['personality_usage_json']) if row['response_status']=='in_progress' and row['personality_usage_json']
                   else metadata.get('personality_usage') or empty_usage())
            metrics=(json.loads(row['operation_metrics_json']) if row['response_status']=='in_progress' and row['operation_metrics_json']
                     else metadata.get('operation_metrics') or empty_metrics())
            result.append(dict(id=row['submission_id'], participation_id=row['participation_id'] or row['submission_id'],
                               study_context=context,operation_diagnostics=diagnostics.get(row['participant_token_hash'],{}),
                               **{key:context.get('config_revision' if key=='context_config_revision' else key) for key in CONTEXT_EXPORT_FIELDS},
                               personality_usage=usage,operation_metrics=metrics,study_arm=displayed_study_arm(answers), experiment_id=row['experiment_id'] if experiment else '', assigned_at_utc=row['assigned_at'] if experiment else '', prior_exposure=row['prior_exposure'] if experiment else '',
                               system_prompt_policy=(row['system_prompt_policy'] or '') if prompt_experiment else '',
                               system_prompt_revision=(row['system_prompt_revision'] if row['system_prompt_revision'] is not None else '') if prompt_experiment else '',
                               system_prompt_base_sha256=(row['system_prompt_base_sha256'] or '') if prompt_experiment else '',
                               consent_linked=bool(row['participation_id']), submitted_at_utc=row['created_at'] if row['response_status']=='completed' else '',
                               response_status=row['response_status'],last_saved_at_utc=max(row['updated_at'],row['last_corrected_at'] or ''),
                               correction_count=row['correction_count'],last_corrected_at_utc=row['last_corrected_at'] or '',
                               edit_revision=edit_revision(row,row['correction_id']),
                               survey_version=answers.pop('version'), answers=answers, study_release_ids=ids,
                               presentation_versions=sorted({release_presentation(releases[key], assignment) for key in ids if key in releases}),
                               openai_models=sorted({releases[key]['openai_model'] for key in ids if key in releases}),
                               reasoning_efforts=sorted({releases[key]['reasoning_effort'] for key in ids if key in releases})))
        return result

    @staticmethod
    def prompt_fingerprint(row):
        policy = row.get('system_prompt_policy') or ''
        revision = row.get('system_prompt_revision')
        sha256 = row.get('system_prompt_base_sha256') or ''
        if not policy or revision in ('', None) or not sha256:
            return ''
        return f'{policy}:{revision}:{sha256}'

    @classmethod
    def prompt_versions(cls, rows):
        """Return exact, non-secret prompt snapshots represented by these rows."""
        grouped = {}
        for row in rows:
            fingerprint = cls.prompt_fingerprint(row)
            if not fingerprint:
                continue
            item = grouped.setdefault(fingerprint, dict(
                value=fingerprint,
                policy=row['system_prompt_policy'],
                revision=row['system_prompt_revision'],
                sha256=row['system_prompt_base_sha256'],
                arms=set(),
                count=0,
            ))
            item['arms'].add(row.get('study_arm') or '')
            item['count'] += 1
        result = []
        for value, item in grouped.items():
            item['arms'] = sorted(arm for arm in item['arms'] if arm)
            result.append(item)
        return sorted(result, key=lambda item: (
            item['arms'], item['policy'], item['revision'], item['sha256']))

    def filtered(self, query='', version='', status='', arm='', prompt='', study_wave=''):
        return [row for row in self.records() if (not query or query.casefold() in row['participation_id'].casefold())
                and (not version or row['survey_version']==version) and (not status or row['response_status']==status)
                and (not arm or row['study_arm']==arm)
                and (not prompt or self.prompt_fingerprint(row)==prompt)
                and (not study_wave or row.get('study_wave')==study_wave)]

    def _deletion_preview(self, db):
        tables = ('survey_responses', 'survey_drafts', 'study_assignments', 'survey_answer_corrections', 'study_personality_usage', 'study_operation_metrics', 'system_prompt_participant_snapshots')
        snapshot = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY 1')] for table in tables}
        snapshot['privacy_links'] = [tuple(row) for row in db.execute("SELECT * FROM privacy_links WHERE token_hash IN (SELECT token_hash FROM privacy_consents WHERE purpose='study') ORDER BY 1")]
        snapshot['active_consents'] = [tuple(row) for row in db.execute("SELECT token_hash FROM privacy_consents WHERE withdrawn_at IS NULL AND purpose='study' ORDER BY token_hash")]
        return dict(responses=len(snapshot['survey_responses']), drafts=len(snapshot['survey_drafts']),
                    active_consents=len(snapshot['active_consents']), assignments=len(snapshot['study_assignments']),
                    fingerprint=hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest())

    def deletion_preview(self):
        with self.surveys.connect() as db:
            db.execute('BEGIN')
            return self._deletion_preview(db)

    def delete_all(self, fingerprint):
        with self.surveys.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            preview = self._deletion_preview(db)
            if fingerprint != preview['fingerprint']:
                raise ValueError('Die Teilnahmen wurden inzwischen geändert. Bitte den Löschdialog erneut öffnen.')
            chat_ids = [row[0] for row in db.execute("SELECT record_id FROM privacy_links WHERE kind='chat' AND token_hash IN (SELECT token_hash FROM privacy_consents WHERE purpose='study')")]
            db.execute("UPDATE privacy_consents SET withdrawn_at=COALESCE(withdrawn_at, ?) WHERE purpose='study'", (datetime.now(timezone.utc).isoformat(),))
            # Keep revoked consent identities as tombstones, so old sessions cannot
            # recreate deleted answers. This does not close or pause the study.
            for table in ('survey_responses', 'survey_drafts', 'survey_response_metadata', 'survey_answer_corrections', 'study_assignments', 'study_runs', 'study_personality_usage', 'study_operation_metrics', 'system_prompt_participant_snapshots', 'track_events', 'study_chat_reservations'):
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    db.execute(f'DELETE FROM {table}')
            for table in ('privacy_links', 'privacy_consent_history'):
                db.execute(f"DELETE FROM {table} WHERE token_hash IN (SELECT token_hash FROM privacy_consents WHERE purpose='study')")
            db.executemany('DELETE FROM chat_sessions WHERE id=?',[(sid,) for sid in chat_ids])
        for sid in chat_ids:
            self.sessions.delete(sid)
        return preview

    def detail(self, response_id):
        row=next((row for row in self.records() if row['id']==response_id),None)
        if row:
            links=self.privacy.participant_records(row['participation_id']) if row['consent_linked'] else None
            row['deletion_count']=links.get('survey',1) if links is not None else 1
            row['editable']=True
            row['corrections']=self.corrections(response_id,row['correction_count'])
            row['definition']=SURVEY_DEFINITION if row['survey_version']==SURVEY_VERSION else V13_SURVEY_DEFINITION if row['survey_version']=='helena-v13' else V12_SURVEY_DEFINITION if row['survey_version']=='helena-v12' else V11_SURVEY_DEFINITION if row['survey_version']=='helena-v11' else V10_SURVEY_DEFINITION if row['survey_version']=='helena-v10' else V9_SURVEY_DEFINITION if row['survey_version']=='helena-v9' else V8_SURVEY_DEFINITION if row['survey_version']=='helena-v8' else V7_SURVEY_DEFINITION if row['survey_version']=='helena-v7' else V6_SURVEY_DEFINITION if row['survey_version']=='helena-v6' else V5_SURVEY_DEFINITION if row['survey_version']=='helena-v5' else V4_SURVEY_DEFINITION if row['survey_version']=='helena-v4' else LEGACY_SURVEY_DEFINITION
            if row['survey_version']=='helena-v6':
                # Admin display uses A/B, but answers and archived branching keep
                # the original B/C codes for reproducible historical exports.
                row['definition']=deepcopy(row['definition'])
                for field in row['definition']['demographics']['fields']:
                    if field['name']=='study_arm':
                        field['options']=[['B','A – Neutrales Suchsystem (historisch mit Scores und Begründungen)'],
                                          ['C','B – Personalisierter Chat- und Suchbot']]
            if row['survey_version']=='helena-v1':
                row['definition']={'version':'helena-v1','demographics':{'fields':[
                    dict(name=name,title=title,kind='scale' if name=='chat_helpfulness' else 'text' if name=='feedback' else 'choice',
                         minimum=1, maximum=5, maxLength=4000, optional=name=='feedback',options=list(ADDED_VALUE_LABELS.items()) if name=='added_value'
                         else list(PREFERENCE_LABELS.items()) if name=='future_preference' else [])
                    for name,title in zip(LEGACY_FIELDS,QUESTIONS)]},'categories':[]}
            elif row['survey_version']=='helena-v2':
                row['definition']=deepcopy(row['definition'])
                row['definition']['version']='helena-v2'
                for group in [row['definition']['demographics'],*row['definition']['categories']]:
                    group['fields']=[field for field in group['fields'] if field['name'] in SurveySubmissionV2.model_fields]
        return row

    def corrections(self, response_id, count=None):
        with self.surveys.connect() as db:
            # Bind history to the same correction count as the exported answer
            # snapshot even if another admin saves while the export is generated.
            history=db.execute('SELECT * FROM survey_answer_corrections WHERE submission_id=? ORDER BY id LIMIT ?',
                               (response_id,-1 if count is None else count)).fetchall()
        result=[]
        for item in reversed(history):
            before,after=json.loads(item['before_json']),json.loads(item['after_json'])
            result.append(dict(corrected_at=item['corrected_at'],reason=item['reason'],actor=item['actor'],
                response_status=item['response_status'],before=before,after=after,
                changes=[dict(field=key,before=before.get(key),after=after.get(key))
                         for key in sorted(set(before)|set(after)) if before.get(key)!=after.get(key)]))
        return result

    def correct(self, response_id, correction):
        with self.surveys.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('''SELECT submission_id,created_at AS updated_at,answers_json,
                'completed' AS response_status,0 AS source_revision FROM survey_responses WHERE submission_id=?''',(response_id,)).fetchone()
            if row is None:
                row=db.execute('''SELECT submission_id,updated_at,answers_json,'in_progress' AS response_status,
                    revision AS source_revision FROM survey_drafts WHERE submission_id=?''',(response_id,)).fetchone()
            if row is None:
                raise LookupError('Antwort nicht gefunden.')
            latest=db.execute('SELECT COALESCE(MAX(id),0) FROM survey_answer_corrections WHERE submission_id=?',(response_id,)).fetchone()[0]
            if correction.edit_revision!=edit_revision(row,latest):
                raise SurveyConflict('Der Antwortstand wurde inzwischen geändert. Bitte die Einzelantwort neu öffnen und die Korrektur prüfen.')
            before=json.loads(row['answers_json']); version=before['version']
            if set(correction.answers)!=set(before)-{'version'}:
                raise ValueError('Bitte alle Antwortfelder dieser Fragebogenversion übermitteln. Teilnahme und Metadaten können nicht geändert werden.')
            if correction.answers.get('study_arm')!=before.get('study_arm'):
                raise ValueError('Die ursprüngliche Studienzuordnung kann nicht geändert werden.')
            if row['response_status']=='completed':
                validated=SurveyRequest.model_validate(dict(submission_id=response_id,version=version,**correction.answers)).root
                after=validated.model_dump(exclude={'submission_id'})
            else:
                validated=SurveyDraftRequest.model_validate(dict(submission_id=response_id,version=version,
                    revision=row['source_revision'],answers=correction.answers)).root
                after=dict(version=version,**validated.answers.model_dump())
            if after==before:
                return False
            now=datetime.now(timezone.utc).isoformat()
            canonical=json.dumps(after,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            db.execute('''INSERT INTO survey_answer_corrections
                (submission_id,corrected_at,reason,actor,response_status,before_json,after_json) VALUES (?,?,?,?,?,?,?)''',
                (response_id,now,correction.reason,'admin',row['response_status'],row['answers_json'],canonical))
            if row['response_status']=='completed':
                db.execute('UPDATE survey_responses SET answers_json=? WHERE submission_id=?',(canonical,response_id))
            else:
                db.execute('UPDATE survey_drafts SET answers_json=?,updated_at=?,revision=revision+1 WHERE submission_id=?',
                    (canonical,now,response_id))
        return True

    def delete(self, response_id, confirmation_id):
        row=self.detail(response_id)
        if not row or row['participation_id']!=confirmation_id:
            return False
        if row['consent_linked']:
            for sid in self.privacy.delete_participant(row['participation_id']):self.sessions.delete(sid)
        else:
            with self.surveys.connect() as db:
                db.execute('DELETE FROM survey_response_metadata WHERE submission_id=?',(response_id,))
                db.execute('DELETE FROM survey_responses WHERE submission_id=?',(response_id,))
                db.execute('DELETE FROM survey_drafts WHERE submission_id=?',(response_id,))
        return True

    def _all_codebook(self, columns='readable'):
        validate_columns(columns)
        result=[dict(variable=key,question=META_TITLES[key][1],level='nominal',codes={},missing='empty',versions=['helena-v1','helena-v2','helena-v3','helena-v4','helena-v5','helena-v6','helena-v7','helena-v8','helena-v9','helena-v10','helena-v11','helena-v12','helena-v13','helena-v14']) for key in META_FIELDS]
        for item in result:
            if item['variable']=='study_arm':
                item['codes']=dict(ARM_CODES)
                item['notes']=ARM_VERSION_NOTE
            if item['variable']=='system_prompt_policy':
                item['codes']={'unprompted':'A: optionaler Basisprompt (leer: kein Systemprompt)', 'career_fixed':'B: fester Top-Berufsberater', 'custom_career':'C: selbst gestaltbar auf Berufsberater-Basis'}
                item['versions']=['helena-v11','helena-v12','helena-v13','helena-v14']
                item['notes']='Seit helena-abc-v4; genaue Experimentkennung beachten. Der Prompttext selbst wird aus Datenschutz- und Exporthygienegründen nicht exportiert.'
            if item['variable']=='system_prompt_revision':
                item['level']='ordinal'
                item['versions']=['helena-v11','helena-v12','helena-v13','helena-v14']
                item['notes']='Positive Revision der für diese Teilnahme eingefrorenen Fassung. Bei A kann der Text dieser Fassung leer sein; die SHA-256-Prüfsumme dokumentiert dies. Eine leere Zelle bedeutet historisch oder noch nicht gebunden.'
            if item['variable']=='system_prompt_base_sha256':
                item['versions']=['helena-v11','helena-v12','helena-v13','helena-v14']
                item['notes']='Prüfsumme des unveränderlich zugeordneten Basis-Systemprompts; kein Prompttext. Bei C wird die selbst gestaltete Persönlichkeit anschließend dynamisch an diesen Basisprompt angefügt und ist nicht Bestandteil dieser Prüfsumme. Der leere A-Prompt besitzt die SHA-256-Prüfsumme des leeren Textes und sendet trotzdem keine Systemnachricht.'
            if item['variable']=='study_wave': item['codes']={'pretest':'Pretest, nicht für Hauptvergleiche','main':'Hauptstudie'}
            if item['variable'] in ('viewport_class','viewport_class_last'): item['codes']={'mobile':'Mobilansicht bis 850 CSS-Pixel','desktop':'Desktopansicht über 850 CSS-Pixel'}
            if item['variable']=='furthest_step_reached': item['codes']={'consent':'Einwilligung','profile':'Gültiges Profil übermittelt','first_search':'Erste Suche abgeschlossen','chat':'Eigene Chatnachricht erfolgreich beantwortet','questionnaire_started':'Erfahrungsbefragung geöffnet','questionnaire_completed':'Befragung abgeschlossen'}
            if item['variable']=='prior_exposure': item['codes']={'0':'Keine frühere HELENA-Suchsitzung unter dieser Teilnahme-ID','1':'Frühere HELENA-Suchsitzung vorhanden'}
            if item['variable']=='correction_count': item['notes']='Anzahl explizit gespeicherter Verwaltungskorrekturen; Originalwerte und Gründe bei korrigierten Teilnahmen in answer_corrections.json.'
            if item['variable']=='last_corrected_at_utc': item['notes']='Zeitpunkt der letzten Verwaltungskorrektur; submitted_at_utc bleibt der ursprüngliche Abschlusszeitpunkt.'
            if item['variable'].startswith('personality_'):
                item['notes']='Automatische Metadaten tatsächlich angewendeter Auswahlen, getrennt von der Selbstauskunft personality_customized. Nur seit ki_erstmals_angewendet_am_utc beobachtet; historische Nutzung wird nicht rekonstruiert. Abgeschlossene Teilnahmen verwenden den Stand bei Abgabe, Entwürfe den aktuellen Stand. Keine Inhalte oder Namen selbst gestalteter Persönlichkeiten.'
                if item['variable'].endswith('_source'):
                    item['codes']=dict(template='Unveränderte Vorlage', custom='Selbst gestaltet oder Vorlage angepasst', unknown='Nicht erfasst / unbekannt', not_applicable='Für Variante A nicht anwendbar')
                elif item['variable'].endswith('_template_id'):
                    item['codes']=dict(career='Top-Berufsberater', expert='Fachexperte')
                    item['missing']='empty; keine unveränderte Vorlage angewendet oder Herkunft unbekannt; zugehörige Herkunftsspalte beachten'
                elif item['variable'] in ('personality_ever_custom','personality_ever_template'):
                    item['codes']={'0':'Im erfassten Zeitraum nicht beobachtet','1':'Im erfassten Zeitraum beobachtet'}
                    item['missing']='empty; nicht vollständig erfasst / mindestens ein unbekannter Abschnitt. 1 bleibt gültig, sobald eine entsprechende Nutzung beobachtet wurde. 0 bedeutet nicht, dass vor Erfassungsbeginn keine solche Nutzung stattfand.'
                elif item['variable']=='personality_capture_version':
                    item['codes']={'0':'Keine erfassten Nutzungsmetadaten','1':'Erfassungsschema Version 1'}
                elif item['variable']=='personality_selection_change_count':
                    item['level']='ratio';item['minimum']=0
                    item['notes']+=' Keine Anzahl einzelner Bearbeitungen. Unveränderte erneute Anwendung zählt nicht als Wechsel; Übergänge von unbekannter zu bekannter Auswahl zählen mit.'

            if item['variable'].startswith('operations_'):
                item['notes']='Serverseitig aggregierte abgeschlossene Operationen seit Erfassungsbeginn; seit Erfassungsversion 2 zusätzlich separate Operationsereignisse in operation_events.csv, ohne Eingabetexte. Abgeschlossene Teilnahmen verwenden den Stand bei Abgabe; Entwürfe den aktuellen Stand. Wiederholte Versuche zählen separat. 0 bezieht sich nur auf den erfassten Zeitraum; historische Lücken bleiben unbekannt.'
                if item['variable']=='operations_capture_version':
                    item['codes']={'0':'Keine erfassten Operationsmetadaten','1':'Aggregierte Zähler Version 1','2':'Zähler plus separate sichere Operationsereignisse Version 2'}
                else:
                    item['level']='ratio';item['minimum']=0
                    item['missing']='empty; nicht erfasst / historisch unbekannt'
                    if item['variable'].endswith('_duration_ms'):
                        item['unit']='ms'
                        item['notes']+=' Summe der Laufzeiten aller erfolgreichen und fehlgeschlagenen Operationen dieses Typs. Chat mit Suche/Neusortierung zählt zusätzlich als Chat; die Zeit enthält diese Operation. Zeitspalten überlappen und dürfen nicht zur Gesamtteilnahmedauer addiert werden.'

        for field in LEGACY_SURVEY_FIELDS:
            scale=field.get('scale',{'low':'Trifft überhaupt nicht zu','high':'Trifft voll und ganz zu'})
            result.append(dict(variable=field['name'],question=field['title'],
                versions=['helena-v3'] if field['name'].endswith('_usefulness') else ['helena-v2','helena-v3'],
                level='ordinal' if field['kind']=='scale' or field['name']=='age_group' else 'nominal' if field['kind']=='choice' else 'text',
                codes={str(i):label for i,(code,label) in enumerate(field.get('options',[]),1) if code!='not_specified'} if field['kind']=='choice' else {},
                original_codes={str(i):code for i,(code,_) in enumerate(field.get('options',[]),1) if code!='not_specified'},
                minimum=1 if field['kind']=='scale' else None,maximum=10 if field['kind']=='scale' else None,
                endpoints=scale if field['kind']=='scale' else None,missing='empty; not asked in this questionnaire version, missing, or explicit Keine Angabe'))
        for name,question in zip(LEGACY_FIELDS,QUESTIONS):
            result.append(dict(variable='v1_'+name,question=question,versions=['helena-v1'],level='ordinal' if name in ('chat_helpfulness','future_preference') else 'nominal' if name=='added_value' else 'text',minimum=1 if name=='chat_helpfulness' else None,maximum=5 if name=='chat_helpfulness' else None,endpoints={'low':'Gar nicht hilfreich','high':'Sehr hilfreich'} if name=='chat_helpfulness' else None,missing='empty for other questionnaire versions or optional empty feedback',codes=ADDED_VALUE_LABELS if name=='added_value' else PREFERENCE_LABELS if name=='future_preference' else {}))
        for version, fields in VERSIONED_FIELDS.items():
            for field in fields:
                codes=choice_codes(field)
                result.append(dict(variable=version[6:]+'_' +field['name'], question=field['title'],
                    level=field.get('level', 'ordinal' if field['kind']=='scale' or field['name']=='age_group' else 'nominal' if field['kind']=='choice' else 'text'),
                    codes={str(codes[code]):label for code,label in field.get('options',[]) if code in codes},
                    original_codes={str(value):code for code,value in codes.items()},
                    minimum=field.get('scale',{}).get('min',1) if field['kind']=='scale' else None, maximum=field.get('scale',{}).get('max',10) if field['kind']=='scale' else None,
                    endpoints=field.get('scale'), visible_if=field.get('visibleIf'), versions=[version],
                    notes=ARM_VERSION_NOTE if field['name']=='study_arm' else '',
                    missing='empty; see companion _status column. No=0 is a valid answer.'))
                result.append(dict(variable=version[6:]+'_' +field['name']+'_status', question='Antwortstatus: '+field['title'], level='nominal',
                    codes=dict(answered='Beantwortet', not_used='Nicht genutzt', not_assessable='Kann ich nicht beurteilen',
                        not_specified='Keine Angabe', skipped='Durch Filterführung übersprungen', no_answer='Optionales Feld leer', not_asked='Andere Fragebogenversion', unanswered='Noch nicht beantwortet'),
                    missing='none', visible_if=field.get('visibleIf'), versions=[version]))
        for item in result:
            technical = item['variable']
            if technical.endswith(('_personalized_search_usefulness', '_system_usefulness')):
                item['notes']=item.get('notes','')+' Historische Frage; seit V12 nicht mehr erhoben (deprecated). Historische Antworten bleiben unverändert erhalten.'
            if (item.get('endpoints') or {}).get('labels'):
                item['codes']={str(index+1):label for index,label in enumerate(item['endpoints']['labels'])}
            item['technical_variable'] = technical
            item['variable'] = export_name(technical, columns)
            item['reverse_direction'] = technical.endswith('_search_effort')
            item['direction'] = ('Hoher Wert bedeutet mehr Aufwand; gegenläufig zu den Nutzenbewertungen. Nicht automatisch umgepolt.'
                if item['reverse_direction'] else
                ('Hoher Wert: ' + item['endpoints']['high'] if item.get('endpoints') else 'Keine gemeinsame Bewertungsrichtung; Codes und Originalfrage beachten.'))
            if item.get('visible_if'):
                prefix = technical.split('_', 1)[0]
                item['visible_if_export'] = dict(item['visible_if'], field=export_name(prefix + '_' + item['visible_if']['field'], columns))
            if technical == 'response_status':
                item['codes'] = {'completed': 'Abgeschlossen', 'in_progress': 'Unvollständig'}
        return result

    def codebook(self, columns='readable'):
        """The public export documents only the active questionnaire."""
        book = [item for item in self._all_codebook(columns)
                if item['technical_variable'] in META_FIELDS or item['technical_variable'].startswith('v14_')]
        by_name = {field['name']: field for field in SURVEY_FIELDS}
        for item in book:
            item['versions'] = [SURVEY_VERSION]
            technical = item['technical_variable']
            if technical == 'study_arm' or technical == 'v14_study_arm':
                item['notes'] = 'A: Basissystem; B: fester Top-Berufsberater; C: selbst gestaltete KI-Beratung. Aktuelles Experiment helena-abc-v7.'
                if technical == 'study_arm':
                    item['codes'] = {'A':'Basissystem', 'B':'Fester Top-Berufsberater', 'C':'Selbst gestaltete KI-Beratung'}
            field = by_name.get(technical.removeprefix('v14_'))
            if field:
                item.update({key:field.get(key) for key in ('framework','construct','source_item','source_url','adaptation','item_type')})
                item['notes'] = (item.get('notes','') + ' ' + ' | '.join(str(field[key]) for key in ('framework','source_item','source_url','adaptation') if field.get(key))).strip()
                if field.get('reverse') or field['name']=='study_effort':
                    item['reverse_direction'] = True
                    item['direction'] = 'Hoher Wert bedeutet mehr Aufwand; kein Bestandteil der drei Konstruktmittelwerte.'
        for construct in SURVEY_DEFINITION.get('constructs', []):
            technical = f"v14_{construct['id']}_mean"
            book.append(dict(variable=export_name(technical, columns), technical_variable=technical,
                question=construct['title']+f" – Mittelwert aus {len(construct['items'])} Items", level='scale_score', codes={},
                minimum=construct['min'], maximum=construct['max'], versions=[SURVEY_VERSION],
                missing=f"empty unless all {len(construct['items'])} items are numeric 1–7; no imputation",
                item_type='multi_item_score', notes=f"Arithmetischer Mittelwert je Teilnahme nur bei {len(construct['items'])} gültigen Antworten. Projektspezifische deutsche Adaptation; Skalenqualität prüfen, kein Gesamtwert über Konstrukte.",
                construct=construct['id'], items=construct['items'], scoring=construct['scoring'],
                reverse_direction=False, direction='Hoher Wert bedeutet höhere Zustimmung zum Konstrukt.'))
        return book

    def csv_data(self, rows, delimiter=';', columns='readable'):
        from survey_analytics import construct_value
        stream=io.StringIO(newline='');writer=csv.writer(stream,delimiter=delimiter)
        question_columns=[column for field in SURVEY_FIELDS for column in ('v14_'+field['name'],'v14_'+field['name']+'_status')]
        constructs=SURVEY_DEFINITION.get('constructs', [])
        writer.writerow(export_headers(META_FIELDS+question_columns+['v14_'+item['id']+'_mean' for item in constructs], columns))
        for row in rows:
            if row['survey_version'] != SURVEY_VERSION:
                continue
            values=[row['participation_id'],row['submitted_at_utc'],row['survey_version'],
                    '|'.join(row['study_release_ids']),'|'.join(row['openai_models']),'|'.join(row['reasoning_efforts']),row['response_status'],row['last_saved_at_utc'],row['study_arm'],row['experiment_id'],row['assigned_at_utc'],row['prior_exposure'],row.get('system_prompt_policy',''),row.get('system_prompt_revision',''),row.get('system_prompt_base_sha256',''),'|'.join(row.get('presentation_versions',[])),row.get('correction_count',0),row.get('last_corrected_at_utc','')]
            usage=row.get('personality_usage') or empty_usage()
            values.extend(int(usage[key]) if isinstance(usage.get(key),bool) else usage.get(key,'') for key in USAGE_FIELDS)
            metrics=row.get('operation_metrics') or empty_metrics()
            values.extend(metrics.get(key,'') for key in METRIC_FIELDS)
            values.extend(row.get(key,'') for key in CONTEXT_EXPORT_FIELDS)
            for field in SURVEY_FIELDS:
                status=answer_status(field,row['answers'])
                value=row['answers'].get(field['name'],'') if status=='answered' else ''
                if field['kind']=='choice' and status=='answered': value=choice_codes(field)[value]
                values.extend([value,status])
            values.extend(construct_value(row['answers'], construct) for construct in constructs)
            writer.writerow([spreadsheet_text(value) if isinstance(value,str) else value for value in values])
        return stream.getvalue().encode('utf-8-sig')

    def participation_flow(self, study_wave=''):
        from survey_analytics import construct_value
        with self.surveys.connect() as db:
            assignments=db.execute("""SELECT a.token_hash,a.arm FROM study_assignments a
                JOIN privacy_consents p ON p.token_hash=a.token_hash
                WHERE a.experiment_id=? AND p.purpose='study' AND p.withdrawn_at IS NULL""",(EXPERIMENT_ID,)).fetchall()
            records=db.execute("""SELECT l.token_hash,s.answers_json,s.completed FROM privacy_links l
                JOIN (SELECT submission_id,answers_json,1 AS completed FROM survey_responses
                    UNION ALL SELECT submission_id,answers_json,0 FROM survey_drafts
                    WHERE submission_id NOT IN (SELECT submission_id FROM survey_responses)) s ON s.submission_id=l.record_id
                WHERE l.kind='survey' AND json_extract(s.answers_json,'$.version')=?""",(SURVEY_VERSION,)).fetchall()
            contexts = {a['token_hash']:context_snapshot(a['token_hash'],db) for a in assignments}
        by_token={}
        for record in records:by_token.setdefault(record['token_hash'],[]).append(record)
        cohorts={}
        for assignment in assignments:
            if study_wave and contexts[assignment['token_hash']].get('study_wave') != study_wave:continue
            arm=assignment['arm']
            row=cohorts.setdefault(arm,dict(experiment_id=EXPERIMENT_ID,studiengruppe=arm,
                umfang='ungefilterter_aktiver_studienbestand',zugeteilt_anzahl=0,antworten_gespeichert_anzahl=0,
                abgeschlossen_anzahl=0,**{c['id']+'_vollstaendig_anzahl':0 for c in SURVEY_DEFINITION['constructs']}))
            row['zugeteilt_anzahl']+=1
            records=by_token.get(assignment['token_hash'],[])
            row['antworten_gespeichert_anzahl']+=bool(records)
            row['abgeschlossen_anzahl']+=any(item['completed'] for item in records)
            for construct in SURVEY_DEFINITION['constructs']:
                row[construct['id']+'_vollstaendig_anzahl']+=any(construct_value(json.loads(item['answers_json']),construct) is not None for item in records)
        return [cohorts[arm] for arm in sorted(cohorts)]

    def participation_flow_csv(self, study_wave=''):
        stream=io.StringIO(newline='')
        fields=['experiment_id','studiengruppe','umfang','zugeteilt_anzahl','antworten_gespeichert_anzahl','abgeschlossen_anzahl',
                *[item['id']+'_vollstaendig_anzahl' for item in SURVEY_DEFINITION['constructs']]]
        writer=csv.DictWriter(stream,fieldnames=fields,delimiter=';');writer.writeheader();writer.writerows(self.participation_flow(study_wave))
        return stream.getvalue().encode('utf-8-sig')

    def package(self, rows, columns='readable', study_wave=''):
        stream=io.BytesIO();book=self.codebook(columns);csvbook=io.StringIO(newline='');writer=csv.writer(csvbook,delimiter=';')
        writer.writerow(['variable','question','measurement_level','codes','original_codes','minimum','maximum','endpoints','missing','visible_if','versions','notes','technical_variable','reverse_direction','direction','visible_if_export','unit','framework','construct','source_item','source_url','adaptation','items','scoring','item_type'])
        for field in book:writer.writerow([field['variable'],field['question'],field['level'],json.dumps(field.get('codes',{}),ensure_ascii=False),json.dumps(field.get('original_codes',{}),ensure_ascii=False),field.get('minimum'),field.get('maximum'),json.dumps(field.get('endpoints'),ensure_ascii=False),field['missing'],json.dumps(field.get('visible_if'),ensure_ascii=False),json.dumps(field.get('versions', ['helena-v1'] if field['variable'].startswith('v1_') else ['helena-v2','helena-v3']),ensure_ascii=False),field.get('notes',''),field['technical_variable'],field['reverse_direction'],field['direction'],json.dumps(field.get('visible_if_export'),ensure_ascii=False),field.get('unit',''),*[json.dumps(field.get(key,''),ensure_ascii=False) if isinstance(field.get(key), (dict,list)) else field.get(key,'') for key in ('framework','construct','source_item','source_url','adaptation','items','scoring','item_type')]])
        ids={key for row in rows for key in row['study_release_ids']};releases=self.releases.all()
        manifest=dict(exported_at=datetime.now(timezone.utc).isoformat(),rows=len(rows),column_names=columns,
                      observed_releases={key:releases[key] for key in ids if key in releases},
                      current_configuration=self.releases.manifest,
                      note='Current configuration is not assigned retrospectively to old answers. Empty metadata means unknown, not the current model.')
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('helena_numiqo.csv',self.csv_data(rows,columns=columns))
            archive.writestr('teilnahmefluss.csv',self.participation_flow_csv(study_wave))
            archive.writestr('analysis_input.csv',self.csv_data(rows,columns='technical'))
            from study_context import context_csv, scoring_csv
            from study_metrics import operation_events_csv
            with self.surveys.connect() as db:
                identifiers={row['participation_id'] for row in rows}
                archive.writestr('studienkontext_alle_einwilligungen.csv',context_csv(db,version=SURVEY_VERSION,wave=study_wave or None))
                archive.writestr('scoring_calls.csv',scoring_csv(db,identifiers))
                archive.writestr('operation_events.csv',operation_events_csv(db,identifiers))
            mapping=io.StringIO(newline='');mapping_writer=csv.writer(mapping,delimiter=';')
            mapping_writer.writerow(['technischer_name','export_spalte','beschreibung_frage','fragebogen_versionen'])
            mapping_writer.writerows([item['technical_variable'],item['variable'],item['question'],'|'.join(item['versions'])] for item in book)
            archive.writestr('spaltenzuordnung.csv',mapping.getvalue().encode('utf-8-sig'))
            archive.writestr('codebook.csv',csvbook.getvalue().encode('utf-8-sig'))
            archive.writestr('codebook.json',json.dumps(book,ensure_ascii=False,indent=2))
            archive.writestr('study_manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            corrections=[dict(participation_id=row['participation_id'],survey_version=row['survey_version'],corrections=self.corrections(row['id'],row['correction_count']))
                         for row in rows if row.get('correction_count')]
            if corrections:
                archive.writestr('answer_corrections.json',json.dumps(corrections,ensure_ascii=False,indent=2))
            archive.writestr('README.txt',EXPORT_README)
        return stream.getvalue()

EXPORT_README = """HELENA V14: Auswahl und deutsche Adaptation aus ResQue und CRS-Que.
Es wird ausschließlich der aktive Fragebogen exportiert. Deutsche Spaltennamen sind der Standard;
spaltenzuordnung.csv ordnet technische Schlüssel, Spaltennamen und vollständige Fragen zu.
Numiqo: CSV mit UTF-8 und Semikolon importieren. Eine Zeile je gespeichertem Antwortdatensatz;
Teilnahme-ID vor inferenzstatistischen Analysen auf Eindeutigkeit prüfen.
Alle Bewertungsitems verwenden dieselbe siebenstufige Zustimmungsskala (1–7).
Nutzen, Kontrolle und Transparenz werden getrennt aus je drei gültigen numerischen Items berechnet.
Vertrauen ist eine eigenständig adaptierte Zweiergruppe; der Mittelwert benötigt beide gültigen Items. Sobald ein Item fehlt oder nicht beurteilbar ist, bleibt der Mittelwert leer.
Es gibt keine Imputation, keine automatische Umpolung und keinen Gesamtwert über alle Konstrukte.
Die Frameworkquellen, Itemzuordnung und Anpassungen stehen im Codebuch. Übersetzung, Auswahl,
Jobsuchkontext und siebenstufige Harmonisierung begründen keine automatische Validierung der Adaptation.
Die Gesprächsmerkmale und HELENA-Zusatzitems und der Manipulationscheck werden einzeln ausgewertet.
_study_effort ist gegenläufig; höhere Werte bedeuten höheren Aufwand.
_antwortstatus unterscheidet fehlende, nicht beurteilbare und nicht gestellte Fragen. Leere Zellen sind
fehlende Werte, niemals 0. 'Kann ich nicht beurteilen' ist keine neutrale Zustimmung.
response_status/teilnahme_status trennt completed und in_progress. teilnahmefluss.csv zählt alle aktiven
Zuordnungen des aktuellen Experiments unabhängig von Antwortfiltern, ein Mal pro Teilnahme-ID.
Korrekturen sind in Diagrammen/CSV enthalten; answer_corrections.json enthält Originale und Gründe.
Studiengruppen, Promptfassungen und Systemstände gesondert beachten; keine rückwirkende Zuweisung.
Freitext mit Formelpräfix ist gegen Tabellenformeln geschützt. Keine automatische Datenübertragung.
studienkontext_alle_einwilligungen.csv enthält zusätzlich frühe Abbrüche ohne Antworten für die gewählte Welle.
Dieser Kontextbestand ignoriert Antwortstatus-, Gruppen- und Promptfilter; sein Umfang ist separat ausgewiesen.
scoring_calls.csv und operation_events.csv enthalten nur die ausgewählten Antwortteilnahmen.
analysis_input.csv hat technische Spalten für research/v14/analyze.py; nur main für Hauptanalysen.
Pretest und alte Fragebogenversionen nicht zusammenführen. Sichtbarkeit ist kein Nachweis des Lesens.
Die exportierten Daten sind pseudonymisiert, nicht anonym.
"""
