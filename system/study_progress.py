"""Authoritative questionnaire eligibility, using the existing successful-chat counter."""
from study_chat_limit import StudyChatLimit, MAX_USER_CHAT_MESSAGES

MIN_USER_CHAT_MESSAGES = MAX_USER_CHAT_MESSAGES
PRE_CHAT_FIELDS = frozenset({'study_arm', 'age_group', 'gender', 'education',
    'study_field', 'previous_participation', 'job_portal_experience', 'ai_chat_experience', 'search_goal'})

class StudyChatRequired(Exception):
    def __init__(self, progress):
        self.progress = progress
        super().__init__('Bitte sende drei eigene Nachrichten im Chat und warte jeweils auf die Antwort, bevor du die Erfahrung mit dem System bewertest.')

def chat_progress(digest, db):
    usage = StudyChatLimit.snapshot(digest, db)
    return dict(used=usage['used'], required=MIN_USER_CHAT_MESSAGES,
                pending=usage['pending'], can_proceed=usage['used'] >= MIN_USER_CHAT_MESSAGES)

def require_study_chat(digest, db):
    progress = chat_progress(digest, db)
    if not progress['can_proceed']:
        raise StudyChatRequired(progress)
    return progress

def has_experience_answers(answers):
    return any(name not in PRE_CHAT_FIELDS and value not in (None, '')
               for name, value in answers.items())
