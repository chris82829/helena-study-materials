import {standaloneArm, consentPurpose} from './test-access.js';
export const CONSENT_KEY = 'helena-privacy-consent';
const memoryTokens = new Map();
const scopeKey = host => consentPurpose(host) === 'study' ? CONSENT_KEY : `${CONSENT_KEY}:${consentPurpose(host)}`;
export function consentToken(host = globalThis.window) {
  try { return host?.sessionStorage.getItem(scopeKey(host)) || memoryTokens.get(scopeKey(host)) || ''; } catch { return memoryTokens.get(scopeKey(host)) || ''; }
}
export function rememberConsent(token, host = globalThis.window) {
  memoryTokens.set(scopeKey(host), token);
  try { token ? host?.sessionStorage.setItem(scopeKey(host), token) : host?.sessionStorage.removeItem(scopeKey(host)); } catch { /* Current page still works. */ }
}
export function consentHeaders() {
  const token = consentToken();
  const arm = standaloneArm();
  return {...(token ? {'X-Helena-Consent':token} : {}), ...(arm ? {'X-Helena-Test':arm} : {})};
}
export function clearParticipation(host = globalThis.window) {
  memoryTokens.delete(scopeKey(host));
  const purpose = consentPurpose(host);
  try {
    const storage = host.sessionStorage;
    for (const key of Object.keys(storage)) {
      if (key === scopeKey(host) || (purpose === 'study' ? key.startsWith('helena-survey:') || key.startsWith('helena-survey-chat:') : key === `helena-test-chat:${purpose}`)) storage.removeItem(key);
    }
    if (purpose === 'study') host.localStorage.removeItem('jobkompass-session-v1');
  } catch { /* In-memory state is discarded by the gate too. */ }
}
export async function privacyRequest(path = '', options = {}) {
  const response = await fetch(`/api/privacy${path}`, {...options, headers:{...consentHeaders(), ...(options.body ? {'Content-Type':'application/json'} : {})}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || 'Datenschutz-Einstellungen konnten nicht geladen werden.');
  return data;
}
