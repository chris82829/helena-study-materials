"""Descriptive, version-separated aggregates. No model calls or data mutations."""
from collections import Counter
from copy import deepcopy
from statistics import mean, median

from survey_store import (SURVEY_DEFINITION, V13_SURVEY_DEFINITION, V12_SURVEY_DEFINITION, V11_SURVEY_DEFINITION, V10_SURVEY_DEFINITION, V9_SURVEY_DEFINITION, V8_SURVEY_DEFINITION, V7_SURVEY_DEFINITION, V6_SURVEY_DEFINITION, V5_SURVEY_DEFINITION,
                          V4_SURVEY_DEFINITION, LEGACY_SURVEY_DEFINITION, answer_status,
                          QUESTIONS, ADDED_VALUE_LABELS, PREFERENCE_LABELS)

DEFINITIONS = {d['version']: d for d in (SURVEY_DEFINITION, V13_SURVEY_DEFINITION, V12_SURVEY_DEFINITION, V11_SURVEY_DEFINITION, V10_SURVEY_DEFINITION, V9_SURVEY_DEFINITION, V8_SURVEY_DEFINITION, V7_SURVEY_DEFINITION, V6_SURVEY_DEFINITION,
               V5_SURVEY_DEFINITION, V4_SURVEY_DEFINITION, LEGACY_SURVEY_DEFINITION)}
DEFINITIONS['helena-v2'] = deepcopy(LEGACY_SURVEY_DEFINITION)
for category in [DEFINITIONS['helena-v2']['demographics'], *DEFINITIONS['helena-v2']['categories']]:
    category['fields'] = [field for field in category['fields'] if not field['name'].endswith('_usefulness')]
DEFINITIONS['helena-v1'] = dict(demographics=dict(title='Erste Umfrage', fields=[
    dict(name='chat_helpfulness', title=QUESTIONS[0], kind='scale', scale=dict(min=1,max=5,low='Gar nicht hilfreich',high='Sehr hilfreich')),
    dict(name='added_value', title=QUESTIONS[1], kind='choice', options=list(ADDED_VALUE_LABELS.items())),
    dict(name='future_preference', title=QUESTIONS[2], kind='choice', options=list(PREFERENCE_LABELS.items())),
    dict(name='feedback', title=QUESTIONS[3], kind='text', optional=True),
]), categories=[])


def summarize(field, rows):
    maximum = field.get('scale', {}).get('max', 10)
    statuses = Counter()
    values = []
    texts = []
    for row in rows:
        answers = row['answers']
        status = answer_status(field, answers)
        value = answers.get(field['name'])
        if status == 'answered':
            if field['kind'] == 'scale' and (type(value) is not int or not 1 <= value <= maximum):
                status = 'invalid'
            elif field['kind'] == 'choice' and value not in dict(field.get('options', [])):
                status = 'invalid'
            elif field['kind'] in ('text', 'textarea'):
                if isinstance(value, str) and value.strip():
                    texts.append({'id': row['id'], 'participation_id': row['participation_id'],
                                  'arm': row['study_arm'], 'text': value})
                else:
                    status = 'no_answer'
            if status == 'answered':
                values.append(value)
        statuses[status] += 1
    counts = Counter(values)
    options = [(i, field.get('scale', {}).get('labels', [str(n) for n in range(1, maximum+1)])[i-1]) for i in range(1, maximum+1)] if field['kind'] == 'scale' else field.get('options', [])
    return dict(total=len(rows), n=len(values), statuses=dict(statuses),
                mean=round(mean(values), 3) if values and field['kind'] == 'scale' else None,
                median=median(values) if values and field['kind'] == 'scale' else None,
                distribution=[dict(value=value, label=label, count=counts[value],
                                   percent=round(100 * counts[value] / len(values), 1) if values else 0)
                              for value, label in options if value not in ('not_used', 'not_assessable', 'not_specified')],
                texts=texts[:50], remaining_texts=max(0, len(texts) - 50))


def construct_value(answers, construct):
    """Only complete numeric item sets yield a mean; missing values stay missing."""
    values = [answers.get(name) for name in construct['items']]
    if not all(type(value) is int and construct['min'] <= value <= construct['max'] for value in values):
        return None
    return mean(values)


def summarize_construct(rows, construct):
    values = [value for row in rows if (value := construct_value(row['answers'], construct)) is not None]
    return dict(total=len(rows), n=len(values), missing=len(rows)-len(values),
                mean=round(mean(values), 3) if values else None,
                median=round(median(values), 3) if values else None)


def analytics(rows, version):
    """Require a version; separate migrated experiment cohorts within that version."""
    definition = DEFINITIONS.get(version)
    result = dict(version=version, total=len(rows), completed=sum(r['response_status']=='completed' for r in rows),
                  in_progress=sum(r['response_status']=='in_progress' for r in rows),
                  versions=dict(Counter(r['survey_version'] for r in rows)), cohorts=[])
    if not definition:
        result['message'] = 'Dieser Fragebogen ist nicht mehr aktiv.'
        return result
    rows = [r for r in rows if r['survey_version'] == version]
    def cohort_key(row):
        return (row.get('experiment_id') or '', tuple(row.get('presentation_versions') or ['undocumented']), row.get('study_wave') or 'unknown', row.get('recruitment_batch') or '')
    def series_key(row):
        arm = row.get('study_arm') or ''
        policy = row.get('system_prompt_policy') or ''
        revision = row.get('system_prompt_revision')
        sha256 = row.get('system_prompt_base_sha256') or ''
        if version in ('helena-v11', 'helena-v12', 'helena-v13', 'helena-v14') and arm and policy and revision not in ('', None) and sha256:
            return f'{arm}:{policy}:{revision}:{sha256}'
        return arm
    experiments = sorted({cohort_key(r) for r in rows}) or [('', ('undocumented',), 'unknown', '')]
    for experiment, presentation, wave, batch in experiments:
        members = [r for r in rows if cohort_key(r) == (experiment, presentation, wave, batch)]
        arms = sorted({r['study_arm'] for r in members if r['study_arm']})
        series = {}
        for row in members:
            key = series_key(row)
            if not key:
                continue
            entry = series.setdefault(key, dict(
                arm=row['study_arm'],
                policy=row.get('system_prompt_policy') or '',
                revision=row.get('system_prompt_revision', ''),
                sha256=row.get('system_prompt_base_sha256') or '',
                count=0,
            ))
            entry['count'] += 1
        mixed_prompt_arms = sorted(
            arm for arm in arms
            if len({series_key(row) for row in members if row.get('study_arm') == arm}) > 1
        )
        cohort = dict(study_wave=wave,recruitment_batch=batch,experiment_id=experiment, presentation_versions=list(presentation), total=len(members),
                      arms={arm: sum(r['study_arm']==arm for r in members) for arm in arms},
                      series=series, mixed_prompt_arms=mixed_prompt_arms, categories=[])
        cohort['constructs'] = [{**construct, 'overall': summarize_construct(members, construct),
            'groups': {key: summarize_construct([row for row in members if series_key(row)==key], construct) for key in series}}
            for construct in definition.get('constructs', [])]
        for category in [definition['demographics'], *definition['categories']]:
            questions = []
            for field in category['fields']:
                if field.get('systemProvided'):
                    continue
                questions.append(dict(name=field['name'], title=field['title'], kind=field['kind'],
                                      scale=field.get('scale', definition.get('scale', {})),
                                      reverse=field['name'] in ('search_effort', 'study_effort'), visible_if=field.get('visibleIf'),
                                      **{key: field.get(key) for key in ('framework','construct','source_item','source_url','adaptation','direction','item_type')},
                                      overall=summarize(field, members),
                                      groups={key: summarize(field, [r for r in members if series_key(r)==key])
                                              for key in series}))
            cohort['categories'].append(dict(title=category['title'], questions=questions))
        result['cohorts'].append(cohort)
    return result
