export const labels = { werkstudent: 'Werkstudent', praktikum: 'Praktikum', vollzeit: 'Vollzeit', teilzeit: 'Teilzeit', ausbildung: 'Ausbildung', trainee: 'Trainee', abschlussarbeit: 'Abschlussarbeit', sonstige: 'Sonstige' };
export const remoteLabels = { remote: '100 % Homeoffice', hybrid: 'Anteilig Homeoffice', onsite: 'Vor Ort', unknown: 'Arbeitsmodell offen' };
export const emptyForm = { query: '', skills: '', preferences: '', cv: '', employment: [], location: '', remote: [], hours: '' };
export const exampleForm = { ...emptyForm, query: 'Ich suche eine studentische Stelle in Data Science oder Softwareentwicklung.', skills: 'Python, SQL, Pandas, Git', preferences: 'Analytische Aufgaben, Teamarbeit, flexible Arbeitszeiten', employment: ['werkstudent', 'praktikum'] };
const split = (s) => [...new Set(s.split(/[,;\n]/).map(x => x.trim()).filter(Boolean))];
export function makeProfile(form) {
  const hours = form.hours === '' ? null : Number(form.hours);
  if (hours !== null && (!Number.isFinite(hours) || hours <= 0 || hours > 80)) throw new Error('Bitte gib zwischen 1 und 80 Wochenstunden an.');
  const profile = { query: form.query.trim(), skills: split(form.skills), preferences: split(form.preferences), cv_text: form.cv.trim(), filters: { employment_types: form.employment, locations: split(form.location), remote: [...form.remote], max_hours: hours } };
  if (!profile.query && !profile.skills.length && !profile.preferences.length && !profile.cv_text) throw new Error('Erzähl kurz, was du suchst, oder ergänze deine Fähigkeiten.');
  for (const [items, max, name] of [[profile.skills, 60, 'Fähigkeiten'], [profile.preferences, 30, 'Präferenzen'], [profile.filters.locations, 10, 'Orte']]) {
    if (items.length > max || items.some(x => x.length > 200)) throw new Error(`${name}: bitte höchstens ${max} Einträge mit je 200 Zeichen verwenden.`);
  }
  return profile;
}
export function fromProfile(p) {
  return { query: p.query, skills: p.skills.join(', '), preferences: p.preferences.join(', '), cv: p.cv_text, employment: p.filters.employment_types, location: p.filters.locations.join(', '), remote: [...p.filters.remote], hours: p.filters.max_hours ?? '' };
}
export function activeFilters(p) {
  return (p?.filters?.employment_types || []).map(value => labels[value] || value);
}
export function profileSummary(p) {
  const f = p?.filters || {};
  return {
    hardFilters: activeFilters(p),
    wishes: [
      ...(p?.preferences || []),
      ...(f.locations || []).map(location => `Ort gewünscht: ${location}`),
      ...(f.remote || []).map(model => `Arbeitsmodell gewünscht: ${remoteLabels[model] || model}`),
      ...(f.max_hours != null ? [`Bis ${f.max_hours} h/Woche gewünscht`] : []),
    ],
    hasExperience: !!p?.cv_text?.trim(),
  };
}
