"""Validated API inputs: only employment type is hard; other context guides the LLM.

The legacy ``filters`` field keeps its shape for existing clients and sessions.
Its location, work-model and hours values are soft preferences, not exclusions.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from advisor import AdvisorConfig

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
Employment = Literal['werkstudent', 'praktikum', 'vollzeit', 'teilzeit',
                     'ausbildung', 'trainee', 'abschlussarbeit', 'sonstige']
Remote = Literal['onsite', 'hybrid', 'remote', 'unknown']


class APIModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, strict=True)


class Filters(APIModel):
    """Legacy API container: one hard employment filter plus soft preferences."""

    employment_types: list[Employment] = Field(default_factory=list, max_length=8,
        description='Einziger harter Filter: zulässige Stellenarten mit ODER-Verknüpfung; leer lässt alle zu.')
    locations: list[ShortText] = Field(default_factory=list, max_length=10,
        description='Gewünschte Orte als weicher LLM-Kontext; andere oder unbekannte Orte bleiben zulässig.')
    remote: list[Remote] = Field(default_factory=list, max_length=4,
        description='Bevorzugte Arbeitsmodelle als weicher LLM-Kontext, ohne Ausschluss anderer Modelle.')
    max_hours: float | None = Field(default=None, gt=0, le=80,
        description='Gewünschter maximaler Wochenstundenumfang als weiche Präferenz, ohne SQL-Ausschluss.')


class Profile(APIModel):
    """Applicant information and preferences; CV content never becomes a hard filter."""

    query: str = Field(default='', max_length=3000)
    skills: list[ShortText] = Field(default_factory=list, max_length=60)
    preferences: list[ShortText] = Field(default_factory=list, max_length=30)
    cv_text: str = Field(default='', max_length=16000,
        description='Lebenslauf als Kontext für fachliche Passung und Begründungen, kein harter Filter.')
    filters: Filters = Field(default_factory=Filters,
        description='Kompatibler Feldcontainer: nur employment_types ist hart; Ort, Arbeitsmodell und Stunden sind weiche Wünsche.')

    @model_validator(mode='after')
    def useful_input(self):
        if not (self.query or self.skills or self.preferences or self.cv_text):
            raise ValueError('Bitte Suchwunsch, Skills, Präferenzen oder Lebenslauf angeben.')
        return self


class AdvisorSelection(APIModel):
    source: Literal['template', 'custom']
    template_id: Literal['career', 'expert'] | None = None

    @model_validator(mode='after')
    def consistent_source(self):
        if (self.source == 'template') != (self.template_id is not None):
            raise ValueError('Vorlage und Auswahlart passen nicht zusammen.')
        return self


class SearchInput(APIModel):
    profile: Profile
    advisor: AdvisorConfig = Field(default_factory=AdvisorConfig)
    advisor_selection: AdvisorSelection | None = None


class ChatInput(APIModel):
    session_id: str = Field(min_length=32, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    message: str = Field(default='', max_length=3000)
    advisor: AdvisorConfig | None = None
    advisor_selection: AdvisorSelection | None = None
    profile: Profile | None = None
    mode: Literal['auto', 'rerank', 'search'] = 'auto'

    @model_validator(mode='after')
    def meaningful_turn(self):
        if self.advisor_selection is not None and self.advisor is None:
            raise ValueError('Die Persönlichkeitsauswahl benötigt die zugehörige Konfiguration.')
        if not self.message and self.advisor is None and self.profile is None and self.mode == 'auto':
            raise ValueError('Nachricht, Profil, Persönlichkeitskonfiguration oder Aktion erforderlich.')
        if self.message and self.profile is not None:
            raise ValueError('Profilbearbeitung und Chatnachricht getrennt senden.')
        return self
