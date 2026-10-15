import React from 'react';

const operations=[['search','Suche über alle Stellen'],['rerank','Ergebnisse neu sortieren'],['chat','Eigene Chatnachrichten']];
const number=value=>new Intl.NumberFormat('de-DE').format(value);
export default function AdminOperationMetrics({metrics}) {
 if (!metrics?.capture_version) return <p className="admin-footnote">Für diese Teilnahme sind keine Laufzeiten oder Nutzungszähler erfasst.</p>;
 return <details className="admin-personality-usage"><summary>Erfasste Nutzung und Laufzeiten</summary><p>Serverseitige Summen des erfassten Zeitraums; keine Texte oder einzelnen Aktionen. Diese Angaben sind nicht bearbeitbar.</p><dl>{operations.map(([kind,label])=><div key={kind}><dt>{label}</dt><dd>{number(metrics[`successful_${kind}_count`])} erfolgreich · {number(metrics[`failed_${kind}_count`])} fehlgeschlagen · {number(metrics[`${kind}_duration_ms`])} ms insgesamt</dd></div>)}</dl><p>Eine Chatnachricht kann eine Suche oder Neusortierung enthalten und zählt dann in beiden Kategorien. Die Laufzeiten überlappen; bitte nicht zu einer Gesamtdauer addieren. Nach Umfrageabschluss bleibt der erfasste Stand erhalten.</p></details>;
}
