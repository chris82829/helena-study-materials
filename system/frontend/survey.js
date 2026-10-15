import {consentHeaders} from './privacy.js';
import definition from '../survey_definition_v14.json' with { type: 'json' };
import definitionV9 from '../survey_definition_v9.json' with { type: 'json' };
import definitionV8 from '../survey_definition_v8.json' with { type: 'json' };
import definitionV7 from '../survey_definition.json' with { type: 'json' };
import definitionV6 from '../survey_definition_v6.json' with { type: 'json' };
import definitionV5 from '../survey_definition_v5.json' with { type: 'json' };
import definitionV4 from '../survey_definition_v4.json' with { type: 'json' };

export const SURVEY_VERSION = definition.version;
export const SURVEY_STORAGE_KEY = `helena-survey:${SURVEY_VERSION}`;
const definitions = Object.fromEntries([definition, definitionV9, definitionV8, definitionV7, definitionV6, definitionV5, definitionV4].map(value => [value.version, value]));
const waitingNames = ['search_goal', 'personality_customized', 'template_selection_ease', 'personality_setup'];
const configurations = Object.fromEntries(Object.entries(definitions).map(([version, value]) => {
  const demographics = {...value.demographics, fields:value.demographics.fields.filter(field=>!field.systemProvided)};
  const surveyCategories = value.categories;
  const surveyFields = [value.demographics, ...surveyCategories].flatMap(group=>group.fields);
  const beforeSystemFields=demographics.fields.filter(field=>field.beforeSystem);
  const versionWaitingNames=['helena-v9','helena-v10','helena-v14'].includes(version)?['search_goal']:waitingNames;
  const waitingQuestionFields = versionWaitingNames.map(name=>surveyFields.find(field=>field.name===name)).filter(Boolean);
  return [version, {beforeSystemFields, demographics, surveyCategories, surveyFields, surveyScale:value.scale,
    surveyStages:['system', 'demographics', ...surveyCategories.map(group=>group.id)],
    waitingQuestionFields, waitingQuestionGroups:[demographics, {id:'setup', title:'Weitere Fragen', fields:waitingQuestionFields}]}];
}));
export function surveyConfiguration(version = SURVEY_VERSION) {
  return configurations[typeof version==='object'?version.version:version] || configurations[SURVEY_VERSION];
}
export const {demographics, surveyCategories, surveyFields, surveyScale, surveyStages, waitingQuestionFields, waitingQuestionGroups} = surveyConfiguration();

export function suggestSearchGoal(state, suggestion) {
  if (typeof suggestion !== 'string' || !suggestion.trim() || suggestion.length > 1000 || state.submitted) return state;
  const text = suggestion.trim();
  return { ...state, searchGoalSuggestion: text,
    answers: state.searchGoalEdited || (state.searchGoalEdited === undefined && state.answers.search_goal)
      ? state.answers : { ...state.answers, search_goal: text } };
}

export function emptyAnswers(version = SURVEY_VERSION) {
  return Object.fromEntries(surveyConfiguration(version).surveyFields.map(field => [field.name, field.kind === 'scale' ? null : '']));
}

export function fieldVisible(field, answers) {
  const condition=field.visibleIf;
  return !condition || (condition.in ? condition.in.includes(answers[condition.field]) : answers[condition.field]===condition.equals);
}

export function visibleFields(fields, answers) {
  return fields.filter(field => fieldVisible(field, answers));
}

export function changeSurveyAnswer(answers, name, value, version = SURVEY_VERSION) {
  const next = { ...answers, [name]: value };
  for (const field of surveyConfiguration(version).surveyFields) if (!fieldVisible(field, next)) next[field.name] = null;
  return next;
}

export function surveyErrors(answers, fields = surveyFields) {
  const errors = {};
  for (const field of visibleFields(fields, answers)) {
    const value = answers[field.name];
    if (field.kind === 'scale') {
      if ((!Number.isInteger(value) || value < (field.scale?.min || 1) || value > (field.scale?.max || 7)) && !field.nonresponse?.some(([code]) => code === value)) errors[field.name] = 'Bitte wähle eine Bewertung oder eine der Antworten darunter.';
    } else if (field.kind === 'choice') {
      if (!field.options.some(([option]) => option === value)) errors[field.name] = 'Bitte wähle eine Antwort.';
    } else if (typeof value !== 'string' || value.length > field.maxLength || (!field.optional && value.trim().length < (field.minLength || 1))) {
      errors[field.name] = typeof value === 'string' && value.length > field.maxLength
        ? `Bitte verwende höchstens ${field.maxLength} Zeichen.` : 'Bitte beschreibe dein Suchvorhaben kurz.';
    }
  }
  return errors;
}

export function reviseSurvey(state, changes) {
  return {...state,...changes,draftRevision:Math.max(Date.now(),(state.draftRevision || 0)+1)};
}

export function waitingFieldDone(state, field) {
  return (state.waitingAnswered || []).includes(field.name)
    && !Object.keys(surveyErrors(state.answers,[field])).length;
}

export function remainingWaitingGroups(state) {
  return surveyConfiguration(state).waitingQuestionGroups.map(group=>({...group,fields:group.fields.filter(field=>fieldVisible(field,state.answers) && !waitingFieldDone(state,field))})).filter(group=>group.fields.length);
}

export function markWaitingFields(state, fields) {
  const valid=fields.filter(field=>fieldVisible(field,state.answers) && !Object.keys(surveyErrors(state.answers,[field])).length).map(field=>field.name);
  return reviseSurvey(state,{...(valid.includes('search_goal')?{searchGoalEdited:true}:{}),waitingAnswered:[...new Set([...(state.waitingAnswered || []),...valid])]});
}

export function finishWaitingIfReady(state) {
  const [demographicGroup,setupGroup]=surveyConfiguration(state).waitingQuestionGroups;
  if(demographicGroup.fields.every(field=>waitingFieldDone(state,field))
      && !Object.keys(surveyErrors(state.answers,setupGroup.fields)).length) {
    return markWaitingFields(state,setupGroup.fields);
  }
  return state;
}

export function displaySurveyGroup(state, stage=state.stage) {
  const group=stageGroup(stage,state.version);
  return group ? {...group,fields:group.fields.filter(field=>fieldVisible(field,state.answers) && !waitingFieldDone(state,field))} : null;
}

export function stageGroup(stage, version = SURVEY_VERSION) {
  const {demographics,surveyCategories}=surveyConfiguration(version);
  return stage === 'demographics' ? demographics : surveyCategories.find(group => group.id === stage);
}

// Every next page requires preceding inputs from the assigned questionnaire.
export function reachableStage(state, target = state.stage) {
  const {surveyStages,demographics,surveyCategories}=surveyConfiguration(state);
  if (!surveyStages.includes(target)) return 'system';
  if (!state.systemOpened || state.systemCompleted !== true || state.chatCompleted !== true || target === 'system') return 'system';
  if (target === 'demographics') return target;
  if (Object.keys(surveyErrors(state.answers, demographics.fields)).length) return 'demographics';
  const index = surveyCategories.findIndex(group => group.id === target);
  for (const group of surveyCategories.slice(0, index)) {
    if (Object.keys(surveyErrors(state.answers, group.fields)).length) return group.id;
  }
  return target;
}

export function nextSurveyState(state) {
  const {surveyStages}=surveyConfiguration(state);
  const index = surveyStages.indexOf(state.stage);
  if (index < 0 || index === surveyStages.length - 1) return state;
  if (state.stage === 'system' && (state.systemCompleted !== true || state.chatCompleted !== true)) return state;
  const group = stageGroup(state.stage,state.version);
  if (group && Object.keys(surveyErrors(state.answers, group.fields)).length) return state;
  let nextIndex=index+1;
  while(nextIndex<surveyStages.length-1 && !displaySurveyGroup(state,surveyStages[nextIndex]).fields.length)nextIndex++;
  const next = { ...state, systemOpened: true, stage: surveyStages[nextIndex] };
  return { ...next, stage: reachableStage(next) };
}

export function newSurveyState(cryptoSource = globalThis.crypto) {
  const token = () => Array.from(cryptoSource.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
  return { version: SURVEY_VERSION, submissionId: token(), runId: token(), stage: 'system', systemTaskStarted: false, systemOpened: true, systemCompleted: false, chatCompleted: false, submitted: false, draftRevision:0, waitingAnswered:[], searchGoalSuggestion: '', searchGoalEdited: false, answers: emptyAnswers() };
}

function sanitizeAnswers(source,version) {
  const answers=emptyAnswers(version), fields=surveyConfiguration(version).surveyFields;
  for(const field of fields) {
    const value=source?.[field.name];
    if(field.kind==='text' && typeof value==='string' && value.length<=field.maxLength
        || !Object.keys(surveyErrors({...source,[field.name]:value},[field])).length)answers[field.name]=value;
  }
  for(const field of fields)if(!fieldVisible(field,answers))answers[field.name]=null;
  return answers;
}

export function loadSurveyState(storage, fresh = newSurveyState) {
  try {
    const keys=[SURVEY_STORAGE_KEY,...Object.keys(definitions).filter(version=>version!==SURVEY_VERSION).map(version=>`helena-survey:${version}`),'helena-survey:helena-v3','helena-survey:helena-v2'];
    const raw=keys.map(key=>storage.getItem(key)).find(Boolean);
    const state=JSON.parse(raw || 'null');
    if ((definitions[state?.version] || ['helena-v2','helena-v3'].includes(state?.version)) && /^[a-f0-9]{32}$/.test(state.submissionId)
        && /^[a-f0-9]{32}$/.test(state.runId) && typeof state.submitted==='boolean' && typeof state.systemOpened==='boolean') {
      if(state.submitted && state.version!==SURVEY_VERSION)return state;
      if(!definitions[state.version]) {
        const answers=emptyAnswers();
        for(const name of [...demographics.fields.map(field=>field.name),'search_goal'])if(state.answers?.[name]!==undefined)answers[name]=state.answers[name];
        return {...state,version:SURVEY_VERSION,answers:sanitizeAnswers(answers,SURVEY_VERSION),stage:'system',systemOpened:true,systemCompleted:false,chatCompleted:false,
          runId:newSurveyState().runId,waitingAnswered:[],draftRevision:Math.max(Date.now(),(state.draftRevision || 0)+1)};
      }
      const version=state.version;
      const {surveyStages,waitingQuestionGroups,surveyFields}=surveyConfiguration(version);
      if(!surveyStages.includes(state.stage))return fresh();
      const answers=sanitizeAnswers(state.answers,version);
      const restored={...state,version,answers,systemOpened:true,systemCompleted:state.systemCompleted===true,chatCompleted:state.chatCompleted===true,
        submitted:state.submitted && !Object.keys(surveyErrors(answers,surveyFields)).length,
        draftRevision:Number.isSafeInteger(state.draftRevision) && state.draftRevision>0?state.draftRevision:0,
        waitingAnswered:Array.isArray(state.waitingAnswered)?[...new Set(state.waitingAnswered)].filter(name=>waitingQuestionGroups.some(group=>group.fields.some(field=>field.name===name))):[],
        searchGoalSuggestion:typeof state.searchGoalSuggestion==='string' && state.searchGoalSuggestion.length<=1000?state.searchGoalSuggestion:'',
        searchGoalEdited:typeof state.searchGoalEdited==='boolean'?state.searchGoalEdited:Boolean(answers.search_goal)};
      return {...restored,stage:reachableStage(restored)};
    }
  } catch { /* Draft storage is optional. */ }
  return fresh();
}

export function saveSurveyState(storage, state) {
  try { storage.setItem(SURVEY_STORAGE_KEY, JSON.stringify(state)); } catch { /* The form still works in memory. */ }
}

export async function submitSurvey(state, { request = globalThis.fetch, signal } = {}) {
  const {surveyFields}=surveyConfiguration(state);
  if (state.systemCompleted !== true) throw new Error('Bitte schließe zuerst die erste Suche mit HELENA ab.');
  if (state.chatCompleted !== true) throw new Error('Bitte sende zuerst eine eigene Nachricht im HELENA-Chat.');
  if (Object.keys(surveyErrors(state.answers,surveyFields)).length) throw new Error('Bitte prüfe deine Antworten.');
  const response = await request('/api/survey-responses', {
    method: 'POST', signal, headers: { ...consentHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ submission_id: state.submissionId, version: state.version,
      ...Object.fromEntries(surveyFields.map(field => [field.name, fieldVisible(field, state.answers) ? state.answers[field.name] : null])) }),
  });
  if (response.status === 409) throw new Error('Für diese Teilnahme wurden bereits Antworten gespeichert. Deine nachträglichen Änderungen wurden nicht übernommen.');
  if (!response.ok) throw new Error('Deine Antworten konnten nicht gespeichert werden. Bitte versuche es erneut.');
  let data;
  try { data = await response.json(); } catch { /* An invalid response is never a confirmation. */ }
  if (data?.saved !== true) throw new Error('Die Speicherbestätigung fehlt. Bitte versuche es erneut.');
}

export function restoreServerDraft(previous,draft) {
  if(draft.completed)return {...previous,submitted:true};
  if(!definitions[draft.version])return previous;
  if(draft.version===previous.version && draft.revision<=(previous.draftRevision || 0))return previous;
  const restored={...previous,version:draft.version,answers:sanitizeAnswers(draft.answers,draft.version),draftRevision:draft.revision,waitingAnswered:draft.waiting_answered || [],searchGoalEdited:true};
  return {...restored,stage:reachableStage(restored)};
}

export function applyStudyAssignment(state,assignment) {
  if(!['A','B','C'].includes(assignment?.arm))throw new Error('Studienzuordnung konnte nicht geladen werden.');
  let version=assignment.questionnaire_version || (assignment.experiment_id==='helena-abc-v2'?'helena-v9':assignment.experiment_id==='helena-abc-v1'?'helena-v8':assignment.experiment_id?.startsWith('helena-ab-')?'helena-v7':SURVEY_VERSION);
  // Some historical B/C participants already moved to v7 before the ABC study.
  if(assignment.experiment_id==='helena-bc-v1' && state.version==='helena-v7')version='helena-v7';
  if(!definitions[version])throw new Error('Diese Fragebogenversion ist nicht verfügbar.');
  let next=state;
  if(version!==state.version) {
    const answers=emptyAnswers(version);
    for(const name of [...demographics.fields.map(field=>field.name),'search_goal'])if(state.answers[name]!==undefined)answers[name]=state.answers[name];
    next={...state,version,answers,stage:'system',systemTaskStarted:false,systemCompleted:false,chatCompleted:false,runId:newSurveyState().runId,waitingAnswered:(state.waitingAnswered || []).filter(name=>[...demographics.fields.map(field=>field.name),'search_goal'].includes(name))};
  }
  const arm=version==='helena-v6' && assignment.experiment_id==='helena-bc-v1'?({A:'B',B:'C'}[assignment.arm] || assignment.arm):assignment.arm;
  const answers=changeSurveyAnswer(next.answers,'study_arm',arm,version);
  return reviseSurvey(next,{answers,assignment});
}

// The same preparation precedes the current conference-study system in every arm.
export function needsSystemPreparation(state) {
  const fields=surveyConfiguration(state).beforeSystemFields;
  const startedOnServer=fields.length>0 && fields.every(field=>waitingFieldDone(state,field));
  return ['helena-v9','helena-v10','helena-v14'].includes(state.version) && !state.systemTaskStarted && !startedOnServer && !state.systemCompleted && !state.submitted;
}
export function startPreparedSystem(state) {
  const fields=surveyConfiguration(state).beforeSystemFields;
  if(Object.keys(surveyErrors(state.answers,fields)).length)return state;
  return reviseSurvey(markWaitingFields(state,fields),{systemTaskStarted:true});
}
