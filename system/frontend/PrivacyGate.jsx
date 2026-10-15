import React, {useEffect, useState} from 'react';
import {ShieldCheck, ArrowRight} from 'lucide-react';
import {clearParticipation, consentToken, privacyRequest, rememberConsent} from './privacy.js';
import './privacy.css';
import {consentPurpose, standaloneArm} from './test-access.js';
import ParticipationId from './ParticipationId.jsx';

export function PrivacyNotice({notice}) {
  return <div className="privacy-notice">{notice.sections.map(([title,text]) => <section key={title}><h2>{title}</h2><p>{text}</p></section>)}<p><a href={notice.imprint} target="_blank" rel="noopener noreferrer">Impressum der Hochschuljobbörse</a> · <a href="https://example.org/datenschutz/" target="_blank" rel="noopener noreferrer">Datenschutzkontakt der Hochschule</a></p></div>;
}

export default function PrivacyGate({children, informationOnly = false, initialStatus = null}) {
  const testArm = standaloneArm();
  const [status,setStatus]=useState(initialStatus);
  const [checked,setChecked]=useState(false);
  const [showInfo,setShowInfo]=useState(informationOnly);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [withdrawn,setWithdrawn]=useState(false);
  const [requestToken]=useState(()=>consentToken() || Array.from(crypto.getRandomValues(new Uint8Array(32)),b=>b.toString(16).padStart(2,'0')).join(''));
  const embedded = typeof window !== 'undefined' && window.parent !== window;
  useEffect(()=>{setChecked(false);},[status?.notice.version]);
  useEffect(()=> {
    let live=true;
    privacyRequest().then(data=>{if(live)setStatus(data);}).catch(()=>{if(live)setError('Die Datenschutzhinweise konnten nicht geladen werden. Bitte lade die Seite neu.');});
    return ()=>{live=false;};
  },[]);
  useEffect(()=>{
    if(status?.active || withdrawn)return;
    let live=true;
    const refresh=()=>{privacyRequest().then(data=>{if(live)setStatus(data);}).catch(()=>{});};
    window.addEventListener('focus',refresh);
    const timer=window.setInterval(refresh,15000);
    return()=>{live=false;window.removeEventListener('focus',refresh);window.clearInterval(timer);};
  },[status?.active,withdrawn]);
  async function accept(event) {
    event.preventDefault();
    if (!checked || !status?.notice.ready || busy) return;
    setBusy(true);setError('');
    try {
      try { window.sessionStorage.setItem('helena-storage-check', '1'); window.sessionStorage.removeItem('helena-storage-check'); }
      catch { throw new Error('Für die Teilnahme muss der Sitzungsspeicher im Browser verfügbar sein. Bitte erlaube ihn und versuche es erneut.'); }
      const result=await privacyRequest('/consent',{method:'POST',body:JSON.stringify({token:requestToken,version:status.notice.version,accepted:true,purpose:consentPurpose()})});
      if(result.accepted!==true || result.version!==status.notice.version) throw new Error('Die Bestätigung fehlt. Bitte versuche es erneut.');
      rememberConsent(requestToken);
      setStatus({...status,active:true,receipt:result.receipt});setShowInfo(false);
    } catch(failure){setError(failure.message);} finally{setBusy(false);}
  }
  async function withdraw() {
    if(busy)return;
    setBusy(true);setError('');
    try {
      const result=await privacyRequest('/consent',{method:'DELETE'});
      if(result.withdrawn!==true)throw new Error('Die Bestätigung fehlt. Bitte versuche es erneut.');
      clearParticipation();setStatus({...status,active:false});setWithdrawn(true);setChecked(false);
    } catch(failure){setError(failure.message);} finally{setBusy(false);}
  }
  const appContent = status?.active && !informationOnly ? <div hidden={showInfo} className={embedded?'':'privacy-app-shell'}><div className="privacy-app-content">{React.isValidElement(children) ? React.cloneElement(children,{participationId:status.receipt?.participation_id}) : children}</div>{!embedded && <footer className="privacy-bar"><button type="button" onClick={()=>setShowInfo(true)}>{testArm ? 'Datenschutz & Widerruf' : 'Teilnahme-ID & Datenschutz'}</button><a href={status.notice.imprint} target="_blank" rel="noopener noreferrer">Impressum</a></footer>}</div> : null;
  return <>{appContent}<main hidden={status?.active && !showInfo && !informationOnly} className="privacy-page"><div className="privacy-card"><span className="privacy-icon"><ShieldCheck size={26}/></span><h1>{withdrawn?'Teilnahme beendet':status?.notice.title || 'Datenschutz'}</h1>
    {error && <p className="privacy-error" role="alert">{error}</p>}
    {!status && !error && <p role="status">Hinweise werden geladen …</p>}
    {withdrawn ? <><p>Deine Einwilligung wurde widerrufen. Die zugehörigen Antworten und Suchsitzungen wurden aus dem aktiven System entfernt. Für bereits erstellte Exporte oder Sicherungen kontaktiere bitte die Studienleitung.</p><a href="/">Zur Vorstellung</a></> : status && <>
      {!status.notice.ready && <p className="privacy-pending" role="status">{status.study?.closed?'Die Studie ist beendet.':'Die Umfrage ist derzeit pausiert. Bitte versuche es später erneut.'}</p>}
      <p className="privacy-lead">{testArm ? `Du testest Variante ${testArm} außerhalb der Umfrage. Es werden keine Umfrageantworten erfasst.` : 'Die Teilnahme ist freiwillig. Du kannst deine Einwilligung jederzeit widerrufen.'}</p>
      <ParticipationId value={status.receipt?.participation_id}/>
      {(informationOnly || (status.active && showInfo)) && <PrivacyNotice notice={status.notice}/>}
      {status.active ? <div className="privacy-controls"><button type="button" onClick={()=>setShowInfo(false)} disabled={busy || informationOnly}>{testArm ? 'Zurück zum Test' : 'Zurück zur Teilnahme'}</button><button type="button" className="privacy-withdraw" onClick={withdraw} disabled={busy}>{busy?'Wird beendet …':'Einwilligung widerrufen & Daten löschen'}</button></div> : !informationOnly && <form onSubmit={accept} className="privacy-consent"><label><input type="checkbox" checked={checked} onChange={event=>setChecked(event.target.checked)} required disabled={!status.notice.ready || busy}/><span>{status.notice.consent_text}</span></label><div className="privacy-controls"><div className="privacy-secondary-links"><a href="/">Nicht teilnehmen</a><a href={testArm ? `/test/${testArm.toLowerCase()}/datenschutz` : "/datenschutz"} target="_blank" rel="noopener noreferrer">Datenschutzhinweise lesen</a></div><button className="privacy-accept" type="submit" disabled={!checked || !status.notice.ready || busy}>{busy?'Wird bestätigt …':'Einwilligen und starten'}<ArrowRight size={18}/></button></div></form>}
      {informationOnly && <a href="/">Zur Vorstellung</a>}
    </>}
  </div></main></>;
}
