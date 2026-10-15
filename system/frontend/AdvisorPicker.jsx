import React, { useId, useState } from 'react';
import { Check, BriefcaseBusiness, GraduationCap, Info, SlidersHorizontal } from 'lucide-react';
import { ADVISOR_DESCRIPTION_MAX_LENGTH, advisorFromTemplate, advisorTemplates, editableAdvisor, sameAdvisor, traitLabels, focusLabels, focusDescriptions } from './advisor.js';
import './advisor-picker.css';
import {templateSelection, selectedTemplate as selectionTemplate} from './advisor-selection.js';

export default function AdvisorPicker({ value, onChange, disabled, headingRef, onExplain, templates = advisorTemplates, selection, allowCustom = true }) {
  const draft = editableAdvisor(value);
  const id = useId();
  const [notice, setNotice] = useState('');
  const selectedTemplate = selectionTemplate(selection, Object.keys(templates).find(key => sameAdvisor(draft, advisorFromTemplate(key, templates))) || '');
  const update = (key, item) => onChange({ ...draft, [key]: item }, templateSelection(''));
  function useTemplate(key) {
    onChange(advisorFromTemplate(key, templates), templateSelection(key));
    setNotice(key ? `${templates[key].name} ausgewählt.` : 'Du kannst deine KI jetzt selbst gestalten.');
  }
  return <section className="advisor-picker advisor-builder" aria-label="Deine Suchpersönlichkeit">
    <div className="advisor-intro profile-intro profile-intro--compact"><span className="step-label">DEINE SUCHPERSÖNLICHKEIT</span><div className="advisor-intro-heading"><div className="advisor-title"><h3 ref={headingRef} tabIndex={-1}>KI-Suchpersönlichkeit</h3><button type="button" className="advisor-help" onClick={onExplain} disabled={disabled} aria-label="Wie beeinflusst das meine Suche?" title="Wie beeinflusst das meine Suche?" aria-haspopup="dialog"><Info size={16} aria-hidden="true" /></button></div>
    </div></div>
    <fieldset className="advisor-role-options" disabled={disabled}>
      <legend>Wie möchtest du beraten werden?</legend>
      <p className="advisor-role-hint">Wähle eine Karte. Deine Auswahl beeinflusst die Stellenbewertung und das Gespräch.</p>
      {[...Object.entries(templates), ...(allowCustom ? [['', {name:'Selbst personalisieren', description:'Lege Name, Eigenschaften und Bewertungsschwerpunkt selbst fest.'}]] : [])].map(([key, option]) => {
        const Icon = key === 'career' ? BriefcaseBusiness : key === 'expert' ? GraduationCap : SlidersHorizontal;
        return <label className={`advisor-role-card${selectedTemplate === key ? ' is-selected' : ''}`} key={key || 'custom'}>
          <input type="radio" name={`${id}-role`} value={key} checked={selectedTemplate === key} onChange={() => useTemplate(key)} />
          <Icon size={22} aria-hidden="true"/><span><strong>{option.name}</strong><span>{option.description}</span></span>
          {selectedTemplate === key && <Check className="advisor-role-check" size={18} aria-hidden="true"/>}
        </label>;
      })}
    </fieldset>
    <span className="sr-only" role="status">{notice}</span>
    {allowCustom && selectedTemplate === '' && <div className="advisor-custom">

      <label className="advisor-name-field" htmlFor={`${id}-name`}><span>Name deiner KI</span><input id={`${id}-name`} required maxLength={60} value={draft.name} onChange={e => update('name', e.target.value)} disabled={disabled} placeholder="Name eingeben" aria-describedby={`${id}-name-hint`} /><span className="sr-only" id={`${id}-name-hint`}>Dieser Name steht im Chat und an deinem persönlichen Score.</span></label>
      <label htmlFor={`${id}-focus`}><span>Was soll zusätzlich bei Stellen zählen?</span><select id={`${id}-focus`} value={draft.focus} onChange={e => update('focus', e.target.value)} disabled={disabled} aria-describedby={`${id}-focus-hint`}>{Object.entries(focusLabels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select><span className="field-hint" id={`${id}-focus-hint`}>{focusDescriptions[draft.focus]}</span></label>
      <fieldset disabled={disabled} aria-describedby={`${id}-traits-hint`}><legend>Wie soll deine KI mit dir sprechen?</legend><div className="choice-group">{Object.entries(traitLabels).map(([key, label]) => <label className={`choice ${draft.traits.includes(key) ? 'selected' : ''}`} key={key}><input type="checkbox" checked={draft.traits.includes(key)} disabled={!draft.traits.includes(key) && draft.traits.length >= 4} onChange={() => update('traits', draft.traits.includes(key) ? draft.traits.filter(x => x !== key) : [...draft.traits, key])} />{draft.traits.includes(key) && <Check size={13} aria-hidden="true" />}{label}</label>)}</div><p className="field-hint" id={`${id}-traits-hint`}>Wähle 1 bis 4 Eigenschaften für Gespräch und Bewertung.</p></fieldset>
      <label htmlFor={`${id}-description`}><span>Eigene Hinweise <span className="optional">optional</span></span><textarea id={`${id}-description`} rows={3} maxLength={ADVISOR_DESCRIPTION_MAX_LENGTH} value={draft.description} onChange={e => update('description', e.target.value)} disabled={disabled} placeholder="Weitere Wünsche zum Gesprächsstil und zu den Begründungen" aria-describedby={`${id}-description-hint`} /><span className="field-hint" id={`${id}-description-hint`}>Für Gesprächsstil und Begründungen. Deine Jobwünsche gehören ins Suchprofil. {draft.description.length}/{ADVISOR_DESCRIPTION_MAX_LENGTH}</span></label>
    </div>}
  </section>;
}
