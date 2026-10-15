import React, { useEffect, useId, useRef } from 'react';
import { ArrowRight, BriefcaseBusiness, Search, Check, UserRound, ListChecks } from 'lucide-react';
import { searchStatus } from './search-progress.js';
import './search-loading.css';

export function SearchLoadingArt({stage}) {
  const id = useId();
  const Icon = stage === 'ranking' ? ListChecks : stage === 'finalizing' ? Check : Search;
  return <div className="search-matching-art" aria-hidden="true">
    <svg viewBox="0 0 320 140" fill="none">
      <defs><linearGradient id={`${id}-scan`} x1="0" y1="0" x2="1" y2="0"><stop stopColor="#c2d8ff" stopOpacity="0"/><stop offset=".5" stopColor="#8bb5ff"/><stop offset="1" stopColor="#c2d8ff" stopOpacity="0"/></linearGradient></defs>
      <ellipse cx="160" cy="67" rx="147" ry="60" fill="#f2f6ff"/>
      <path d="M98 68h124" stroke="#c9d8f4" strokeWidth="2" strokeDasharray="4 6" className="matching-flow"/>
      <g className="matching-profile"><rect x="30" y="24" width="72" height="88" rx="12" fill="white" stroke="#cbd9f1"/>
        <UserRound x="54" y="36" width="24" height="24" color="#5778bc"/>
        <path d="M46 75h40M46 84h30M46 93h35" stroke="#d1def2" strokeWidth="4" strokeLinecap="round"/>
      </g>
      <g className="matching-jobs"><rect x="224" y="20" width="64" height="83" rx="11" fill="#e0eafb" transform="rotate(8 256 61)"/>
        <rect x="215" y="25" width="65" height="84" rx="11" fill="white" stroke="#cbd9f1"/>
        <BriefcaseBusiness x="236" y="37" width="24" height="24" color="#5778bc"/>
        <path d="M230 75h35M230 84h26M230 93h31" stroke="#d1def2" strokeWidth="4" strokeLinecap="round"/>
        <rect className="matching-scan" x="221" y="35" width="53" height="5" rx="2.5" fill={`url(#${id}-scan)`}/>
      </g>
      <circle cx="159" cy="68" r="28" fill="white" stroke="#dbe5fa"/>
      <circle className="matching-orbit" cx="159" cy="68" r="28" stroke="#7597ef" strokeWidth="2" strokeDasharray="45 131"/>
      <Icon x="147" y="56" width="24" height="24" color="#3159d3"/>
      <text x="66" y="133" textAnchor="middle" fill="#61728d" fontSize="11">Dein Profil</text>
      <text x="248" y="133" textAnchor="middle" fill="#61728d" fontSize="11">Stellenanzeigen</text>
    </svg>
  </div>;
}

export default function SearchLoadingDialog({ open, assistantName = 'Dein KI-Assistent', onQuestions, progress }) {
  const dialog = useRef(null);
  const heading = useRef(null);
  const id = useId();
  const status = searchStatus(progress);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      element.showModal();
      heading.current?.focus({ preventScroll: true });
    } else if (!open && element.open) {
      element.close();
    }
    return () => { if (element.open) element.close(); };
  }, [open]);

  return <dialog ref={dialog} className="search-loading-dialog" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} onCancel={event => event.preventDefault()}>
    <h2 ref={heading} id={`${id}-title`} tabIndex={-1}><span className="search-loading-persona">{assistantName}</span>{' '}<span>sucht Jobs</span></h2>
    <SearchLoadingArt stage={progress?.stage}/>
    <span id={`${id}-description`} className="sr-only" role="status" aria-live="polite" aria-atomic="true">{status.title}. {status.description}</span>
    <ol className="search-phase-summary" aria-label="Suchfortschritt">
      {['Profil', 'Stellensuche', 'KI-Abgleich'].map((label, index) => {
        const current = status.index < 2 ? 0 : status.index === 2 ? 1 : 2;
        const done = index < current || progress?.stage === 'finalizing';
        return <li key={label} className={done ? 'is-done' : index === current ? 'is-active' : ''} aria-current={!done && index === current ? 'step' : undefined}>
          {done ? <Check size={13} aria-hidden="true"/> : <i aria-hidden="true"/>}{label}
        </li>;
      })}
    </ol>
    <p className="search-loading-time">Die Suche dauert etwa 1–2 Minuten.</p>
    {onQuestions && <button className="survey-primary helena-action-motion search-loading-questions" type="button" onClick={onQuestions}><span>Wartezeit für Fragen nutzen</span><ArrowRight className="helena-action-arrow" size={18}/></button>}
  </dialog>;
}
