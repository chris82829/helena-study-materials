import { readSearchProgress } from './search-progress.js';
import { surveyRun } from './app-session.js';
import { labels, remoteLabels } from './profile.js';

const COMPLETION = 'helena:survey-search-completed';
const REQUEST = 'helena:survey-progress-request';
const CONTEXT = 'helena:survey-search-context';
const CHAT_COMPLETED = 'helena:survey-chat-completed';
const OPEN_CHAT = 'helena:survey-open-chat';

export function searchGoalSuggestion(profile) {
  if (!profile || typeof profile !== 'object') return '';
  const strings = values => Array.isArray(values) ? values.filter(value => typeof value === 'string').join(', ') : '';
  const mapped = (values, names) => strings(Array.isArray(values) ? values.map(key => names[key]) : []);
  return [typeof profile.query === 'string' ? profile.query.trim() : '',
    strings(profile.skills) && `Fähigkeiten: ${strings(profile.skills)}`,
    mapped(profile.filters?.employment_types, labels) && `Stellenart: ${mapped(profile.filters.employment_types, labels)}`,
    strings(profile.preferences) && `Wünsche: ${strings(profile.preferences)}`,
    strings(profile.filters?.locations) && `Ort: ${strings(profile.filters.locations)}`,
    mapped(profile.filters?.remote, remoteLabels) && `Arbeitsmodell: ${mapped(profile.filters.remote, remoteLabels)}`,
    Number.isFinite(profile.filters?.max_hours) && `Gewünschte Wochenstunden: ${profile.filters.max_hours}`,
  ].filter(Boolean).join('\n').slice(0, 1000);
}

// Only committed results carry a server session. Catalog data and streamed
// previews must never unlock the follow-up questionnaire.
export function hasSearchResults(session) {
  return Boolean(session && /^[A-Za-z0-9_-]{32,100}$/.test(session.session_id || '') && Array.isArray(session.jobs));
}

export function hasChatMessage(session) {
  return hasSearchResults(session) && Array.isArray(session.messages)
    && session.messages.some(message => message.role === 'user' && typeof message.content === 'string' && message.content.trim());
}

export function isSurveyResultsView({ session, page, booting, busy, editor, personalityIntro }) {
  return hasSearchResults(session) && page === 'search' && !booting && !busy
    && !editor && !personalityIntro;
}

export function reportSurveyProgress(host, ready, context, onOpenChat) {
  const runId = surveyRun(host.location.search);
  if (!runId || host.parent === host) return () => {};
  const announce = () => {
    if (context) host.parent.postMessage({ type: CONTEXT, runId,
      resultsVisible: context.resultsVisible === true,
      ...(context.searching && readSearchProgress(context.searchProgress) ? {searchProgress:readSearchProgress(context.searchProgress)} : {}),
      ...(typeof context.assistantName==='string'?{assistantName:context.assistantName.slice(0,100)}:{}),
      searching: context.searching === true, searchGoal: typeof context.searchGoal === 'string' ? context.searchGoal.slice(0, 1000) : '' }, host.location.origin);
    if (ready) host.parent.postMessage({ type: COMPLETION, runId, completedStep: 3 }, host.location.origin);
    if (context?.chatCompleted === true) host.parent.postMessage({ type: CHAT_COMPLETED, runId }, host.location.origin);
  };
  const onRequest = event => {
    if (event.origin !== host.location.origin || event.source !== host.parent || event.data?.runId !== runId) return;
    if (event.data.type === REQUEST) announce();
    if (event.data.type === OPEN_CHAT) onOpenChat?.();
  };
  host.addEventListener('message', onRequest);
  announce();
  return () => host.removeEventListener('message', onRequest);
}

export function readSurveySearchContext(event, frameWindow, origin, runId) {
  const data = event.data;
  if (!frameWindow || event.source !== frameWindow || event.origin !== origin
      || data?.type !== CONTEXT || data.runId !== runId || typeof data.searching !== 'boolean'
      || typeof data.searchGoal !== 'string' || data.searchGoal.length > 1000) return null;
  return { ...(data.searching && readSearchProgress(data.searchProgress) ? {searchProgress:readSearchProgress(data.searchProgress)} : {}), searching: data.searching, resultsVisible: data.resultsVisible === true, searchGoal: data.searchGoal.trim(), ...(typeof data.assistantName==='string' && data.assistantName.length<=100?{assistantName:data.assistantName}:{}) };
}

export function requestSurveyProgress(frameWindow, origin, runId) {
  frameWindow?.postMessage({ type: REQUEST, runId }, origin);
}

export function isSurveyCompletion(event, frameWindow, origin, runId) {
  return Boolean(frameWindow && event.source === frameWindow && event.origin === origin
    && event.data?.type === COMPLETION && event.data.runId === runId && event.data.completedStep === 3);
}

export function isSurveyChatCompletion(event, frameWindow, origin, runId) {
  return Boolean(frameWindow && event.source === frameWindow && event.origin === origin
    && event.data?.type === CHAT_COMPLETED && event.data.runId === runId);
}

export function requestSurveyChat(frameWindow, origin, runId) {
  frameWindow?.postMessage({ type: OPEN_CHAT, runId }, origin);
}
