import { labels, remoteLabels } from './profile.js';
import { MIN_MATCH_SCORE } from './score-visibility.js';

const normalize = value => String(value || '').normalize('NFKC').toLocaleLowerCase('de-DE').replace(/\s+/g, ' ').trim();
const short = (value, limit) => String(value || '').length > limit ? `${String(value).slice(0, limit - 1)}…` : String(value || '');
const unique = items => [...new Set(items || [])];
const sameOnly = (items, value) => unique(items).length === 1 && items[0] === value;

function mentionsTerm(text, term) {
  const needle = normalize(term);
  if (!needle) return false;
  // Punctuation is meaningful in C++, C# and similar skill names.
  let index = text.indexOf(needle);
  while (index !== -1) {
    const word = /[\p{L}\p{N}+#]/u;
    if (!word.test(text[index - 1] || '') && !word.test(text[index + needle.length] || '')) return true;
    index = text.indexOf(needle, index + 1);
  }
  return false;
}

function refersTo(text, job) {
  if (text.includes('job-id ')) return mentionsTerm(text, `job-id ${job.id}`);
  return !!job.title && !!job.company && text.includes(normalize(job.title)) && text.includes(normalize(job.company));
}

function jobReference(job) {
  return `„${short(job.title || 'Stellenangebot', 180)}“ bei ${short(job.company || 'diesem Unternehmen', 100)} (Job-ID ${job.id})`;
}

export function buildChatSuggestions(session, visibleJobs = [], { showScores = true } = {}) {
  if (!session?.profile) return [];
  visibleJobs = (Array.isArray(visibleJobs) ? visibleJobs : []).filter(job => job && typeof job === 'object');
  const profile = session.profile;
  const filters = profile.filters || {};
  const employment = filters.employment_types || [];
  const remote = filters.remote || [];
  const history = (session.messages || []).filter(entry => entry.role === 'user').slice(-8).map(entry => normalize(entry.content));
  const candidates = [];
  const add = (id, label, message, alreadyDiscussed) => {
    if (history.some(text => text === normalize(message) || text === normalize(label) || alreadyDiscussed?.(text))) return;
    if (!candidates.some(item => item.id === id)) candidates.push({ id, label: short(label, 90), message });
  };
  const addProfileQuestions = () => {
    add('profile:details', 'Welche Profilangaben helfen noch?', 'Welche konkreten Angaben fehlen in meinem Suchprofil, um die Passung besser beurteilen zu können?');
    if (!(profile.skills || []).length && !profile.cv_text) {
      add('profile:skills', 'Wie beschreibe ich meine Fähigkeiten?', 'Wie kann ich meine bisherigen Kenntnisse und Erfahrungen im Suchprofil konkret beschreiben?');
    }
    add('profile:directions', 'Welche Aufgaben passen zu meinem Profil?', 'Welche beruflichen Aufgaben passen zu meinen angegebenen Fähigkeiten und Zielen? Bitte begründe deine Einschätzung, ohne meine Suchkriterien zu ändern.');
  };

  if (!(session.jobs || []).length) {
    if (employment.length && employment.length < Object.keys(labels).length) add('relax:employment', 'Weitere Stellenarten einbeziehen', 'Bitte hebe nur den Filter für die Stellenart auf und suche erneut. Alle anderen Kriterien bleiben erhalten.');
    addProfileQuestions();
    return candidates.slice(0, 3);
  }

  if (!visibleJobs.length) {
    if (showScores) add('scores:explain', 'Warum sind die Scores niedrig?', 'Warum erreichen die bewerteten Stellen den Mindestscore nicht? Welche Anforderungen oder Profilangaben sind dafür ausschlaggebend?');
    addProfileQuestions();
    return candidates.slice(0, 3);
  }

  // Only reference cards currently visible to the user, with stable IDs instead
  // of positions that could change after a new ranking or a visibility toggle.
  const jobs = visibleJobs.filter(job => typeof job.id === 'string' && job.id.length <= 100);
  for (const job of jobs) {
    const before = candidates.length;
    add(`fit:${job.id}`, `Passung bei ${short(job.company || 'dieser Stelle', 44)} prüfen`,
      `Warum passt die Stelle ${jobReference(job)} zu meinem Profil? Nenne die wichtigsten Übereinstimmungen und möglichen Lücken.`,
      text => refersTo(text, job) && /warum|passung|passt|geeignet|übereinstimmung/.test(text));
    if (candidates.length > before) break;
  }

  // Only employment type excludes jobs. Other suggestions change wishes used
  // in assessment; they never discard jobs. The basic variant has no public scores,
  // so its suggestions describe available options without asserting a good match.
  const goodJobs = showScores ? visibleJobs.filter(job => Number.isInteger(job.match?.score) && job.match.score >= MIN_MATCH_SCORE && job.match.score <= 100) : visibleJobs;
  if (goodJobs.length) {
    const refinements = [];
    const propose = (...args) => refinements.push(args);
    const types = unique(goodJobs.flatMap(job => job.employment_types || []));
    for (const type of types) {
      if (!labels[type] || sameOnly(employment, type) || (employment.length && !employment.includes(type))) continue;
      propose(`filter:employment:${type}`, `Nur ${labels[type]}`, `Bitte zeige mir nur Stellen der Art „${labels[type]}“. Alle anderen Kriterien bleiben erhalten.`,
        text => text.includes('nur ') && mentionsTerm(text, labels[type]));
    }
    const workModels = unique(goodJobs.map(job => job.remote));
    for (const model of workModels) {
      if (!remoteLabels[model] || model === 'unknown' || sameOnly(remote, model) || (remote.length && !remote.includes(model))) continue;
      propose(`preference:remote:${model}`, `${remoteLabels[model]} bevorzugen`, `Ich wünsche mir bevorzugt das Arbeitsmodell „${remoteLabels[model]}“. Berücksichtige diesen Wunsch bei der Neubewertung der vorhandenen Jobs, ohne andere Arbeitsmodelle auszuschließen. Meine übrigen Angaben bleiben erhalten.`);
    }
    if (filters.max_hours == null) {
      const hours = unique(goodJobs.map(job => job.hours_max)).filter(value => typeof value === 'number' && Number.isFinite(value) && value > 0 && value <= 80);
      for (const value of hours) propose(`preference:hours:${value}`, `Bis ${value} Stunden gewünscht`, `Ich wünsche mir höchstens ${value} Wochenstunden. Berücksichtige das als Präferenz bei der Neubewertung der vorhandenen Jobs, ohne Stellen allein wegen ihrer Arbeitszeit auszuschließen. Meine übrigen Angaben bleiben erhalten.`);
    }
    for (const args of refinements) {
      const before = candidates.length;
      add(...args);
      if (candidates.length > before) break;
    }
  }

  for (const job of jobs) {
    for (const skill of unique(showScores ? job.match?.missing_skills : []).filter(value => typeof value === 'string' && value.trim())) {
      if ((profile.skills || []).some(known => normalize(known) === normalize(skill))) continue;
      add(`skill:${job.id}:${normalize(skill)}`, `Wie wichtig ist ${short(skill, 38)}?`,
        `Welche Rolle spielt ${short(skill, 200)} bei der Stelle ${jobReference(job)}, und wie könnte ich entsprechende Kenntnisse nachweisen?`,
        text => refersTo(text, job) && mentionsTerm(text, skill) && /wichtig|rolle|nachweis|kenntnis|anforderung/.test(text));
    }
  }
  if (jobs.length >= 2) {
    const [first, second] = jobs;
    add(`compare:${first.id}:${second.id}`, 'Die ersten beiden Stellen vergleichen',
      `Vergleiche die Stelle ${jobReference(first)} mit der Stelle ${jobReference(second)}. Welche Unterschiede sind für mein Profil wichtig?`,
      text => refersTo(text, first) && refersTo(text, second) && /vergleich|unterschied/.test(text));
  }
  addProfileQuestions();
  return candidates.slice(0, 3);
}
