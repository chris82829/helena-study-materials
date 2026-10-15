import React, {useEffect, useRef, useState} from 'react';
import {answerFields, answerVisible, updateAnswer, changedAnswers, answerLabel} from './admin-answer-editor.js';

export default function AdminAnswerEditor({row, busy, error, onCancel, onSave}) {
  const [answers, setAnswers] = useState(() => ({...row.answers}));
  const [reason, setReason] = useState('');
  const heading = useRef(null);
  useEffect(() => { heading.current?.focus(); }, []);
  const fields = answerFields(row.definition);
  const completed = row.response_status === 'completed';
  const changed = changedAnswers(row.answers, answers);
  function change(name, value) { setAnswers(previous => updateAnswer(previous, name, value, row.definition)); }
  return <form className="admin-answer-editor" onSubmit={event => {event.preventDefault(); if (!busy && changed.length && reason.trim().length >= 3) onSave({answers, reason: reason.trim(), edit_revision: row.edit_revision});}}>
    <h3 ref={heading} tabIndex={-1}>Antworten bearbeiten</h3>
    <p>Änderungen werden erst mit „Korrektur speichern“ übernommen. Der vorherige Antwortstand und dein Korrekturgrund bleiben im Änderungsverlauf erhalten. Teilnahme-ID, Fragebogenversion, Studienzuordnung und Einwilligung bleiben erhalten.</p>
    {!completed && <p>Diese Umfrage ist unvollständig. Fehlende Antworten dürfen leer bleiben. Eine inzwischen gespeicherte Teilnehmerantwort verhindert das Überschreiben durch einen älteren Bearbeitungsstand.</p>}
    <fieldset disabled={busy}>
      {fields.filter(field => answerVisible(field, answers)).map(field => {
        const required = completed && !field.optional;
        const value = answers[field.name];
        if (field.name === 'study_arm') return <div className="admin-locked-answer" key={field.name}><strong>{field.title}</strong><span>{answerLabel(field, value)} · fest zugeordnet</span></div>;
        const options = field.kind === 'scale'
          ? [...Array.from({length: (field.maximum || 10) - (field.minimum || 1) + 1}, (_, index) => {const n = index + (field.minimum || 1); return [n, String(n)];}), ...(field.nonresponse || [])]
          : field.options || [];
        return <label key={field.name}>{field.title}{field.optional ? ' (optional)' : ''}
          {field.kind === 'text'
            ? <textarea value={value ?? ''} onChange={event => change(field.name, event.target.value)} required={required} minLength={required ? field.minLength || 1 : undefined} maxLength={field.maxLength} rows={field.maxLength > 160 ? 3 : 2}/>
            : <select value={value ?? ''} required={required} onChange={event => {const raw = event.target.value; change(field.name, raw === '' ? null : field.kind === 'scale' && /^\d+$/.test(raw) ? Number(raw) : raw);}}><option value="">{completed ? 'Bitte auswählen' : 'Noch nicht beantwortet'}</option>{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select>}
          {field.kind === 'scale' && field.scale && <small>{field.minimum || 1}: {field.scale.low} · {field.maximum || 10}: {field.scale.high}</small>}
        </label>;
      })}
      <label className="admin-correction-reason">Grund für die Korrektur<textarea value={reason} onChange={event => setReason(event.target.value)} minLength={3} maxLength={1000} required rows={3} placeholder="Zum Beispiel: dokumentierte Rückmeldung der teilnehmenden Person"/></label>
    </fieldset>
    <p role="status">{changed.length} geänderte Antwort{changed.length === 1 ? '' : 'en'} · noch nicht gespeichert</p>
    {error && <p role="alert" className="admin-error">{error}</p>}
    <div className="admin-dialog-actions"><button type="button" disabled={busy} onClick={onCancel}>Änderungen verwerfen</button><button type="submit" className="admin-primary" disabled={busy || !changed.length || reason.trim().length < 3}>{busy ? 'Wird gespeichert …' : 'Korrektur speichern'}</button></div>
  </form>;
}

export function AdminCorrectionHistory({row}) {
  if (!row.corrections?.length) return null;
  const fields = answerFields(row.definition);
  return <details className="admin-correction-history"><summary>Änderungsverlauf ({row.correction_count})</summary><p>Die ursprünglichen Werte sind im ältesten Korrektureintrag und im Auswertungspaket erhalten. Die Verwaltung nutzt einen gemeinsamen Zugang.</p>{row.corrections.map((correction, index) => <article key={index}><h3>{new Date(correction.corrected_at).toLocaleString('de-DE')} · Verwaltung</h3><p>{correction.reason}</p><dl>{correction.changes.map(change => {const field = fields.find(item => item.name === change.field); return <div key={change.field}><dt>{field?.title || change.field}</dt><dd><span>Vorher: {answerLabel(field, change.before)}</span><span>Gespeichert: {answerLabel(field, change.after)}</span></dd></div>;})}</dl></article>)}</details>;
}
