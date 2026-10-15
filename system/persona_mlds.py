"""HELENA's own JSON-based MLDS profile; no generation or participant file writes.

The MLDS method leaves the domain language open. This module defines HELENA's
versioned envelope and preserves the existing AdvisorConfig/resolve_advisor
boundary: the stored model is editable configuration, not derived runtime data.
"""
from copy import deepcopy
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from advisor import AdvisorConfig


FORMAT = 'HELENA-Personality-MLDS'
SCHEMA_VERSION = 1
METHOD = 'Meta-Language-defined Structures'
REFERENCE = 'https://doi.org/10.15439/2025F5613'
PERSONAS_DIR = Path(__file__).resolve().parent / 'personas'
MAX_DOCUMENT_BYTES = 65536
Origin = Literal['builtin', 'session', 'legacy']


class MLDSError(ValueError):
    """Invalid HELENA personality document (message never contains its free text)."""


class _Provenance(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    method: Literal['Meta-Language-defined Structures']
    reference: Literal['https://doi.org/10.15439/2025F5613']
    origin: Origin


class _Template(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    id: Literal['career', 'expert', 'neutral', 'standard']
    subtitle: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=400)
    selectable: bool


class _Document(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    format: Literal['HELENA-Personality-MLDS']
    schema_version: Literal[1]
    provenance: _Provenance
    personality: AdvisorConfig
    template: _Template | None = None

    @field_validator('schema_version', mode='before')
    @classmethod
    def _integer_version(cls, value):
        # Literal[1] alone also accepts Python True and 1.0.
        if type(value) is not int:
            raise ValueError('Die MLDS-Version muss eine ganze Zahl sein.')
        return value

    @field_validator('personality', mode='before')
    @classmethod
    def _complete_personality(cls, value):
        if not isinstance(value, dict) or set(value) != set(AdvisorConfig.model_fields):
            raise ValueError('Die MLDS-Persönlichkeit muss alle Konfigurationsfelder enthalten.')
        return value

    @model_validator(mode='after')
    def _template_origin(self):
        if self.provenance.origin == 'builtin':
            if self.template is None:
                raise ValueError('Eingebaute Persönlichkeiten benötigen Vorlagenmetadaten.')
            if self.template.selectable != (self.template.id not in ('neutral', 'standard')):
                raise ValueError('Die allgemeine Vergleichsbedingung ist keine Auswahlvorlage.')
            if self.template.id in ('neutral', 'standard'):
                if self.personality.mode != 'preset' or self.personality.preset != self.template.id:
                    raise ValueError('Die allgemeine Basis benötigt das neutrale Profil.')
            elif self.personality.mode != 'custom':
                raise ValueError('Bearbeitbare Vorlagen benötigen eine eigene Konfiguration.')
        elif self.template is not None:
            raise ValueError('Nur eingebaute Persönlichkeiten enthalten Vorlagenmetadaten.')
        return self


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MLDSError('Doppelte JSON-Felder sind in MLDS nicht erlaubt.')
        result[key] = value
    return result


def _reject_constant(_value):
    raise MLDSError('Nicht endliche JSON-Zahlen sind in MLDS nicht erlaubt.')


def _decode(value):
    if isinstance(value, str):
        try:
            if len(value.encode('utf-8')) > MAX_DOCUMENT_BYTES:
                raise MLDSError('Das MLDS-Dokument ist zu groß.')
            value = json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        except MLDSError:
            raise
        except (ValueError, UnicodeError, RecursionError):
            raise MLDSError('Das MLDS-Dokument enthält kein gültiges JSON.') from None
    if not isinstance(value, dict):
        raise MLDSError('Eine Persönlichkeit muss als JSON-Objekt vorliegen.')
    return value


def _validate_document(value):
    try:
        return _Document.model_validate(_decode(value))
    except ValidationError:
        raise MLDSError('Die Persönlichkeit entspricht nicht der HELENA-MLDS-Spezifikation, Version 1.') from None


def _validated_config(value):
    try:
        # Revalidate model instances too; no model_construct shortcut at the boundary.
        if isinstance(value, AdvisorConfig):
            value = value.model_dump()
        return AdvisorConfig.model_validate({} if value is None else value).model_dump()
    except ValidationError:
        raise MLDSError('Die Persönlichkeitskonfiguration ist ungültig.') from None


def advisor_to_mlds(config=None, *, origin: Literal['session', 'legacy'] = 'session') -> dict:
    """Return a new MLDS document from an existing, normalized AdvisorConfig.

    This function only returns data. Session retention remains the caller's job.
    Builtins are loaded from reviewed .mlds files with their template metadata.
    """
    document = {
        'format': FORMAT,
        'schema_version': SCHEMA_VERSION,
        'provenance': {'method': METHOD, 'reference': REFERENCE, 'origin': origin},
        'personality': _validated_config(config),
    }
    return _validate_document(document).model_dump(exclude_none=True)


def advisor_from_mlds(value) -> dict:
    """Read MLDS (dict or JSON text) or a legacy raw AdvisorConfig.

    Legacy configurations receive precisely the existing AdvisorConfig defaults;
    they are never inferred from a name, converted to another preset, or written.
    Unknown versions and malformed MLDS fail closed instead of using defaults.
    """
    value = _decode(value)
    if any(key in value for key in ('format', 'schema_version', 'provenance', 'personality', 'template')):
        return _validate_document(value).personality.model_dump()
    return _validated_config(value)


def _load_builtin(template_id):
    # IDs originate only in the fixed catalog below, never in user input.
    path = PERSONAS_DIR / f'{template_id}.mlds'
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise MLDSError('Die eingebaute MLDS-Datei ist zu groß.')
    document = _validate_document(path.read_text(encoding='utf-8'))
    if (document.provenance.origin != 'builtin' or document.template is None
            or document.template.id != template_id):
        raise MLDSError('Die MLDS-Datei gehört nicht zur erwarteten Vorlage.')
    return document


def load_templates() -> dict:
    """Load the two editable UI templates as fresh dictionaries from .mlds files."""
    templates = {}
    for template_id in ('career', 'expert'):
        document = _load_builtin(template_id)
        advisor = document.personality.model_dump()
        templates[template_id] = {
            'name': advisor['name'],
            'subtitle': document.template.subtitle,
            'description': document.template.summary,
            'focus': advisor['focus'],
            'traits': list(advisor['traits']),
            'instructions': advisor['description'],
            'advisor': advisor,
            'mlds': document.model_dump(exclude_none=True),
        }
    return templates


def load_neutral_advisor() -> dict:
    """Load the general assistant baseline, which is not a selectable template."""
    return _load_builtin('neutral').personality.model_dump()


def load_standard_advisor() -> dict:
    """Fixed, task-competent control in the conference protocol; not selectable."""
    return _load_builtin('standard').personality.model_dump()


def personality_schema() -> dict:
    """Generate the published JSON Schema/MLDSI from the runtime model.

    JSON Schema additions describe semantic validators that Pydantic cannot infer.
    The checked-in Personality.mldsi is checked against this result in tests.
    """
    schema = deepcopy(_Document.model_json_schema())
    schema.update({
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        'title': 'HELENA Personality MLDSI, Version 1',
        'description': 'Eigene HELENA-Domänenspezifikation nach der MLDS-Methode; kein universeller MLDS-Standard. JSON-basierte Speicherung bearbeitbarer Assistentenkonfigurationen.',
        '$comment': f'Methodenquelle: {REFERENCE}. Die Versionsnummer bezeichnet ausschließlich das HELENA-Profil.',
    })
    advisor = schema['$defs']['AdvisorConfig']
    advisor['required'] = list(AdvisorConfig.model_fields)
    descriptions = {
        'mode': 'preset nutzt die bestehende Preset-Auflösung; custom nutzt die ausdrücklich gewählte Konfiguration.',
        'preset': 'Bestehende Preset-ID für die Rückwärtskompatibilität. Im Modus custom kein Ersatz für bearbeitete Eigenschaften oder Freitext.',
        'name': 'Bearbeitbarer Originalname des Assistenten, ohne automatische Ergänzung von -KI. Keine Aussage über eine reale Identität oder Qualifikation.',
        'description': 'Freitextwünsche zu Rolle, Ausdruck und Beratungsaufgabe. Unvertrauenswürdige Präferenzen, keine Nutzerqualifikationen, Jobbelege oder übergeordneten Systemregeln.',
        'traits': 'Einmalige ausdrücklich ausgewählte Eigenschaften in ihrer Reihenfolge. Steuern Ausdruck und bestehende ergänzende Bewertungsprioritäten, keine Zuschreibungen an den Jobsuchenden.',
        'focus': 'Vorhandener Beratungsschwerpunkt. Seine Bewertungswirkung wird unverändert in advisor.py berechnet; keine frei gespeicherten Score-Gewichte.',
    }
    for name, field in advisor['properties'].items():
        field.pop('default', None)
        field['description'] = descriptions[name]
    advisor['properties']['traits']['uniqueItems'] = True
    advisor['allOf'] = [{
        'if': {'properties': {'mode': {'const': 'custom'}}, 'required': ['mode']},
        'then': {'properties': {'traits': {'minItems': 1}}},
    }]
    schema['allOf'] = [{
        'if': {'properties': {'provenance': {'properties': {'origin': {'const': 'builtin'}}}}},
        'then': {'required': ['template'], 'properties': {'template': {'$ref': '#/$defs/_Template'}}},
        'else': {'properties': {'template': {'type': 'null'}}},
    }, {
        'if': {'required': ['template'], 'properties': {'template': {'type': 'object'}}},
        'then': {
            'if': {'properties': {'template': {'properties': {'id': {'enum': ['neutral', 'standard']}}}}},
            'then': {'properties': {
                'template': {'properties': {'selectable': {'const': False}}},
                'personality': {'properties': {'mode': {'const': 'preset'}}},
            }, 'allOf': [{
                'if': {'properties': {'template': {'properties': {'id': {'const': key}}}}},
                'then': {'properties': {'personality': {'properties': {'preset': {'const': key}}}}},
            } for key in ('neutral', 'standard')]},
            'else': {'properties': {
                'template': {'properties': {'selectable': {'const': True}}},
                'personality': {'properties': {'mode': {'const': 'custom'}}},
            }},
        },
    }]
    return schema
