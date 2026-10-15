"""Consent-bound, filter-bound descriptive usage analysis for the administration.

Card-visible durations may overlap between simultaneously visible cards. They are
neither elapsed session time nor a measurement of actual reading or attention.
Missing capture is deliberately NULL, never an invented zero observation.
"""
import csv
import io
import json
import statistics

from study_context import context_snapshot
from study_metrics import operation_diagnostics

METRIC_NAMES = ('dwell_seconds', 'viewed_job_count', 'job_expand_count',
                'job_detail_count', 'successful_chat_count')
EVENT_NAMES = ('dwell_justification', 'job_expand', 'job_detail', 'chat_turn')
NOTES = [
    'Die sichtbare Begründungszeit summiert erfasste Zeitabschnitte je Stellenkarte. '
    'Gleichzeitig sichtbare Karten können sich zeitlich überschneiden; dies ist '
    'weder die gesamte Nutzungsdauer noch ein Nachweis tatsächlicher Aufmerksamkeit.',
    'Fehlende Erfassung wird als unbekannt ausgewiesen und nicht als null Sekunden '
    'oder null Klicks in Mittelwerte einbezogen. Auch vorhandene Ereignisse '
    'garantieren keine lückenlose Erfassung (z. B. bei Verbindungsabbrüchen).',
    'Chatnachrichten stammen aus dem erfolgreichen serverseitigen Nachrichten-Zähler. '
    'Fehlgeschlagene Nachrichten und Telemetrie-Ereignisse erhöhen diesen Wert nicht.',
    'Die Ansicht und beide CSV-Exporte berücksichtigen dieselbe Auswahl der Teilnahmen. '
    'Zeitangaben sind in Sekunden; Ereignis-Zeitstempel sind UTC.',
]


def _table_exists(db, name):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _object(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _natural(value):
    return value if type(value) is int and value >= 0 else None


def _metric(values):
    observed = [value for value in values if value is not None]
    return dict(n=len(observed), mean=round(statistics.mean(observed), 3) if observed else None,
                median=round(statistics.median(observed), 3) if observed else None,
                total=round(sum(observed), 3) if observed else None,
                min=min(observed) if observed else None, max=max(observed) if observed else None)


def _summary(participants):
    return dict(participant_count=len(participants), event_count=sum(row['event_count'] for row in participants),
                metrics={name: _metric([row[name] for row in participants]) for name in METRIC_NAMES})


def telemetry_analysis(db, rows):
    """Analyze already filtered AdminSurveyData rows inside the caller's DB read.

    Active study consent is re-checked here so a stale filtered list cannot leak
    revoked/deleted participants. Neither token hashes nor free text are returned.
    A participant appears once even if several historical response rows exist.
    """
    allowed = {}
    for row in rows:
        identifier = row.get('participation_id')
        if identifier and row.get('consent_linked', True):
            # Admin records are newest first. Do not duplicate the same events
            # when multiple answers share one participant identity.
            allowed.setdefault(identifier, row)
    active = {}
    if allowed and _table_exists(db, 'privacy_consents'):
        for digest, identifier in db.execute("SELECT token_hash, participation_id FROM privacy_consents WHERE purpose='study' AND withdrawn_at IS NULL"):
            if identifier in allowed:
                active[digest] = identifier
    participants = {}
    for digest, identifier in active.items():
        row = allowed[identifier]
        participants[identifier] = dict(
            participation_id=identifier, study_arm=row.get('study_arm') or '',
            response_status=row.get('response_status') or '', response_id=row.get('id') or '',
            response_kind=row.get('response_status') or '',
            event_count=0, client_event_count=0, dwell_event_count=0,
            dwell_seconds=None, viewed_job_count=None, job_expand_count=None,
            job_detail_count=None, successful_chat_count=None,
            first_event_at=None, last_event_at=None, jobs={}, _dwell_ms=0,
            **context_snapshot(digest, db), **operation_diagnostics(digest, db),
        )
    # Do not derive successful chat counts from chat_turn rows or their metadata.
    # This is the same durable operation counter used by the study's 3-turn gate.
    if active and _table_exists(db, 'study_operation_metrics'):
        for digest, raw in db.execute('SELECT token_hash, metadata_json FROM study_operation_metrics'):
            identifier = active.get(digest)
            if identifier:
                metrics = _object(raw)
                if _natural(metrics.get('capture_version')):
                    participants[identifier]['successful_chat_count'] = _natural(metrics.get('successful_chat_count'))
    event_counts = dict.fromkeys(EVENT_NAMES, 0)
    if active and _table_exists(db, 'track_events'):
        for digest, session_id, kind, timestamp, raw in db.execute(
                'SELECT token_hash, session_id, event_type, timestamp, metadata FROM track_events ORDER BY id'):
            identifier = active.get(digest)
            if not identifier or kind not in event_counts:
                continue
            participant = participants[identifier]
            metadata = _object(raw)
            event_counts[kind] += 1
            participant['event_count'] += 1
            if participant['first_event_at'] is None or timestamp < participant['first_event_at']:
                participant['first_event_at'] = timestamp
            if participant['last_event_at'] is None or timestamp > participant['last_event_at']:
                participant['last_event_at'] = timestamp
            if kind == 'chat_turn':
                continue
            participant['client_event_count'] += 1
            if participant['job_expand_count'] is None:
                participant['job_expand_count'] = participant['job_detail_count'] = 0
            job_id = metadata.get('job_id')
            if not isinstance(job_id, (str, int)) or isinstance(job_id, bool) or not str(job_id):
                continue
            job_id = str(job_id)
            job = participant['jobs'].setdefault(job_id, dict(
                job_id=job_id, dwell_seconds=None, job_expand_count=0,
                job_detail_count=0, displayed_ranks=set(), _sessions=set(), _dwell_ms=0))
            job['_sessions'].add(session_id)
            rank = _natural(metadata.get('rank'))
            if rank:
                job['displayed_ranks'].add(rank)
            if kind == 'dwell_justification':
                duration = _natural(metadata.get('duration_ms'))
                if duration is not None:
                    participant['dwell_event_count'] += 1
                    participant['_dwell_ms'] += duration
                    job['_dwell_ms'] += duration
                    participant['dwell_seconds'] = round(participant['_dwell_ms'] / 1000, 3)
                    job['dwell_seconds'] = round(job['_dwell_ms'] / 1000, 3)
            else:
                counter = f'{kind}_count'
                participant[counter] += 1
                job[counter] += 1
    result = []
    for participant in participants.values():
        if participant['client_event_count']:
            participant['viewed_job_count'] = len(participant['jobs'])
        jobs = []
        for job in participant['jobs'].values():
            job['displayed_ranks'] = sorted(job['displayed_ranks'])
            job['session_count'] = len(job.pop('_sessions'))
            job.pop('_dwell_ms')
            jobs.append(job)
        participant['jobs'] = sorted(jobs, key=lambda item: (-(item['dwell_seconds'] or 0), item['job_id']))
        participant.pop('_dwell_ms')
        result.append(participant)
    result.sort(key=lambda item: item['participation_id'])
    summary = _summary(result)
    coverage = dict(
        with_events=sum(row['event_count'] > 0 for row in result),
        with_client_events=sum(row['client_event_count'] > 0 for row in result),
        with_dwell=sum(row['dwell_seconds'] is not None for row in result),
        with_chat_metrics=sum(row['successful_chat_count'] is not None for row in result),
        without_events=sum(row['event_count'] == 0 for row in result),
        without_client_events=sum(row['client_event_count'] == 0 for row in result),
    )
    groups = [dict(study_arm=arm, **_summary([row for row in result if row['study_arm'] == arm])) for arm in ('A', 'B', 'C')]
    return dict(summary=summary, groups=groups, participants=result, coverage=coverage,
                events=event_counts, notes=list(NOTES))


CSV_COLUMNS = (
    ('teilnahme_id', 'participation_id'), ('studiengruppe', 'study_arm'),
    ('antwortstatus', 'response_status'), ('studienphase', 'study_wave'),
    ('rekrutierungswelle_utc', 'recruitment_batch'), ('ansicht_bei_beginn', 'viewport_class'),
    ('ansicht_zuletzt', 'viewport_class_last'), ('weitester_studienschritt', 'furthest_step_reached'),
    ('fehlgeschlagene_versuche', 'failed_attempt_count'), ('letzter_fehlercode', 'last_error_code'),
    ('letzte_fehlerphase', 'last_error_stage'), ('letzte_operation_erfolgreich', 'last_operation_success'),
    ('ereignisse_anzahl', 'event_count'),
    ('browserereignisse_anzahl', 'client_event_count'),
    ('begruendung_sichtbare_zeit_summe_sekunden', 'dwell_seconds'),
    ('stellen_mit_erfasster_interaktion_anzahl', 'viewed_job_count'),
    ('begruendungen_aufgeklappt_anzahl', 'job_expand_count'),
    ('stellendetails_geoeffnet_anzahl', 'job_detail_count'),
    ('erfolgreiche_chatnachrichten_anzahl', 'successful_chat_count'),
    ('erstes_ereignis_utc', 'first_event_at'), ('letztes_ereignis_utc', 'last_event_at'),
)


def telemetry_participant_csv(analysis):
    """One participant per row; empty unknown values and explicit time units."""
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=';')
    writer.writerow([label for label, _key in CSV_COLUMNS])
    for participant in analysis['participants']:
        values = []
        for _label, key in CSV_COLUMNS:
            value = participant.get(key)
            if isinstance(value, str) and value.startswith(('=', '+', '-', '@')):
                value = "'" + value
            values.append(value)
        writer.writerow(values)
    return '\ufeff' + output.getvalue()
