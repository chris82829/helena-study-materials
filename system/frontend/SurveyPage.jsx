import React, { useEffect, useId, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, CheckCheck, Compass, LoaderCircle, MessageCircle, X } from 'lucide-react';
import { needsSystemPreparation, startPreparedSystem, surveyConfiguration, applyStudyAssignment, restoreServerDraft, finishWaitingIfReady, displaySurveyGroup, markWaitingFields, remainingWaitingGroups, reviseSurvey, changeSurveyAnswer, visibleFields, demographics, emptyAnswers, loadSurveyState, newSurveyState, nextSurveyState, reachableStage, saveSurveyState, submitSurvey, surveyErrors, surveyScale, suggestSearchGoal } from './survey.js';
import './survey.css';
import SearchLoadingDialog from './SearchLoadingDialog.jsx';
import {createSurveyAutosave} from './survey-autosave.js';
import {consentHeaders} from './privacy.js';
import ParticipationId from './ParticipationId.jsx';
import './action-motion.css';
import { isSurveyChatCompletion, isSurveyCompletion, requestSurveyChat, requestSurveyProgress, readSurveySearchContext } from './survey-progress.js';

function initialState() {
  if (typeof window === 'undefined') return newSurveyState();
  try { return loadSurveyState(window.sessionStorage); } catch { return newSurveyState(); }
}

export function SurveyQuestion({ field, value, onChange, busy, error, suggestion, number, onCommit }) {
  const id = useId();
  const hintId = `${field.name}-${id}-hint`;
  const errorId = `${field.name}-${id}-error`;
  const scaleId = `${field.name}-${id}-scale`;
  const scale = field.scale || surveyScale;
  const describedBy = [field.hint ? hintId : '', field.kind === 'scale' ? scaleId : '', error ? errorId : ''].filter(Boolean).join(' ') || undefined;
  const inputProps = { onBlur:()=>onCommit?.(field), name: field.name, 'aria-label': field.title, 'aria-invalid': Boolean(error), 'aria-describedby': describedBy, required: !field.optional };
  return <fieldset className={`survey-question${field.kind === 'scale' ? ' survey-rating-card' : ''}${error ? ' has-error' : ''}`} disabled={busy}>
    <legend>{field.kind === 'scale' && <span className="survey-question-meta"><span>{number ? `${number} · ` : ''}{field.topic || 'Deine Einschätzung'}</span>{Number.isInteger(value) && <span className="survey-answer-mark"><CheckCheck size={14} aria-hidden="true" />{value} / {scale.max || 7}</span>}</span>}<span>{field.title}</span>{field.optional && <span className="survey-optional">Optional</span>}</legend>
    {field.kind === 'choice' && field.presentation === 'radio' ? <div className="survey-options">
      {field.options.map(([option, label]) => <label key={option} className={`survey-option${value === option ? ' is-selected' : ''}`}>
        <input type="radio" name={field.name} value={option} checked={value === option} onChange={() => onChange(field.name, option)} required={!field.optional} aria-invalid={Boolean(error)} aria-describedby={describedBy} /><span>{label}</span>
      </label>)}
    </div> : field.kind === 'choice' ? <select {...inputProps} value={value} onChange={event => onChange(field.name, event.target.value)}>
      <option value="" disabled>Bitte wählen</option>
      {field.options.map(([option, label]) => <option key={option} value={option}>{label}</option>)}
    </select> : field.kind === 'scale' ? <>
      <div className="survey-scale">
        {Array.from({ length: (scale.max || 7) - (scale.min || 1) + 1 }, (_, index) => index + (scale.min || 1)).map(score => <label key={score} className={`survey-score${value === score ? ' is-selected' : ''}`}>
          <input type="radio" name={field.name} value={score} checked={value === score} onChange={() => onChange(field.name, score)} required aria-label={`${score}${score === 1 ? ` – ${scale.low}` : score === (scale.max || 7) ? ` – ${scale.high}` : ''}`} aria-invalid={Boolean(error)} aria-describedby={describedBy} />
          <span>{score}</span>
        </label>)}
      </div>
      <div id={scaleId} className="survey-scale-ends"><span>1 · {scale.low}</span><span>{scale.max || 7} · {scale.high}</span></div>
      {field.nonresponse?.length > 0 && <div className="survey-options survey-nonresponse">{field.nonresponse.map(([option, label]) => <label key={option} className={`survey-option${value === option ? ' is-selected' : ''}`}>
        <input type="radio" name={field.name} value={option} checked={value === option} onChange={() => onChange(field.name, option)} aria-describedby={describedBy} /><span>{label}</span>
      </label>)}</div>}
    </> : <>
      {field.multiline ? <textarea {...inputProps} value={value} onChange={event => onChange(field.name, event.target.value)} rows={4} maxLength={field.maxLength} />
        : <input {...inputProps} type="text" value={value} onChange={event => onChange(field.name, event.target.value)} maxLength={field.maxLength} />}
      {field.name === 'search_goal' && suggestion && <p className="survey-field-hint">{value === suggestion ? 'Aus deinem HELENA-Suchprofil übernommen. Bitte prüfe und ergänze den Vorschlag.' : <button type="button" className="survey-suggestion-button" onClick={() => onChange(field.name, suggestion)}>Suchvorhaben aus HELENA übernehmen</button>}</p>}
    </>}
    {field.hint && <p id={hintId} className="survey-field-hint">{field.hint}</p>}
    {error && <p className="survey-field-error" id={errorId}>{error}</p>}
  </fieldset>;
}

export function SurveyForm({ version, group = demographics, answers = emptyAnswers(), onChange, onSubmit, onBack, saveStatus, onRetry, busy = false, errors = {}, error = '', formRef, headingRef, searchSuggestion }) {
  const categories=surveyConfiguration(version).surveyCategories.filter(category=>visibleFields(category.fields,answers).length);
  const categoryIndex = categories.findIndex(category => category.id === group.id);
  const last = categoryIndex === categories.length - 1;
  return <form className="survey-form" ref={formRef} onSubmit={onSubmit} noValidate>
    <div className="survey-form-intro">
      <p className="survey-eyebrow">{categoryIndex < 0 ? 'ÜBER DICH' : `RÜCKMELDUNG · KATEGORIE ${categoryIndex + 1} VON ${categories.length}`}</p>
      <h1 ref={headingRef} tabIndex={-1}>{group.title}</h1><p>{group.description}</p>
      {categoryIndex >= 0 && <progress className="survey-progress" value={categoryIndex} max={categories.length} aria-label={`${categoryIndex} von ${categories.length} Frageblöcken abgeschlossen`} />}
    </div>
    <div className={group.id === 'demographics' ? 'survey-demographics-grid' : undefined}>
      {visibleFields(group.fields, answers).map((field, index) => <SurveyQuestion key={field.name} field={field} number={index + 1} value={answers[field.name]} onChange={onChange} busy={busy} error={errors[field.name]} suggestion={searchSuggestion} />)}
    </div>
    {error && <p className="survey-error" role="alert">{error}</p>}
    <div className="survey-form-actions">
      <button className="survey-back" type="button" disabled={busy} onClick={onBack}><ArrowLeft size={17} />{group.id === 'demographics' ? 'Zurück zum System' : 'Zurück'}</button>
      <button className="survey-primary helena-action-motion" type="submit" disabled={busy}>{busy ? <><LoaderCircle className="survey-spin" size={18} />Wird gespeichert …</> : <>{last ? 'Umfrage abschließen' : 'Weiter'}<ArrowRight className="helena-action-arrow" size={18} /></>}</button>
    </div>
    <AutosaveStatus status={saveStatus} onRetry={onRetry} />
    {last && <p className="survey-storage-note">Deine Umfrageantworten werden getrennt von Suchprofil und Chatverlauf gespeichert.</p>}
  </form>;
}

export function SystemPreparation({state, onChange, onStart, busy, errors, error, saveStatus, onRetry}) {
  const fields=surveyConfiguration(state).beforeSystemFields;
  return <main className="survey-main survey-preparation">
    <form className="survey-form" onSubmit={onStart} noValidate>
      <div className="survey-form-intro"><p className="survey-eyebrow">HELENA AUSPROBIEREN</p><h1>Bevor du loslegst</h1><p>Zwei kurze Angaben zu deiner bisherigen Erfahrung.</p></div>
      <div className="survey-demographics-grid">{fields.map(field=><SurveyQuestion key={field.name} field={field} value={state.answers[field.name]} onChange={onChange} busy={busy} error={errors[field.name]} />)}</div>
      <div className="survey-task"><h2>Deine Aufgabe</h2><ol>
        <li>Erstelle ein Suchprofil für eine Stelle, die du tatsächlich suchen würdest.</li>
        <li>Sieh dir die vorgeschlagenen Stellen und ihre Begründungen an.</li>
        <li>Stelle im Chat mindestens eine eigene inhaltliche Frage zu einer Stelle oder deinen Suchwünschen.</li>
      </ol><p>Du kannst deine Suchwünsche anschließend präzisieren. Nutze die angebotenen Einstellungen so, wie sie für dich sinnvoll sind.</p></div>
      {error && <p className="survey-error" role="alert">{error}</p>}
      <div className="survey-form-actions"><AutosaveStatus status={saveStatus} onRetry={onRetry}/><button type="submit" className="survey-primary helena-action-motion" disabled={busy}>{busy?'Wird gespeichert …':'System ausprobieren'}<ArrowRight className="helena-action-arrow" size={18}/></button></div>
    </form>
  </main>;
}

export function AutosaveStatus({status,onRetry}) {
  return <div className="survey-autosave" role="status">{status==='error' ? <>Noch nicht auf dem Server gespeichert. <button type="button" onClick={onRetry}>Erneut versuchen</button></> : status==='saving' || status==='pending' ? 'Wird gespeichert …' : status==='saved' ? <><CheckCheck size={14} aria-hidden="true" />Gespeichert</> : 'Antworten werden automatisch gespeichert.'}</div>;
}

export function SurveyWaitingDialog({ open, searching, completed, state, suggestion, onChange, onCommit, onNext, onClose, saveStatus, onRetry }) {
  const dialog = useRef(null), title = useRef(null);
  // Keep current questions in place while typing. Only advance on an explicit
  // next action, or close automatically when every waiting question is done.
  const [group,setGroup]=useState(()=>remainingWaitingGroups(state)[0]);
  const [errors,setErrors]=useState({});
  useEffect(() => {
    const element = dialog.current;
    if (open && !element.open) { element.showModal(); title.current?.focus(); }
    else if (!open && element.open) element.close();
    return () => { if (element.open) element.close(); };
  }, [open]);
  async function next(event) {
    event.preventDefault();
    const invalid=surveyErrors(state.answers,group.fields);setErrors(invalid);
    if(Object.keys(invalid).length)return;
    const nextState=onNext(group.fields);
    const nextGroup=remainingWaitingGroups(nextState)[0];
    if(nextGroup){setGroup(nextGroup);requestAnimationFrame(()=>title.current?.focus());}
  }
  if(!group)return null;
  const last=group.id===surveyConfiguration(state).waitingQuestionGroups.at(-1).id;
  return <dialog ref={dialog} className="survey-waiting-dialog" aria-labelledby="waiting-survey-title" onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className="survey-waiting-status"><span role="status">{searching ? 'System steht im Hintergrund.' : completed ? 'Deine Ergebnisse sind bereit.' : 'Die Berechnung ist beendet.'}</span><button className="survey-dialog-close" type="button" aria-label="Fragenfenster schließen" onClick={onClose}><X size={22}/></button></div>
    <form onSubmit={next} noValidate><div className="survey-waiting-body"><h2 id="waiting-survey-title" ref={title} tabIndex={-1}>{group.title}</h2><p className="survey-waiting-intro">Beantworte diese Fragen während der Wartezeit. Bereits beantwortete Fragen überspringen wir später.</p>
      <div className={group.id==='demographics'?'survey-demographics-grid':undefined}>{group.fields.map((field,index)=><SurveyQuestion key={field.name} field={field} number={index+1} value={state.answers[field.name]} onChange={onChange} onCommit={onCommit} suggestion={suggestion} error={errors[field.name]} />)}</div>
    </div><div className="survey-waiting-actions"><AutosaveStatus status={saveStatus} onRetry={onRetry}/><button className="survey-primary helena-action-motion" type="submit">{last?'Fertig':'Weitere Fragen'}<ArrowRight className="helena-action-arrow" size={18}/></button></div></form>
  </dialog>;
}

export function ChatRequiredDialog({ onClose }) {
  const dialog = useRef(null);
  const heading = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    element.showModal(); heading.current?.focus();
    return () => { if (element.open) element.close(); };
  }, []);
  return <dialog ref={dialog} className="survey-chat-required" aria-labelledby="survey-chat-required-title" aria-describedby="survey-chat-required-description" onCancel={event => { event.preventDefault(); onClose(); }}>
    <MessageCircle size={32} aria-hidden="true" />
    <h2 id="survey-chat-required-title" ref={heading} tabIndex={-1}>Probiere zuerst den Chat aus</h2>
    <p id="survey-chat-required-description">Sende mindestens eine eigene Nachricht an den Chatbot, bevor du mit der Umfrage fortfährst. Du kannst eine Empfehlung besprechen oder deine Suchwünsche verfeinern.</p>
    <button className="survey-primary helena-action-motion" type="button" onClick={onClose}>Zum Chat<ArrowRight className="helena-action-arrow" size={18} /></button>
  </dialog>;
}

export default function SurveyPage({ initial, participationId }) {
  const [state, setState] = useState(() => initial || initialState());
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchProgress, setSearchProgress] = useState(null);
  const [resultsVisible, setResultsVisible] = useState(false);
  const [searchAssistant,setSearchAssistant]=useState('Dein KI-Assistent');
  const [waitingOpen, setWaitingOpen] = useState(false);
  const [chatRequired, setChatRequired] = useState(false);
  const [saveStatus,setSaveStatus]=useState('idle');
  const [hydrated,setHydrated]=useState(false);
  const [assignmentReady,setAssignmentReady]=useState(false);
  const [assignmentAttempt,setAssignmentAttempt]=useState(0);
  const latestState=useRef(state);latestState.current=state;
  const alive=useRef(true);
  const autosave=useRef(null);
  if(!autosave.current)autosave.current=createSurveyAutosave({onStatus:status=>{if(alive.current)setSaveStatus(status);},onCompleted:()=>{if(alive.current)setState(previous=>({...previous,submitted:true}));}});
  const closingWaiting=useRef(false);
  const sending = useRef(false);
  const controller = useRef(null);
  const form = useRef(null);
  const heading = useRef(null);
  const frame = useRef(null);
  const systemActive = state.stage === 'system' && !state.submitted;
  const preparationRequired=needsSystemPreparation(state);
  const {demographics,surveyCategories,surveyStages,waitingQuestionGroups}=surveyConfiguration(state);
  const group = displaySurveyGroup(state);
  const waitingAvailable=remainingWaitingGroups(state).length>0;
  useEffect(() => {
    document.title = 'HELENA · Umfrage';
    return () => controller.current?.abort();
  }, []);
  useEffect(() => { try { saveSurveyState(window.sessionStorage, state); } catch { /* Optional draft. */ } }, [state]);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{
    if(state.submitted){setHydrated(true);return;}
    let cancelled=false;const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),10000);
    (async()=>{
      const response=await fetch('/api/survey-drafts/'+state.submissionId,{headers:consentHeaders(),signal:controller.signal});
      if(!response.ok)throw new Error('Deine Teilnahme konnte nicht geladen werden. Bitte versuche es erneut.');
      const {draft}=await response.json();
      if(cancelled)return;
      if(draft?.completed){setState(previous=>({...previous,submitted:true}));setHydrated(true);return;}
      const assigned=await fetch('/api/study-assignment',{method:'POST',headers:consentHeaders(),signal:controller.signal});
      if(!assigned.ok)throw new Error('Deine Studienvariante konnte nicht geladen werden. Bitte versuche es erneut.');
      const assignment=await assigned.json();
      if(cancelled)return;
      setState(previous=>applyStudyAssignment(draft?restoreServerDraft(previous,draft):previous,assignment));
      setAssignmentReady(true);setHydrated(true);setError('');
    })().catch(failure=>{if(!cancelled)setError(failure.message);}).finally(()=>clearTimeout(timeout));
    return()=>{cancelled=true;clearTimeout(timeout);controller.abort();};
  },[state.submissionId,assignmentAttempt]);
  useEffect(()=>{
    if(!hydrated || state.submitted)return;
    autosave.current.enqueue(state);
    const timer=setTimeout(()=>autosave.current.flush().catch(()=>{}),350);
    return()=>clearTimeout(timer);
  },[state.answers,state.waitingAnswered,state.draftRevision,state.submitted,hydrated]);
  useEffect(()=>{
    const flush=()=>autosave.current.flush().catch(()=>{});
    window.addEventListener('online',flush);window.addEventListener('pagehide',flush);
    return()=>{window.removeEventListener('online',flush);window.removeEventListener('pagehide',flush);};
  },[]);
  useEffect(()=>{
    if(!waitingOpen || waitingAvailable || closingWaiting.current || !hydrated)return;
    closingWaiting.current=true;autosave.current.enqueue(state);
    autosave.current.flush().then(()=>setWaitingOpen(false)).catch(()=>{}).finally(()=>{closingWaiting.current=false;});
  },[waitingOpen,waitingAvailable,state.draftRevision,hydrated]);

  useEffect(() => {
    if (!state.systemOpened) return;
    const onProgress = event => {
      const context = readSurveySearchContext(event, frame.current?.contentWindow, window.location.origin, state.runId);
      if (context) {
        setSearching(context.searching);
        setSearchProgress(context.searchProgress || null);
        setResultsVisible(context.resultsVisible);
        if(context.assistantName)setSearchAssistant(context.assistantName);
        setState(previous => { const next=suggestSearchGoal(previous,context.searchGoal); return next.answers!==previous.answers ? reviseSurvey(next,{}) : next; });
      }
      if (isSurveyChatCompletion(event, frame.current?.contentWindow, window.location.origin, state.runId)) {
        setState(previous => previous.chatCompleted ? previous : { ...previous, chatCompleted: true });
      }
      if (isSurveyCompletion(event, frame.current?.contentWindow, window.location.origin, state.runId)) {
        setState(previous => previous.systemCompleted ? previous : { ...previous, systemCompleted: true });
      }
    };
    window.addEventListener('message', onProgress);
    requestSurveyProgress(frame.current?.contentWindow, window.location.origin, state.runId);
    return () => window.removeEventListener('message', onProgress);
  }, [state.systemOpened, state.runId]);
  useEffect(() => {
    window.scrollTo({ top: 0 });
    if (systemActive) frame.current?.focus();
    else heading.current?.focus({ preventScroll: true });
  }, [state.stage, state.submitted]);

  function change(name, value, waiting=false) {
    if (!assignmentReady || !hydrated) return;
    setState(previous => {
      let next=reviseSurvey(previous,{...(name==='search_goal'?{searchGoalEdited:true}:{}),answers:changeSurveyAnswer(previous.answers,name,value,previous.version)});
      const field=waitingQuestionGroups.flatMap(group=>group.fields).find(field=>field.name===name);
      if(waiting && field && field.kind!=='text')next=finishWaitingIfReady(markWaitingFields(next,[field]));
      return next;
    });
    setErrors(previous => ({ ...previous, [name]: undefined }));setError('');
  }
  function commitWaiting(fields) {
    const next=finishWaitingIfReady(markWaitingFields(latestState.current,fields));
    latestState.current=next;setState(next);autosave.current.enqueue(next);
    return next;
  }
  function retrySave() {
    autosave.current.enqueue(latestState.current);
    autosave.current.flush().then(()=>{if(!remainingWaitingGroups(latestState.current).length)setWaitingOpen(false);}).catch(()=>{});
  }
  function closeWaiting() {
    autosave.current.enqueue(latestState.current);autosave.current.flush().catch(()=>{});
    setWaitingOpen(false);
    requestAnimationFrame(() => frame.current?.focus());
  }
  function openChat() {
    setChatRequired(false);
    requestAnimationFrame(() => {
      frame.current?.focus();
      requestSurveyChat(frame.current?.contentWindow, window.location.origin, state.runId);
    });
  }
  async function beginSystem(event) {
    event.preventDefault();
    if(busy || !assignmentReady || !hydrated)return;
    const invalid=surveyErrors(state.answers,surveyConfiguration(state).beforeSystemFields);
    setErrors(invalid);
    if(Object.keys(invalid).length)return;
    const next=startPreparedSystem(state);
    setBusy(true);setError('');
    try {
      autosave.current.enqueue(next);await autosave.current.flush();
      setState(next);
    } catch(failure) {setError(failure.message);}
    finally {setBusy(false);}
  }
  function advance() {
    if (sending.current || !assignmentReady || !hydrated) return;
    if (state.stage === 'system' && state.chatCompleted !== true) { setChatRequired(true); return; }
    setErrors({}); setError('');
    setState(previous => nextSurveyState(previous));
  }
  function back() {
    if (sending.current || !assignmentReady || !hydrated) return;
    setErrors({}); setError('');
    setState(previous => {let index=surveyStages.indexOf(previous.stage)-1;while(index>0 && !displaySurveyGroup(previous,surveyStages[index]).fields.length)index--;return {...previous,stage:reachableStage(previous,surveyStages[index])};});
  }
  async function send(event) {
    event.preventDefault();
    if (sending.current || state.submitted || !assignmentReady || !hydrated) return;
    const nextErrors = surveyErrors(state.answers, group.fields);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) {
      setError('Bitte prüfe die markierten Fragen.');
      const field = form.current?.elements.namedItem(Object.keys(nextErrors)[0]);
      // A select has indexed options too; only a RadioNodeList needs its first item.
      (field?.focus ? field : field?.[0])?.focus();
      return;
    }
    if (state.stage !== surveyStages.at(-1)) { advance(); return; }
    const firstIncomplete = [demographics, ...surveyCategories].find(category => Object.keys(surveyErrors(state.answers, category.fields)).length);
    if (firstIncomplete) { setState(previous => ({ ...previous, stage: firstIncomplete.id })); return; }
    sending.current = true;
    setBusy(true); setError('');
    controller.current = new AbortController();
    const timeout = setTimeout(() => controller.current.abort(), 20000);
    try {
      autosave.current.enqueue(state);await autosave.current.flush();
      await submitSurvey(state, { signal: controller.current.signal });
      setState(previous => ({ ...previous, submitted: true }));
    } catch (failure) {
      setError(failure.name === 'AbortError' || failure instanceof TypeError
        ? 'Die Verbindung wurde unterbrochen. Deine Antworten bleiben hier erhalten. Bitte sende sie erneut.' : failure.message);
    } finally {
      clearTimeout(timeout); sending.current = false; setBusy(false);
    }
  }

  return <div className={`survey-page${systemActive && !preparationRequired ? ' is-system' : ''}`}>
    {/* The live iframe stays mounted across question pages and return visits. */}
    {!state.submitted && !assignmentReady && <div className="empty-state" role="status"><p>{error || 'Dein Systemtest wird vorbereitet …'}</p>{error && <button className="survey-primary" onClick={()=>setAssignmentAttempt(value=>value+1)}>Erneut versuchen</button>}</div>}
    {systemActive && assignmentReady && preparationRequired && <SystemPreparation state={state} onChange={change} onStart={beginSystem} busy={busy} errors={errors} error={error} saveStatus={saveStatus} onRetry={retrySave}/> }
    {state.systemOpened && assignmentReady && !preparationRequired && <section className="survey-system-view" hidden={!systemActive} aria-label="HELENA ausprobieren">
      <iframe ref={frame} title="HELENA Jobsuche – interaktiv ausprobieren" src={`/suche?embed=survey&run=${state.runId}`} referrerPolicy="same-origin" onLoad={() => { setResultsVisible(false); requestSurveyProgress(frame.current?.contentWindow, window.location.origin, state.runId); }} />
      {resultsVisible && !searching && !waitingOpen && !chatRequired && state.systemCompleted && <div className="survey-system-actions"><button className="survey-primary helena-action-motion" type="button" onClick={advance} aria-label="Weitere Fragen für die Umfrage beantworten"><span className="survey-continue-long">Weitere Fragen für die Umfrage beantworten</span><span className="survey-continue-short">Weiter zur Umfrage</span><ArrowRight className="helena-action-arrow" size={18}/></button></div>}
    </section>}
    <div className="survey-questionnaire" hidden={systemActive || (!state.submitted && (!assignmentReady || !hydrated))}>
      <header className="survey-header"><a href="/" className="survey-brand" aria-label="Über HELENA und Studienleitung"><span><Compass size={23} strokeWidth={1.7} /></span><strong>HELENA<small>Umfrage</small></strong></a><span className="survey-header-label">{state.submitted ? 'Abgeschlossen' : 'Deine Erfahrung mit dem Suchsystem'}</span></header>
      <main className="survey-main">
        {state.submitted ? <div className="survey-thanks"><span className="survey-thanks-icon"><CheckCheck size={32} /></span><h1 ref={heading} tabIndex={-1}>Danke für deine Teilnahme!</h1><p>Deine Antworten wurden gespeichert. Du hilfst uns damit, die KI-gestützte Jobsuche weiterzuentwickeln.</p><ParticipationId value={participationId}/><a className="survey-back" href="/"><ArrowLeft size={17} />Zur Vorstellung</a></div>
          : assignmentReady && hydrated && group && <SurveyForm version={state.version} group={group} answers={state.answers} onChange={change} onSubmit={send} onBack={back} busy={busy} errors={errors} error={error} formRef={form} headingRef={heading} searchSuggestion={state.searchGoalSuggestion} saveStatus={saveStatus} onRetry={retrySave} />}
      </main>
    </div>
    {chatRequired && systemActive && <ChatRequiredDialog onClose={openChat} />}
    <SearchLoadingDialog progress={searchProgress} assistantName={searchAssistant} open={systemActive && searching && !waitingOpen} onQuestions={waitingAvailable?()=>setWaitingOpen(true):undefined} />
    {waitingOpen && systemActive && <SurveyWaitingDialog open searching={searching} completed={state.systemCompleted} state={state} suggestion={state.searchGoalSuggestion} onChange={(name,value)=>change(name,value,true)} onCommit={field=>commitWaiting([field])} onNext={commitWaiting} onClose={closeWaiting} saveStatus={saveStatus} onRetry={retrySave} />}
  </div>;
}
