import React, { useEffect, useId, useRef } from 'react';
import { ArrowDown, ArrowDownWideNarrow, ArrowRight, Compass, MessagesSquare, X } from 'lucide-react';
import './personality-intro.css';

export default function PersonalityIntroDialog({ open, onboarding = false, onContinue, onClose, allowCustom = true }) {
  const dialog = useRef(null);
  const heading = useRef(null);
  const id = useId();
  useEffect(() => {
    const element = dialog.current;
    if (open && !element.open) {
      element.showModal();
      heading.current?.focus({ preventScroll: true });
    } else if (!open && element.open) element.close();
    return () => { if (element.open) element.close(); };
  }, [open]);
  function closeThen(callback) {
    dialog.current?.close();
    callback?.();
  }
  return <dialog ref={dialog} className="personality-intro-dialog" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} onCancel={event => { event.preventDefault(); closeThen(onClose); }}>
    <button type="button" className="personality-intro-close" aria-label="Erklärung schließen" onClick={() => closeThen(onClose)}><X size={19} aria-hidden="true" /></button>
    <h2 ref={heading} id={`${id}-title`} tabIndex={-1}>KI-Suchpersönlichkeit</h2>
    <p id={`${id}-description`} className="personality-intro-description">Dein Profil beschreibt, was zu dir passt. Deine KI-Persönlichkeit ergänzt den Blick auf die Stellen und gestaltet euer Gespräch. Die fachliche Passung zählt weiterhin am stärksten. {allowCustom ? 'Wähle den Top-Berufsberater, einen Experten für dein Fachgebiet oder gestalte deine KI selbst.' : 'Wähle den Top-Berufsberater oder einen Experten für dein Fachgebiet. Beide haben feste Beratungseigenschaften.'}</p>
    <div className="personality-flow">
      <div className="personality-flow-source"><Compass size={22} aria-hidden="true" /><span>KI-Suchpersönlichkeit</span></div>
      <div className="personality-flow-branches" aria-hidden="true"><ArrowDown size={19} /><ArrowDown size={19} /></div>
      <div className="personality-effects">
      <section className="personality-effect personality-effect-search">
        <span className="personality-effect-icon"><ArrowDownWideNarrow size={22} aria-hidden="true" /></span>
        <div><h3>Jobs bewerten & sortieren</h3><p>Dein Nutzerprofil und deine KI-Persönlichkeit bestimmen gemeinsam die Bewertung und Reihenfolge der Jobs.</p></div>
      </section>
      <section className="personality-effect personality-effect-chat">
        <span className="personality-effect-icon"><MessagesSquare size={22} aria-hidden="true" /></span>
        <div><h3>Mit dir sprechen</h3><p>Die gewählte Persönlichkeit bestimmt, wie die KI antwortet und ihre Empfehlungen erklärt.</p></div>
      </section>
      </div>
    </div>
    <button type="button" className={`personality-intro-continue${onboarding ? ' helena-action-motion' : ''}`} onClick={() => closeThen(onContinue)}>{onboarding ? (allowCustom ? 'Persönlichkeit gestalten' : 'Vorlage auswählen') : 'Verstanden'}<ArrowRight className="helena-action-arrow" size={17} aria-hidden="true" /></button>
  </dialog>;
}
