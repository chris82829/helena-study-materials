export const SEARCH_STAGES = ['loaded', 'profiling', 'retrieval', 'ranking', 'finalizing'];

// Only public phase metadata crosses the survey iframe boundary.
export function readSearchProgress(value) {
  if (!value || !SEARCH_STAGES.includes(value.stage)) return null;
  const result = {stage:value.stage};
  for (const key of ['job_count', 'candidate_count']) {
    if (Number.isSafeInteger(value[key]) && value[key] >= 0) result[key] = value[key];
  }
  return result;
}

export function searchStatus(value) {
  const progress = readSearchProgress(value);
  const jobs = progress?.job_count?.toLocaleString('de-DE');
  const messages = {
    loaded: ['Stellenanzeigen sind geladen', `${jobs ? `${jobs} Anzeigen stehen` : 'Die Anzeigen stehen'} für deine Suche bereit.`],
    profiling: ['Dein Suchprofil wird vorbereitet', 'Die KI bereitet deine Fähigkeiten und Wünsche für die Suche auf.'],
    retrieval: [`${jobs ? `${jobs} Stellen werden` : 'Stellen werden'} durchsucht`, 'Das System vergleicht Stichwörter und Inhalte mit deinem Suchprofil.'],
    ranking: [jobs ? `${jobs} Stellen durchsucht` : 'Stellensuche abgeschlossen', 'Die KI gleicht passende Treffer mit deinem Profil ab.'],
    finalizing: ['Deine Ergebnisse werden vorbereitet', 'Der Abgleich ist fertig. Gleich erscheinen die Stellenkarten.'],
  };
  const [title, description] = messages[progress?.stage] || ['Deine Suche startet', 'Das System bereitet deine Anfrage vor.'];
  return {title, description, index:SEARCH_STAGES.indexOf(progress?.stage)};
}
