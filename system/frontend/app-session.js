import {standaloneArm,consentPurpose} from './test-access.js';
// Embedded survey runs must not resume the user's ordinary HELENA session.
export function surveyRun(search = '') {
  const params = new URLSearchParams(search);
  const run = params.get('run');
  return params.get('embed') === 'survey' && /^[a-f0-9]{32}$/.test(run || '') ? run : null;
}

export function appSessionStorage(host = window) {
  const run = surveyRun(host.location.search);
  const test = standaloneArm(host.location.pathname);
  const key = test ? `helena-test-chat:${consentPurpose(host)}` : run ? `helena-survey-chat:${run}` : 'jobkompass-session-v1';
  const storage = () => run || test ? host.sessionStorage : host.localStorage;
  return {
    read() { try { return storage().getItem(key); } catch { return null; } },
    remember(id) {
      try { id ? storage().setItem(key, id) : storage().removeItem(key); } catch { /* Storage is optional. */ }
    },
  };
}

export function appPath(page, search = '', pathname = globalThis.window?.location?.pathname || '') {
  const test = standaloneArm(pathname);
  if (test && page !== 'about') return `/test/${test.toLowerCase()}`;
  const path = page === 'about' ? '/' : '/suche';
  const run = surveyRun(search);
  return run ? `${path}?embed=survey&run=${run}` : path;
}
