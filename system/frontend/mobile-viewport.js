/** Keep fixed workspaces within the visible viewport when mobile keyboards open. */
export function installMobileViewport(host) {
  const root = host.document.documentElement;
  const viewport = host.visualViewport;
  let scheduled;
  const update = () => {
    scheduled = undefined;
    // Preserve normal pinch zoom rather than resizing content under the user.
    if (viewport && viewport.scale !== 1) return;
    const height = viewport?.height || host.innerHeight;
    if (!Number.isFinite(height) || height <= 0) return;
    root.style.setProperty('--helena-viewport-height', `${Math.round(height)}px`);
    root.classList.toggle('helena-keyboard-open', host.innerHeight - height > 120);
  };
  const schedule = () => { if (scheduled === undefined) scheduled = host.requestAnimationFrame(update); };
  host.addEventListener('resize', schedule);
  viewport?.addEventListener('resize', schedule);
  viewport?.addEventListener('scroll', schedule);
  update();
  return () => {
    host.removeEventListener('resize', schedule);
    viewport?.removeEventListener('resize', schedule);
    viewport?.removeEventListener('scroll', schedule);
    if (scheduled !== undefined) host.cancelAnimationFrame(scheduled);
    root.style.removeProperty('--helena-viewport-height');
    root.classList.remove('helena-keyboard-open');
  };
}

export function shouldSendOnEnter(event, touchKeyboard = false) {
  return event.key === 'Enter' && !event.shiftKey && !event.isComposing
    && (!touchKeyboard || event.ctrlKey || event.metaKey);
}
