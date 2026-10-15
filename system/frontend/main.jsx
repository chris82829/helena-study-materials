import React, { useEffect, useId, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowRight, ArrowUp, ArrowUpRight, Check, ChevronDown, Clock3, Compass, GripVertical, MapPin, MessageCircle, Plus, RotateCcw, Search, SlidersHorizontal } from 'lucide-react';
import { emptyForm, exampleForm, fromProfile, labels, makeProfile, profileSummary, remoteLabels } from './profile.js';
import './style.css';
import './job-reasons.css';
import './job-card-actions.css';
import './chat-bubbles.css';
import useChatResize from './useChatResize.js';
import { messagePreview } from './chat-layout.js';
import { actionFeedback, candidatePool, canSendChat, pendingFeedback, profileChangeAction, recoveredSubmission, submittedChangeApplied } from './chat-actions.js';
import { MIN_MATCH_SCORE, resultVisibilityKey, scoreVisibility } from './score-visibility.js';
import { buildChatSuggestions } from './chat-suggestions.js';
import JourneyGuide from './JourneyGuide.jsx';
import ProfileSummaryPopover from './ProfileSummaryPopover.jsx';
import './assistant-actions.css';
import SearchLoadingDialog from './SearchLoadingDialog.jsx';
import { requestOperation } from './search-request.js';
import { canVisitJourneyStep, currentJourneyStep } from './journey-state.js';
import AdvisorPicker from './AdvisorPicker.jsx';
import PersonalityIntroDialog from './PersonalityIntroDialog.jsx';
import AboutPage from './AboutPage.jsx';
import SurveyPage from './SurveyPage.jsx';
import AdminPage from './AdminPage.jsx';
import PrivacyGate from './PrivacyGate.jsx';
import {standaloneArm, leavesTestContext} from './test-access.js';
import {templateSelection, selectionForRequest} from './advisor-selection.js';
import {consentHeaders} from './privacy.js';
import { appPath, appSessionStorage, surveyRun } from './app-session.js';
import { hasChatMessage, hasSearchResults, isSurveyResultsView, reportSurveyProgress, searchGoalSuggestion } from './survey-progress.js';
import './action-motion.css';
import { neutralAdvisor, standardAdvisor, defaultAdvisor, advisorAiLabel, advisorScoreLabel, editableAdvisor, validateAdvisor } from './advisor.js';

import { installMobileViewport, shouldSendOnEnter } from './mobile-viewport.js';
import './mobile.css';

const sessionStorageAccess = appSessionStorage();
const isEmbeddedSurvey = Boolean(surveyRun(window.location.search));
const currentPage = () => (window.location.pathname === '/suche' || standaloneArm()) ? 'search' : 'about';
function CompassAvatar({ className = '' }) { return <span className={`compass-avatar ${className}`} aria-hidden="true"><Compass strokeWidth={1.7} /></span>; }
function ChatMessageText({ text, assistant }) {
  const [expanded, setExpanded] = useState(false);
  const preview = assistant ? messagePreview(text) : text;
  return <div className="message-bubble"><div className="message-text">{expanded ? text : preview}</div>{preview !== text && <button type="button" className="message-expand" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? 'Weniger anzeigen' : 'Mehr anzeigen'}</button>}</div>;
}
const demoIds = new Set(['900001', '900002', '900003', '900004', '900005']);
function remember(id) { sessionStorageAccess.remember(id); }
async function api(path, body) {
  const response = await fetch(`/api${path}`, { method: body ? 'POST' : 'GET', headers: { ...consentHeaders(), ...(body ? { 'Content-Type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error?.message || 'Die Anfrage konnte nicht verarbeitet werden.');
    error.status = response.status;
    throw error;
  }
  return data;
}

function SearchIntro({ neutral = false, allowCustom = true, onSelect, activeStep, completedSteps, busy }) {
  return <div className="search-intro">
    <JourneyGuide allowCustom={allowCustom} neutral={neutral} activeStep={activeStep} completedSteps={completedSteps} busy={busy} hasSession={false} onSelect={onSelect} />
  </div>;
}

function MoreMatchReasons({ reasons, matchedSkills }) {
  const [expanded, setExpanded] = useState(false);
  const contentId = useId();
  return <div className="reason-more">
    <div className="reason-more-content" id={contentId} hidden={!expanded}>
      {reasons.length > 1 && <ul className="reason-bullets">{reasons.slice(1).map((reason, i) => <li key={i}>{reason}</li>)}</ul>}
      {matchedSkills.length > 0 && <div className="skills-list">{matchedSkills.map(skill => <span key={skill}><Check size={13} aria-hidden="true" />{skill}</span>)}</div>}
    </div>
    <button type="button" className="reason-more-toggle" aria-expanded={expanded} aria-controls={contentId} onClick={() => setExpanded(value => !value)}>
      {expanded ? 'Weniger anzeigen' : 'Mehr anzeigen'}<ChevronDown size={16} aria-hidden="true" />
    </button>
  </div>;
}

function AssistantActionArea({ feedback, children }) {
  const [expanded, setExpanded] = useState(false);
  const contentId = useId();
  return <div className="assistant-action-area">
    <div className="assistant-action-header">
      <button type="button" className="assistant-actions-toggle" aria-label="Weitere Aktionen" aria-expanded={expanded} aria-controls={contentId} onClick={() => setExpanded(value => !value)}>
        Aktionen<ChevronDown size={15} aria-hidden="true" />
      </button>
      <p className="action-feedback" role="status" title={feedback}>
        {feedback && <><Check size={13} aria-hidden="true" /><span>{feedback}</span></>}
      </p>
    </div>
    <div className="assistant-actions-content" id={contentId} hidden={!expanded}>{children}</div>
  </div>;
}

export function JobCard({ job, index, ranked, showInsights = true, scoreLabel, assistantName, onAsk, busy }) {
  const [detailsExpanded, setDetailsExpanded] = useState(false);
  const detailsId = useId();
  const match = showInsights ? job.match : null;
  const reasons = (match?.reasons?.length ? match.reasons : [match?.reason]).filter(reason => typeof reason === 'string' && reason.trim());
  const matchedSkills = match?.matched_skills || [];
  const demo = demoIds.has(job.id);
  const initials = (job.company || 'Stelle').split(/\s+/).slice(0, 2).map(x => x[0]).join('');
  const hours = job.hours_min != null ? `${job.hours_min}${job.hours_max != null && job.hours_max !== job.hours_min ? `–${job.hours_max}` : ''} h / Woche` : 'Stunden nach Absprache';
  return <article className="job-card" style={{ '--card-order': index }}>
    <div className="job-top"><div className={`company-icon color-${index % 4}`} aria-hidden="true">{initials}</div><div className="company-line"><span>{job.company || 'Unternehmen'}</span><span className="job-type">{job.employment_types.map(x => labels[x] || x).join(' · ')}</span></div>
      {ranked && match && <div className="match-score" title={`${scoreLabel}: Passung von 1 bis 100. Keine Einstellungswahrscheinlichkeit.`}><strong>{match.score}<small>/100</small></strong><span>{scoreLabel}</span></div>}
    </div>
    <h3 tabIndex={-1}>{job.title}</h3>
    <div className="job-meta"><span><MapPin size={15} />{job.location || 'Ort offen'}</span><span><Clock3 size={15} />{hours}</span></div>
    <div className="tags"><span className="tag">{remoteLabels[job.remote]}</span>{job.professional_fields.slice(0, 2).map(x => <span className="tag neutral" key={x}>{x}</span>)}</div>
    {match ? <div className="match-reason">
      <span className="reason-title"><CompassAvatar className="inline-compass" />Warum das passen könnte</span>
      {reasons.length > 0 && <ul className="reason-bullets"><li>{reasons[0]}</li></ul>}
      {(reasons.length > 1 || matchedSkills.length > 0) && <MoreMatchReasons key={JSON.stringify([match.score, reasons, matchedSkills])} reasons={reasons} matchedSkills={matchedSkills} />}
    </div> : <p className="job-summary">{job.summary || job.tasks}</p>}
    <div className="job-card-footer">
      <div className="job-card-actions">
        <button type="button" className="job-action-details" aria-label="Stellendetails" aria-expanded={detailsExpanded} aria-controls={detailsId} onClick={() => setDetailsExpanded(value => !value)}>
          <span className="job-details-label-full" aria-hidden="true">Stellendetails</span><span className="job-details-label-compact" aria-hidden="true">Details</span><ChevronDown size={16} aria-hidden="true" />
        </button>
        {ranked && <button type="button" className="job-action-chat" disabled={busy} aria-label={`Mit ${assistantName} besprechen`} title={`Mit ${assistantName} besprechen`} onClick={() => onAsk(job)}>
          <CompassAvatar className="inline-compass" /><span className="job-chat-label-full" aria-hidden="true">Mit {assistantName} besprechen</span><span className="job-chat-label-compact" aria-hidden="true">Besprechen</span><span className="job-chat-label-mobile" aria-hidden="true">Diese Stelle besprechen</span><ArrowRight size={15} aria-hidden="true" />
        </button>}
      </div>
      <div className="detail-content" id={detailsId} hidden={!detailsExpanded}>
      {[['Deine Aufgaben', job.tasks], ['Das bringst du mit', job.requirements], ['Das wird geboten', job.benefits]].map(([title, text]) => text && <section key={title}><h4>{title}</h4><p>{text}</p></section>)}
      {match?.missing_skills?.length > 0 && <section><h4>Im Profil noch nicht belegt</h4><p>{match.missing_skills.join(' · ')}</p></section>}
      {job.application_url && !demo && /^https?:\/\//.test(job.application_url) && <a className="application-link" href={job.application_url} target="_blank" rel="noopener noreferrer">Zur Stellenanzeige <ArrowUpRight size={16} /></a>}
      {demo && <p className="demo-caption">Fiktive Anzeige zum Ausprobieren.</p>}
      </div>
    </div>
  </article>;
}

function ScoreNotice({ lowCount, total, showLowScores, scoreLabel, busy, onToggle }) {
  return <div className={`score-notice ${lowCount === total && !showLowScores ? 'all-below-threshold' : ''}`}>
    <strong>{showLowScores ? 'Niedriger bewertete Stellen eingeblendet' : lowCount === total ? 'Noch keine ausreichend passende Stelle' : 'Weitere, weniger passende Stellen verfügbar'}</strong>
    <p>{lowCount === 1 ? 'Eine bewertete Stelle liegt' : `${lowCount} bewertete Stellen liegen`} unter {MIN_MATCH_SCORE} von 100 Punkten im {scoreLabel}.</p>
    <button type="button" onClick={onToggle} disabled={busy} aria-expanded={showLowScores} aria-controls="ranked-jobs">{showLowScores ? 'Niedrige Scores wieder ausblenden' : lowCount === total ? (lowCount === 1 ? 'Diese Stelle trotzdem anzeigen' : `Alle ${lowCount} Stellen trotzdem anzeigen`) : `${lowCount} weitere ${lowCount === 1 ? 'Stelle' : 'Stellen'} anzeigen`}<ChevronDown size={16} aria-hidden="true" /></button>
  </div>;
}

export function ProfileForm({ neutral = false, allowCustom = true, form, setForm, onSubmit, busy, ready, advisor, setAdvisor, step, onNext, onBack, onExplainAdvisor, templates, advisorSelection, editMode = false }) {
  const assistantName = advisorAiLabel(advisor);
  const update = (key, value) => setForm(f => ({ ...f, [key]: value }));
  const heading = useRef(null);
  useEffect(() => {
    heading.current?.closest('.profile-scroll')?.scrollTo({ top: 0 });
    heading.current?.focus({ preventScroll: true });
  }, [step, editMode]);
  return <form className="profile-form" onSubmit={!editMode && step === 1 && !neutral ? onNext : onSubmit}>
    {editMode || step === 1 ? <>
    <div className={`profile-intro${editMode ? '' : ' profile-intro--compact'}`}><span className="step-label">DEIN SUCHPROFIL</span><div className="profile-intro-row"><h2 ref={heading} tabIndex={-1}>{editMode ? 'Dein Profil bearbeiten' : 'Was passt zu dir?'}</h2>{!editMode && <button type="button" className="example-button" aria-label="Mit Beispielprofil ausprobieren" title="Mit Beispielprofil ausprobieren" onClick={() => setForm({ ...exampleForm })} disabled={busy}>Beispielprofil<ArrowUpRight size={14} aria-hidden="true" /></button>}</div>{editMode && <p>Passe deine Angaben an. Dein Chat bleibt erhalten.</p>}</div>
    <label>Was möchtest du machen?<textarea value={form.query} onChange={e => update('query', e.target.value)} maxLength={3000} rows={3} placeholder="Zum Beispiel: Ich suche einen Einstieg in Data Science …" disabled={busy} /></label>
    <label>Deine Fähigkeiten<input value={form.skills} onChange={e => update('skills', e.target.value)} placeholder="Python, SQL, Projektmanagement …" disabled={busy} /><span className="field-hint">Mit Kommas trennen</span></label>
    <label>Was ist dir bei der Arbeit wichtig?<input value={form.preferences} onChange={e => update('preferences', e.target.value)} placeholder="Teamarbeit, selbstständig arbeiten …" disabled={busy} /><span className="field-hint">Deine Wünsche fließen in die persönliche Bewertung ein.</span></label>
    <fieldset disabled={busy}><legend>Stellenart · feste Einschränkung</legend><div className="choice-group">{Object.entries(labels).map(([value, label]) => <label className={`choice ${form.employment.includes(value) ? 'selected' : ''}`} key={value}><input type="checkbox" checked={form.employment.includes(value)} onChange={() => update('employment', form.employment.includes(value) ? form.employment.filter(x => x !== value) : [...form.employment, value])} />{form.employment.includes(value) && <Check size={13} />}{label}</label>)}</div><p className="field-hint">Nur die Stellenart schränkt die Auswahl fest ein. Keine Auswahl bedeutet: alle Stellenarten.</p></fieldset>
    <details className="more-filters"><summary><SlidersHorizontal size={15} />Weitere Wünsche und Erfahrung<ChevronDown size={16} /></summary><div className="filter-fields">
      <p className="field-hint preference-explanation">{assistantName} bewertet Ort, Arbeitsmodell und Stunden als Wünsche. Diese Angaben schließen keine Stellen aus.</p>
      <label>Gewünschte Orte<input value={form.location} onChange={e => update('location', e.target.value)} placeholder="Zum Beispiel München, Berlin" disabled={busy} /></label>
      <fieldset disabled={busy}><legend>Bevorzugtes Arbeitsmodell</legend><div className="choice-group">{Object.entries(remoteLabels).map(([value, label]) => <label className={`choice ${form.remote.includes(value) ? 'selected' : ''}`} key={value}><input type="checkbox" checked={form.remote.includes(value)} onChange={() => update('remote', form.remote.includes(value) ? form.remote.filter(x => x !== value) : [...form.remote, value])} />{form.remote.includes(value) && <Check size={13} />}{label}</label>)}</div><p className="field-hint">Mehrere Wünsche sind möglich. Ohne Auswahl bevorzugst du kein Arbeitsmodell.</p></fieldset><label>Gewünschte Wochenstunden, höchstens<input type="number" min="1" max="80" step="0.5" value={form.hours} onChange={e => update('hours', e.target.value)} placeholder="Pro Woche" disabled={busy} /><span className="field-hint">Ein Wunsch für die Bewertung, keine feste Obergrenze für die Suche.</span></label>
      <label>Ausbildung, Erfahrung oder Lebenslauf <span className="optional">optional</span><textarea value={form.cv} onChange={e => update('cv', e.target.value)} maxLength={16000} rows={4} placeholder="Zum Beispiel Studium, Ausbildung, Projekte und bisherige Berufserfahrung." disabled={busy} /><span className="field-hint">Hilft {assistantName}, deine Erfahrung und die fachliche Passung einzuschätzen.</span></label>
    </div></details>
    {editMode ? <><div className="onboarding-actions"><button type="button" className="back-button" onClick={onBack} disabled={busy}>Abbrechen</button><button type="submit" className="primary-button" disabled={busy}>{busy ? 'Profil wird angewendet …' : 'Profil anwenden'}<ArrowRight size={18} /></button></div><p className="privacy-note">Geänderte Wünsche und Erfahrung fließen in die Neubewertung ein. Suchziel, Fähigkeiten oder Stellenart starten eine neue Suche.</p></> : <button type="submit" className="primary-button helena-action-motion" disabled={busy || (neutral && !ready)}>{neutral ? 'Passende Jobs finden' : 'Weiter zur Persönlichkeit'}<ArrowRight className="helena-action-arrow" size={18} /></button>}
    </> : <>
    <AdvisorPicker allowCustom={allowCustom} templates={templates} selection={advisorSelection} value={advisor} onChange={setAdvisor} disabled={busy} headingRef={heading} onExplain={onExplainAdvisor} />
    <div className="onboarding-actions"><button type="button" className="back-button" onClick={onBack} disabled={busy}>Zurück</button>
    <button type="submit" className="primary-button helena-action-motion" disabled={busy || !ready}>{!ready ? 'Suchindex wird vorbereitet …' : busy ? 'Deine Suche wird ausgewertet …' : 'Passende Jobs finden'}{!busy && ready && <ArrowRight className="helena-action-arrow" size={18} />}</button></div>
    <p className="privacy-note">Dein Profil und ausgewählte Stellen werden zur KI-Auswertung an OpenAI übermittelt.</p>
    </>}
  </form>;
}

export function App({studyArm = 'B', personalityPolicy = studyArm === 'A' ? 'standard' : studyArm === 'B' ? 'templates' : 'configurable', presentationPolicy = 'ranked_insights'}) {
  const neutral=studyArm==='A';
  const allowCustom=personalityPolicy==='configurable';
  const showInsights=presentationPolicy==='ranked_insights';
  const fixedAdvisor=personalityPolicy==='standard' ? standardAdvisor : neutralAdvisor;
  const [page, setPage] = useState(currentPage);
  const [catalog, setCatalog] = useState([]);
  const [total, setTotal] = useState(0);
  const [session, setSession] = useState(null);
  const [revealedResults, setRevealedResults] = useState(null);
  const [form, setForm] = useState({ ...emptyForm });
  const [onboardingStep, setOnboardingStep] = useState(1);
  const [onboardingStarted, setOnboardingStarted] = useState(false);
  const [personalityIntro, setPersonalityIntro] = useState(null);
  const personalityIntroSeen = useRef(false);
  const [advisor, setAdvisor] = useState(neutral ? {...fixedAdvisor} : { ...defaultAdvisor });
  const [templates, setTemplates] = useState(undefined);
  const [advisorSelection, setAdvisorSelection] = useState(neutral ? null : templateSelection('career'));
  const [editor, setEditor] = useState(null);
  const [operation, setOperation] = useState(null);
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  const [searchActive, setSearchActive] = useState(false);
  const [searchProgress, setSearchProgress] = useState(null);
  const [surveySearchProfile, setSurveySearchProfile] = useState(null);
  const [streamingText, setStreamingText] = useState('');
  const [indexState, setIndexState] = useState(null);
  const [mobileView, setMobileView] = useState('jobs');
  const [activity, setActivity] = useState('results');
  const [completedSteps, setCompletedSteps] = useState([]);
  const generation = useRef(0);
  const sending = useRef(false);
  const messagesEnd = useRef(null);
  const followChat = useRef(true);
  const workspace = useRef(null);
  const previousPage = useRef(page);
  // Each editor retains its local draft when the guide opens another area.
  // Only explicit cancellation or a successful save discards that draft.
  const editorDrafts = useRef({ profile: false, advisor: false });
  const chatLayout = useChatResize(workspace, !session);

  const surveyResultsReady = !booting && !busy && hasSearchResults(session);
  const surveyResultsVisible = isSurveyResultsView({ session, page, booting, busy, editor, personalityIntro });
  const surveySearching = busy && searchActive;
  const surveyGoal = searchGoalSuggestion(surveyResultsReady ? session?.profile : surveySearchProfile);
  const surveyChatCompleted = hasChatMessage(session);
  const surveyAssistantName=operation?.assistantName || advisorAiLabel(session?.advisor || advisor);
  useEffect(() => reportSurveyProgress(window, surveyResultsReady, { resultsVisible: surveyResultsVisible, searching: surveySearching, searchGoal: surveyGoal, chatCompleted: surveyChatCompleted, assistantName:surveyAssistantName, searchProgress }, () => {
    setEditor(null); setMobileView('chat'); setActivity('chat');
    requestAnimationFrame(() => document.getElementById('chat-input')?.focus());
  }), [surveyResultsReady, surveyResultsVisible, surveySearching, surveyGoal, surveyChatCompleted, surveyAssistantName, searchProgress]);

  useEffect(() => {
    const onPopState = () => setPage(currentPage());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);
  useEffect(() => {
    document.title = page === 'about' ? 'Forschungsprojekt HELENA' : 'HELENA Jobsuche';
    if (page === 'search' && previousPage.current === 'about') {
      requestAnimationFrame(() => {
        const selector = editor === 'profile' || (!session && onboardingStarted && onboardingStep === 1) ? '.profile-intro h2'
          : editor === 'advisor' || (!session && onboardingStarted && onboardingStep === 2) ? '.advisor-intro h3'
          : session && mobileView === 'chat' ? '#chat-input' : '#helena-results-heading';
        workspace.current?.querySelector(selector)?.focus({ preventScroll: true });
      });
    }
    previousPage.current = page;
    window.scrollTo({ top: 0 });
  }, [page]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [jobs, index, personas] = await Promise.all([api('/jobs'), api('/index-status'), api('/persona-templates')]);
        if (!alive) return;
        setCatalog(jobs.jobs); setTotal(jobs.total); setIndexState(index); setTemplates(personas.templates);
        if (!neutral) { setAdvisor(personas.templates[personas.default].advisor); setAdvisorSelection(templateSelection(personas.default)); }
        let saved;
        saved = sessionStorageAccess.read();
        if (saved && /^[A-Za-z0-9_-]{32,100}$/.test(saved)) {
          try {
            const data = await api(`/sessions/${saved}`);
            if (alive) { setSession(data); setForm(fromProfile(data.profile)); setAdvisor(data.advisor || { ...defaultAdvisor }); setAdvisorSelection(data.advisor_selection || null); setMobileView('chat'); setActivity('chat'); setCompletedSteps(data.messages.some(message => message.role === 'user') ? [1, 2, 3, 4] : [1, 2, 3]); }
          } catch (e) { if (e.status === 404) remember(null); else throw e; }
        }
      } catch { if (alive) setError('Die Verbindung zum Backend ist unterbrochen. Bitte lade die Seite erneut.'); }
      finally { if (alive) setBooting(false); }
    })();
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!indexState?.required || indexState.status === 'ready') return;
    let alive = true;
    const timer = setInterval(() => { api('/index-status').then(result => { if (alive) setIndexState(result); }).catch(() => {}); }, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, [indexState?.required, indexState?.status]);
  useEffect(() => {
    followChat.current = true;
    messagesEnd.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [session?.messages?.length, pending]);
  useEffect(() => {
    if (streamingText && followChat.current) messagesEnd.current?.scrollIntoView({ block: 'nearest', behavior: 'auto' });
  }, [streamingText]);

  function markSteps(...steps) {
    setCompletedSteps(previous => {
      const next = [...new Set([...previous, ...steps])].sort((left, right) => left - right);
      return next.length === previous.length ? previous : next;
    });
  }
  function syncSession(result, preserveProfile = false, preserveAdvisor = false) {
    setSession(result);
    if (!preserveProfile && !editorDrafts.current.profile) setForm(fromProfile(result.profile));
    if (!preserveAdvisor && !editorDrafts.current.advisor) { setAdvisor(result.advisor || { ...defaultAdvisor }); setAdvisorSelection(result.advisor_selection || null); }
    remember(result.session_id);
  }
  async function run(body, endpoint, kind = 'chat') {
    if (sending.current) return;
    setSurveySearchProfile(body.profile || session?.profile || null);
    setSearchProgress(null);
    sending.current = true; setBusy(true); setError(''); setSearchActive(false); setStreamingText('');
    let operationMode = kind === 'profile' ? profileChangeAction(session?.profile, body.profile) : body.mode || 'auto';
    if (kind === 'profile' && operationMode === 'rerank' && candidatePool(session).refreshRequired) operationMode = 'search';
    setOperation({ kind, mode: operationMode, assistantName: advisorAiLabel(body.advisor || session?.advisor || advisor) });
    const turn = ++generation.current;
    function accept(result) {
      const applied = submittedChangeApplied(result, body, kind);
      if (applied && (kind === 'profile' || kind === 'advisor')) editorDrafts.current[kind] = false;
      if (applied && kind === 'onboard') editorDrafts.current = { profile: false, advisor: false };
      if (result.chat_action === 'search' || result.chat_action === 'rerank') setRevealedResults(null);
      syncSession(result,
        (kind === 'profile' && !applied) || (kind !== 'profile' && editor === 'profile'),
        (kind === 'advisor' && !applied) || (kind !== 'advisor' && editor === 'advisor'));
      if (applied) {
        if (kind === 'onboard') markSteps(1, 2);
        if (kind === 'profile') markSteps(1);
        if (kind === 'advisor') markSteps(2);
        if (kind === 'chat') markSteps(3, 4);
        if (kind === 'profile' || kind === 'advisor' || kind === 'onboard') setEditor(null);
        if (kind === 'chat') setDraft('');
        if (['onboard', 'profile', 'advisor', 'rerank', 'refresh'].includes(kind)) {
          setActivity('results'); setMobileView('jobs');
        }
      } else {
        setError('Deine Änderung wurde noch nicht angewendet. Deine Eingaben bleiben erhalten.');
      }
    }
    try {
      const result = await requestOperation(endpoint, body, phase => {
        if (generation.current !== turn || phase !== 'search') return;
        setSearchActive(true); setStreamingText('');
        setOperation(previous => previous ? { ...previous, mode: 'search' } : previous);
      }, text => {
        if (generation.current === turn) setStreamingText(text);
      }, progress => {
        if (generation.current === turn) setSearchProgress(progress);
      });
      if (generation.current !== turn) return;
      accept(result);
    } catch (e) {
      if (generation.current !== turn) return;
      setSearchActive(false); setStreamingText('');
      if (endpoint === '/chat' && session) {
        // Restore after conflicts or lost replies; never automatically resend a paid request.
        try {
          const latest = await api(`/sessions/${session.session_id}`);
          if (generation.current !== turn) return;
          syncSession(latest, kind === 'profile' || editor === 'profile', kind === 'advisor' || editor === 'advisor');
          if (e.status !== 409 && recoveredSubmission(session, latest, body, kind)) {
            accept(latest); setError('Die Antwort ist nachträglich angekommen. Dein Verlauf wurde aktualisiert.');
            return;
          }
        } catch (restoreError) { if (restoreError.status === 404) { remember(null); setSession(null); setEditor(null); setOnboardingStep(1); setOnboardingStarted(false); setMobileView('jobs'); editorDrafts.current = { profile: false, advisor: false }; setActivity('results'); setCompletedSteps([]); } }
      }
      setError(e.status === 409 ? 'Dein Chat wurde zwischenzeitlich geändert. Der aktuelle Verlauf ist geladen; deine Eingabe bleibt erhalten.' : e instanceof TypeError ? 'Die Verbindung wurde unterbrochen. Deine Eingabe bleibt erhalten.' : e.message);
    } finally { if (generation.current === turn) { sending.current = false; setBusy(false); setPending(''); setOperation(null); setSearchActive(false); setStreamingText(''); } }
  }
  function beginOnboarding() {
    if (booting || busy || session) return;
    setOnboardingStarted(true); setOnboardingStep(1); setMobileView('chat');
  }
  function nextOnboardingStep(event) {
    event.preventDefault();
    if (booting || busy) return;
    try {
      makeProfile(form); setError(''); markSteps(1);
      if (personalityIntroSeen.current) setOnboardingStep(2);
      else setPersonalityIntro('onboarding');
    } catch (e) { setError(e.message); }
  }
  function continuePersonalityIntro() {
    personalityIntroSeen.current = true;
    setPersonalityIntro(null);
    if (personalityIntro === 'onboarding') setOnboardingStep(2);
  }
  function startSearch(event) {
    event.preventDefault();
    if (booting || busy || !indexReady) return;
    try { const body = { profile: makeProfile(form), advisor: neutral ? {...fixedAdvisor} : validateAdvisor(editableAdvisor(advisor)), advisor_selection: neutral ? undefined : selectionForRequest(advisorSelection) }; markSteps(1, 2); void run(body, '/onboard', 'onboard'); } catch (e) { setError(e.message); }
  }
  function sendMessage(event) {
    event.preventDefault();
    const message = draft.trim();
    if (busy || !canSendChat('auto', message, session)) return;
    setActivity('chat'); setPending(message); void run({ session_id: session.session_id, mode: 'auto', message }, '/chat');
  }
  function applyProfile(event) {
    event.preventDefault();
    if (!session || busy) return;
    try { void run({ session_id: session.session_id, profile: makeProfile(form) }, '/chat', 'profile'); } catch (e) { setError(e.message); }
  }
  function applyAdvisor(event) {
    event.preventDefault();
    if (!session || busy || !candidatePool(session).canRerank) return;
    try { void run({ session_id: session.session_id, advisor: neutral ? {...fixedAdvisor} : validateAdvisor(editableAdvisor(advisor)), advisor_selection: neutral ? undefined : selectionForRequest(advisorSelection), mode: 'rerank' }, '/chat', 'advisor'); } catch (e) { setError(e.message); }
  }
  function cancelEditor() {
    if (busy) return;
    if (editor === 'profile') { setForm(fromProfile(session.profile)); editorDrafts.current.profile = false; }
    if (editor === 'advisor') { setAdvisor(session.advisor || { ...defaultAdvisor }); setAdvisorSelection(session.advisor_selection || null); editorDrafts.current.advisor = false; }
    setEditor(null); setError('');
  }
  function editProfileDraft(value) {
    editorDrafts.current.profile = true;
    setForm(value);
  }
  function chooseAdvisor(value, selection) {
    setAdvisor(value); setAdvisorSelection(selection || templateSelection(''));
  }
  function editAdvisorDraft(value, selection) {
    editorDrafts.current.advisor = true;
    chooseAdvisor(value, selection);
  }
  function openEditor(next) {
    if (!session || busy || (neutral && next==='advisor')) return;
    if (!editor && activity === 'results') markSteps(3);
    if (editor === next && mobileView === 'jobs') { setMobileView('chat'); return; }
    if (editor === next) { cancelEditor(); return; }
    if (!editorDrafts.current[next]) {
      if (next === 'profile') setForm(fromProfile(session.profile));
      if (next === 'advisor') { setAdvisor(session.advisor || { ...defaultAdvisor }); setAdvisorSelection(session.advisor_selection || null); }
    }
    setEditor(next); setError(''); setMobileView('chat');
  }
  function showChat() {
    if (busy || booting) return;
    if (session) markSteps(3);
    setEditor(null); setMobileView('chat'); setActivity('chat');
  }
  function selectAssistantView(view) {
    if (!session || busy || booting) return;
    setError('');
    if (view === 'chat') showChat();
    else if (editor !== view) openEditor(view);
    else setMobileView('chat');
  }
  function visitJourneyStep(step) {
    if(neutral && step===2)return;
    if (!canVisitJourneyStep(step, { hasSession: !!session, activeStep, busy, booting })) return;
    if (!session && !onboardingStarted) {
      document.getElementById('start-onboarding')?.focus();
      return;
    }
    if (session && activeStep === 3) markSteps(3);
    if (!session) {
      if (step === 2) {
        try { makeProfile(form); } catch (e) {
          setError(e.message); setOnboardingStep(1); setMobileView('chat');
          requestAnimationFrame(() => document.getElementById('helena-chat')?.querySelector('textarea')?.focus());
          return;
        }
      }
      setError(''); setOnboardingStep(step); setMobileView('chat');
    } else if (step === 1 || step === 2) {
      const next = step === 1 ? 'profile' : 'advisor';
      if (editor !== next) openEditor(next);
      else setMobileView('chat');
    } else if (step === 3) {
      setEditor(null); setMobileView('jobs'); setActivity('results');
    } else showChat();
    requestAnimationFrame(() => {
      const selector = step === 3 ? '#helena-results-heading' : step === 4 ? '#chat-input' : step === 1 ? '.profile-intro h2' : '.advisor-intro h3';
      const target = workspace.current?.querySelector(selector);
      target?.focus({ preventScroll: true });
      target?.closest('.profile-scroll')?.scrollTo({ top: 0 });
      if (step === 3) target?.closest('.jobs-panel')?.scrollTo({ top: 0 });
    });
  }
  function rerankJobs() {
    if (!session || busy || editor || !candidatePool(session).canRerank) return;
    void run({ session_id: session.session_id, mode: 'rerank' }, '/chat', 'rerank');
  }
  function refreshCandidates() {
    if (!session || busy) return;
    setEditor(null); setActivity('results');
    void run({ session_id: session.session_id, mode: 'search' }, '/chat', 'refresh');
  }
  function askAboutJob(job) {
    setDraft(`Warum passt die Stelle „${job.title}“ bei ${job.company} (Job-ID ${job.id}) zu mir, und welche Kenntnisse fehlen noch?`.slice(0, 3000));
    setEditor(null); setMobileView('chat'); setActivity('chat'); markSteps(3);
    requestAnimationFrame(() => document.getElementById('chat-input')?.focus());
  }
  function reset() {
    if (busy) return;
    personalityIntroSeen.current = false; setPersonalityIntro(null);
    generation.current++; remember(null); setSession(null); setRevealedResults(null); setOnboardingStep(1); setOnboardingStarted(false); setDraft(''); setPending(''); setError(''); setEditor(null); setMobileView('jobs'); setActivity('results'); setCompletedSteps([]); editorDrafts.current = { profile: false, advisor: false };
  }
  function navigate(nextPage, event) {
    if (event && (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)) return;
    event?.preventDefault();
    if (nextPage === page) return;
    // Unmount the test consent gate before changing the token namespace.
    if (leavesTestContext(nextPage, window.location.pathname)) {
      window.location.assign(appPath(nextPage, window.location.search));
      return;
    }
    window.history.pushState(null, '', appPath(nextPage, window.location.search));
    setPage(nextPage);
  }
  const jobs = session?.jobs || [];
  const visibilityKey = resultVisibilityKey(session);
  const showLowScores = visibilityKey !== null && revealedResults === visibilityKey;
  const { visibleJobs, lowCount } = showInsights ? scoreVisibility(jobs, showLowScores) : { visibleJobs: jobs, lowCount: 0 };
  const chatSuggestions = buildChatSuggestions(session, visibleJobs, { showScores: showInsights });
  const allDemo = catalog.length > 0 && catalog.every(j => demoIds.has(j.id));
  const profileInfo = profileSummary(session?.profile);
  const indexReady = indexState?.status === 'ready';
  const pool = candidatePool(session);
  const poolRefreshHint = 'Diese Auswahl wurde noch nach Ort, Arbeitsmodell oder Stunden eingeschränkt. Eine neue Suche berücksichtigt diese Angaben als Wünsche.';
  const feedback = actionFeedback(session, visibleJobs.length);
  const progressLabel = pendingFeedback(operation, pool.count);
  const activeStep = currentJourneyStep({ hasSession: !!session, onboardingStep, editor, activity, busy, operation });
  const showWelcome = !session && !onboardingStarted;
  const showHeaderJourney = !!session;
  // The label belongs to the displayed results, not to an unsaved personality edit.
  const scoreLabel = advisorScoreLabel(session?.advisor);
  const assistantName = advisorAiLabel(session?.advisor);
  const pendingAssistantName = operation?.assistantName || advisorAiLabel(session?.advisor || advisor);

  function toggleLowScoreResults() {
    if (busy || booting) return;
    const revealing = !showLowScores;
    const visibleIds = new Set(visibleJobs.map(job => job.id));
    const firstAdditionalIndex = jobs.findIndex(job => !visibleIds.has(job.id));
    setRevealedResults(revealing ? visibilityKey : null);
    if (revealing && firstAdditionalIndex >= 0) {
      requestAnimationFrame(() => {
        const card = document.getElementById('ranked-jobs')?.children[firstAdditionalIndex];
        card?.querySelector('h3')?.focus({ preventScroll: true });
        card?.scrollIntoView({ block: 'start', behavior: 'auto' });
      });
    }
  }

  return <><div className="app-shell" hidden={page === 'about'}>
    <header className={`topbar${showHeaderJourney ? ' topbar--with-journey' : ''}`}>
      <div className="topbar-inner">
        {isEmbeddedSurvey ? <div className="brand"><CompassAvatar className="brand-compass" /><span className="brand-name">HELENA Jobsuche</span></div> : <a href="/" className="brand" aria-label="HELENA Startseite" onClick={event => navigate('about', event)}><CompassAvatar className="brand-compass" /><span className="brand-name">HELENA Jobsuche</span></a>}
        {showHeaderJourney && <div className="topbar-journey"><JourneyGuide allowCustom={allowCustom} neutral={neutral} iconOnly activeStep={activeStep} completedSteps={completedSteps} busy={busy || booting} hasSession={!!session} /></div>}
        <div className="local-status"><i aria-hidden="true" />{allDemo ? `${total} fiktive Beispielstellen` : `${total.toLocaleString('de-DE')} Stellenanzeigen`}</div>
      </div>
    </header>
    {(session || onboardingStarted) && <nav className={`mobile-view-switch${session ? ' mobile-view-switch--results' : ''}`} aria-label="Stellen und Chat">
      <button type="button" aria-pressed={mobileView === 'jobs'} disabled={busy || booting} onClick={() => { setMobileView('jobs'); if (session) { setEditor(null); setActivity('results'); } }}><Search size={21} aria-hidden="true"/><span>{session ? 'Stellen ansehen' : 'Anleitung'}</span></button>
      <button type="button" aria-pressed={mobileView === 'chat'} disabled={busy || booting} onClick={() => session ? showChat() : setMobileView('chat')}><MessageCircle size={21} aria-hidden="true"/><span>{session ? 'Chat öffnen' : onboardingStep === 1 ? 'Profil' : 'Persönlichkeit'}</span></button>
    </nav>}
    <main ref={workspace} data-journey-step={activeStep} className={`workspace view-${mobileView} ${!session ? 'is-onboarding' : ''} ${showWelcome ? 'is-welcome' : ''} ${chatLayout.dragging ? 'is-resizing' : ''}`} style={{ '--chat-width': `${chatLayout.width}px` }}>
      <section className="jobs-panel" aria-label={session ? 'Stellenangebote' : 'So funktioniert HELENA'} onPointerDownCapture={() => { if (session && !editor && !busy && !booting) setActivity('results'); }} onFocusCapture={() => { if (session && !editor && !busy && !booting) setActivity('results'); }}>
        <div className="jobs-heading"><div><span className="eyebrow">DEINE JOBSUCHE</span><h1 id="helena-results-heading" tabIndex={-1}>{session ? 'Deine Empfehlungen' : 'So funktioniert HELENA'}</h1></div>{session && <ProfileSummaryPopover key={session.session_id} summary={profileInfo} disabled={busy || booting || page !== 'search'} context={`${page}-${mobileView}-${editor}`} onEdit={() => selectAssistantView('profile')} />}</div>
        {indexState?.required && !indexReady && <div className="index-notice" role="status"><strong>{indexState.status === 'failed' ? 'Suchindex noch nicht vollständig' : 'Deine gesamte Jobdatenbank wird vorbereitet'}</strong><p>{indexState.completed.toLocaleString('de-DE')} von {indexState.total.toLocaleString('de-DE')} Anzeigen sind für die semantische Suche indexiert. Du kannst dein Profil schon ausfüllen.</p><progress value={indexState.completed} max={indexState.total || 1} aria-label="Fortschritt der Indexierung" /></div>}
        {error && (showWelcome || mobileView === 'jobs') && <div className={`error-banner${showWelcome ? '' : ' journey-mobile-error'}`} role="alert">{error}</div>}
        {booting ? <div className="empty-state" role="status"><span className="spinner" /><p>Deine Jobsuche wird geladen …</p></div> : session ? <>
          <div id="ranked-jobs" className="jobs-list" aria-busy={busy}>
            {visibleJobs.map((job, i) => <JobCard key={job.id} job={job} index={i} ranked showInsights={showInsights} scoreLabel={scoreLabel} assistantName={assistantName} onAsk={askAboutJob} busy={busy} />)}
            {!jobs.length && <div className="empty-state"><Search size={34} strokeWidth={1.3} /><h2>Hier ist noch Platz für deinen Match.</h2><p>{profileInfo.hardFilters.length && !pool.refreshRequired ? 'Aktuell gibt es keine Stellen zur gewählten Stellenart. Du kannst im Suchprofil oder Chat weitere Stellenarten einbeziehen.' : 'Aktuell liegen keine Stellenempfehlungen vor. Prüfe dein Suchprofil oder starte eine neue Suche.'}</p><button className="text-button" disabled={busy} onClick={() => { setDraft(profileInfo.hardFilters.length ? 'Welche Stellenarten sind aktuell ausgewählt und welche weiteren kommen für mich infrage?' : 'Welche Angaben sind aktuell in meinem Suchprofil gespeichert?'); showChat(); }}>Suchprofil im Chat besprechen <ArrowRight size={15} /></button></div>}
          </div>
          {lowCount > 0 && <ScoreNotice lowCount={lowCount} total={jobs.length} showLowScores={showLowScores} scoreLabel={scoreLabel} busy={busy} onToggle={toggleLowScoreResults} />}
          {allDemo && <p className="catalog-note">Zum Ausprobieren: Diese Anzeigen und Unternehmen sind fiktiv.</p>}
        </> : <SearchIntro allowCustom={allowCustom} neutral={neutral} busy={busy || booting} activeStep={activeStep} completedSteps={completedSteps} onSelect={visitJourneyStep} />}
      </section>
      <div className="split-handle" {...chatLayout.separatorProps}><GripVertical size={17} aria-hidden="true" /></div>
      <aside id="helena-chat" className="assistant-panel" aria-label={session ? `Chat mit ${assistantName}` : 'Persönlicher Jobberater'} onPointerDownCapture={() => { if (session && !editor && !busy && !booting) { setActivity('chat'); markSteps(3); } }} onFocusCapture={() => { if (session && !editor && !busy && !booting) { setActivity('chat'); markSteps(3); } }}>
        {showWelcome ? <div className="onboarding-welcome"><button id="start-onboarding" type="button" className="primary-button helena-action-motion" onClick={beginOnboarding} disabled={booting || busy}><span className="onboarding-start-copy"><strong>Jetzt Profil erstellen</strong><span>Hier klicken und loslegen</span></span><span className="onboarding-start-arrow helena-action-arrow" aria-hidden="true"><ArrowRight size={22} /></span></button></div> : <>
        {session && <AssistantActionArea key={session.session_id} feedback={!busy ? feedback : ''}>
          <div className="assistant-actions" role="group" aria-label="Aktionen für deine Jobsuche">
            <button type="button" className="rerank-button mobile-edit-action" onClick={() => selectAssistantView('profile')} disabled={busy || booting}><SlidersHorizontal size={16} aria-hidden="true"/><span>Suchprofil bearbeiten</span></button>
            {!neutral && <button type="button" className="rerank-button mobile-edit-action" onClick={() => selectAssistantView('advisor')} disabled={busy || booting}><Compass size={16} aria-hidden="true"/><span>Persönlichkeit ändern</span></button>}
            <button type="button" className="rerank-button" onClick={rerankJobs} disabled={busy || booting || !!editor || !pool.canRerank}><RotateCcw size={16} aria-hidden="true" /><span>{pool.count} Jobs neu sortieren</span></button>
            <button type="button" className="rerank-button" onClick={reset} disabled={busy || booting} title="Neue Suche mit deinem Profil"><RotateCcw size={14} aria-hidden="true" /><span>Neu starten</span></button>
          </div>
          {!pool.canRerank && <p className="pool-hint">{pool.refreshRequired ? poolRefreshHint : 'Zum erneuten Bewerten brauchst du eine neue Suche.'} <button type="button" onClick={refreshCandidates} disabled={busy || booting}>Neue Suche starten</button></p>}
          {pool.canRerank && jobs.length < pool.count && <p className="pool-hint">Diese frühere Suche zeigt bisher nur {jobs.length} von {pool.count} ausgewählten Stellen. Mit „{pool.count} Jobs neu sortieren“ werden alle als bewertete Ergebnisse verfügbar.</p>}
        </AssistantActionArea>}
        {error && <div className="error-banner" role="alert">{error}</div>}
        {indexState?.required && !indexReady && <p className="index-chat-status" role="status">Suchindex: {indexState.completed.toLocaleString('de-DE')} von {indexState.total.toLocaleString('de-DE')} Anzeigen vorbereitet. {session ? 'Fragen und das Bewerten gespeicherter Jobs bleiben möglich. Neue Suchen sind nach Abschluss verfügbar.' : 'Deine Suche ist nach Abschluss verfügbar.'}</p>}
        {!session ? <div className="profile-scroll"><ProfileForm allowCustom={allowCustom} templates={templates} advisorSelection={advisorSelection} neutral={neutral} form={form} setForm={setForm} onSubmit={startSearch} busy={busy || booting} ready={indexReady} advisor={advisor} setAdvisor={chooseAdvisor} step={onboardingStep} onNext={nextOnboardingStep} onBack={() => { setError(''); setOnboardingStep(1); }} onExplainAdvisor={() => setPersonalityIntro('help')} /></div> : editor === 'profile' ? <div className="profile-scroll"><ProfileForm neutral={neutral} editMode advisor={session.advisor} form={form} setForm={editProfileDraft} onSubmit={applyProfile} busy={busy} onBack={cancelEditor} /></div> : editor === 'advisor' && !neutral ? <form className="advisor-editor profile-form" onSubmit={applyAdvisor}><AdvisorPicker allowCustom={allowCustom} templates={templates} selection={advisorSelection} value={advisor} onChange={editAdvisorDraft} disabled={busy} onExplain={() => setPersonalityIntro('help')} />{!pool.canRerank && <p className="pool-hint">{pool.refreshRequired ? poolRefreshHint : 'Zum Anwenden deiner Persönlichkeit brauchst du eine neue Suche.'} Deine Auswahl bleibt dabei erhalten. <button type="button" onClick={refreshCandidates} disabled={busy}>Neue Suche starten</button></p>}<div className="onboarding-actions"><button type="button" className="back-button" onClick={cancelEditor} disabled={busy}>Abbrechen</button><button type="submit" className="primary-button" disabled={busy || !pool.canRerank}>{busy ? 'Jobs werden geprüft …' : 'Persönlichkeit anwenden'}<ArrowRight size={17} /></button></div><p className="privacy-note">Dein Suchprofil mit Stellenart, Wünschen und Erfahrung bleibt erhalten.{pool.canRerank ? ` ${advisorAiLabel(advisor)} bewertet die vorhandenen ${pool.count} Jobs neu.` : ''}</p></form> : <>
          <div className="chat-feed" role="log" aria-label="Chatverlauf" aria-live="polite" onScroll={event => { const feed = event.currentTarget; followChat.current = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80; }}>{session.messages.map((message, index) => <div className={`chat-message ${message.role}`} key={`${index}-${message.role}`}><span className="message-author">{message.role === 'user' ? 'DU' : <><CompassAvatar className="message-compass" /><span className="advisor-name">{message.advisor_name || assistantName}</span></>}</span><ChatMessageText text={message.content} assistant={message.role === 'assistant'} /></div>)}{pending && <div className="chat-message user pending"><span className="message-author">DU</span><ChatMessageText text={pending} assistant={false} /></div>}{busy && <div className="chat-message assistant"><span className="message-author"><CompassAvatar className="message-compass" /><span className="advisor-name">{pendingAssistantName}</span></span><div className="message-bubble" aria-busy="true">{streamingText ? <div className="message-text streaming-text">{streamingText}</div> : <div className="chat-typing"><span className="sr-only">{progressLabel}</span><span aria-hidden="true"><i /><i /><i /></span></div>}</div></div>}<div ref={messagesEnd} /></div>
          <div className="chat-bottom">{chatSuggestions.length > 0 && <details className="chat-examples"><summary>Vorschläge für deinen nächsten Schritt</summary><div className="suggestions">{chatSuggestions.map(suggestion => <button key={suggestion.id} disabled={busy} onClick={() => { setDraft(suggestion.message); requestAnimationFrame(() => document.getElementById('chat-input')?.focus()); }}><Plus size={13} />{suggestion.label}</button>)}</div></details>}
            {!pool.canRerank && <p className="pool-hint">{pool.refreshRequired ? poolRefreshHint : 'Zum erneuten Bewerten sind gerade keine gespeicherten Jobs verfügbar.'} Du kannst im Chat um eine neue Suche bitten.</p>}
            <form className="chat-composer" onSubmit={sendMessage}><label className="sr-only" htmlFor="chat-input">Nachricht an {assistantName}</label><textarea id="chat-input" rows={2} maxLength={3000} value={draft} onChange={e => setDraft(e.target.value)} placeholder="Was möchtest du wissen oder ändern?" disabled={busy} onKeyDown={e => { if (shouldSendOnEnter({...e, isComposing:e.nativeEvent.isComposing}, window.matchMedia('(pointer: coarse)').matches)) { e.preventDefault(); sendMessage(e); } }} /><button type="submit" aria-label="Nachricht senden" disabled={busy || !canSendChat('auto', draft, session)}><ArrowUp size={20} /></button></form>
          </div>
        </>}
        </>}
      </aside>
    </main>

  </div>{page === 'about' && <AboutPage />}<PersonalityIntroDialog allowCustom={allowCustom} open={!neutral && personalityIntro !== null && page === 'search'} onboarding={personalityIntro === 'onboarding'} onContinue={continuePersonalityIntro} onClose={() => setPersonalityIntro(null)} /><SearchLoadingDialog open={!isEmbeddedSurvey && busy && searchActive && page === 'search'} assistantName={pendingAssistantName} progress={searchProgress} /></>;
}

export function AssignedSearch() {
  const [assignment,setAssignment]=useState(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
  useEffect(()=>{
    let active=true;const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);
    fetch('/api/study-assignment',{method:'POST',headers:consentHeaders(),signal:controller.signal}).then(async response=>{
      if(!response.ok)throw new Error('Der Systemtest konnte nicht vorbereitet werden.');
      const value=await response.json();if(!['A','B','C'].includes(value.arm) || !['generic','standard','templates','configurable'].includes(value.personality_policy) || !['ranked_insights','legacy_neutral'].includes(value.presentation_policy))throw new Error('Studienzuordnung fehlt.');
      if(active){setAssignment(value);setError('');}
    }).catch(()=>{if(active)setError('Der Systemtest konnte nicht vorbereitet werden. Bitte versuche es erneut.');}).finally(()=>clearTimeout(timeout));
    return()=>{active=false;clearTimeout(timeout);controller.abort();};
  },[attempt]);
  if(!assignment)return <div className="empty-state" role="status"><p>{error || 'Dein Systemtest wird vorbereitet …'}</p>{error && <button className="primary-button" onClick={()=>setAttempt(value=>value+1)}>Erneut versuchen</button>}</div>;
  return <App studyArm={assignment.arm} personalityPolicy={assignment.personality_policy} presentationPolicy={assignment.presentation_policy} />;
}

const isSurveyPage = /^\/umfrage\/?$/.test(window.location.pathname);
const testArm = standaloneArm();
const isSearchPage = window.location.pathname === '/suche' || !!testArm;
const isAdminPage = window.location.pathname === '/verwaltung';
const isPrivacyPage = window.location.pathname === '/datenschutz' || /^\/test\/[abc]\/datenschutz\/?$/.test(window.location.pathname);
if (!import.meta.env.SSR) installMobileViewport(window);
if (!import.meta.env.SSR) createRoot(document.getElementById('root')).render(<React.StrictMode>{isAdminPage ? <AdminPage /> : isPrivacyPage ? <PrivacyGate informationOnly /> : isSurveyPage || isSearchPage ? <PrivacyGate>{isSurveyPage ? <SurveyPage /> : testArm ? <App studyArm={testArm}/> : <AssignedSearch />}</PrivacyGate> : <AboutPage />}</React.StrictMode>);
