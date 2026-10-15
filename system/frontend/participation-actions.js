export function deletionEmail(value) {
  const subject = 'HELENA – Löschung meiner Teilnahme '+value;
  const body = 'Hallo Studienleitung,\r\n\r\nbitte lösche meine Umfragedaten.\r\nMeine Teilnahme-ID: '+value+'\r\n\r\nVielen Dank!';
  return `mailto:study@example.org?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

export async function copyParticipationId(value, container, {navigator: nav = globalThis.navigator, document: doc = globalThis.document} = {}) {
  try {
    if (nav?.clipboard?.writeText) {
      await nav.clipboard.writeText(value);
      return true;
    }
  } catch { /* HTTP and denied clipboard permissions need the selection fallback. */ }
  const previousFocus = doc.activeElement;
  const input = doc.createElement('textarea');
  input.value = value;
  input.readOnly = true;
  input.tabIndex = -1;
  input.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px;pointer-events:none;';
  // Stay inside the active dialog so its focus restrictions do not block copying.
  (container || doc.body).appendChild(input);
  try {
    input.focus({preventScroll:true});
    input.select();
    input.setSelectionRange(0, value.length);
    return doc.execCommand?.('copy') === true;
  } catch {
    return false;
  } finally {
    input.remove();
    previousFocus?.focus({preventScroll:true});
  }
}
