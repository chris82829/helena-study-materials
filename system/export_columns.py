"""Stable, readable export names; stored questionnaire keys are never renamed."""
import re

COLUMN_FORMATS = ('readable', 'technical')

META_TITLES = {
    'participation_id': ('teilnahme_id', 'Teilnahme-ID für Zuordnung und Löschung'),
    'submitted_at_utc': ('abgeschlossen_am_utc', 'Zeitpunkt des ursprünglichen Umfrageabschlusses (UTC)'),
    'survey_version': ('fragebogen_version', 'Version des beantworteten Fragebogens'),
    'study_release_ids': ('systemstand_ids', 'Kennungen der während der Teilnahme verwendeten Systemstände'),
    'openai_models': ('openai_modelle', 'Verwendete OpenAI-Modellversionen'),
    'reasoning_efforts': ('denkaufwand_stufen', 'Verwendete Einstellungen für den Denkaufwand'),
    'response_status': ('teilnahme_status', 'Abgeschlossen oder noch unvollständig'),
    'last_saved_at_utc': ('zuletzt_gespeichert_am_utc', 'Letzter Speicher- oder Korrekturzeitpunkt (UTC)'),
    'study_arm': ('studiengruppe', 'Studiengruppe A, B oder C; Bedeutung anhand von Fragebogenversion und Experimentkennung bestimmen'),
    'experiment_id': ('experiment_id', 'Kennung des Experiments; gemeinsam mit Fragebogenversion auswerten'),
    'assigned_at_utc': ('zugeteilt_am_utc', 'Zeitpunkt der ursprünglichen Gruppenzuteilung (UTC)'),
    'prior_exposure': ('vorherige_systemnutzung', 'Suchsitzung bereits vor der ursprünglichen Gruppenzuteilung vorhanden'),
    'system_prompt_policy': ('systemprompt_variante', 'Unveränderlich zugeordnete Systemprompt-Variante; bei historischen Teilnahmen leer'),
    'system_prompt_revision': ('systemprompt_revision', 'Revision der unveränderlich zugeordneten Promptfassung; zusammen mit Variante und SHA-256 auswerten'),
    'system_prompt_base_sha256': ('systemprompt_basis_sha256', 'SHA-256-Prüfsumme des unveränderlich zugeordneten Basis-Systemprompts; bei C enthält sie nicht die anschließend ergänzte selbst gestaltete Persönlichkeit; bei leerem A-Prompt ist dies die Prüfsumme des leeren Textes'),
    'presentation_versions': ('darstellungs_versionen', 'Versionen der Ergebnisdarstellung während der Teilnahme'),
    'correction_count': ('antwortkorrekturen_anzahl', 'Anzahl gespeicherter Verwaltungskorrekturen'),
    'last_corrected_at_utc': ('zuletzt_korrigiert_am_utc', 'Zeitpunkt der letzten Verwaltungskorrektur (UTC)'),
    'personality_capture_version': ('ki_nutzung_erfassungsversion', 'Version der automatischen Erfassung tatsächlich angewendeter KI-Persönlichkeiten'),
    'personality_initial_source': ('ki_erste_verwendung', 'Herkunft der zuerst erfassten, tatsächlich angewendeten KI-Persönlichkeit'),
    'personality_initial_template_id': ('ki_erste_vorlage', 'Zuerst tatsächlich angewendete unveränderte KI-Vorlage'),
    'personality_last_source': ('ki_letzte_verwendung', 'Herkunft der zuletzt erfassten, tatsächlich angewendeten KI-Persönlichkeit'),
    'personality_last_template_id': ('ki_letzte_vorlage', 'Zuletzt tatsächlich angewendete unveränderte KI-Vorlage'),
    'personality_ever_custom': ('ki_jemals_selbst_gestaltet', 'Im erfassten Zeitraum mindestens einmal eine selbst gestaltete KI-Persönlichkeit angewendet'),
    'personality_ever_template': ('ki_jemals_vorlage', 'Im erfassten Zeitraum mindestens einmal eine unveränderte KI-Vorlage angewendet'),
    'personality_selection_change_count': ('ki_auswahlwechsel_anzahl', 'Anzahl erfasster Wechsel zwischen Vorlage und Selbstgestaltung oder zwischen Vorlagen'),
    'personality_first_applied_at_utc': ('ki_erstmals_angewendet_am_utc', 'Beginn des erfassten Nutzungszeitraums (UTC)'),
    'personality_last_selection_changed_at_utc': ('ki_auswahl_geaendert_am_utc', 'Zeitpunkt des zuletzt erfassten Auswahlwechsels bzw. der ersten Anwendung (UTC)'),
}

META_TITLES.update({
    'study_wave': ('studienphase','Bei Einwilligung festgeschriebene Phase: pretest oder main; fehlend bedeutet unbekannt'),
    'recruitment_batch': ('versandwelle_utc','Konfigurierter UTC-Zeitpunkt der zugehörigen Einladungswelle'),
    'viewport_class': ('ansicht_ersterfasst','Erste erfasste UI-Darstellung mobile/desktop; keine Gerätekennung'),
    'viewport_class_last': ('ansicht_zuletzt','Letzte erfasste UI-Darstellung; mobile bis einschließlich 850 CSS-Pixel'),
    'furthest_step_reached': ('weitester_studienschritt','Weitester serverseitig belegter Studienschritt, monoton'),
    'context_config_revision': ('studienphase_revision','Unveränderliche Kontextrevision bei Einwilligung'),
})

META_TITLES['operations_capture_version'] = ('nutzung_erfassungsversion', 'Version der serverseitigen Erfassung aggregierter Nutzungsoperationen')
for _kind, _label, _prefix in [('search', 'Suche über den Stellenbestand', 'suchen'), ('rerank', 'Neusortierung bestehender Ergebnisse', 'neusortierungen'), ('chat', 'Nutzer-Chatnachricht', 'chatnachrichten')]:
    META_TITLES[f'operations_successful_{_kind}_count'] = (f'{_prefix}_erfolgreich_anzahl', f'Anzahl erfolgreich abgeschlossener Operationen: {_label}')
    META_TITLES[f'operations_failed_{_kind}_count'] = (f'{_prefix}_fehlgeschlagen_anzahl', f'Anzahl fehlgeschlagener Operationen: {_label}')
    META_TITLES[f'operations_{_kind}_duration_ms'] = (f'{_prefix}_dauer_gesamt_ms', f'Gesamte erfasste Laufzeit in Millisekunden: {_label}')

QUESTION_NAMES = {
    'adapt_search_ease': 'suchwuensche_aendern_einfachheit',
    'age_group': 'altersgruppe',
    'chat_helpfulness': 'chat_hilfreich',
    'chat_used': 'chat_selbst_genutzt',
    'education': 'studien_ausbildungssituation',
    'explanation_helpfulness': 'begruendungen_verstaendlichkeit',
    'express_search_needs': 'suchwuensche_mitteilen',
    'feedback': 'verbesserungsvorschlaege_freitext',
    'future_use': 'kuenftige_nutzung',
    'gender': 'geschlecht',
    'match_reasons_usefulness': 'begruendungen_nutzen',
    'personality_clarity': 'ki_wirkung_verstaendnis',
    'personality_clarity_chat': 'ki_wirkung_chat_verstaendnis',
    'personality_clarity_explanations': 'ki_wirkung_sprachstil_begruendungen_verstaendnis',
    'personality_clarity_search': 'ki_wirkung_rangfolge_verstaendnis',
    'personality_consistency': 'ki_eigenschaften_wiedererkannt',
    'personality_customized': 'ki_selbst_angepasst_selbstauskunft',
    'personality_setup': 'ki_einrichten_einfachheit',
    'job_portal_experience': 'jobportal_vorerfahrung',
    'ai_chat_experience': 'ki_chat_vorerfahrung',
    'template_selection_ease': 'ki_vorlagenauswahl_einfachheit',
    'personality_value': 'ki_personalisierung_mehrwert',
    'personalized_chat_usefulness': 'chat_personalisierung_nutzen',
    'personalized_search_usefulness': 'suche_personalisierung_nutzen',
    'score_usefulness': 'score_nutzen',
    'search_ease': 'system_bedienung_einfachheit',
    'search_effort': 'suche_aufwand',
    'search_goal': 'suchvorhaben_freitext',
    'search_refinement': 'suchwuensche_im_chat_geaendert',
    'study_arm': 'studiengruppe_originalcode',
    'study_field': 'studien_fachrichtung_freitext',
    'usefulness_effective': 'system_nutzen_effektivitaet',
    'usefulness_speed': 'system_nutzen_geschwindigkeit',
    'usefulness_overall': 'system_nutzen_gesamturteil',
    'system_usefulness': 'system_nutzen',
    'added_value': 'mehrwert_gegenueber_filterboerse',
    'future_preference': 'ki_beratung_kuenftig_bevorzugt',
}

QUESTION_NAMES.update({'previous_participation':'fruehere_teilnahme_selbstauskunft','trust_fit':'vertrauen_passung','trust_credibility':'vertrauen_glaubwuerdigkeit','perceived_character':'manipulationscheck_beratungscharakter','trust_mean':'vertrauen_mittelwert','usefulness_ideal': 'nutzen_passende_stelle', 'usefulness_find_easy': 'nutzen_einfacher_finden', 'usefulness_suggestions': 'nutzen_vorschlaege', 'dialogue_understanding': 'dialog_verstaendnis', 'dialogue_response_quality': 'dialog_antwortqualitaet', 'dialogue_attentiveness': 'dialog_aufmerksamkeit', 'control_preferences': 'kontrolle_praeferenzen', 'control_recommendations': 'kontrolle_empfehlungen', 'control_adjustment': 'kontrolle_anpassung', 'transparency_why': 'transparenz_empfehlungsgrund', 'transparency_assessment': 'transparenz_bewertung', 'transparency_fit': 'transparenz_passung', 'overall_satisfaction': 'gesamtzufriedenheit', 'intention_reuse': 'wiederverwendungsabsicht', 'study_effort': 'zusatz_suchaufwand', 'study_style_control': 'zusatz_beratungsstil_steuerbarkeit', 'usefulness_mean': 'nutzen_mittelwert', 'control_mean': 'kontrolle_mittelwert', 'transparency_mean': 'transparenz_mittelwert'})


def validate_columns(columns):
    if columns not in COLUMN_FORMATS:
        raise ValueError('Spaltennamen müssen readable oder technical sein.')
    return columns


def export_name(technical, columns='readable'):
    validate_columns(columns)
    if columns == 'technical':
        return technical
    if technical in META_TITLES:
        return META_TITLES[technical][0]
    match = re.fullmatch(r'(v[1-9][0-9]*)_(.+)', technical)
    prefix, name = (match.group(1), match.group(2)) if match else ('v3' if technical.endswith('_usefulness') else 'v2_v3', technical)
    suffix = ''
    if name.endswith('_status'):
        name, suffix = name[:-7], '_antwortstatus'
    # From V6 onward this question specifically concerns clarifying search wishes.
    base = 'chat_hilfe_suchwuensche' if name == 'chat_helpfulness' and prefix in ('v6', 'v7', 'v8', 'v9', 'v10', 'v11', 'v12') else QUESTION_NAMES[name]
    return f'{prefix}_{base}{suffix}'


def export_headers(technical, columns='readable'):
    validate_columns(columns)
    result = [export_name(name, columns) for name in technical]
    if len(result) != len(set(result)):
        raise ValueError('Exportspalten müssen eindeutig sein.')
    return result
