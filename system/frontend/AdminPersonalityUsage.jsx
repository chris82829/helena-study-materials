import React from 'react';

const sources={template:'Unveränderte Vorlage',custom:'Selbst gestaltet',unknown:'Nicht erfasst',not_applicable:'Keine wählbare Persönlichkeit (A)'};
const templates={career:'Top-Berufsberater',expert:'Fachexperte'};
const yesNo=value=>value===true?'Ja':value===false?'Nein':'Nicht sicher erfasst';
export default function AdminPersonalityUsage({usage}) {
  if (!usage?.capture_version) return <p className="admin-footnote">Die tatsächlich verwendete Persönlichkeitsauswahl wurde für diese Teilnahme noch nicht erfasst.</p>;
  function selection(prefix) {
    const source=sources[usage[`${prefix}_source`]] || 'Nicht erfasst';
    const template=templates[usage[`${prefix}_template_id`]];
    return template ? `${source} · ${template}` : source;
  }
  return <details className="admin-personality-usage"><summary>Tatsächlich verwendete Persönlichkeit: {selection('last')}</summary><p>Automatisch bei erfolgreicher Verwendung erfasst. Diese Angaben sind unabhängig von der Selbstauskunft im Fragebogen und nicht bearbeitbar.</p><dl>
    <div><dt>Erste erfasste Verwendung</dt><dd>{selection('initial')}</dd></div>
    <div><dt>Letzte erfasste Verwendung</dt><dd>{selection('last')}</dd></div>
    <div><dt>Mindestens einmal selbst gestaltet</dt><dd>{yesNo(usage.ever_custom)}</dd></div>
    <div><dt>Mindestens einmal eine Vorlage verwendet</dt><dd>{yesNo(usage.ever_template)}</dd></div>
    <div><dt>Erfasste Auswahlwechsel</dt><dd>{usage.selection_change_count ?? 'Nicht erfasst'}</dd></div>
  </dl><p>Nach Abschluss der Umfrage bleibt dieser Stand festgehalten. Wechsel innerhalb eigener Charaktereigenschaften und Inhalte werden nicht protokolliert.</p></details>;
}
