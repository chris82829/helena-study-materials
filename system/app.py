"""Flask API for the hybrid matching prototype. Run: python app.py"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import secrets
import time
from contextlib import contextmanager
from pathlib import Path

import click
from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request, send_from_directory, stream_with_context
from flask_cors import CORS
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from data_store import JobStore
from llm_service import (MODEL, REASONING_EFFORT, LLMUnavailable, OpenAIService,
                         PersonaResult, unprompted_persona)
from retrieval import EmbeddingUnavailable, HybridRetriever
from schemas import ChatInput, Profile, SearchInput
from session_store import SessionConflict, SessionStore, EphemeralSessionStore
from index_state import read_progress, write_progress
from advisor import AdvisorConfig, resolve_advisor
from persona_mlds import MLDSError, advisor_to_mlds, advisor_from_mlds, load_templates, load_neutral_advisor
from study_usage import StudyPersonalityUsage, normalize_selection
from study_metrics import StudyOperationMetrics
from study_context import StudyContext, context_snapshot
from study_telemetry import register_telemetry
from study_progress import StudyChatRequired, chat_progress, require_study_chat, has_experience_answers
from study_chat_limit import StudyChatLimit, ChatMessageLimit, ChatReservationExpired, MAX_USER_CHAT_MESSAGES
from study_assignment import StudyAssignments, EXPERIMENT_ID, PREVIOUS_FRAMEWORK_EXPERIMENT_ID, PREVIOUS_PERSONALITY_EXPERIMENT_ID, PREVIOUS_QUESTIONNAIRE_EXPERIMENT_ID, personality_policy, presentation_policy, advisor_for_policy, PersonalityPolicyError
from test_access import test_notice, TEST_PURPOSES
from survey_store import SurveyConflict, SurveyStore, SurveyRequest, SurveyDraftRequest, SURVEY_VERSION
from privacy import PrivacyStore, ConsentInput, ConsentRequired, load_notice, token_hash
from study_release import StudyReleases
from system_prompt_store import SystemPromptStore
from admin import register_admin

BASE_DIR = Path(__file__).resolve().parent
MATCHING_POLICY_VERSION = 'employment-only-v1'
# Bump when persona instructions or its output contract change incompatibly.
PERSONA_CACHE_VERSION = 'search-persona-v2'
NEUTRAL_PRESENTATION_VERSION = 'random-order-generic-chat-v2'


def neutral_card_order(cards, seed=None):
    """A random permutation of retrieved cards, stable for a retained search pool.

    Canonical input order prevents LLM scores/order from influencing the shuffle.
    The seed remains private in the session, never supplied by the participant.
    """
    seed = seed or secrets.token_hex(16)
    ordered = sorted(cards, key=lambda card: str(card['id']))
    random.Random(seed).shuffle(ordered)
    return ordered, seed


def outdated_neutral_presentation(state):
    return (bool(state.get('jobs')) and resolve_advisor(state.get('advisor'))['neutral']
            and state.get('_presentation_version') != NEUTRAL_PRESENTATION_VERSION)


def persona_fingerprint(profile, prompt_policy=None):
    """Fingerprint all applicant inputs; only the owning session stores this value."""
    canonical = json.dumps(Profile.model_validate(profile).model_dump(mode='json'),
                           sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    policy = prompt_policy or 'legacy'
    return f'{PERSONA_CACHE_VERSION}:{policy}:{hashlib.sha256(canonical.encode()).hexdigest()}'


def reusable_persona(persona, saved_fingerprint, current_fingerprint):
    if saved_fingerprint != current_fingerprint:
        return False
    try:
        PersonaResult.model_validate(persona)
    except ValidationError:
        return False
    return True


def project_path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


def merge_profile(profile, patch):
    """None preserves a value; [] clears a list; max-hours has an explicit clear flag."""
    merged = {**profile, 'filters': dict(profile['filters'])}
    for key in ('query', 'skills', 'preferences'):
        if patch.get(key) is not None:
            merged[key] = patch[key]
    filters = patch.get('filters') or {}
    for key in ('employment_types', 'locations', 'remote'):
        if filters.get(key) is not None:
            merged['filters'][key] = filters[key]
    if filters.get('clear_max_hours'):
        merged['filters']['max_hours'] = None
    elif filters.get('max_hours') is not None:
        merged['filters']['max_hours'] = filters['max_hours']
    return Profile.model_validate(merged).model_dump()


def describe_filters(filters):
    labels = {'werkstudent': 'Werkstudent', 'praktikum': 'Praktikum', 'vollzeit': 'Vollzeit',
              'teilzeit': 'Teilzeit', 'ausbildung': 'Ausbildung', 'trainee': 'Trainee',
              'abschlussarbeit': 'Abschlussarbeit', 'sonstige': 'Sonstige'}
    types = filters.get('employment_types') or []
    return f"Stellenarten: {', '.join(labels.get(x, x) for x in types)}" if types else 'alle Stellenarten'


def profile_changes(before, after):
    """Ignore list order/casing; only changed retrieval inputs need another search."""
    def comparable(value):
        if isinstance(value, str):
            return ' '.join(value.casefold().split())
        if isinstance(value, list):
            return sorted({comparable(item) for item in value})
        if isinstance(value, dict):
            return {key: comparable(item) for key, item in value.items()}
        return value
    core = any(comparable(before.get(key)) != comparable(after.get(key))
               for key in ('query', 'skills'))
    before_filters, after_filters = before.get('filters') or {}, after.get('filters') or {}
    core = core or comparable(before_filters.get('employment_types', [])) != comparable(after_filters.get('employment_types', []))
    soft = any(comparable(before.get(key)) != comparable(after.get(key))
               for key in ('preferences', 'cv_text'))
    soft = soft or any(comparable(before_filters.get(key)) != comparable(after_filters.get(key))
                       for key in ('locations', 'remote', 'max_hours'))
    return core, soft


def restricted_legacy_pool(state):
    """Older sessions may have discarded jobs using now-soft preferences."""
    filters = (state.get('profile') or {}).get('filters') or {}
    return (state.get('_matching_policy_version') != MATCHING_POLICY_VERSION
            and bool(filters.get('locations') or filters.get('remote')
                     or filters.get('max_hours') is not None))


def public_state(state):
    """Expose evaluated job cards while keeping retrieval pools and caches private."""
    public = {**{key: value for key, value in state.items() if not key.startswith('_')},
            'candidate_pool': {'available': '_candidates' in state,
                               'count': len(state.get('_candidates', [])),
                               'refresh_required': restricted_legacy_pool(state)}}
    if resolve_advisor(state.get('advisor'))['neutral']:
        # The baseline has plain job cards. Keep assessment evidence only inside
        # the session for the identical retrieval/reranking pipeline, never in API cards.
        public['jobs'] = [{key: value for key, value in job.items()
                           if key not in ('match', 'retrieval')} for job in state.get('jobs', [])]
    return public


def welcome_message(result):
    """Use final card counts, not model guesses or the whole prefiltered corpus."""
    jobs = result['jobs']
    total = len(jobs)
    if resolve_advisor(result.get('advisor'))['neutral']:
        return 'Hallo ich bin dein KI Assistent'
    # Match the initial visibility policy in frontend/result-visibility.js.
    visible = min(total, 10)
    if not total:
        overview = 'Ich habe aktuell keine Stellen zur gewählten Stellenart gefunden.'
    else:
        found = 'Eine Stelle' if total == 1 else f'{total} Stellen'
        overview = f'{found} gefunden und bewertet.'
        if visible == total:
            overview += ' Du findest alle links in der Ergebnisübersicht.'
        else:
            overview += (f' Links siehst du die ersten {visible}; '
                         'weitere findest du über „Weitere Stellen anzeigen“.')
    # Counts stay authoritative; the model's concrete advice/question is the conclusion.
    return f"Hallo! {overview}\n\n{result['assistant_message']}"


def create_app(config=None, *, retriever=None, llm=None):
    # Explicit path: never load an unrelated parent-directory .env.
    load_dotenv(BASE_DIR / '.env', override=False)
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_PATH=os.getenv('DATABASE_PATH', 'instance/jobs.sqlite3'),
        SEED_DUMMY_DATA=os.getenv('SEED_DUMMY_DATA', 'false').lower() == 'true',
        REQUIRE_COMPLETE_INDEX=os.getenv('REQUIRE_COMPLETE_INDEX', 'false').lower() == 'true',
        EMBEDDING_CACHE_DIR=os.getenv('EMBEDDING_CACHE_DIR', '.cache/embeddings'),
        E5_DEVICE=os.getenv('E5_DEVICE', 'cpu'),
        E5_BATCH_SIZE=int(os.getenv('E5_BATCH_SIZE', '8')),
        OPENAI_API_KEY=os.getenv('OPENAI_API_KEY', ''),
        CORS_ORIGINS=os.getenv('CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173'),
        MAX_CONTENT_LENGTH=128 * 1024,
        JSON_SORT_KEYS=False,
        ADMIN_PASSWORD_HASH=os.getenv('HELENA_ADMIN_PASSWORD_HASH', ''),
        PRIVACY_REQUIRED=not (config or {}).get('TESTING', False),
        PERSIST_CHAT_SESSIONS=(config or {}).get('TESTING', False),
        PRIVACY_SETTINGS_PATH=BASE_DIR / 'privacy_settings.json',
    )
    if config:
        app.config.update(config)
    app.json.ensure_ascii = False
    origins = app.config['CORS_ORIGINS']
    if isinstance(origins, str):
        origins = [x.strip() for x in origins.split(',') if x.strip()]
    CORS(app, resources={r'/api/*': {'origins': origins}})

    db_path = project_path(app.config['DATABASE_PATH'])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = JobStore(db_path)
    store.initialize()
    if app.config['SEED_DUMMY_DATA']:
        store.seed_if_empty(BASE_DIR / 'dummy_jobs.json')
    sessions = (SessionStore if app.config['PERSIST_CHAT_SESSIONS'] else EphemeralSessionStore)(db_path)
    privacy = PrivacyStore(db_path)
    personality_usage = StudyPersonalityUsage(db_path)
    operation_metrics = StudyOperationMetrics(db_path)
    study_context = StudyContext(db_path)
    app.extensions['study_context'] = study_context
    chat_limit = StudyChatLimit(db_path)
    system_prompts = SystemPromptStore(db_path)
    notice = load_notice(app.config['PRIVACY_SETTINGS_PATH'])
    releases = StudyReleases(db_path, BASE_DIR, store.filter_jobs({}))
    surveys = SurveyStore(db_path)
    assignments = StudyAssignments(surveys, privacy, notice)
    personality_templates = load_templates()
    neutral_personality = load_neutral_advisor()
    app.extensions['study_assignments'] = assignments
    register_admin(app, surveys, privacy, releases, sessions, notice, system_prompts)
    engine = retriever or HybridRetriever(
        cache_dir=project_path(app.config['EMBEDDING_CACHE_DIR']),
        device=app.config['E5_DEVICE'], batch_size=app.config['E5_BATCH_SIZE'])
    performance_logger = app.logger.getChild('performance')
    performance_logger.setLevel(logging.INFO)
    language_model = llm or OpenAIService(api_key=app.config['OPENAI_API_KEY'],
                                        performance_logger=performance_logger)
    app.extensions.update(job_store=store, chat_store=sessions, retriever=engine, personality_usage=personality_usage, operation_metrics=operation_metrics, chat_limit=chat_limit, system_prompt_store=system_prompts,
                          llm_service=language_model, survey_store=surveys, privacy_store=privacy, study_releases=releases)

    @contextmanager
    def timed_phase(phase, **metadata):
        started, status = time.monotonic(), 'ok'
        try:
            yield
        except Exception:
            status = 'error'
            if not getattr(g, 'study_error_stage', None):
                g.study_error_stage = phase
            raise
        finally:
            performance_logger.info(json.dumps({
                'event': 'matching_phase', 'phase': phase,
                'elapsed_ms': round((time.monotonic() - started) * 1000, 2),
                'status': status, **metadata}, separators=(',', ':')))

    def consent_token():
        return request.headers.get('X-Helena-Consent', '')

    def test_arm():
        value = request.headers.get('X-Helena-Test', '')
        if value and value not in TEST_PURPOSES:
            raise ConsentRequired()
        return value or None

    def request_notice():
        arm = test_arm()
        return test_notice(notice, arm) if arm else notice

    def request_assignment():
        arm = test_arm()
        return {'arm': arm, 'test': True, 'experiment_id': EXPERIMENT_ID,
                'personality_policy': personality_policy(EXPERIMENT_ID, arm),
                'presentation_policy': presentation_policy(EXPERIMENT_ID, arm)} if arm else assignments.get(consent_token())

    def request_policy():
        assigned = request_assignment()
        return assigned['personality_policy'] if assigned else None

    def prompt_snapshot(policy, assigned=None):
        if policy not in ('unprompted', 'career_fixed', 'custom_career'):
            return None
        # Standalone test URLs intentionally pick up the current prompt when a
        # new session starts.  Real v4 assignments are instead bound once to an
        # immutable participant snapshot, so a later admin edit cannot change
        # their treatment halfway through the study.
        if test_arm():
            return system_prompts.snapshot(policy)
        assigned = assigned or request_assignment()
        if assigned and assigned.get('experiment_id') in (EXPERIMENT_ID, PREVIOUS_FRAMEWORK_EXPERIMENT_ID, PREVIOUS_QUESTIONNAIRE_EXPERIMENT_ID, PREVIOUS_PERSONALITY_EXPERIMENT_ID):
            return system_prompts.participant_snapshot(
                token_hash(consent_token()), assigned['experiment_id'], policy
            )
        return None

    def request_advisor(requested):
        policy = request_policy()
        return advisor_for_policy(requested, policy) if policy else requested

    def checked_selection(advisor, selection):
        try:
            policy = request_policy()
            marker = selection.model_dump() if hasattr(selection, 'model_dump') else selection
            if policy == 'career_fixed':
                if marker is not None and marker != {'source':'template', 'template_id':'career'}:
                    raise ValueError('In dieser Variante ist der Top-Berufsberater fest eingestellt.')
                selection = {'source':'template', 'template_id':'career'}
            elif policy == 'custom_career':
                if marker is not None and marker != {'source':'custom', 'template_id':None}:
                    raise ValueError('In dieser Variante wird die KI-Persönlichkeit selbst gestaltet.')
                selection = {'source':'custom', 'template_id':None}
            elif policy == 'unprompted':
                if marker not in (None, {'source':'not_applicable', 'template_id':None}):
                    raise ValueError('In dieser Variante gibt es keine KI-Persönlichkeit.')
                selection = None
            elif policy == 'templates':
                if marker is not None and marker.get('source') != 'template':
                    raise ValueError('In dieser Variante kannst du ausschließlich unveränderte Vorlagen auswählen.')
                # In immutable B the server knows the only permitted actual source.
                # Legacy configurable sessions without a marker still stay unknown.
                if marker is None:
                    template_id = next(key for key, template in personality_templates.items() if template['advisor'] == advisor)
                    selection = {'source':'template', 'template_id':template_id}
            return normalize_selection(advisor, selection), None
        except ValueError as failure:
            return None, error_response({'code':'advisor_selection_mismatch','message':str(failure)},400)

    def incompatible_session(state, assigned):
        if assigned and state.get('_study_arm') != assigned['arm']:
            return True
        if assigned and state.get('_experiment_id') not in (None, assigned.get('experiment_id')):
            return True
        # Old direct B test sessions had an editable persona. They cannot be
        # resumed in the new template-only B condition after deployment.
        if assigned and assigned['personality_policy'] in ('templates', 'unprompted', 'career_fixed', 'custom_career'):
            if state.get('_personality_policy') != assigned['personality_policy']:
                return True
        if assigned and assigned['personality_policy'] == 'custom_career':
            # Normalizing only the advisor would retain results ranked under a
            # former focus. Require a new search before resuming those sessions.
            try:
                for key in ('advisor', 'advisor_mlds'):
                    if key in state and advisor_from_mlds(state[key])['focus'] != 'ausgewogen':
                        return True
            except MLDSError:
                return True
        return False

    def operation_id():
        if not getattr(g, 'study_operation_id', None):
            g.study_operation_id = secrets.token_hex(16)
        return g.study_operation_id

    def advance_study(step):
        if app.config['PRIVACY_REQUIRED'] and not test_arm():
            with surveys.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                digest = privacy.require(consent_token(), request_notice(), db)
                study_context.advance(digest, step, db)

    def diagnostic_code(failure):
        for failure_type, code in ((LLMUnavailable, 'llm_unavailable'),
                (EmbeddingUnavailable, 'embedding_unavailable'),
                (SessionConflict, 'session_conflict'),
                (ChatReservationExpired, 'chat_reservation_expired'),
                (ConsentRequired, 'consent_required'),
                (ValidationError, 'validation_error'),
                (GeneratorExit, 'client_disconnected'), (HTTPException, 'http_error')):
            if isinstance(failure, failure_type):
                return code
        return 'internal_error'

    def record_metrics(db, digest, timings, success, failure=None):
        now = time.monotonic()
        for operation, started in (timings or {}).items():
            operation_metrics.record_operation(digest, operation, success,
                max(0, round((now - started) * 1000)), db,
                error_code=diagnostic_code(failure) if not success else None,
                error_stage=getattr(g, 'study_error_stage', operation),
                operation_id=operation_id())

    def failed_metrics(timings, failure=None):
        if not timings or not app.config['PRIVACY_REQUIRED'] or test_arm():
            return
        # Diagnostics must not replace the actual request error or resurrect a
        # withdrawn participant. No request text is written to logs or metadata.
        try:
            with surveys.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                digest = privacy.require(consent_token(), request_notice(), db)
                record_metrics(db, digest, timings, False, failure)
        except Exception:
            app.logger.warning('Operation statistics could not be recorded.')

    def measured_operation(operation, timings):
        try:
            return (yield from operation)
        except (Exception, GeneratorExit) as failure:
            failed_metrics(timings, failure)
            raise
        finally:
            operation.close()

    def consent_link(kind, *, selection=None, completed=False, timings=None, chat_reservation=None, requires_chat=False):
        if not app.config['PRIVACY_REQUIRED'] and not test_arm():
            return None
        token = consent_token()
        active_notice = request_notice()
        testing = bool(test_arm())
        def attach(db, record_id):
            privacy.attach(token, active_notice, kind, record_id, db)
            digest = privacy.require(token, active_notice, db)
            if testing:
                return
            if kind == 'survey' and (completed or requires_chat):
                require_study_chat(digest, db)
            if kind == 'chat':
                if chat_reservation and chat_reservation.get('id'):
                    chat_limit.finish(digest, chat_reservation['id'], db)
                releases.mark_run(digest, db)
                record_metrics(db, digest, timings, True)
                if (timings or {}).get('search') is not None:
                    study_context.advance(digest, 'first_search', db)
                if (timings or {}).get('chat') is not None:
                    telemetry.record_chat_turn(digest, record_id, db)
                    study_context.advance(digest, 'chat', db)
                if selection is not None:
                    personality_usage.mark_applied(digest, selection, db)
            elif not db.execute('SELECT 1 FROM survey_responses WHERE submission_id=?', (record_id,)).fetchone():
                if completed or requires_chat:
                    study_context.advance(digest, 'questionnaire_completed' if completed else 'questionnaire_started', db)
                releases.capture_response(digest, record_id, db, completed=completed)
        return attach

    def chat_usage(state):
        session_used = state.get('_user_chat_count', sum(message.get('role') == 'user' for message in state.get('messages', [])))
        if test_arm():
            # Only an actual consent for this exact standalone test can bypass
            # the allowance; the client-supplied header alone is insufficient.
            privacy.require(consent_token(), request_notice())
            return dict(limit=None, used=session_used, pending=0, remaining=None)
        if not app.config['PRIVACY_REQUIRED']:
            return dict(limit=MAX_USER_CHAT_MESSAGES, used=session_used, pending=0,
                        remaining=max(0, MAX_USER_CHAT_MESSAGES - session_used))
        with surveys.connect() as db:
            db.execute('BEGIN')
            digest = privacy.require(consent_token(), request_notice(), db)
            return chat_limit.snapshot(digest, db)

    def limited_chat_operation(operation, reservation, state):
        try:
            if test_arm():
                privacy.require(consent_token(), request_notice())
            elif app.config['PRIVACY_REQUIRED']:
                with surveys.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    digest = privacy.require(consent_token(), request_notice(), db)
                    reservation['id'] = chat_limit.reserve(digest, db)
            elif chat_usage(state)['remaining'] == 0:
                raise ChatMessageLimit(chat_usage(state))
            return (yield from operation)
        finally:
            try:
                operation.close()
            finally:
                if reservation.get('id'):
                    chat_limit.release(reservation['id'])

    def follow_up_allowed(state, *, message=False, reservation=None):
        remaining = chat_usage(state)['remaining']
        # A database reservation already deducts the in-flight message. Without
        # persisted study consent, deduct it here; standalone tests are unlimited.
        unreserved_message = int(bool(message) and not (reservation or {}).get('id'))
        return remaining is None or remaining > unreserved_message

    telemetry = register_telemetry(app, privacy, surveys, sessions,
                                   request_notice, consent_token, test_arm)

    @app.before_request
    def require_consent():
        if request.method == 'OPTIONS':
            return
        if test_arm() and request.endpoint in {'assign_study', 'proceed_to_survey', 'submit_survey', 'save_survey_draft', 'get_survey_draft'}:
            raise ConsentRequired()
        if not app.config['PRIVACY_REQUIRED'] and not test_arm():
            return
        if request.endpoint in {'search', 'onboard', 'chat', 'get_session', 'delete_session', 'proceed_to_survey', 'submit_survey', 'save_survey_draft', 'get_survey_draft'}:
            privacy.require(consent_token(), request_notice())
            if request.endpoint == 'get_survey_draft' and not privacy.owns(consent_token(), 'survey', request.view_args['submission_id']):
                return jsonify(draft=None)
            if request.endpoint in {'get_session', 'delete_session'} and not privacy.owns(consent_token(), 'chat', request.view_args['session_id']):
                raise ConsentRequired()

    @app.after_request
    def privacy_headers(response):
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/privacy')
    def privacy_status():
        active = False
        try:
            privacy.require(consent_token(), request_notice())
            active = True
        except ConsentRequired:
            pass
        active_notice = request_notice()
        study = privacy.study_status(active_notice)
        return jsonify(notice={**active_notice, 'ready': study['enabled']}, study=study,
                       active=active, receipt=privacy.receipt(consent_token()))

    @app.post('/api/privacy/consent')
    def accept_consent():
        body, error = parse_body(ConsentInput)
        if error:
            return error
        active_notice = request_notice()
        had_receipt = privacy.receipt(body.token) is not None
        privacy.accept(body, active_notice)
        if active_notice.get('purpose', 'study') == 'study' and not had_receipt:
            with surveys.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                digest = privacy.require(body.token, active_notice, db)
                assigned = db.execute('SELECT experiment_id FROM study_assignments WHERE token_hash=?', (digest,)).fetchone()
                if not assigned or assigned[0] == EXPERIMENT_ID:
                    study_context.enroll(digest, db, experiment_id=EXPERIMENT_ID, questionnaire_version=SURVEY_VERSION)
        return jsonify(accepted=True, version=active_notice['version'], receipt=privacy.receipt(body.token))

    @app.route('/api/study-context', methods=['GET', 'PUT'])
    def participant_study_context():
        with surveys.connect() as db:
            db.execute('BEGIN IMMEDIATE' if request.method == 'PUT' else 'BEGIN')
            digest = privacy.require(consent_token(), request_notice(), db)
            if test_arm():
                return jsonify(status='ignored_test', study_context={})
            if request.method == 'PUT':
                payload = request.get_json(silent=True)
                if (not isinstance(payload, dict) or set(payload) != {'viewport_class'}
                        or payload['viewport_class'] not in ('mobile', 'desktop')):
                    return error_response({'code':'validation_error',
                        'message':'Nur die Darstellungsart mobile oder desktop ist zulässig.'}, 400)
                study_context.viewport(digest, payload['viewport_class'], db)
            return jsonify(study_context=context_snapshot(digest, db))

    @app.delete('/api/privacy/consent')
    def withdraw_consent():
        for session_id in privacy.withdraw(consent_token()):
            sessions.delete(session_id)
        return jsonify(withdrawn=True)

    @app.get('/')
    @app.get('/index.html')
    @app.get('/suche')
    @app.get('/test/a')
    @app.get('/test/a/')
    @app.get('/test/b')
    @app.get('/test/b/')
    @app.get('/test/c')
    @app.get('/test/c/')
    @app.get('/test/a/datenschutz')
    @app.get('/test/b/datenschutz')
    @app.get('/test/c/datenschutz')
    @app.get('/mehr-erfahren')
    @app.get('/umfrage')
    @app.get('/umfrage/')
    @app.get('/datenschutz')
    @app.get('/verwaltung')
    def website():
        return send_from_directory(BASE_DIR / 'web-dist', 'index.html', max_age=0)

    @app.get('/assets/<path:filename>')
    def website_asset(filename):
        return send_from_directory(BASE_DIR / 'web-dist' / 'assets', filename)

    @app.post('/api/study-assignment')
    def assign_study():
        assigned = assignments.assign(
            consent_token(),
            on_assign=lambda digest, current, db: system_prompts.participant_snapshot(
                digest, current['experiment_id'], current['personality_policy'], db=db
            ) if current.get('experiment_id') in (EXPERIMENT_ID, PREVIOUS_FRAMEWORK_EXPERIMENT_ID, PREVIOUS_QUESTIONNAIRE_EXPERIMENT_ID, PREVIOUS_PERSONALITY_EXPERIMENT_ID) else None,
        )
        with surveys.connect() as db:
            assigned['chat_progress'] = chat_progress(token_hash(consent_token()), db)
            assigned['study_context'] = context_snapshot(token_hash(consent_token()), db)
        return jsonify(assigned)

    @app.errorhandler(StudyChatRequired)
    def study_chat_required(failure):
        return error_response({'code': 'study_chat_required', 'message': str(failure),
                               'chat_progress': failure.progress}, 403)

    @app.post('/api/proceed_to_survey')
    def proceed_to_survey():
        # Never trust a client messageCount/session ID or postMessage flag.
        with surveys.connect() as db:
            db.execute('BEGIN')
            digest = privacy.require(consent_token(), request_notice(), db)
            if test_arm() or not assignments.get(consent_token()):
                raise ConsentRequired()
            progress = require_study_chat(digest, db)
            study_context.advance(digest, 'questionnaire_started', db)
        return jsonify(status='ok', chat_progress=progress)

    @app.put('/api/survey-drafts')
    def save_survey_draft():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get('version') != SURVEY_VERSION:
            return error_response({'code':'questionnaire_retired','message':'Dieser Fragebogen wurde ersetzt. Bitte lade die Umfrage neu.'}, 409)
        body, error = parse_body(SurveyDraftRequest)
        if error:
            return error
        try:
            assignments.validate_answers(consent_token(), body.root.version, body.root.answers.model_dump())
            return jsonify(surveys.save_draft(body.root, before_save=consent_link('survey', requires_chat=has_experience_answers(body.root.answers.model_dump()))))
        except ValueError as failure:
            return error_response({'code':'assignment_mismatch','message':str(failure)},400)
        except SurveyConflict as failure:
            return error_response({'code': 'survey_conflict', 'message': str(failure)}, 409)

    @app.get('/api/survey-drafts/<submission_id>')
    def get_survey_draft(submission_id):
        draft=surveys.get_draft(submission_id)
        return jsonify(draft=draft if draft and draft.get('version') == SURVEY_VERSION else None)

    @app.post('/api/survey-responses')
    def submit_survey():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get('version') != SURVEY_VERSION:
            return error_response({'code':'questionnaire_retired','message':'Dieser Fragebogen wurde ersetzt. Bitte lade die Umfrage neu.'}, 409)
        body, error = parse_body(SurveyRequest)
        if error:
            return error
        try:
            assignments.validate_answers(consent_token(), body.root.version, body.root.model_dump())
            created = surveys.save(body.root, before_save=consent_link('survey', completed=True))
        except ValueError as failure:
            return error_response({'code':'assignment_mismatch','message':str(failure)},400)
        except SurveyConflict as error:
            return error_response({'code': 'survey_conflict', 'message': str(error)}, 409)
        response = jsonify(saved=True)
        response.headers['Cache-Control'] = 'no-store'
        return response, 201 if created else 200

    @app.get('/api/jobs')
    def browse_jobs():
        # Initial browsing is unranked and never calls either model.
        jobs = store.filter_jobs({})
        return jsonify(jobs=[{k: v for k, v in job.items() if k not in ('search_text', 'raw')}
                             for job in jobs[:20]], total=len(jobs), ranked=False)

    @app.get('/api/persona-templates')
    def persona_templates():
        return jsonify(templates={'career': personality_templates['career']}, default='career',
                       format='HELENA-Personality-MLDS', schema_version=1)

    @app.get('/api/index-status')
    def index_status():
        return jsonify(read_progress(db_path, store.count(), app.config['REQUIRE_COMPLETE_INDEX']))

    def wants_ndjson():
        # An ordinary browser's */* is not an opt-in to streaming. Limit this
        # protocol to the two mutation endpoints that the frontend negotiates.
        return request.endpoint in {'onboard', 'chat'} and any(
            media_type == 'application/x-ndjson' and quality > 0
            for media_type, quality in request.accept_mimetypes
        )

    def ndjson_line(event):
        return app.json.dumps(event, separators=(',', ':'), allow_nan=False) + '\n'

    def error_response(error, status):
        if wants_ndjson():
            return Response(ndjson_line({'type': 'error', 'error': error, 'status': status}),
                            status=status, mimetype='application/x-ndjson',
                            headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
        return jsonify(error=error), status

    def complete_operation(operation):
        """Run the same generator synchronously for existing JSON clients."""
        try:
            while True:
                next(operation)
        except StopIteration as completed:
            return completed.value
        finally:
            operation.close()

    def operation_response(operation, status=200):
        if not wants_ndjson():
            return jsonify(complete_operation(operation)), status

        # Preserve HTTP errors before the first event, while forwarding the first
        # preview/phase immediately rather than buffering the completed operation.
        try:
            first_event = next(operation)
        except StopIteration as completed:
            operation.close()
            return Response(ndjson_line({'type': 'result', 'data': completed.value}),
                            mimetype='application/x-ndjson',
                            headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
        except BaseException:
            operation.close()
            raise

        @stream_with_context
        def events():
            try:
                yield ndjson_line(first_event)
                while True:
                    try:
                        event = next(operation)
                    except StopIteration as completed:
                        yield ndjson_line({'type': 'result', 'data': completed.value})
                        return
                    yield ndjson_line(event)
            except Exception as error:
                # Headers may already be sent. Reuse the existing safe error
                # handlers, including validation fields and optimistic-lock 409,
                # then deliver their status in the final protocol event.
                response = app.make_response(app.handle_user_exception(error))
                yield response.get_data(as_text=True)
            finally:
                operation.close()

        response = Response(events(), mimetype='application/x-ndjson',
                            headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
        response.call_on_close(operation.close)
        return response

    def parse_body(schema):
        if not request.is_json:
            return None, error_response({'code': 'invalid_content_type',
                                         'message': 'Content-Type application/json erforderlich.'}, 415)
        body = request.get_json()
        return schema.model_validate(body), None

    def model_steps(method, *args, **kwargs):
        stream_method = getattr(language_model, f'{method}_steps', None)
        if wants_ndjson() and callable(stream_method):
            return (yield from stream_method(*args, **kwargs, stream=True))
        return getattr(language_model, method)(*args, **kwargs)

    def rank_candidate_steps(profile, persona, candidates, filtered_count, advisor,
                        chat_message=None, chat_context=None, assessment_cache=None,
                        ordering_seed=None, prompt_policy=None, system_prompt=None):
        with timed_phase('rerank'):
            steps = model_steps('rerank', persona or {}, profile, candidates,
                                advisor=advisor, chat_message=chat_message,
                                chat_context=chat_context, assessment_cache=assessment_cache,
                                prompt_policy=prompt_policy, system_prompt=system_prompt)
            try:
                while True:
                    try:
                        event = next(steps)
                    except StopIteration as completed:
                        reranked = completed.value
                        break
                    if not resolve_advisor(advisor)['neutral']:
                        yield {'type': 'assistant_text', 'text': event['data']['assistant_message']}
            finally:
                steps.close()
        # Evidence comes from the actual numerical scoring function, never from
        # the persona prompt or a frontend claim. It is stored per calculation.
        scoring = reranked.get('_scoring_metadata')
        if scoring and app.config['PRIVACY_REQUIRED'] and not test_arm():
            with surveys.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                digest = privacy.require(consent_token(), request_notice(), db)
                study_context.record_scoring(digest, scoring, operation_id(), db)
        lookup = {item['job']['id']: item for item in candidates}
        cards = []
        for result in reranked['rankings']:
            candidate = lookup[result['job_id']]
            job = {key: value for key, value in candidate['job'].items()
                   if key not in ('search_text', 'raw')}
            cards.append({**job, 'match': result,
                          'retrieval': {k: v for k, v in candidate.items() if k != 'job'}})
        # Retain the complete retrieval pool independently of evaluated cards.
        # Raw exports and embedding inputs are not needed by later reranking calls.
        pool = [{**item, 'job': {key: value for key, value in item['job'].items()
                                if key not in ('search_text', 'raw')}} for item in candidates]
        result = {'profile': profile, 'persona': persona, 'advisor': advisor, 'jobs': cards,
                  '_matching_policy_version': MATCHING_POLICY_VERSION,
                  '_candidates': pool, 'assistant_message': reranked['assistant_message'],
                  'retrieval': {'filtered_count': filtered_count, 'candidate_count': len(pool)}}
        if resolve_advisor(advisor)['neutral']:
            result['jobs'], result['_ordering_seed'] = neutral_card_order(cards, ordering_seed)
            result['_presentation_version'] = NEUTRAL_PRESENTATION_VERSION
            result['assistant_message'] = 'Die Stellenliste ist aktualisiert. Die Reihenfolge ist zufällig und sagt nichts über die Passung aus.'
        if isinstance(reranked.get('assessment_cache'), dict):
            result['_assessment_cache'] = reranked['assessment_cache']
        return result

    def match_steps(profile, persona=None, chat_message=None, chat_context=None, advisor=None,
                    saved_persona_fingerprint=None, prompt_policy=None, system_prompt=None):
        advisor = AdvisorConfig.model_validate(advisor or {}).model_dump()
        # Only employment type excludes jobs. The legacy filters container also
        # holds soft location, work-model and hours wishes for the LLM.
        with timed_phase('prefilter'):
            jobs = store.filter_jobs({'employment_types': profile['filters']['employment_types']})
        if not jobs:
            return {'profile': profile, 'persona': persona, 'advisor': advisor, 'jobs': [],
                    'assistant_message': 'Für die gewählten Stellenarten sind keine Anzeigen vorhanden. '
                    f"{describe_filters(profile['filters'])}. "
                    'Du kannst die Stellenart im Suchprofil oder im Chat ändern.',
                    'retrieval': {'filtered_count': 0, 'candidate_count': 0},
                    '_candidates': [], '_matching_policy_version': MATCHING_POLICY_VERSION,
                    **({'_persona_fingerprint': saved_persona_fingerprint}
                       if saved_persona_fingerprint is not None else {}),
                    'chat_action': 'search'}
        progress = read_progress(db_path, store.count(), app.config['REQUIRE_COMPLETE_INDEX'])
        if progress['status'] != 'ready':
            raise LLMUnavailable(f"Der Suchindex wird vorbereitet: {progress['completed']} von {progress['total']} Stellen. Bitte kurz warten.")
        # This event is reached only after the server committed to a real full
        # search, not while chat intent is still unknown or a cached pool reranks.
        yield {'type': 'phase', 'phase': 'search'}
        yield {'type': 'search_progress', 'stage': 'loaded', 'job_count': len(jobs)}
        yield {'type': 'search_progress', 'stage': 'profiling', 'job_count': len(jobs)}
        current_fingerprint = persona_fingerprint(profile, prompt_policy)
        cache_hit = reusable_persona(persona, saved_persona_fingerprint, current_fingerprint)
        with timed_phase('persona', cache_hit=cache_hit):
            if prompt_policy in ('unprompted', 'career_fixed', 'custom_career'):
                persona = unprompted_persona(profile)
            elif not cache_hit:
                persona = language_model.generate_persona(profile)
        # Include literal skills to preserve BM25 keywords even if the persona paraphrases them.
        # Skills and the distilled query must precede verbose free text for E5's
        # 512-token limit. BM25 still receives the complete text.
        query = '\n'.join(x for x in [' '.join(profile['skills']),
                                      persona['retrieval_query'], profile['query']] if x)
        yield {'type': 'search_progress', 'stage': 'retrieval', 'job_count': len(jobs)}
        with timed_phase('retrieval'):
            candidates = engine.search(jobs, query, top_k=20)
        yield {'type': 'search_progress', 'stage': 'ranking',
               'job_count': len(jobs), 'candidate_count': len(candidates)}
        ranked = yield from rank_candidate_steps(profile, persona, candidates, len(jobs), advisor,
                                   chat_message, {**(chat_context or {}), 'scope': 'new_search'},
                                   prompt_policy=prompt_policy, system_prompt=system_prompt)
        yield {'type': 'search_progress', 'stage': 'finalizing',
               'job_count': len(jobs), 'candidate_count': len(candidates)}
        return {**ranked,
                '_persona_fingerprint': current_fingerprint,
                'chat_action': 'search'}

    def match(profile, **kwargs):
        return complete_operation(match_steps(profile, **kwargs))

    @app.get('/api/health')
    def health():
        return jsonify(status='ok', jobs=store.count(), openai_model=MODEL,
                       openai_reasoning_effort=REASONING_EFFORT,
                       embedding_model='intfloat/multilingual-e5-large-instruct',
                       openai_configured=bool(app.config['OPENAI_API_KEY']),
                       readiness='Modelle werden erst bei Suche oder warmup geladen.')

    @app.post('/api/search')
    def search():
        body, error = parse_body(SearchInput)
        if error:
            return error
        advisor = request_advisor(body.advisor.model_dump())
        selection, error = checked_selection(advisor, body.advisor_selection)
        if error:
            return error
        advance_study('profile')
        timings = {'search': time.monotonic()}
        try:
            policy = request_policy()
            result = {**match(body.profile.model_dump(), advisor=advisor,
                              prompt_policy=policy, system_prompt=prompt_snapshot(policy)),
                      'advisor_selection':selection}
            if app.config['PRIVACY_REQUIRED'] and not test_arm():
                with surveys.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    digest = privacy.require(consent_token(), request_notice(), db)
                    releases.mark_run(digest, db)
                    personality_usage.mark_applied(digest, selection, db)
                    record_metrics(db, digest, timings, True)
                    study_context.advance(digest, 'first_search', db)
        except Exception as failure:
            failed_metrics(timings, failure)
            raise
        return jsonify(public_state(result))

    @app.post('/api/onboard')
    def onboard():
        body, error = parse_body(SearchInput)
        if error:
            return error
        assigned = request_assignment()
        policy = assigned['personality_policy'] if assigned else None
        frozen_prompt = prompt_snapshot(policy, assigned)
        search_advisor = request_advisor(body.advisor.model_dump())
        selection, error = checked_selection(search_advisor, body.advisor_selection)
        if error:
            return error
        advance_study('profile')
        timings = {'search': time.monotonic()}
        def operation():
            result = yield from match_steps(body.profile.model_dump(), advisor=search_advisor,
                chat_context={'follow_up_allowed': follow_up_allowed({'messages': []})},
                prompt_policy=policy, system_prompt=frozen_prompt)
            result['assistant_message'] = welcome_message(result)
            state = {**result, 'advisor_selection':selection, 'advisor_mlds': advisor_to_mlds(result['advisor']), '_study_arm': assigned['arm'] if assigned else None, '_test_arm': test_arm(), '_personality_policy': assigned['personality_policy'] if assigned else None, '_system_prompt_snapshot': frozen_prompt,
                     '_experiment_id': assigned.get('experiment_id') if assigned else None, '_user_chat_count': 0, 'messages': [{'role': 'assistant', 'content': result['assistant_message'],
                                            'advisor_name': resolve_advisor(result['advisor'])['name']}]}
            session_id = sessions.create(state, before_save=consent_link('chat', selection=selection, timings=timings))
            return {'session_id': session_id, **public_state(state), 'chat_usage': chat_usage(state)}

        return operation_response(measured_operation(operation(), timings), status=201)

    @app.get('/api/sessions/<session_id>')
    def get_session(session_id):
        saved = sessions.get(session_id)
        if not saved:
            return jsonify(error={'code': 'not_found', 'message': 'Chat nicht gefunden.'}), 404
        assigned = request_assignment()
        if incompatible_session(saved[0], assigned):
            return error_response({'code':'not_found','message':'Bitte starte deine Suche neu.'},404)
        if outdated_neutral_presentation(saved[0]):
            return error_response({'code':'not_found','message':'Die einfache Studienvariante wurde geändert. Bitte starte deine Suche neu.'},404)
        return jsonify(session_id=session_id, **public_state({**saved[0],
                       'advisor': saved[0].get('advisor', AdvisorConfig().model_dump())}),
                       chat_usage=chat_usage(saved[0]))

    @app.delete('/api/sessions/<session_id>')
    def delete_session(session_id):
        if not sessions.delete(session_id):
            return jsonify(error={'code': 'not_found', 'message': 'Chat nicht gefunden.'}), 404
        return '', 204

    @app.post('/api/chat')
    def chat():
        body, error = parse_body(ChatInput)
        if error:
            return error
        if (app.config['PRIVACY_REQUIRED'] or test_arm()) and not privacy.owns(consent_token(), 'chat', body.session_id):
            raise ConsentRequired()
        saved = sessions.get(body.session_id)
        if not saved:
            return error_response({'code': 'not_found', 'message': 'Chat nicht gefunden.'}, 404)
        state, version = saved
        assigned = request_assignment()
        if incompatible_session(state, assigned):
            return error_response({'code':'not_found','message':'Bitte starte deine Suche neu.'},404)
        if outdated_neutral_presentation(state):
            return error_response({'code':'not_found','message':'Die einfache Studienvariante wurde geändert. Bitte starte deine Suche neu.'},404)
        policy = state.get('_personality_policy') or (assigned['personality_policy'] if assigned else None)
        frozen_prompt = state.get('_system_prompt_snapshot')
        if frozen_prompt is None and policy in ('unprompted', 'career_fixed', 'custom_career'):
            frozen_prompt = prompt_snapshot(policy, assigned)
        previous_advisor = request_advisor(advisor_from_mlds(state.get('advisor_mlds', state.get('advisor', {}))))
        selected_advisor = request_advisor(body.advisor.model_dump() if body.advisor is not None else previous_advisor)
        previous_selection = normalize_selection(previous_advisor, state.get('advisor_selection'))
        selected_selection, error = checked_selection(selected_advisor,
            body.advisor_selection if body.advisor is not None else previous_selection)
        if error:
            return error
        timings = {'chat': time.monotonic()} if body.message else {}
        reservation = {}
        def operation():
            advisor = selected_advisor
            applied_selection = selected_selection
            profile = body.profile.model_dump() if body.profile is not None else state['profile']
            context = {'messages': state['messages'][-12:], 'jobs': public_state({**state, 'advisor': advisor})['jobs'][:20],
                       'follow_up_allowed': follow_up_allowed(state, message=body.message, reservation=reservation)}
            action = 'answer'
            answer = 'Dein Suchprofil ist unverändert. Die bisherigen Empfehlungen bleiben erhalten.'
            if body.message:
                with timed_phase('chat_plan'):
                    steps = model_steps('plan_chat', profile, context['messages'], body.message,
                                        jobs=context['jobs'], advisor=advisor, mode=body.mode,
                                        candidate_count=len(state.get('_candidates', [])),
                                        follow_up_allowed=context['follow_up_allowed'],
                                        prompt_policy=policy, system_prompt=frozen_prompt)
                    try:
                        while True:
                            try:
                                event = next(steps)
                            except StopIteration as completed:
                                decision = completed.value
                                break
                            preview = event['data']
                            preview_profile = merge_profile(profile, preview['profile_patch'])
                            # Only show a planner answer when the server can keep
                            # the current results. Search/rerank confirmations are
                            # replaced by the actual ranking response later.
                            if (body.mode == 'auto' and preview['action'] == 'answer'
                                    and advisor == previous_advisor
                                    and not any(profile_changes(state['profile'], preview_profile))):
                                yield {'type': 'assistant_text', 'text': preview['assistant_message']}
                    finally:
                        steps.close()
                try:
                    profile = merge_profile(profile, decision['profile_patch'])
                except ValidationError:
                    raise LLMUnavailable('Die KI hat eine ungültige Profiländerung vorgeschlagen.') from None
                action, answer = decision['action'], decision['assistant_message']
            core_changed, preferences_changed = profile_changes(state['profile'], profile)
            advisor_changed = advisor != previous_advisor
            planned_action = action
            # The server, not the model, decides whether changed hard criteria may be
            # applied to cached jobs. A new search is mandatory for retrieval changes.
            if body.mode == 'search' or core_changed:
                action = 'search'
            elif body.mode == 'rerank':
                action = 'rerank'
            elif action != 'search' and (preferences_changed or advisor_changed):
                action = 'rerank'

            refresh_required = restricted_legacy_pool(state)
            if action == 'rerank' and refresh_required and body.mode != 'rerank':
                # Once, on an actual matching request, rebuild pools that were
                # previously narrowed by location, work model or hours. Plain
                # questions still leave stored results and scores untouched.
                action = 'search'

            if body.mode == 'rerank' and refresh_required:
                action = 'answer'
                answer = ('Deine bisherige Auswahl wurde noch nach Ort, Arbeitsmodell oder Stunden '
                          'vorab eingeschränkt. Starte einmal „Neue Suche“, damit auch andere '
                          'Stellen berücksichtigt werden. Danach kannst du wieder nur neu bewerten.')
                profile, advisor = state['profile'], previous_advisor
                applied_selection = previous_selection
            elif body.mode == 'rerank' and (core_changed or planned_action == 'search'):
                action = 'answer'
                answer = ('Dafür ist eine neue Suche nötig, weil sich die Suchkriterien ändern '
                          'oder weitere Stellen benötigt werden. Wähle „Neue Suche“ oder „Automatisch“. '
                          'Dein bisheriges Profil und die Ergebnisse bleiben erhalten.')
                profile, advisor = state['profile'], previous_advisor
                applied_selection = previous_selection
            elif action == 'rerank' and '_candidates' not in state:
                action = 'answer'
                answer = ('Für diesen älteren Chat wurden nur die angezeigten Empfehlungen gespeichert. '
                          'Wähle einmal „Neue Suche“, um die vollständige Auswahl für späteres '
                          'Nachsortieren zu speichern. Dein Profil und die Ergebnisse bleiben erhalten.')
                profile, advisor = state['profile'], previous_advisor
                applied_selection = previous_selection
            elif action == 'rerank' and not state['_candidates']:
                action = 'answer'
                answer = ('Deine bisherige Suche hat keine passenden Stellen gefunden. '
                          'Zum Nachsortieren sind deshalb keine Jobs vorhanden. '
                          'Ändere dein Suchprofil oder starte eine neue Suche.')
                profile, advisor = state['profile'], previous_advisor
                applied_selection = previous_selection

            if action == 'search':
                timings['search'] = time.monotonic()
                result = yield from match_steps(
                    profile, chat_message=body.message or 'Erkläre kurz die neue Auswahl.',
                    chat_context=context, advisor=advisor, persona=state.get('persona'),
                    saved_persona_fingerprint=state.get('_persona_fingerprint'),
                    prompt_policy=policy, system_prompt=frozen_prompt)
            elif action == 'rerank':
                timings['rerank'] = time.monotonic()
                result = yield from rank_candidate_steps(profile, state.get('persona'), state['_candidates'],
                                         state['retrieval']['filtered_count'], advisor,
                                         body.message or 'Bewerte die vorhandene Auswahl neu und erkläre sie kurz.',
                                         {**context, 'scope': 'existing_candidates'},
                                         assessment_cache=state.get('_assessment_cache'),
                                         ordering_seed=state.get('_ordering_seed'),
                                         prompt_policy=policy, system_prompt=frozen_prompt)
                # The retained persona was generated for its original profile.
                # Never label it with the profile just used for soft reranking.
                if '_persona_fingerprint' in state:
                    result['_persona_fingerprint'] = state['_persona_fingerprint']
            else:
                # Questions preserve jobs, scores, pool and search persona exactly.
                result = {**state, 'profile': profile, 'advisor': advisor, 'assistant_message': answer}
            result['chat_action'] = action
            messages = state['messages'] + ([{'role': 'user', 'content': body.message}] if body.message else [])
            messages.append({'role': 'assistant', 'content': result['assistant_message'],
                             'advisor_name': resolve_advisor(result['advisor'])['name']})
            new_state = {**result, 'advisor_selection':applied_selection, 'advisor_mlds': advisor_to_mlds(result['advisor']), '_study_arm': state.get('_study_arm'), '_test_arm': state.get('_test_arm'), '_personality_policy': state.get('_personality_policy'), '_system_prompt_snapshot': frozen_prompt,
                         '_experiment_id': state.get('_experiment_id'), 'messages': messages[-100:],
                         '_user_chat_count': state.get('_user_chat_count', sum(message.get('role') == 'user' for message in state['messages'])) + int(bool(body.message))}
            sessions.update(body.session_id, new_state, version, before_save=consent_link('chat', selection=applied_selection, timings=timings, chat_reservation=reservation))
            return {'session_id': body.session_id, **public_state(new_state), 'chat_usage': chat_usage(new_state)}

        measured = measured_operation(operation(), timings)
        return operation_response(limited_chat_operation(measured, reservation, state) if body.message else measured)

    @app.errorhandler(ValidationError)
    def bad_input(error):
        # Do not echo CV text or the complete request back in validation errors.
        fields = ['.'.join(str(part) for part in item['loc']) or 'profile'
                  for item in error.errors(include_input=False, include_context=False)]
        return error_response({'code': 'validation_error', 'message': 'Eingaben prüfen.',
                               'fields': fields}, 400)

    @app.errorhandler(PersonalityPolicyError)
    def personality_policy_error(error):
        return error_response({'code':'personality_policy_violation','message':str(error)},400)

    @app.errorhandler(ConsentRequired)
    def consent_error(error):
        return error_response({'code': 'consent_required', 'message': 'Bitte prüfe die Datenschutzhinweise und deine Einwilligung. Die Studie muss dafür freigegeben sein.'}, 428)

    @app.errorhandler(ChatMessageLimit)
    def chat_limit_error(error):
        return error_response({'code': 'chat_message_limit', 'message': str(error),
                               'chat_usage': error.usage}, 409)

    @app.errorhandler(ChatReservationExpired)
    def chat_reservation_expired(error):
        return error_response({'code': 'chat_reservation_expired',
                               'message': 'Die Chatantwort hat zu lange gedauert. Deine Nachricht wurde nicht gezählt. Bitte versuche es erneut.'}, 409)

    @app.errorhandler(LLMUnavailable)
    def llm_error(error):
        return error_response({'code': 'llm_unavailable', 'message': str(error)}, 503)

    @app.errorhandler(EmbeddingUnavailable)
    def embedding_error(error):
        return error_response({'code': 'embedding_unavailable',
                               'message': 'E5-Modell nicht verfügbar. Installation, Cache und Netzwerk prüfen.'}, 503)

    @app.errorhandler(SessionConflict)
    def conflict(error):
        return error_response({'code': 'session_conflict', 'message': str(error)}, 409)

    @app.errorhandler(HTTPException)
    def http_error(error):
        return error_response({'code': error.name, 'message': error.description}, error.code)

    @app.errorhandler(Exception)
    def unexpected_error(error):
        # Class only: SDK exception strings may contain submitted personal information.
        app.logger.error('Request failed (%s)', type(error).__name__)
        return error_response({'code': 'internal_error', 'message': 'Interner Verarbeitungsfehler.'}, 500)

    @app.cli.command('privacy-delete')
    @click.option('--participation-id', required=True, help='Exakte HELENA-Teilnahme-ID der Löschanfrage.')
    @click.option('--confirm', is_flag=True, help='Zugeordnete Antworten tatsächlich löschen und Einwilligung widerrufen.')
    def delete_participant(participation_id, confirm):
        records = privacy.participant_records(participation_id)
        if records is None:
            raise click.ClickException('Teilnahme-ID nicht gefunden.')
        if not confirm:
            click.echo(f"Vorschau: {records.get('survey', 0)} Umfrageantworten, {records.get('chat', 0)} Sitzungskennungen. Zum Löschen --confirm ergänzen.")
            return
        for session_id in privacy.delete_participant(participation_id):
            sessions.delete(session_id)
        click.echo('Teilnahme widerrufen; zugeordnete Antworten aus der aktiven Datenbank gelöscht. Exporte und Sicherungen separat berücksichtigen.')

    @app.cli.command('privacy-end-study')
    @click.option('--confirm', is_flag=True, help='Endgültige Löschung der Umfrageantworten und Nachweise bestätigen.')
    def end_study(confirm):
        """Deliberately close the study and delete its data; never runs automatically."""
        if not confirm:
            raise click.ClickException('Diese Aktion löscht alle Umfrageantworten und Einwilligungsnachweise. --confirm ist erforderlich.')
        for session_id in privacy.end_study():
            sessions.delete(session_id)
        click.echo('Studie geschlossen; Umfrageantworten und Nachweise gelöscht. Exporte, Sicherungen und historische Chatdaten müssen separat geprüft werden.')

    @app.cli.command('survey-export')
    @click.option('--output', required=True, type=click.Path(dir_okay=False, path_type=Path),
                  help='Neue CSV-Datei für die Umfrageauswertung (UTF-8, Semikolon).')
    def survey_export(output):
        """Export survey answers locally; no public download endpoint."""
        try:
            with output.open('x', encoding='utf-8-sig', newline='') as stream:
                count = surveys.export_csv(stream)
        except FileExistsError:
            raise click.ClickException('Die Zieldatei existiert bereits. Bitte einen neuen Dateinamen wählen.') from None
        except OSError as error:
            raise click.ClickException(f'CSV konnte nicht geschrieben werden ({type(error).__name__}).') from None
        click.echo(f'{count} Umfrageantworten exportiert: {output}')

    @app.cli.command('import-jobs')
    @click.argument('path', type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option('--allow-control-characters', is_flag=True,
                  help='Nur unescaped JSON-Steuerzeichen tolerieren; Originaldatei bleibt unverändert.')
    def import_jobs(path, allow_control_characters):
        """Import original-schema job JSON, upserting by jobId."""
        try:
            click.echo(store.import_json(path, allow_control_characters=allow_control_characters))
        except (ValueError, OSError) as error:
            raise click.ClickException(str(error)) from None

    @app.cli.command('warmup')
    def warmup():
        """Download E5 and cache embeddings before starting Gunicorn."""
        jobs = store.filter_jobs({})
        started = time.monotonic()
        completed = 0
        write_progress(db_path, 0, len(jobs), 'building', 0)

        def progress(done, total):
            nonlocal completed
            completed = done
            write_progress(db_path, done, total, 'building', time.monotonic() - started)
            click.echo(f'{done}/{total} Stellen vorbereitet.')

        try:
            engine.warmup(jobs, progress=progress)
        except Exception as error:
            write_progress(db_path, completed, len(jobs), 'failed', time.monotonic() - started)
            raise click.ClickException(f'Indexierung fehlgeschlagen ({type(error).__name__}). '
                                       'Gespeicherte Vektoren bleiben erhalten.') from None
        write_progress(db_path, len(jobs), len(jobs), 'ready', time.monotonic() - started)
        click.echo(f'E5 bereit: {len(jobs)} Stellen im Cache.')

    return app


if __name__ == '__main__':
    app = create_app()
    app.logger.setLevel(logging.INFO)
    app.logger.info('E5 wird vor dem lokalen Serverstart vorbereitet; kein GPT-Aufruf.')
    try:
        app.extensions['retriever'].prepare_query_encoder()
        app.logger.info('E5 ist geladen und für Suchanfragen bereit.')
    except EmbeddingUnavailable:
        app.logger.warning('E5 konnte nicht vorgeladen werden. Ein neuer Versuch erfolgt bei der Suche.')
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '5050')), debug=False)
