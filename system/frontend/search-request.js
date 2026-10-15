import {readSearchProgress} from './search-progress.js';
import {consentHeaders} from './privacy.js';
function responseError(data, status) {
  const error = new Error(data?.error?.message || 'Die Anfrage konnte nicht verarbeitet werden.');
  error.status = status;
  return error;
}

/** Read actual server phases without guessing the intent of a chat message. */
export async function readOperationResponse(response, onPhase = () => {}, onText = () => {}, onProgress = () => {}) {
  if (!response.ok || !response.headers.get('content-type')?.includes('application/x-ndjson')) {
    let data;
    try { data = await response.json(); }
    catch { throw new Error('Die Serverantwort konnte nicht gelesen werden. Bitte versuche es erneut.'); }
    if (!response.ok) throw responseError(data, response.status);
    return data;
  }
  if (!response.body) throw new Error('Die Verbindung wurde ohne Antwort beendet.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let searchReported = false;
  let result;
  let complete = false;
  function consume(line) {
    if (!line.trim()) return;
    let event;
    try { event = JSON.parse(line); }
    catch { throw new Error('Die Serverantwort konnte nicht gelesen werden. Bitte versuche es erneut.'); }
    if (!event || typeof event !== 'object') throw new Error('Die Serverantwort ist unvollständig.');
    if (event.type === 'error') throw responseError(event, event.status || 500);
    if (event.type === 'assistant_text') {
      if (typeof event.text !== 'string') {
        throw new Error('Der Antworttext konnte nicht gelesen werden.');
      }
      // Generic chat has no answer-length cap. The transport buffer limit below
      // still applies. Only the final result commits a message.
      onText(event.text);
    }
    if (event.type === 'phase' && event.phase === 'search' && !searchReported) {
      searchReported = true;
      onPhase('search');
    }
    if (event.type === 'search_progress' && searchReported) {
      const progress = readSearchProgress(event);
      if (progress) onProgress(progress);
    }
    if (event.type === 'result') {
      if (!event.data || typeof event.data !== 'object' || Array.isArray(event.data)) {
        throw new Error('Die Serverantwort enthält kein gültiges Ergebnis.');
      }
      result = event.data;
      complete = true;
    }
  }
  try {
    while (!complete) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      if (buffer.length > 8 * 1024 * 1024) throw new Error('Die Serverantwort ist zu groß.');
      let newline;
      while (!complete && (newline = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        consume(line);
      }
      if (complete) return result;
      if (done) {
        consume(buffer);
        if (complete) return result;
        throw new Error('Die Verbindung wurde vor dem vollständigen Ergebnis beendet. Deine Eingabe bleibt erhalten.');
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function requestOperation(path, body, onPhase = () => {}, onText = () => {}, onProgress = () => {}) {
  const response = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { ...consentHeaders(), 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
    body: JSON.stringify(body),
  });
  return readOperationResponse(response, onPhase, onText, onProgress);
}
