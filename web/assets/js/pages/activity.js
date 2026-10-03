import { initPage, api, h, $, mount, link, showError, skeleton, fmtDateTime, fmtAgo, state } from '../core.js';

initPage({ page: 'activity', title: 'Activity' });
const feed = $('#feed'), pollState = $('#poll-state'), toggle = $('#poll-toggle'), kindSeg = $('#kind-filter');
const POLL_MS = 15000;

// kind → [glyph, tier colour, group]
function kindStyle(kind = '') {
  const k = kind.toLowerCase();
  if (/disagree|dispute|failed|reject/.test(k)) return ['!', 'disputed', 'claims'];
  if (/agree|reproduc|verified/.test(k)) return ['T2', 'reproduced', 'claims'];
  if (/quote|check|source/.test(k)) return ['T1', 'source-checked', 'claims'];
  if (/stale|expire/.test(k)) return ['~', 'stale', 'claims'];
  if (/steward|resolve|spot|gap/.test(k)) return ['S', 'reported', 'steward'];
  if (/join|contributor|register/.test(k)) return ['+', 'reported', 'people'];
  if (/claim|lease|submi|task|release|heartbeat/.test(k)) return ['→', 'reported', 'tasks'];
  return ['·', 'reported', 'other'];
}
const GROUPS = [['', 'All'], ['claims', 'Claims & checks'], ['tasks', 'Tasks'], ['steward', 'Steward'], ['people', 'People']];
let group = '', paused = false, timer = 0, lastOk = 0, loadFailed = false, seen = new Set(), events = [];

function refHref(e) {
  if (!e.ref_id) return null;
  switch (e.ref_type) {
    case 'claim': return link.claim(e.ref_id);
    case 'task': return link.task(e.ref_id);
    case 'artifact': return link.artifact(e.ref_id);
    case 'gap': return 'map.html?tier=gap';
    case 'contributor': return 'people.html';
    default: return null;
  }
}
const keyOf = (e) => `${e.ts}|${e.kind}|${e.summary}`;

function row(e, isNew) {
  const [glyph, tier] = kindStyle(e.kind);
  const href = refHref(e);
  return h('li', { class: isNew ? 'flash' : '' },
    h('time', { class: 't', datetime: e.ts, title: fmtDateTime(e.ts) }, fmtAgo(e.ts)),
    h('span', { class: 'ic', 'data-tier': tier, 'aria-hidden': 'true' }, glyph),
    h('div', { class: 's' }, String(e.summary || '').startsWith(e.actor || '\u0000') ? null : h('span', { class: 'actor' }, e.actor || 'system'),
      href ? h('a', { href }, e.summary) : h('span', {}, e.summary),
      h('span', { class: 'kind' }, String(e.kind).replace(/_/g, ' '))));
}
function render(newKeys = new Set()) {
  const vis = events.filter(e => !group || kindStyle(e.kind)[2] === group);
  mount(feed, vis.length ? vis.map(e => row(e, newKeys.has(keyOf(e)))) : h('li', { class: 'empty', style: { display: 'block' } }, 'Nothing here yet.'));
}
mount(kindSeg, GROUPS.map(([id, label]) => {
  const b = h('button', { type: 'button', 'aria-pressed': String(id === group) }, label);
  b.addEventListener('click', () => { group = id; [...kindSeg.children].forEach(x => x.setAttribute('aria-pressed', String(x === b))); render(); });
  return b;
}));

async function poll(first = false) {
  clearTimeout(timer);
  try {
    const list = await api('/activity?limit=50');
    const fresh = new Set();
    list.forEach(e => { const k = keyOf(e); if (!seen.has(k)) { if (!first) fresh.add(k); seen.add(k); } });
    events = [...list].sort((a, b) => new Date(b.ts) - new Date(a.ts));
    render(fresh); lastOk = Date.now(); loadFailed = false;
  } catch (e) { loadFailed = true; if (!lastOk) showError(feed, e, 'activity'); }
  if (!paused) timer = setTimeout(poll, POLL_MS);
}
setInterval(() => {
  if (loadFailed) { pollState.textContent = `Updates unavailable${lastOk ? ` · showing data from ${fmtAgo(lastOk)}` : ''} · ${paused ? 'paused' : 'retrying'}`; return; }
  if (!lastOk) { pollState.textContent = 'loading…'; return; }
  const ago = Math.round((Date.now() - lastOk) / 1000);
  pollState.textContent = paused ? `paused · updated ${ago}s ago` : `${state.mock ? 'example data · ' : ''}updated ${ago}s ago · next in ${Math.max(0, Math.round(POLL_MS / 1000) - ago)}s`;
}, 1000);
toggle.addEventListener('click', () => {
  paused = !paused; toggle.setAttribute('aria-pressed', String(paused)); toggle.textContent = paused ? 'Resume updates' : 'Pause updates';
  if (!paused) poll(); else clearTimeout(timer);
});
document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(timer); else if (!paused) poll(); });
mount(feed, h('li', { style: { display: 'block' } }, skeleton(6)));
poll(true);
