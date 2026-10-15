"""Versioned study configuration, without applicant inputs or conversation text."""
import hashlib
import importlib.metadata
import json
import platform
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from llm_service import MODEL, REASONING_EFFORT, MAX_OUTPUT_TOKENS, RERANK_OUTPUT_TOKENS, ChatDecision, MAX_ASSISTANT_MESSAGE_CHARS, ADVISORY_VERSION
from retrieval import MODEL_ID, MODEL_REVISION, CACHE_VERSION, RRF_K, LEG_LIMIT
from study_usage import CAPTURE_VERSION, usage_snapshot
from study_metrics import METRICS_CAPTURE_VERSION, metrics_snapshot
from study_context import context_snapshot
from study_chat_limit import MAX_USER_CHAT_MESSAGES
from study_assignment import EXPERIMENT_ID
from survey_store import SURVEY_VERSION, SURVEY_DEFINITION
from advisor import SCORING_VERSION, SCORING_WEIGHTS
from study_progress import MIN_USER_CHAT_MESSAGES
from study_telemetry import CAPTURE_VERSION as TELEMETRY_CAPTURE_VERSION
from system_prompt_store import DEFAULT_SYSTEM_PROMPTS


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class StudyReleases:
    def __init__(self, path, root, jobs):
        self.path = path
        files = ['llm_service.py', 'advisor.py', 'retrieval.py', 'schemas.py', 'app.py',
                 'data_store.py', 'survey_store.py', 'survey_definition_v3.json', 'survey_definition_v4.json', 'survey_definition_v5.json', 'survey_definition_v6.json', 'study_assignment.py', 'advisor.py', 'survey_definition.json', 'requirements.txt', 'requirements-server.txt',
                 'web-dist/index.html']
        files += ['persona_mlds.py', 'study_usage.py', 'survey_definition_v7.json', 'survey_definition_v8.json', 'survey_definition_v9.json', 'survey_definition_v10.json', 'survey_definition_v11.json', 'survey_definition_v12.json', 'survey_definition_v13.json', 'survey_definition_v14.json', 'study_context.py', 'V14-METHODS.md', 'requirements-analysis.txt', 'survey_migrations.py', 'study_metrics.py', 'study_chat_limit.py', 'system_prompt_store.py', 'test_access.py', 'STUDY-PROTOCOL.md']
        files += [path.relative_to(root).as_posix() for path in sorted((root/'research/v14').glob('*')) if path.is_file()]
        files += ['study_progress.py', 'study_telemetry.py', 'migrations/012_study_telemetry.sql']
        files += [path.relative_to(root).as_posix() for path in sorted((root/'personas').glob('*')) if path.is_file()]
        sources = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files if (root/name).is_file()}
        packages = {}
        for name in ['openai','pydantic','sentence-transformers','torch','transformers','numpy','rank-bm25','Flask','scipy']:
            try: packages[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError: packages[name] = None
        manifest = dict(format_version=1, openai_model=MODEL, reasoning_effort=REASONING_EFFORT,
                        experiment_id=EXPERIMENT_ID,
                        assignment_probabilities={'A':1/3,'B':1/3,'C':1/3},
                        personality_policies={'A':'unprompted','B':'career_fixed','C':'custom_career'},
                        personality_focus_policy={'A':'ausgewogen','B':'lernpotenzial','C':'ausgewogen'},
                        scoring_focus_policy='fixed balanced weights, regardless of stored personality focus',
                        questionnaire_version=SURVEY_VERSION,
                        questionnaire_frameworks=SURVEY_DEFINITION.get('frameworks', []),
                        default_system_prompt_base_sha256={policy:hashlib.sha256(text.encode('utf-8')).hexdigest()
                                                           for policy,text in DEFAULT_SYSTEM_PROMPTS.items()},
                        system_prompts_admin_editable=True,
                        a_empty_prompt_means_no_system_message=True,
                        system_prompt_snapshot_scope='base prompt frozen per participant for helena-abc-v4/v5/v6/v7; policy, revision and base sha256 are exported without prompt text; C appends the participant-controlled personality at runtime',
                        presentation_policy='ranked_insights',
                        historical_neutral_presentation='random-order-generic-chat-v2',
                        operation_metrics_capture_version=METRICS_CAPTURE_VERSION,
                        personality_usage_capture_version=CAPTURE_VERSION,
                        historical_neutral_chat_max_output_tokens=None, historical_neutral_chat_max_characters=None,
                        chat_max_output_tokens=MAX_OUTPUT_TOKENS,
                        max_user_chat_messages=MAX_USER_CHAT_MESSAGES,
                        test_max_user_chat_messages=None,
                        chat_max_characters=MAX_ASSISTANT_MESSAGE_CHARS,
                        chat_schema_max_characters=None, advisory_version=ADVISORY_VERSION,
                        scoring_version=SCORING_VERSION, scoring_weights=dict(SCORING_WEIGHTS),
                        min_user_chat_messages=MIN_USER_CHAT_MESSAGES,
                        telemetry_capture_version=TELEMETRY_CAPTURE_VERSION,
                        response_store=False, max_output_tokens=MAX_OUTPUT_TOKENS,
                        rerank_output_tokens=RERANK_OUTPUT_TOKENS, embedding_model=MODEL_ID,
                        embedding_revision=MODEL_REVISION, embedding_preprocessing=CACHE_VERSION,
                        rrf_k=RRF_K, retrieval_top_k=LEG_LIMIT, source_sha256=sources,
                        python=platform.python_version(), packages=packages,
                        job_count=len(jobs), job_data_sha256=hashlib.sha256(canonical(sorted(jobs,key=lambda job:str(job['id']))).encode()).hexdigest(),
                        reproducibility_note='Fixed model and configuration do not guarantee identical generative outputs. No personal search inputs or chats are archived.')
        self.release_id = hashlib.sha256(canonical(manifest).encode()).hexdigest()
        self.manifest = {**manifest, 'release_id': self.release_id}
        with sqlite3.connect(path) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS study_releases (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, manifest_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS study_runs (token_hash TEXT NOT NULL, release_id TEXT NOT NULL, PRIMARY KEY(token_hash, release_id));
                CREATE TABLE IF NOT EXISTS survey_response_metadata (submission_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL);''')
            db.execute('INSERT OR IGNORE INTO study_releases VALUES (?, ?, ?)',
                       (self.release_id, datetime.now(timezone.utc).isoformat(), canonical(self.manifest)))

    def mark_run(self, digest, db):
        db.execute('INSERT OR IGNORE INTO study_runs VALUES (?, ?)', (digest, self.release_id))

    def capture_response(self, digest, submission_id, db, *, completed=False):
        # Never retrofit historical/completed submissions with later behavior.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='survey_responses'").fetchone():
            if db.execute('SELECT 1 FROM survey_responses WHERE submission_id=?', (submission_id,)).fetchone():
                return
        ids = [row[0] for row in db.execute('SELECT release_id FROM study_runs WHERE token_hash=? ORDER BY release_id',(digest,))]
        previous = db.execute('SELECT metadata_json FROM survey_response_metadata WHERE submission_id=?', (submission_id,)).fetchone()
        metadata = json.loads(previous[0]) if previous else {}
        if metadata.get('personality_usage_frozen'):
            return
        if previous:
            ids = sorted(set(ids) | set(metadata.get('release_ids', [])))
        metadata.update(release_ids=ids, personality_usage=usage_snapshot(digest, db),
                        personality_usage_frozen=bool(completed),
                        operation_metrics=metrics_snapshot(digest, db), study_context=context_snapshot(digest, db))
        db.execute('INSERT INTO survey_response_metadata VALUES (?, ?) ON CONFLICT(submission_id) DO UPDATE SET metadata_json=excluded.metadata_json', (submission_id, canonical(metadata)))

    def all(self):
        with sqlite3.connect(self.path) as db:
            return {row[0]:json.loads(row[1]) for row in db.execute('SELECT id,manifest_json FROM study_releases')}
