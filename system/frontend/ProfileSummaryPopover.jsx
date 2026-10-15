import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { ArrowRight, Check, SlidersHorizontal, X } from 'lucide-react';
import { labels } from './profile.js';
import './profile-summary-popover.css';

export default function ProfileSummaryPopover({ summary, disabled, context, onEdit }) {
  const id = useId();
  const trigger = useRef(null);
  const panel = useRef(null);
  const closeButton = useRef(null);
  const pinned = useRef(false);
  const leaveTimer = useRef(null);
  const [open, setOpen] = useState(false);
  const allTypes = !summary.hardFilters.length || Object.values(labels).every(label => summary.hardFilters.includes(label));

  function cancelLeave() { clearTimeout(leaveTimer.current); }
  function close(restoreFocus = false) {
    cancelLeave();
    pinned.current = false;
    panel.current?.hidePopover();
    setOpen(false);
    if (restoreFocus) trigger.current?.focus({ preventScroll: true });
  }
  function show() {
    cancelLeave();
    if (disabled) return;
    panel.current?.showPopover();
    setOpen(true);
  }
  function leave() {
    cancelLeave();
    leaveTimer.current = setTimeout(() => {
      if (!pinned.current && !panel.current?.contains(document.activeElement)) close();
    }, 220);
  }
  function onBlur(event) {
    if (event.relatedTarget && !panel.current?.contains(event.relatedTarget) && event.relatedTarget !== trigger.current) close();
  }

  useEffect(() => { close(); }, [context, disabled]);
  useEffect(() => () => clearTimeout(leaveTimer.current), []);

  useLayoutEffect(() => {
    if (!open) return;
    const anchor = trigger.current;
    const popup = panel.current;
    function position(event) {
      if (event?.type === 'scroll' && event.target instanceof Node && popup.contains(event.target)) return;
      if (!anchor.getClientRects().length) { close(); return; }
      const viewport = window.visualViewport;
      const x = viewport?.offsetLeft || 0;
      const y = viewport?.offsetTop || 0;
      const width = viewport?.width || window.innerWidth;
      const height = viewport?.height || window.innerHeight;
      const rect = anchor.getBoundingClientRect();
      if (rect.bottom < y || rect.top > y + height) { close(); return; }
      const below = y + height - rect.bottom - 20;
      const above = rect.top - y - 20;
      const placeAbove = below < 280 && above > below;
      popup.style.width = `${Math.min(360, width - 24)}px`;
      popup.style.maxHeight = `${Math.max(0, Math.min(480, height - 24, Math.max(180, placeAbove ? above : below)))}px`;
      const size = popup.getBoundingClientRect();
      popup.style.left = `${Math.max(x + 12, Math.min(rect.right - size.width, x + width - size.width - 12))}px`;
      popup.style.top = `${Math.max(y + 12, Math.min(placeAbove ? rect.top - size.height - 8 : rect.bottom + 8, y + height - size.height - 12))}px`;
    }
    position();
    const observer = new ResizeObserver(() => position());
    observer.observe(anchor.parentElement);
    observer.observe(popup);
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    window.visualViewport?.addEventListener('resize', position);
    window.visualViewport?.addEventListener('scroll', position);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', position);
      window.removeEventListener('scroll', position, true);
      window.visualViewport?.removeEventListener('resize', position);
      window.visualViewport?.removeEventListener('scroll', position);
    };
  }, [open]);

  return <>
    <button ref={trigger} type="button" className="profile-summary-trigger" disabled={disabled}
      aria-label="Filter und Wünsche anzeigen" aria-haspopup="dialog" aria-expanded={open} aria-controls={id}
      onPointerEnter={event => { if (event.pointerType === 'mouse' && window.matchMedia('(hover: hover)').matches) show(); }}
      onPointerLeave={leave} onBlur={onBlur}
      onKeyDown={event => { if (event.key === 'Escape' && open) { event.preventDefault(); close(true); } }}
      onClick={event => {
        if (pinned.current) { close(true); return; }
        show(); pinned.current = true;
        if (event.detail === 0) closeButton.current?.focus({ preventScroll: true });
      }}>
      <SlidersHorizontal size={19} aria-hidden="true" /><span>Filter</span>
    </button>
    <div ref={panel} id={id} popover="auto" className="profile-summary-popover" role="dialog" aria-labelledby={`${id}-title`}
      onToggle={() => {
        const shown = panel.current?.matches(':popover-open') || false;
        setOpen(shown);
        if (!shown) { pinned.current = false; cancelLeave(); }
      }}
      onPointerEnter={cancelLeave} onPointerLeave={leave} onBlurCapture={onBlur}
      onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); close(true); } }}>
      <div className="profile-summary-popover-heading">
        <h2 id={`${id}-title`}>Filter & Wünsche</h2>
        <button ref={closeButton} type="button" className="profile-summary-close" aria-label="Übersicht schließen" onClick={() => close(true)}><X size={18} aria-hidden="true" /></button>
      </div>
      <div className="profile-summary-popover-content">
        <section><h3>Stellenart <span>Feste Einschränkung</span></h3>
          <p className="profile-summary-types">{allTypes ? 'Alle Stellenarten' : summary.hardFilters.join(' · ')}</p>
        </section>
        <section><h3>Wünsche <span>Für die KI-Bewertung</span></h3>
          {summary.wishes.length ? <ul>{summary.wishes.map((wish, index) => <li key={`${wish}-${index}`}>{wish}</li>)}</ul> : <p>Keine zusätzlichen Wünsche angegeben.</p>}
        </section>
        {summary.hasExperience && <p className="profile-summary-experience"><Check size={15} aria-hidden="true" />Erfahrungskontext hinterlegt</p>}
      </div>
      <div className="profile-summary-popover-footer"><button type="button" onClick={() => { close(); onEdit(); }} disabled={disabled}>Suchprofil bearbeiten<ArrowRight size={16} aria-hidden="true" /></button></div>
    </div>
  </>;
}
