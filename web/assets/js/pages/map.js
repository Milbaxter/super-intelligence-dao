import { initPage, api, h, $, mount, tierBadge, tierBar, TIERS, tierInfo, link, params, showError, skeleton, fmtDate } from '../core.js';

initPage({ page: 'map', title: 'The Map' });

const els = { stack: $('#stack'), layers: $('#layers'), summary: $('#map-summary'), count: $('#map-count'),
  layer: $('#f-layer'), kind: $('#f-kind'), q: $('#f-q'), tier: $('#f-tier') };
$('#map-filters').addEventListener('submit', (e) => e.preventDefault());
const KINDS = ['model', 'dataset', 'framework', 'harness', 'benchmark', 'environment', 'tool', 'app', 'library'];
const TIER_FILTERS = [...TIERS.map(t => t.id), 'disputed', 'stale', 'gap'];
const f = { layer: params.get('layer') || '', kind: params.get('kind') || '', q: params.get('q') || '', tier: params.get('tier') || '' };

let MAP = null, GAPS = [];

function syncUrl() {
  const u = new URL(location.href);
  for (const [k, v] of Object.entries(f)) v ? u.searchParams.set(k, v) : u.searchParams.delete(k);
  history.replaceState(null, '', u);
}

function buildFilters() {
  MAP.layers.forEach(l => els.layer.append(h('option', { value: l.id }, l.name)));
  KINDS.forEach(k => els.kind.append(h('option', { value: k }, k)));
  els.layer.value = f.layer; els.kind.value = f.kind; els.q.value = f.q;
  const mk = (id, label, tierAttr) => {
    const b = h('button', { type: 'button', 'aria-pressed': String(f.tier === id), 'data-tier': tierAttr },
      tierAttr ? h('span', { class: 'sw', 'aria-hidden': 'true' }) : null, label);
    b.addEventListener('click', () => { f.tier = f.tier === id ? '' : id; [...els.tier.children].forEach(x => x.setAttribute('aria-pressed', 'false')); b.setAttribute('aria-pressed', String(!!f.tier)); if (!f.tier) els.tier.firstChild.setAttribute('aria-pressed', 'true'); render(); });
    return b;
  };
  els.tier.append(mk('', 'All tiers', null));
  if (!f.tier) els.tier.firstChild.setAttribute('aria-pressed', 'true');
  TIER_FILTERS.forEach(id => {
    const info = tierInfo(id);
    els.tier.append(mk(id, id === 'gap' ? 'gaps only' : `${TIERS.find(t => t.id === id)?.code || ''} ${info?.name || id}`.trim(), id === 'gap' ? 'none' : id));
  });
  els.layer.addEventListener('change', () => { f.layer = els.layer.value; render(); });
  els.kind.addEventListener('change', () => { f.kind = els.kind.value; render(); });
  let t; els.q.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { f.q = els.q.value.trim(); render(); }, 120); });
}

function stackOverview() {
  const rows = [h('div', { class: 'stack-row stack-head', 'aria-hidden': 'true' },
    h('span', {}, '#'), h('span', {}, 'layer'), h('span', { class: 'cov' }, 'artifacts by best tier'), h('span', { class: 'n' }, 'claims'), h('span', { class: 'n' }, 'verified'), h('span', { class: 'n g' }, 'gaps'))];
  MAP.layers.forEach((l, i) => {
    const gaps = l.gap_ids?.length || 0;
    const claims = l.artifacts.reduce((a, x) => a + (x.claim_count || 0), 0);
    const ver = l.artifacts.reduce((a, x) => a + (x.verified_claim_count || 0), 0);
    rows.push(h('a', { class: 'stack-row', href: `#layer-${l.id}`, 'aria-label': `${l.name}: ${l.artifacts.length} artifacts, ${claims} claims, ${ver} verified, ${gaps} gaps` },
      h('span', { class: 'idx' }, String(i + 1).padStart(2, '0')),
      h('span', { class: 'nm' }, l.name),
      h('span', { class: 'cov', 'aria-hidden': 'true' }, l.artifacts.map(a => h('i', { 'data-tier': a.best_tier || 'none', title: `${a.name}: ${a.best_tier || 'no claims yet'}` }))),
      h('span', { class: 'n' }, String(claims), h('small', {}, 'claims')),
      h('span', { class: 'n' }, String(ver), h('small', {}, 'verified')),
      h('span', { class: 'n g' }, String(gaps), h('small', {}, 'gaps'))));
  });
  mount(els.stack, rows);
}

const matchArtifact = (a) => (!f.kind || a.kind === f.kind) && (!f.q || a.name.toLowerCase().includes(f.q.toLowerCase()) || a.id.includes(f.q.toLowerCase()));
const cellMatches = (cell) => !f.tier || f.tier === cell?.best_tier || (f.tier === 'gap' && !cell);

function layerSection(l, idx) {
  const arts = l.artifacts.filter(matchArtifact);
  const cellsBy = new Map(l.cells.map(c => [`${c.artifact_id}|${c.benchmark_id}`, c]));
  const gaps = GAPS.filter(g => g.layer === l.id && g.status !== 'rejected' && g.status !== 'resolved');
  const sec = h('section', { class: 'layer-sec', id: `layer-${l.id}`, 'aria-labelledby': `lh-${l.id}` });
  sec.append(h('header', { class: 'layer-sec-head' },
    h('span', { class: 'idx' }, String(idx + 1).padStart(2, '0')),
    h('h2', { id: `lh-${l.id}` }, l.name),
    h('span', { class: 'counts' }, `${l.artifacts.length} artifacts · ${l.benchmarks.length} benchmarks · ${gaps.length} gaps`),
    h('p', {}, l.description || '')));

  let shown = 0;
  if (l.benchmarks.length && arts.length) {
    const rows = arts.map(a => {
      const cells = l.benchmarks.map(b => cellsBy.get(`${a.id}|${b.id}`));
      const any = cells.some(cellMatches);
      if (f.tier && !any) return null;
      shown++;
      return h('tr', {},
        h('th', { scope: 'row' }, h('a', { href: link.artifact(a.id) }, a.name),
          h('div', { class: 'meta' }, h('span', {}, a.kind), a.open_weights ? h('span', {}, 'open weights') : null, a.license ? null : h('span', { title: 'Licence unknown — a profile task can fill it' }, 'licence ?'))),
        l.benchmarks.map((b, j) => {
          const c = cells[j];
          const dim = f.tier && !cellMatches(c) ? ' hidden-tier' : '';
          if (!c) return h('td', {}, h('span', { class: 'cell gapcell' + dim, title: `No claim yet for ${a.name} on ${b.name}` }, 'gap'));
          const extra = c.claim_ids.length > 1 ? ` +${c.claim_ids.length - 1}` : '';
          return h('td', {}, h('a', { class: 'cell' + dim, 'data-tier': c.best_tier, href: link.claim(c.claim_ids[0]), 'aria-label': `${a.name} on ${b.name}: ${c.value_summary}, ${c.best_tier}` },
            /^hidden/i.test(c.value_summary || '')
              ? h('span', { class: 'val', title: 'Value withheld while a blind check is pending' }, 'hidden', h('small', { class: 'muted', style: { display: 'block', fontSize: '.7rem' } }, 'blind check pending'))
              : h('span', { class: 'val' }, c.value_summary || '—', extra ? h('small', { class: 'muted' }, extra) : null), tierBadge(c.best_tier, { compact: true })));
        }));
    }).filter(Boolean);
    if (rows.length) {
      sec.append(h('div', { class: 'matrix-wrap', role: 'region', 'aria-label': `${l.name} claims matrix`, tabindex: '0' },
        h('table', { class: 'matrix' },
          h('caption', { class: 'visually-hidden' }, `${l.name}: artifacts by benchmark. Cells show the value and verification tier.`),
          h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'artifact ↓ benchmark →'),
            l.benchmarks.map(b => h('th', { scope: 'col' }, b.name, h('small', {}, b.measures + (b.saturated ? ' · saturated' : '')))))),
          h('tbody', {}, rows))));
    }
  }
  if (!l.benchmarks.length) {
    const list = arts.filter(a => !f.tier || f.tier === a.best_tier || (f.tier === 'gap' && !a.best_tier));
    shown += list.length;
    if (list.length) {
      sec.append(h('p', { class: 'small muted', style: { margin: '0 0 10px' } }, 'No benchmarks tracked for this layer yet — artifacts are listed with their best claim.'));
      sec.append(h('div', { class: 'artlist' }, list.map(a => h('a', { class: 'artpill', href: link.artifact(a.id) }, a.name, h('span', { class: 'k' }, a.kind), a.best_tier ? tierBadge(a.best_tier, { compact: true }) : h('span', { class: 'k' }, 'no claims')))));
    }
  }
  if (gaps.length && (!f.tier || f.tier === 'gap') && !f.q && !f.kind) {
    sec.append(h('h3', { class: 'label', style: { margin: '22px 0 0' } }, h('strong', {}, `Gaps in ${l.name}`), ' — first-class, they become tasks'));
    sec.append(h('div', { class: 'gaps' }, gaps.map(g => h('article', { class: 'gap' },
      h('div', { class: 'gk' }, h('span', {}, g.kind.replace(/_/g, ' ')), h('span', { class: 'chip' }, g.status), g.task_ids?.length ? h('span', {}, `${g.task_ids.length} task(s)`) : null),
      h('h4', {}, g.title), h('p', {}, g.description)))));
  }
  return { sec, shown: shown + (gaps.length && f.tier === 'gap' ? 1 : 0) };
}

function render() {
  syncUrl();
  const out = []; let total = 0;
  MAP.layers.forEach((l, i) => {
    if (f.layer && l.id !== f.layer) return;
    const { sec, shown } = layerSection(l, i);
    if (shown || (!f.q && !f.kind && !f.tier)) { out.push(sec); total += shown; }
  });
  mount(els.layers, out.length ? out : h('div', { class: 'empty' }, 'Nothing matches these filters. An empty result is a gap too — ', h('a', { href: 'board.html' }, 'see the Board'), '.'));
  els.count.textContent = (f.layer || f.kind || f.q || f.tier) ? `Filtered: ${out.length} layer(s) shown.` : `Map generated ${fmtDate(MAP.generated_at)}.`;
}

(async () => {
  mount(els.layers, skeleton(6));
  try {
    const [map, gaps, stats] = await Promise.all([api('/map'), api('/gaps').catch(() => []), api('/stats').catch(() => null)]);
    MAP = map; GAPS = gaps || [];
    if (stats) mount(els.summary, h('p', { class: 'label', style: { marginBottom: '10px' } }, h('strong', {}, `${stats.claims_total} claims`), ` · ${stats.artifacts_total} artifacts · ${stats.gaps_open} open gaps`), tierBar(stats.claims_by_tier));
    stackOverview(); buildFilters(); render();
    if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
  } catch (e) { showError(els.layers, e, 'the map'); }
})();
