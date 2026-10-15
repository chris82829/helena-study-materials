import {consentHeaders} from './privacy.js';
import {fieldVisible, surveyConfiguration} from './survey.js';

export function draftPayload(state) {
  const {surveyFields}=surveyConfiguration(state);
  return {submission_id:state.submissionId, version:state.version, revision:state.draftRevision,
    waiting_answered:state.waitingAnswered || [],
    answers:Object.fromEntries(surveyFields.map(field=>{
      const value=state.answers[field.name];
      return [field.name,!fieldVisible(field,state.answers) || value===undefined || (field.kind!=='text' && value==='') ? null : value];
    }))};
}

// One request at a time; retries keep the same revision. A newer snapshot always
// includes the earlier answers and supersedes a queued obsolete snapshot.
export function createSurveyAutosave({request=globalThis.fetch,onStatus=()=>{},onCompleted=()=>{}}={}) {
  let latest=null, running=null, acknowledged=0;
  function enqueue(state) {
    if(state.submitted || !state.draftRevision || state.draftRevision<=acknowledged)return;
    if(!latest || state.draftRevision>latest.revision)latest=draftPayload(state);
    onStatus('pending');
  }
  async function pump() {
    while(latest && latest.revision>acknowledged) {
      const payload=latest, controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),20000);
      onStatus('saving');
      try {
        const response=await request('/api/survey-drafts',{method:'PUT',keepalive:true,signal:controller.signal,
          headers:{...consentHeaders(),'Content-Type':'application/json'},body:JSON.stringify(payload)});
        if(!response.ok)throw new Error(response.status===409?'Ein neuerer Antwortstand ist gespeichert. Bitte lade die Seite neu.':'Speichern fehlgeschlagen. Deine Eingaben bleiben hier erhalten.');
        const result=await response.json();
        if(result.saved!==true || result.revision!==payload.revision)throw new Error('Die Speicherbestätigung fehlt.');
        acknowledged=payload.revision;
        if(result.completed===true){latest=null;onCompleted();break;}
      } catch(error) {onStatus('error',error.message);throw error;}
      finally {clearTimeout(timeout);}
    }
    onStatus('saved');
  }
  function flush() {
    if(!running)running=pump().finally(()=>{running=null;});
    return running;
  }
  return {enqueue,flush};
}
