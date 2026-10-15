import React, { useEffect, useRef } from 'react';
import { ArrowRight } from 'lucide-react';
import portrait from './assets/anonymous-researcher.svg';
import './about-landing.css';
import './action-motion.css';
import './privacy.css';

// Research/bio: supplied presentation, slides 1, 11, 12.
// Contact: https://example.org
// Institute/address: official IFAI team and contact page (see README).
export default function AboutPage() {
  const heading = useRef(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, []);
  return <main className="about-page about-landing">
    <div className="about-content">
      <div className="about-landing-intro">
      <section className="about-project" aria-labelledby="about-title">
        <span className="eyebrow">DAS FORSCHUNGSPROJEKT</span>
        <h1 id="about-title" ref={heading} tabIndex={-1}>Das Forschungsprojekt HELENA</h1>
        <p>HELENA erforscht, wie sich Such- und Empfehlungssysteme an die Ziele, Fähigkeiten und Wünsche einzelner Menschen anpassen lassen.</p>
        <p>Das Promotionsvorhaben verbindet die Erfassung persönlicher Angaben mit einem anpassbaren Matching und verständlichen Ergebnissen. Am Beispiel der Jobsuche untersucht es, wie diese Bereiche zusammenwirken und wie Nutzerinnen und Nutzer Empfehlungen im Dialog nachvollziehen und mitgestalten können.</p>
      </section>
      <div className="about-launch">
        <a href="/umfrage" className="about-start-link helena-action-motion"><span>Umfrage starten</span><span className="about-start-arrow helena-action-arrow" aria-hidden="true"><ArrowRight size={23} /></span></a>
      </div>
      </div>
      <section className="about-person" aria-labelledby="researcher-name">
        <img className="researcher-portrait" src={portrait} alt="Studienleitung" width="1122" height="1402" />
        <div className="researcher-copy">
          <span className="eyebrow">DER FORSCHER DAHINTER</span>
          <h2 id="researcher-name">Studienleitung <span>M. Sc.</span></h2>
          <p>Die Angaben zur Studienleitung sind für die Begutachtung anonymisiert. Mein Forschungsschwerpunkt ist die Verbindung von Matching und natürlicher Sprachverarbeitung. Mit HELENA führe ich meine Forschung zum Abgleich von Lebensläufen und Stellenanzeigen fort.</p>
          <address className="researcher-contact">
            <a href="mailto:study@example.org">study@example.org</a>
            <span>Forschungseinrichtung</span>
            <span>[Kontaktadresse]</span>
            <span>Sprechzeiten nach E-Mail-Vereinbarung</span>
          </address>
        </div>
      </section>
      <footer className="about-legal"><a href="/datenschutz">Datenschutz</a><a href="https://example.org/impressum" target="_blank" rel="noopener noreferrer">Impressum der Hochschuljobbörse</a></footer>
    </div>
  </main>;
}
