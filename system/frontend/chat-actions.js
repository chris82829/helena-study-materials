import { sameAdvisor } from './advisor.js';

export function candidatePool(session) {
  const pool = session?.candidate_pool;
  const count = Number.isInteger(pool?.count) && pool.count >= 0 ? pool.count : 0;
  const refreshRequired = pool?.refresh_required === true;
  return { count, available: pool?.available === true, refreshRequired, canRerank: pool?.available === true && count > 0 && !refreshRequired };
}

export function canSendChat(mode, message, session) {
  if (!session) return false;
  if (mode === 'rerank') return candidatePool(session).canRerank;
  return mode === 'search' || (mode === 'auto' && !!message.trim());
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}
export function sameProfile(left, right) {
  return !!left && !!right && JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

export function profileChangeAction(before, after) {
  if (!before || !after) return 'search';
  function comparable(value) {
    if (typeof value === 'string') return value.trim().replace(/\s+/g, ' ').toLocaleLowerCase('de-DE').replace(/ß/g, 'ss');
    if (Array.isArray(value)) return [...new Set(value.map(comparable))].sort();
    return value;
  }
  const differs = (left, right) => JSON.stringify(comparable(left)) !== JSON.stringify(comparable(right));
  const previousFilters = before.filters || {};
  const nextFilters = after.filters || {};
  if (differs(before.query || '', after.query || '') || differs(before.skills || [], after.skills || []) ||
      differs(previousFilters.employment_types || [], nextFilters.employment_types || [])) return 'search';
  if (differs(before.preferences || [], after.preferences || []) || differs(before.cv_text || '', after.cv_text || '') ||
      differs(previousFilters.locations || [], nextFilters.locations || []) ||
      differs(previousFilters.remote || [], nextFilters.remote || []) ||
      differs(previousFilters.max_hours ?? null, nextFilters.max_hours ?? null)) return 'rerank';
  return 'answer';
}

export function submittedChangeApplied(result, body, kind) {
  if (kind === 'profile') return sameProfile(result.profile, body.profile);
  if (kind === 'advisor') return result.chat_action === 'rerank' && sameAdvisor(result.advisor, body.advisor);
  return true;
}

// Without a request ID, a bare rerank/search cannot safely be attributed to us.
// Never clear a draft just because another request changed the session.
export function recoveredSubmission(previous, latest, body, kind) {
  if (!previous || !latest || JSON.stringify(previous.messages) === JSON.stringify(latest.messages)) return false;
  if (!['answer', 'rerank', 'search'].includes(latest.chat_action)) return false;
  if (body.mode && body.mode !== 'auto' && latest.chat_action !== body.mode) return false;
  if (kind === 'profile') return !sameProfile(previous.profile, body.profile) && submittedChangeApplied(latest, body, kind);
  if (kind === 'advisor') return !sameAdvisor(previous.advisor, body.advisor) && submittedChangeApplied(latest, body, kind);
  if (!body.message?.trim()) return false;
  const lastUser = [...latest.messages].reverse().find(message => message.role === 'user');
  const previousUser = [...previous.messages].reverse().find(message => message.role === 'user');
  return lastUser?.content === body.message && (previousUser?.content !== body.message || latest.messages.length > previous.messages.length);
}

export function actionFeedback(session, visibleCount = session?.jobs?.length || 0) {
  if (session?.chat_action === 'answer') return 'Ergebnisse unverändert';
  if (session?.chat_action === 'rerank') return `${candidatePool(session).count} Jobs neu bewertet`;
  if (session?.chat_action === 'search') return `Neue Suche abgeschlossen · ${visibleCount} von ${session.jobs.length} Ergebnissen angezeigt`;
  return '';
}

export function pendingFeedback(operation, count) {
  if (!operation) return '';
  if (operation.kind === 'profile') return operation.mode === 'rerank' ? 'Profilangaben werden neu bewertet' : operation.mode === 'search' ? 'Profil wird für eine neue Suche geprüft' : 'Profil wird geprüft';
  if (operation.kind === 'advisor' || operation.kind === 'rerank' || operation.mode === 'rerank') return `Vorhandene ${count} Jobs werden neu bewertet`;
  if (operation.kind === 'onboard' || operation.kind === 'refresh' || operation.mode === 'search') return 'Neue Stellen werden gesucht';
  return 'Nachricht wird verarbeitet';
}
