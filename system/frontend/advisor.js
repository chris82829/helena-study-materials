export const standardAdvisor = {mode:'preset',preset:'standard',name:'Standardberatung',traits:[],focus:'ausgewogen',description:''};
export const neutralAdvisor = {mode:'preset',preset:'neutral',name:'HELENA',traits:[],focus:'ausgewogen',description:''};
const careerInstructions = 'Arbeite als besonders sorgfältiger KI-Berufsberater. Betrachte die Stelle im Kontext der Ziele, Fähigkeiten und Wünsche aus dem Suchprofil. Erkläre passende Karrierewege, belegte Lernchancen und realistische nächste Schritte. Sprich empathisch, strukturiert und ermutigend, ohne leere Versprechen. Trenne belegte Passung von offenen Voraussetzungen. Erfinde keine Qualifikationen oder Berufserfahrung und behaupte keine echte berufliche Zulassung.';
export const defaultAdvisor = { mode: 'custom', preset: 'helena', name: 'Top-Berufsberater', traits: ['empathisch', 'strukturiert', 'ermutigend'], focus: 'lernpotenzial', description: careerInstructions };
export const ADVISOR_DESCRIPTION_MAX_LENGTH = 2000;
export const advisorPresets = {
  standard: {name:'Standardberatung',subtitle:'Sachlich & ausgewogen',description:'Feste sachliche Jobsuche mit fachlichem Kontext.',focus:'ausgewogen',traits:[]},
  helena: { name: 'HELENA', subtitle: 'Ausgewogen & ermutigend', description: 'Prüft fachliche Passung und Wünsche ausgewogen. Erklärt analytisch und ermutigt mit konkreten nächsten Schritten.', focus: 'ausgewogen', traits: ['analytisch', 'ermutigend'] },
  steve: { name: 'Steve Jobs', subtitle: 'Gestaltung & neue Ideen', description: 'Spricht direkt, pointiert und mit einem klaren Anspruch an die Wirkung deiner Arbeit. Stellt Gestaltungsspielraum und die entscheidende Frage in den Vordergrund.', focus: 'innovation', traits: ['kreativ', 'direkt', 'neugierig'] },
  angela: { name: 'Angela Merkel', subtitle: 'Abwägung & fachliche Tiefe', description: 'Wägt ruhig Chancen und offene Voraussetzungen ab. Argumentiert präzise, prüft fachliche Tiefe und kommt zu einem begründeten, vorsichtigen Fazit.', focus: 'ausgewogen', traits: ['analytisch', 'strukturiert', 'kritisch'] },
  guenther: { name: 'Günther Jauch', subtitle: 'Lernen & gute Fragen', description: 'Erklärt anschaulich und im Gespräch mit dir. Macht Lernchancen verständlich und fragt gezielt nach, wenn dir das bei der Entscheidung hilft.', focus: 'lernpotenzial', traits: ['neugierig', 'strukturiert', 'empathisch'] },
};
export const traitLabels = { analytisch: 'Analytisch', direkt: 'Direkt', ermutigend: 'Ermutigend', empathisch: 'Empathisch', neugierig: 'Neugierig', kreativ: 'Kreativ', strukturiert: 'Strukturiert', kritisch: 'Kritisch' };
export const focusLabels = { ausgewogen: 'Ausgewogen', fachliche_tiefe: 'Fachliche Vertiefung', lernpotenzial: 'Lernen & Entwicklung', innovation: 'Innovation & Gestaltung' };
export const focusDescriptions = {
  ausgewogen: 'Bezieht fachliche Tiefe, Lernchancen, Gestaltung und klare Aufgaben ausgewogen ein.',
  fachliche_tiefe: 'Gewichtet fachliche Vertiefung und anspruchsvolle Aufgaben stärker.',
  lernpotenzial: 'Gewichtet Betreuung, Lernmöglichkeiten und Entwicklung stärker.',
  innovation: 'Gewichtet Gestaltungsspielraum, neue Ideen und eigene Beiträge stärker.',
};
const legacyTemplates = {
  steve: { ...advisorPresets.steve, instructions: 'Inspiriert von Steve Jobs: Beginne mit einem klaren, kurzen Urteil. Sprich direkt und pointiert in kurzen aktiven Sätzen. Zeige, was ich mit meiner Arbeit konkret bewirken oder gestalten würde, statt meine Skills aufzuzählen. Verdichte die Beratung auf das Wesentliche und einen sinnvollen nächsten Schritt. Keine Werbesprüche, Zitate oder erfundenen Möglichkeiten.' },
  angela: { ...advisorPresets.angela, instructions: 'Inspiriert von Angela Merkel: Wäge ruhig und präzise ab. Trenne das tragende Argument und einen relevanten offenen Punkt in kurze Absätze oder beschriftete Stichpunkte, dann ziehe ein begründetes Fazit. Keine vorschnellen Versprechen; erkenne klare fachliche Passung dennoch klar an. Sprich mich mit du an. Keine politischen Anspielungen oder Zitate.' },
  guenther: { ...advisorPresets.guenther, instructions: 'Inspiriert von Günther Jauch: Führe ein verständliches, interessiertes Gespräch mit mir. Beschreibe konkret, wie eine belegte Aufgabe im Arbeitsalltag aussehen würde. Greife meinen Suchwunsch auf und stelle eine präzise Rückfrage, wenn meine Antwort bei der Entscheidung hilft. Keine lange Bestandsaufnahme, kein Quiz und keine Show-Sprüche.' },
};
export const advisorTemplates = {
  career: { name: 'Top-Berufsberater', subtitle: 'Karriere & Entwicklung', description: 'Ordnet Stellen in deine beruflichen Ziele ein und zeigt dir passende Entwicklungsmöglichkeiten.', focus: defaultAdvisor.focus, traits: [...defaultAdvisor.traits], instructions: careerInstructions },
  expert: { name: 'Fachexperte', subtitle: 'Kenntnisse & fachliche Tiefe', description: 'Prüft Aufgaben und Anforderungen genauer. Das Fachgebiet ergibt sich aus deinem Suchprofil.', focus: 'fachliche_tiefe', traits: ['analytisch', 'kritisch', 'strukturiert'], instructions: 'Arbeite als fachlich spezialisierter KI-Berater für das Gebiet, das aus dem Suchziel und den Fähigkeiten im Nutzerprofil hervorgeht. Lege dich bei uneindeutigen oder mehreren Gebieten nicht ohne Beleg fest; frage bei Bedarf gezielt nach. Prüfe konkrete Aufgaben, Methoden, Werkzeuge und erforderliche Kenntnisse. Unterscheide Muss-Anforderungen, optionale Kenntnisse und noch unbelegte Fähigkeiten. Erkläre fachliche Zusammenhänge präzise und verständlich und nenne sinnvolle Lernschritte. Bewerte fachliche Vertiefung besonders, ohne neue Anforderungen zu erfinden. Behaupte keine echte Qualifikation oder Berufserfahrung.' },
};
function fromTemplate(template) {
  return { ...defaultAdvisor, name: template.name, traits: [...template.traits], focus: template.focus, description: template.instructions };
}
export function advisorFromTemplate(key, templates = advisorTemplates) {
  if (key === '') return { mode: 'custom', preset: 'helena', name: '', traits: ['analytisch', 'ermutigend'], focus: 'ausgewogen', description: '' };
  if (!Object.hasOwn(templates, key)) throw new Error('Diese Persönlichkeitsvorlage ist nicht verfügbar.');
  return fromTemplate(templates[key]);
}
export function editableAdvisor(advisor) {
  if (advisor?.mode === 'preset') {
    if (Object.hasOwn(legacyTemplates, advisor.preset)) return fromTemplate(legacyTemplates[advisor.preset]);
    const preset = advisorPresets[advisor.preset] || advisorPresets.helena;
    return { mode: 'custom', preset: 'helena', name: preset.name, traits: [...preset.traits], focus: preset.focus, description: '' };
  }
  const value = advisor || defaultAdvisor;
  return { ...defaultAdvisor, ...value, traits: [...(value.traits ?? defaultAdvisor.traits)], description: value.description ?? '' };
}
export function advisorLabel(advisor) {
  const a = advisor || defaultAdvisor;
  return a.mode === 'custom' ? (a.name?.trim() || advisorPresets.helena.name) : (advisorPresets[a.preset]?.name || advisorPresets.helena.name);
}
export function advisorAiLabel(advisor) {
  const name = advisorLabel(advisor).trim().replace(/\s+/g, '-');
  return /-ki$/i.test(name) ? name.replace(/-ki$/i, '-KI') : `${name}-KI`;
}
export function advisorScoreLabel(advisor) {
  const name = advisorLabel(advisor).trim().replace(/\s+/g, '-');
  return `${name}-Score`;
}
export function validateAdvisor(a) {
  if (a.mode === 'preset') return { ...defaultAdvisor, mode: 'preset', preset: a.preset, traits: [...defaultAdvisor.traits], description: '' };
  if (a.mode === 'custom' && (!a.name.trim() || !a.traits.length || a.traits.length > 4)) throw new Error('Gib deiner Persönlichkeit einen Namen und wähle eine bis vier Eigenschaften.');
  const description = a.description === undefined ? '' : a.description;
  if (typeof description !== 'string' || description.trim().length > ADVISOR_DESCRIPTION_MAX_LENGTH) throw new Error(`Beschreibe deine Persönlichkeit mit höchstens ${ADVISOR_DESCRIPTION_MAX_LENGTH} Zeichen.`);
  return { ...a, name: a.name.trim(), traits: [...a.traits], description: description.trim() };
}

export function sameAdvisor(left, right) {
  if (!left || !right) return false;
  return ['mode', 'preset', 'name', 'focus'].every(key => left[key] === right[key]) && JSON.stringify(left.traits) === JSON.stringify(right.traits) && (left.description ?? '') === (right.description ?? '');
}
