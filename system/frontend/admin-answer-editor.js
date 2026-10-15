export function answerFields(definition) {
  return [definition.demographics, ...definition.categories].flatMap(group => group.fields);
}

export function answerVisible(field, answers) {
  const condition = field.visibleIf;
  if (!condition) return true;
  return Array.isArray(condition.in) ? condition.in.includes(answers[condition.field]) : answers[condition.field] === condition.equals;
}

export function updateAnswer(answers, field, value, definition) {
  if (field === 'study_arm') return answers;
  const next = {...answers, [field]: value};
  for (const question of answerFields(definition)) {
    if (!answerVisible(question, next)) next[question.name] = null;
  }
  return next;
}

export function changedAnswers(before, after) {
  return Object.keys(after).filter(name => before[name] !== after[name]);
}

export function answerLabel(field, value) {
  if (value == null) return 'Leer / übersprungen';
  if (value === '') return 'Keine Angabe';
  return [...(field?.options || []), ...(field?.nonresponse || [])].find(([key]) => key === value)?.[1] ?? String(value);
}
