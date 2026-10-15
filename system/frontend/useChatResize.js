import { useEffect, useRef, useState } from 'react';
import { CHAT_WIDTH_KEY, DEFAULT_CHAT_WIDTH, chatWidthBounds, clampChatWidth, keyboardChatWidth, onboardingChatWidth } from './chat-layout.js';

export default function useChatResize(workspaceRef, onboarding = false) {
  const [preferredWidth, setPreferredWidth] = useState(() => {
    try {
      const stored = localStorage.getItem(CHAT_WIDTH_KEY);
      return stored === null ? DEFAULT_CHAT_WIDTH : clampChatWidth(Number(stored), 1600);
    } catch { return DEFAULT_CHAT_WIDTH; }
  });
  const [containerWidth, setContainerWidth] = useState(1200);
  const [setupWidth, setSetupWidth] = useState(null);
  const [dragging, setDragging] = useState(false);
  const drag = useRef(null);
  const width = clampChatWidth(onboarding ? setupWidth ?? onboardingChatWidth(containerWidth) : preferredWidth, containerWidth);
  const setWidth = onboarding ? setSetupWidth : setPreferredWidth;
  const bounds = chatWidthBounds(containerWidth);

  useEffect(() => {
    const element = workspaceRef.current;
    const observer = new ResizeObserver(([entry]) => setContainerWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, [workspaceRef]);
  useEffect(() => {
    const timeout = setTimeout(() => { try { localStorage.setItem(CHAT_WIDTH_KEY, String(preferredWidth)); } catch { /* Optional layout preference. */ } }, 200);
    return () => clearTimeout(timeout);
  }, [preferredWidth]);

  function finish(event, cancel = false) {
    if (!drag.current || event.pointerId !== drag.current.id) return;
    if (cancel) setWidth(drag.current.width);
    drag.current = null; setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }
  return { width, dragging, separatorProps: {
    role: 'separator', tabIndex: 0, 'aria-orientation': 'vertical',
    'aria-label': 'Chatbreite ändern', 'aria-controls': 'helena-chat',
    'aria-valuemin': bounds.min, 'aria-valuemax': bounds.max, 'aria-valuenow': width,
    'aria-valuetext': `${width} Pixel`,
    title: 'Ziehen oder mit den Pfeiltasten die Chatbreite ändern. Doppelklick setzt die Breite zurück.',
    onPointerDown(event) {
      if (event.button !== 0 || !event.isPrimary) return;
      event.preventDefault(); event.currentTarget.focus();
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { id: event.pointerId, x: event.clientX, width };
      setDragging(true);
    },
    onPointerMove(event) {
      if (drag.current?.id !== event.pointerId) return;
      setWidth(clampChatWidth(drag.current.width + drag.current.x - event.clientX, containerWidth));
    },
    onPointerUp(event) { finish(event); },
    onPointerCancel(event) { finish(event, true); },
    onLostPointerCapture() { drag.current = null; setDragging(false); },
    onDoubleClick() { setWidth(onboarding ? null : DEFAULT_CHAT_WIDTH); },
    onKeyDown(event) {
      if (event.key === 'Escape' && drag.current) {
        event.preventDefault(); setWidth(drag.current.width);
        const id = drag.current.id;
        drag.current = null; setDragging(false);
        if (event.currentTarget.hasPointerCapture(id)) event.currentTarget.releasePointerCapture(id);
        return;
      }
      const next = keyboardChatWidth(event.key, width, containerWidth, event.shiftKey);
      if (next !== null) { event.preventDefault(); setWidth(next); }
    },
  } };
}
