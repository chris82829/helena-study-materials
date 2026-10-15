import React, {useRef, useState} from 'react';
import {copyParticipationId, deletionEmail} from './participation-actions.js';

export default function ParticipationId({value}) {
  const [message,setMessage]=useState('');
  const section=useRef(null), id=useRef(null);
  if(!value)return null;
  async function copy(){
    if(await copyParticipationId(value,section.current)) {setMessage('ID kopiert.');return;}
    const range=document.createRange();range.selectNodeContents(id.current);
    const selection=window.getSelection();selection?.removeAllRanges();selection?.addRange(range);
    setMessage('Automatisches Kopieren ist in diesem Browser nicht möglich. Die ID ist markiert – bitte wähle „Kopieren“ oder drücke Strg+C / ⌘C.');
  }
  const email=deletionEmail(value);
  return <section ref={section} className="participation-id" aria-label="Deine Teilnahme-ID"><strong>Deine Teilnahme-ID</strong><code ref={id}>{value}</code><p>Bitte bewahre diese ID auf. Wenn du deine Daten löschen lassen möchtest, schicke sie an <a href={email}>study@example.org</a>.</p><div><button type="button" onClick={copy}>ID kopieren</button><a href={email}>Löschung per E-Mail anfragen</a></div>{message && <p role="status">{message}</p>}</section>;
}
