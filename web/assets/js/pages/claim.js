import { SITE_NAME, initPage, api, h, $, mount, tierBadge, tierLadder, stamp, tierInfo, tierLevel, link, params, showError, extLink, fmtValue, claimValue, isValueHidden, HIDDEN_VALUE_LABEL, fmtDate, fmtDateTime, daysUntil, prettyUrl, state } from '../core.js';

initPage({ page: 'map', title: 'Claim' });
const head = $('#claim-head'), body = $('#claim-body');
const id = params.get('id');

const TRAIL_TIER = { submitted: 'reported', quote_check: 'source-checked', quote_check_passed: 'source-checked', blind_agree: 'reproduced', blind_disagree: 'disputed', expired: 'stale', quote_check_failed: 'disputed', steward: 'reported' };

/** Highlight the value inside the quote (text-only, no HTML injection). */
function quoteWithMark(quote, value) {
  const q = String(quote ?? '');
  const forms = [String(value), (+value).toFixed(1), (+value).toFixed(2)].filter(Boolean).sort((a, b) => b.length - a.length);
  for (const f of forms) {
    const i = q.indexOf(f);
    if (i >= 0) return [q.slice(0, i), h('mark', {}, q.slice(i, i + f.length)), q.slice(i + f.length)];
  }
  return [q];
}

(async () => {
  if (!id) { mount(head, h('h1', {}, 'Claim')); showError(body, { status: 404, message: 'No claim id in the URL.' }, 'this claim'); return; }
  let c;
  try { c = await api(`/claims/${encodeURIComponent(id)}`); }
  catch (e) { mount(head, h('h1', {}, 'Claim not found')); showError(body, e, 'this claim'); return; }
  const status = c.display_status || c.special_status || c.tier;
  document.title = `${c.artifact_name} × ${c.benchmark_name} · Claim · ${SITE_NAME}`;
  head.closest('.page-head').dataset.tier = status;

  const verified = !c.special_status && tierLevel(c.tier) >= 2;
  const hidden = isValueHidden(c);
  mount(head,
    h('p', { class: 'crumbs' }, h('a', { href: 'map.html' }, 'Map'), '/', h('a', { href: link.map(c.layer) + `#layer-${encodeURIComponent(c.layer)}` }, c.layer), '/', h('a', { href: link.artifact(c.artifact_id) }, c.artifact_name), '/', h('span', {}, c.id)),
    h('div', { class: 'claim-hero', 'data-tier': status, style: { marginTop: '22px' } },
      h('div', {},
        h('p', { class: 'label', style: { marginBottom: '14px', display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' } }, tierBadge(c), c.seed ? h('span', { class: 'chip' }, 'seeded') : null, h('span', {}, `reported by ${String(c.reported_by || '').replace(/-/g, ' ')}`)),
        h('h1', {}, h('a', { href: link.artifact(c.artifact_id), style: { color: 'inherit', textDecoration: 'none' } }, c.artifact_name), h('span', { class: 'x', 'aria-hidden': 'true' }, ' × '), h('span', { class: 'visually-hidden' }, ' on '), c.benchmark_name),
        h('div', { class: 'claim-value' },
          hidden ? h('span', { class: 'big hidden-value', title: 'Withheld so the blind verifier cannot copy it' }, HIDDEN_VALUE_LABEL)
            : h('span', { class: 'big' }, (+c.value).toLocaleString('en-US', { maximumFractionDigits: 3 })),
          hidden ? null : h('span', { class: 'unit' }, c.unit || ''),
          h('span', { class: 'cmetric' }, `${c.metric} · ${c.higher_is_better ? 'higher is better' : 'lower is better'}`))),
      h('div', { class: 'stamp-slot' }, (verified || c.special_status) ? (() => { const s = stamp(status, `${tierInfo(c.tier)?.code ?? ''} · ${fmtDate(c.tier_changed_at)}`); s.classList.add('big', 'thunk'); return s; })() : null)));

  const trail = (c.trail || []).slice().sort((a, b) => new Date(a.ts) - new Date(b.ts));
  const cond = c.conditions && typeof c.conditions === 'object' ? c.conditions : {};
  const days = daysUntil(c.expires_at), total = 180;
  const left = Math.max(0, Math.min(1, days / total));

  const main = h('div', {},
    h('section', { class: 'block', 'data-tier': status }, h('h2', {}, 'The quote', h('span', { class: 'label' }, 'as cited — the referee checks it against the live source')),
      hidden ? h('p', { class: 'note' }, h('strong', {}, 'Hidden — blind check pending. '),
        'A different contributor’s agent is re-extracting this value from the source without seeing it. The value and quote reappear once that check is done.')
        : h('blockquote', { class: 'quote', cite: c.source_url }, quoteWithMark(c.quote, c.value)),
      h('p', { class: 'small', style: { marginTop: '10px' } }, 'Source: ', extLink(c.source_url, prettyUrl(c.source_url)))),
    h('section', { class: 'block' }, h('h2', {}, 'Conditions', h('span', { class: 'label' }, 'a number without conditions is not a claim')),
      Object.keys(cond).length ? h('dl', { class: 'kv' }, Object.entries(cond).flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, typeof v === 'object' ? JSON.stringify(v) : String(v))])) : h('div', { class: 'empty' }, 'No conditions recorded — that is itself a gap.')),
    h('section', { class: 'block' }, h('h2', {}, 'Evidence trail', h('span', { class: 'label' }, `${trail.length} event${trail.length === 1 ? '' : 's'}`)),
      trail.length ? h('ol', { class: 'trail' }, trail.map(ev => h('li', { class: /agree|quote_check$|passed/.test(ev.kind) ? 'solid' : '', 'data-tier': TRAIL_TIER[ev.kind] || 'reported' },
        h('span', { class: 'when' }, fmtDateTime(ev.ts), ' · ', h('span', {}, String(ev.kind).replace(/_/g, ' '))),
        h('p', { class: 'what' }, ev.summary),
        h('span', { class: 'who' }, 'by ', ev.actor || 'unknown',
          ev.detail && typeof ev.detail === 'object' && Object.keys(ev.detail).length ? h('span', { class: 'muted' }, ' · ' + Object.entries(ev.detail).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ')) : null))))
      : h('div', { class: 'empty' }, 'No events recorded yet.')),
    c.check_result ? h('section', { class: 'block' }, h('h2', {}, 'Mechanical check', h('span', { class: 'label' }, c.check_result.passed ? 'passed' : 'did not pass')),
      h('dl', { class: 'kv' },
        h('dt', {}, 'result'), h('dd', {}, c.check_result.passed ? '✓ quote found verbatim, value in quote' : `✕ ${c.check_result.reason || 'failed'}`),
        h('dt', {}, 'fetched'), h('dd', {}, extLink(c.check_result.fetched_url, prettyUrl(c.check_result.fetched_url))),
        h('dt', {}, 'http'), h('dd', { class: 'mono' }, String(c.check_result.http_status ?? '—')),
        h('dt', {}, 'at'), h('dd', {}, fmtDateTime(c.check_result.fetched_at)),
        h('dt', {}, 'sha-256'), h('dd', { class: 'mono small' }, c.check_result.content_sha256 || '—'))) : null,
    state.mock ? h('p', { class: 'note warn', style: { marginTop: '28px' } }, h('strong', {}, 'Example data'), 'This claim, its value and its quote are illustrative fixtures for layout. The source link points to the real project, but the quote is not taken from it.') : null);

  const aside = h('aside', {},
    h('div', { class: 'panel', 'data-tier': status }, h('div', { class: 'panel-head' }, h('span', { class: 'label' }, h('strong', {}, 'Where this claim stands')), tierBadge(c, { compact: true })),
      h('div', { class: 'panel-body' }, tierLadder({ current: c.tier, special: c.special_status, compact: true }),
        c.special_status ? h('p', { class: 'small', style: { marginTop: '12px' }, 'data-tier': c.special_status }, h('strong', { style: { color: 'var(--tc)' } }, `${c.special_status}: `), tierInfo(c.special_status)?.short) : null,
        h('p', { class: 'small muted', style: { marginTop: '12px' } }, 'T0–T2 run in Phase 0. ', h('a', { href: 'referee.html' }, 'How the referee works →')))),
    h('div', { class: 'panel', 'data-tier': status }, h('div', { class: 'panel-body expiry' },
      h('span', { class: 'label' }, h('strong', {}, 'Expiry')),
      h('div', { class: 'bar', role: 'img', 'aria-label': `${Math.round(left * 100)}% of validity left` }, h('i', { style: { width: `${left * 100}%` } })),
      h('p', { class: 'small' }, days >= 0 ? `Expires ${fmtDate(c.expires_at)} — in ${days} days.` : `Expired ${fmtDate(c.expires_at)} — ${-days} days ago. Queued for re-checking.`),
      h('p', { class: 'small muted' }, `Last tier change ${fmtDate(c.tier_changed_at)}. Claims expire 180 days after their last tier change.`))),
    h('div', { class: 'panel' }, h('div', { class: 'panel-body' }, h('dl', { class: 'kv' },
      h('dt', {}, 'claim id'), h('dd', { class: 'mono small' }, c.id),
      h('dt', {}, 'artifact'), h('dd', {}, h('a', { href: link.artifact(c.artifact_id) }, c.artifact_name)),
      h('dt', {}, 'benchmark'), h('dd', {}, c.benchmark_name),
      h('dt', {}, 'value'), h('dd', { class: hidden ? 'small muted' : 'mono' }, claimValue(c)),
      h('dt', {}, 'created'), h('dd', {}, fmtDate(c.created_at))))));
  mount(body, main, aside);
})();
