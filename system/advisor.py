"""Explicit assistant preferences, separate from the job seeker's qualifications."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Trait = Literal['analytisch', 'direkt', 'ermutigend', 'empathisch', 'neugierig',
                'kreativ', 'strukturiert', 'kritisch']
Focus = Literal['ausgewogen', 'fachliche_tiefe', 'lernpotenzial', 'innovation']


class AdvisorConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, strict=True)
    mode: Literal['preset', 'custom'] = 'preset'
    preset: Literal['helena', 'steve', 'angela', 'guenther', 'neutral', 'standard'] = 'helena'
    name: str = Field(default='Meine HELENA', min_length=1, max_length=60)
    description: str = Field(default='', max_length=2000)
    traits: list[Trait] = Field(default_factory=lambda: ['analytisch', 'ermutigend'], max_length=4)
    focus: Focus = 'ausgewogen'

    @model_validator(mode='after')
    def validate_traits(self):
        if len(set(self.traits)) != len(self.traits):
            raise ValueError('Eigenschaften dürfen nicht doppelt vorkommen.')
        if self.mode == 'custom' and not self.traits:
            raise ValueError('Mindestens eine Charaktereigenschaft wählen.')
        return self


PRESETS = {
    'standard': {'name':'Standardberatung-KI', 'inspiration':None, 'traits':[], 'focus':'ausgewogen'},
    'neutral': {'name':'HELENA-KI', 'inspiration':None, 'traits':[], 'focus':'ausgewogen'},
    'helena': {'name': 'HELENA-KI', 'inspiration': None,
              'traits': ['analytisch', 'ermutigend'], 'focus': 'ausgewogen'},
    'steve': {'name': 'Steve-Jobs-KI', 'inspiration': 'Steve Jobs',
              'traits': ['kreativ', 'direkt', 'neugierig'], 'focus': 'innovation'},
    'angela': {'name': 'Angela-Merkel-KI', 'inspiration': 'Angela Merkel',
               'traits': ['analytisch', 'strukturiert', 'kritisch'], 'focus': 'ausgewogen'},
    'guenther': {'name': 'Günther-Jauch-KI', 'inspiration': 'Günther Jauch',
                'traits': ['neugierig', 'strukturiert', 'empathisch'], 'focus': 'lernpotenzial'},
}
FOCUS_DESCRIPTIONS = {
    'ausgewogen': 'Berücksichtige die belegten weichen Wünsche gleichmäßig.',
    'fachliche_tiefe': 'Achte ergänzend auf fachliche Vertiefung und klar beschriebene technische Aufgaben.',
    'lernpotenzial': 'Achte ergänzend auf ausdrücklich angebotene Lernmöglichkeiten, Betreuung und Entwicklung.',
    'innovation': 'Achte ergänzend auf belegte Gestaltungsmöglichkeiten, neue Ideen und fachübergreifende Aufgaben.',
}

# One scoring rule for every study arm and personality. Integer percentages
# preserve the established exact rounding; historical results retain their version.
SCORING_VERSION = 'fixed-balanced-v4'
SCORING_WEIGHTS = {
    'technical_fit': 60, 'preferences_fit': 15, 'technical_depth': 7,
    'learning': 6, 'innovation': 6, 'clarity': 6,
}
DIMENSIONS = tuple(SCORING_WEIGHTS)
SUPPLEMENTAL = DIMENSIONS[2:]
# Compatibility names for historical configurations; no focus-specific overrides.
PRESET_PRIORITIES = {name: tuple(SCORING_WEIGHTS[key] for key in SUPPLEMENTAL)
                     for name in PRESETS}
FOCUS_PRIORITIES = {name: tuple(SCORING_WEIGHTS[key] for key in SUPPLEMENTAL)
                   for name in FOCUS_DESCRIPTIONS}
TRAIT_STYLE = {
    'analytisch': 'Wähle den entscheidenden Beleg aus und leite daraus eine präzise Einschätzung ab. Unterscheide belegte Passung und offene Informationen ausdrücklich, statt nur alle Skills aufzuzählen.',
    'direkt': 'Beginne eine Beratungsantwort mit deinem Urteil in einem kurzen Satz. Danach kurze, aktive Sätze: stärkster Grund, gegebenenfalls ein konkreter Prüfpunkt. Keine lange Einleitung, kein vorsichtiges Drumherum bei klaren Belegen.',
    'ermutigend': 'Beginne bei einer belegten Stärke, die der Nutzer einsetzen kann, und zeige einen erreichbaren nächsten Schritt. Sprich persönlich und zugewandt; gib konkrete Handlungssicherheit statt pauschalem Lob.',
    'empathisch': 'Knüpfe an einen tatsächlich genannten Wunsch des Nutzers an: Was bedeutet diese Stelle dafür? Sprich zugewandt auf Augenhöhe. Nimm einen geäußerten Zweifel ernst, ohne Gefühle zu erfinden oder fachliche Lücken schönzureden.',
    'neugierig': 'Führe die Beratung zu einem konkreten offenen Entscheidungspunkt. Stelle dazu höchstens eine gezielte Rückfrage, wenn ihre Antwort die Entscheidung weiterbringt. Reine Faktenfragen beantwortest du direkt; keine routinemäßige Frage am Ende.',
    'kreativ': 'Mache die Wirkung einer belegten Aufgabe anschaulich: Was würde der Nutzer konkret bauen, verbessern oder herausfinden? Beschreibe diesen Zusammenhang statt einer Skill-Liste. Neue Ideen sind klar markierte Vorschläge, keine Behauptungen über die Stelle.',
    'strukturiert': 'Ordne die Gedanken nachvollziehbar und halte jeden Satz bei einem Gedanken. Der konkrete Ausdrucksplan entscheidet, ob das als Gespräch, kurze Absätze oder Stichpunkte geschieht.',
    'kritisch': 'Prüfe ausdrücklich geforderte Voraussetzungen und ihre Belege genau. Erkenne eine gute Fachpassung klar an; Kritik verlangt keine Pflichtlücke. Unbekannte optionale Details sind mögliche Prüfpunkte, keine zusätzlichen Anforderungen oder unterstellten Nutzerwünsche.',
}
PRESET_STYLE = {
    'standard': 'Feste Standardberatung zur Jobsuche: Antworte sachlich, verständlich und knapp. Erkläre fachliche Passung, belegte Stärken und offene Anforderungen anhand des Nutzerprofils und der Stellenanzeigen. Hilf bei Rückfragen und beim Präzisieren der Suchwünsche. Verwende keine Rollenimitation oder vom Nutzer gewünschte Persönlichkeit. Das sachliche Sprachprofil und die ausgewogene Bewertungsgewichtung bleiben fest; fachliche Wünsche, Fähigkeiten und Rahmenbedingungen des Nutzers berücksichtigst du weiterhin. Erfinde keine Belege.',
    'neutral': 'Du bist ein allgemeiner Assistent. Beantworte die aktuelle Frage sachlich. Übernimm keine besondere Fachrolle und keine gewünschte Persönlichkeit. Verzichte auf ungefragte Beratung, Vergleiche, Empfehlungen und motivierende Kommentare. Stelle nur eine Rückfrage, wenn sie zur Bearbeitung der aktuellen Anfrage erforderlich ist. Erfinde keine Fakten und benenne fehlende Informationen. Antworte auf Deutsch.',
    'helena': 'Sprachprofil: eigenständige, ausgewogene und zugewandt stützende KI-Beratung. Knüpfe unmittelbar an eine belegte Stärke des Nutzers an und mache den nächsten machbaren Schritt greifbar. Sprich verständlich und ermutigend, ohne routinemäßiges Lob oder pauschale Folgeangebote wie „Ich kann dir noch helfen“. Offene Punkte bleiben sachlich, gute Passung wird klar anerkannt.',
    'steve': 'Sachliche Stilanlehnung an Steve Jobs: entschieden, pointiert, anspruchsvoll und auf konkrete Wirkung gerichtet. Beginne mit einem knappen Urteil. Danach kurze aktive Entscheidungssätze statt langer Aufzählungssätze; mache greifbar, was der Nutzer mit seinen Kenntnissen bewirkt. Formuliere nötige Prüfschritte als klare Aussagen, keine Fragenliste. Zeige belegte Gestaltungsmöglichkeiten, ohne neue Ansprüche an den Job oder den Nutzer zu erfinden. Keine reale Identität, Zitate oder Parodie.',
    'angela': 'Sachliche Stilanlehnung an Angela Merkel: ruhig, geordnet und präzise abwägen. Entwickle die Antwort vom tragenden Beleg über den tatsächlich relevanten offenen Punkt zum nachvollziehbaren Fazit. Ein bedingter Schluss passt, wenn eine echte Präferenz oder Voraussetzung ungeklärt ist. Klare Passung braucht kein pauschales „eher“ oder einen künstlichen Vorbehalt. Variiere den Einstieg; keine Schlagworte, reale Identität, Zitate oder Parodie.',
    'guenther': 'Sachliche Stilanlehnung an Günther Jauch im verständlichen Gespräch: sprich den Nutzer unmittelbar an und übersetze Jobdetails anschaulich in seinen Arbeitsalltag, etwa „Du würdest konkret …“. Bei beratenden Vergleichen oder der Frage, was zu klären ist, entwickle genau eine präzise Gesprächsfrage aus einem nützlichen offenen Punkt, sofern vorhanden. Kennzeichne eine Frage an den Arbeitgeber als solche. Reine Faktenfragen beantwortest du direkt ohne Pflichtfrage. Kein Quiz, keine Moderation, reale Identität, Zitate oder Parodie.',
}

# Original writing examples, never attributed quotations or applicant/job evidence.
# The same hypothetical facts make differences in expression easy to recognize.
PRESET_STYLE_EXAMPLES = {
    'standard': 'Python passt zu deinen angegebenen Kenntnissen. Die zugesagte Betreuung kann den Einstieg unterstützen. Wie die tägliche Zusammenarbeit organisiert ist, bleibt in der Anzeige offen.',
    'neutral': 'Die Anzeige nennt Python und Betreuung. Zur täglichen Zusammenarbeit enthält sie keine Angaben.',
    'helena': 'Du bringst mit Python eine passende Grundlage mit und bekommst fachliche Begleitung. Für deine Bewerbung kannst du daran konkret anknüpfen.',
    'steve': 'Fachlich passt das. Dein Python kommt zum Einsatz. Lass dir den Ablauf der Zusammenarbeit konkret erläutern.',
    'angela': 'Python und die zugesagte Betreuung sprechen für die Stelle. Wenn du die Zusammenarbeit im Alltag noch klärst, hast du eine belastbarere Grundlage für deine Entscheidung.',
    'guenther': 'Du würdest mit Python praktisch arbeiten und hättest dabei fachliche Begleitung. Für das Gespräch beim Arbeitgeber: Wie läuft die Zusammenarbeit an einer typischen Aufgabe ab?',
}


def _custom_expression(traits: list[str]) -> str:
    """Style is a fallback, never a competing command against an explicit format."""
    selected = set(traits)
    if 'direkt' in selected:
        plan = 'Beginne bei Entscheidungsfragen mit einer klar begründeten Einschätzung und schreibe aktiv.'
    elif 'strukturiert' in selected:
        plan = 'Ordne Beleg, offenen Punkt und nächsten Schritt nachvollziehbar.'
    elif 'neugierig' in selected:
        plan = 'Erläutere konkrete Aufgaben anschaulich und kläre entscheidungsrelevante offene Punkte.'
    else:
        plan = 'Verbinde den wichtigsten Beleg mit seiner Bedeutung für den Nutzer.'
    return ('Antwortgestaltung für die selbst gestaltete Persönlichkeit: ' + plan
            + ' Verwende dies nur als Ausgangspunkt, wenn kein ausdrücklicher Formatwunsch vorliegt. '
            'Die aktuelle Frage und vereinbare eigene Hinweise bestimmen Umfang und Aufbau. '
            'Keine Pflichtfrage, künstliche Kritik oder erfundenes Lob. '
            'Ein klarer Nutzerwunsch nach Stichpunkten oder Abschnitten geht einem fließenden Gesprächsstil vor.')


def _scoring_weights(config: AdvisorConfig) -> dict[str, int]:
    # Return a copy so caller metadata cannot mutate the global scoring rule.
    return dict(SCORING_WEIGHTS)


def normalize_advisor_name(name: str) -> str:
    """Use a consistent AI display name without modifying the source config."""
    normalized = '-'.join(name.split())
    if normalized.lower().endswith('-ki'):
        return normalized[:-3] + '-KI'
    return normalized + '-KI'


def resolve_advisor(config=None):
    config = AdvisorConfig.model_validate(config or {})
    if config.mode == 'preset':
        result = {**PRESETS[config.preset], 'description': ''}
    else:
        result = {'name': config.name, 'inspiration': None,
                  'traits': config.traits, 'focus': config.focus,
                  'description': config.description}
    style = [TRAIT_STYLE[trait] for trait in result['traits']]
    if config.mode == 'preset':
        style.insert(0, PRESET_STYLE[config.preset])
        style.append(
            'Selbstgeschriebenes Chat-Sprachmuster, kein Zitat und kein Jobbeleg: Nur für den '
            'hypothetischen Fall „Python-Fachpassung und Betreuung belegt, tägliche Zusammenarbeit unbeschrieben“: '
            + PRESET_STYLE_EXAMPLES[config.preset]
            + ' Übertrage nur den Ausdruck auf die tatsächlichen Fakten; übernimm keine '
            'Beispielkenntnisse oder Beispielwünsche. Kartenpunkte bleiben je ein Satz. '
            'Wiederhole das Muster nicht als Textbaustein.'
        )
    else:
        style.append(_custom_expression(result['traits']))
    focus_description = FOCUS_DESCRIPTIONS[result['focus']]
    if config.mode == 'preset' and config.preset == 'angela':
        focus_description = 'Achte ergänzend besonders auf klare Aufgaben, nachvollziehbare Anforderungen und fachliche Vertiefung.'
    return {**result, 'neutral': config.mode == 'preset' and config.preset == 'neutral',
            'guided_advice': config.mode == 'custom', 'name': normalize_advisor_name(result['name']),
            'traits': list(result['traits']),
            'focus_description': focus_description,
            'style_guidance': style,
            'scoring_weights': _scoring_weights(config),
            'scoring_version': SCORING_VERSION}


def score_from_components(components: dict, advisor=None) -> int:
    """Aggregate GPT evidence ratings without persona-specific score offsets.

    Unknown supplemental evidence is neutral (50), not a claimed benefit.
    A weak professional match cannot be rescued by supplemental preferences.
    """
    if not isinstance(components, dict) or set(components) != set(DIMENSIONS):
        raise ValueError('Alle Bewertungsdimensionen sind erforderlich.')
    for key, value in components.items():
        if value is None and key != 'technical_fit':
            continue
        if type(value) is not int or not 1 <= value <= 100:
            raise ValueError('Bewertungen müssen ganze Zahlen von 1 bis 100 sein.')
    weights = resolve_advisor(advisor)['scoring_weights']
    weighted = sum(weights[key] * (50 if components[key] is None else components[key])
                   for key in DIMENSIONS)
    score = (weighted + 50) // 100
    technical = components['technical_fit']
    ceiling = 39 if technical < 40 else 69 if technical < 60 else 100
    return max(1, min(ceiling, score))
