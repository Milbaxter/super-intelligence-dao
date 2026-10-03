// Shared UI components built on core.js (safe DOM only).
import { h, famChip, link, fmtAgo, tierBadge, extLink, fmtValue, claimValue, isValueHidden, awaitingPill, prettyUrl } from './core.js';

export const COLUMNS = [
  { id: 'open', title: 'Open', statuses: ['open'], hint: 'Waiting for an agent.' },
  { id: 'progress', title: 'In progress', statuses: ['leased', 'submitted', 'verifying'], hint: 'Leased, submitted or being verified.' },
  { id: 'verified', title: 'Verified', statuses: ['verified', 'closed'], hint: 'Passed the referee.' },
  { id: 'attention', title: 'Needs a ruling', statuses: ['needs_steward', 'disputed', 'rejected'], hint: 'Disputed, rejected or waiting for the steward.' },
];
export function statusPill(s) { return h('span', { class: 'status-pill', 'data-s': s }, s.replace(/_/g, ' ')); }
export function prioBars(p, max = 8) {
  const n = Math.max(1, Math.min(5, Math.round((p / max) * 5)));
  return h('span', { class: 'prio', role: 'img', 'aria-label': `priority ${(+p).toFixed(1)}`, title: `priority ${(+p).toFixed(2)}` },
    [0, 1, 2, 3, 4].map(i => h('i', { class: i < n ? 'on' : '', style: { height: `${4 + i * 2}px` } })));
}
export function taskCard(t, trackName) {
  return h('a', { class: 'tcard', href: link.task(t.id) },
    h('span', { class: 'ttype' }, h('span', {}, t.type), prioBars(t.priority)),
    h('span', { class: 'ttitle' }, t.title),
    h('span', { class: 'tmeta' }, statusPill(t.status), (t.allowed_model_families || []).map(famChip),
      h('span', { class: 'chip' }, `≤ ${t.budget_minutes} min`), t.attempts ? h('span', { class: 'chip' }, `attempt ${t.attempts + 1}`) : null),
    trackName ? h('span', { class: 'small muted' }, trackName, ' · ', fmtAgo(t.created_at)) : null);
}


/** Compact claims ledger table. */
export function claimsTable(claims, { showArtifact = true, showBenchmark = true } = {}) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'ledger' },
    h('thead', {}, h('tr', {},
      showArtifact ? h('th', { scope: 'col' }, 'artifact') : null,
      showBenchmark ? h('th', { scope: 'col' }, 'benchmark') : null,
      h('th', { scope: 'col', class: 'num' }, 'value'),
      h('th', { scope: 'col' }, 'tier'),
      h('th', { scope: 'col' }, 'conditions'),
      h('th', { scope: 'col' }, 'source'))),
    h('tbody', {}, claims.map(c => h('tr', {},
      showArtifact ? h('td', {}, h('a', { href: link.artifact(c.artifact_id) }, c.artifact_name || c.artifact_id)) : null,
      showBenchmark ? h('td', { style: { minWidth: '150px' } }, h('a', { href: link.claim(c.id) }, c.benchmark_name || c.benchmark_id), h('div', { class: 'small muted' }, c.metric)) : null,
      h('td', { class: 'num' }, isValueHidden(c) ? awaitingPill()
        : h('a', { href: link.claim(c.id), 'aria-label': `Open claim ${c.id}` }, claimValue(c))),
      h('td', {}, tierBadge(c)),
      h('td', { class: 'small muted', style: { minWidth: '200px' } }, condSummary(c.conditions)),
      h('td', { class: 'small nowrap' }, extLink(c.source_url, '↗ ' + prettyUrl(c.source_url).split('/')[0])))))));
}
export function condSummary(cond) {
  if (!cond || typeof cond !== 'object') return '—';
  const parts = ['model', 'harness', 'scaffold', 'budget', 'attempts', 'date'].filter(k => cond[k] !== undefined && cond[k] !== null && cond[k] !== '').map(k => `${k}: ${cond[k]}`);
  return parts.join(' · ') || '—';
}
export function gapCard(g) {
  return h('article', { class: 'gap' },
    h('div', { class: 'gk' }, h('span', {}, String(g.kind || '').replace(/_/g, ' ')), h('span', { class: 'chip' }, g.status)),
    h('h4', {}, g.title), h('p', {}, g.description));
}
