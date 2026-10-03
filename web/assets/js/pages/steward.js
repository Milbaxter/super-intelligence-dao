import { initPage, api, stewardFetch, h, $, mount, tierBadge, link, params, copyText, fmtDateTime } from '../core.js';
import { statusPill } from '../components.js';

initPage({ page: 'steward', title: 'Steward console' });
const KEY = 'agentdao.steward_key';
const con = $('#console'), keyInput = $('#key'), keyState = $('#key-state'), forgetBtn = $('#forget');
const getKey = () => { try { return sessionStorage.getItem(KEY) || ''; } catch { return ''; } };
const setKey = (k) => { try { k ? sessionStorage.setItem(KEY, k) : sessionStorage.removeItem(KEY); } catch {} };
const demo = params.get('mock') === '1';

const log = h('pre', { class: 'result-log', 'aria-live': 'polite', 'aria-label': 'Last action result' }, 'No actions yet.');
function logResult(label, data) { log.textContent = `[${new Date().toLocaleTimeString()}] ${label}\n` + (typeof data === 'string' ? data : JSON.stringify(data, null, 2)); }

async function act(label, path, body, btn) {
  if (demo) { logResult(label, 'Example mode (?mock=1): actions are disabled. Remove ?mock=1 and use the real steward key.'); return null; }
  if (btn) btn.disabled = true;
  try { const r = await stewardFetch(path, { method: 'POST', body, key: getKey() }); logResult(`${label} ✓`, r); return r; }
  catch (e) { logResult(`${label} ✕ ${e.status || ''} ${e.code || ''}`, e.message); return null; }
  finally { if (btn) btn.disabled = false; }
}

function sel(name, options) { return h('label', { class: 'field' }, h('span', {}, name), h('select', { name }, options.map(([v, l]) => h('option', { value: v }, l)))); }
function note() { return h('label', { class: 'field', style: { flex: '2 1 220px' } }, h('span', {}, 'note (required)'), h('input', { type: 'text', name: 'note', required: true, maxlength: '500' })); }

function claimItem(c, { spot = false } = {}) {
  const form = h('form', {},
    sel('ruling', [['tier:reproduced', 'Uphold → T2 reproduced'], ['tier:source-checked', 'Set T1 source-checked'], ['tier:reported', 'Demote → T0 reported'], ['special:disputed', 'Keep disputed'], ['special:retracted', 'Retract']]),
    note(), h('button', { class: 'btn btn-sm btn-primary', type: 'submit' }, 'Resolve'));
  form.addEventListener('submit', async (e) => {
    e.preventDefault(); const fd = new FormData(form); const [kind, val] = String(fd.get('ruling')).split(':');
    const body = { note: String(fd.get('note') || '') }; body[kind === 'tier' ? 'tier' : 'special_status'] = val;
    if (kind === 'tier' && val === 'reproduced' && c.special_status === 'disputed') body.special_status = 'none'; // uphold = extractor wins, clears the dispute
    await act(`resolve claim ${c.id}`, `/admin/claims/${encodeURIComponent(c.id)}/resolve`, body, form.querySelector('button'));
  });
  const recheck = h('button', { class: 'btn btn-sm', type: 'button' }, 'Re-run quote check');
  recheck.addEventListener('click', () => act(`recheck ${c.id}`, `/admin/recheck/${encodeURIComponent(c.id)}`, {}, recheck));
  return h('div', { class: 'qitem' },
    h('div', { class: 'row' }, tierBadge(c), spot ? h('span', { class: 'chip' }, 'spot check') : null, h('a', { href: link.claim(c.id) }, `${c.artifact_name} × ${c.benchmark_name}`), h('span', { class: 'mono small muted' }, c.id)),
    h('p', { class: 'small mono' }, `${c.value} ${c.unit || ''} — “${String(c.quote || '').slice(0, 220)}”`),
    (c.verifications || []).length ? h('ul', { class: 'small' }, c.verifications.map(v => h('li', {}, `${v.verdict} · ${fmtDateTime(v.created_at)} · `,
      h('span', { class: 'mono' }, JSON.stringify(v.detail || {}).slice(0, 300))))) : null,
    form, h('div', {}, recheck));
}
function roundItem(c) {
  const r = c.blind_round || {};
  const item = claimItem({ ...c, verifications: r.verdicts || [] });
  item.insertBefore(h('p', { class: 'small' }, `Blind round undecided: ${r.votes?.agree ?? 0} agree · ${r.votes?.disagree ?? 0} disagree · open ${r.age_days ?? '?'} day(s)${r.overdue ? ' (overdue)' : ''}. If no other contributor can take the tie-breaker, resolve the claim here.`), item.children[1] || null);
  return item;
}
function gapItem(g) {
  const form = h('form', {}, sel('status', [['accepted', 'Accept'], ['rejected', 'Reject'], ['resolved', 'Mark resolved']]), note(), h('button', { class: 'btn btn-sm btn-primary', type: 'submit' }, 'Resolve'));
  form.addEventListener('submit', async (e) => { e.preventDefault(); const fd = new FormData(form);
    await act(`resolve gap ${g.id}`, `/admin/gaps/${encodeURIComponent(g.id)}/resolve`, { status: fd.get('status'), note: fd.get('note') }, form.querySelector('button')); });
  return h('div', { class: 'qitem' }, h('div', { class: 'row' }, h('span', { class: 'chip' }, g.layer), h('span', { class: 'chip' }, String(g.kind || '').replace(/_/g, ' ')), h('strong', {}, g.title)), h('p', { class: 'small' }, g.description), form);
}
function needsItem(x) {
  const isSub = String(x.id || '').startsWith('s_');
  const form = isSub
    ? h('form', {}, sel('status', [['verified', 'Verified'], ['rejected', 'Rejected']]), note(), h('button', { class: 'btn btn-sm btn-primary', type: 'submit' }, 'Resolve submission'))
    : h('form', {}, sel('status', [['open', 'Re-open'], ['closed', 'Close'], ['verified', 'Verified'], ['rejected', 'Rejected']]), h('button', { class: 'btn btn-sm btn-primary', type: 'submit' }, 'Set task status'));
  form.addEventListener('submit', async (e) => { e.preventDefault(); const fd = new FormData(form);
    if (isSub) await act(`resolve submission ${x.id}`, `/admin/submissions/${encodeURIComponent(x.id)}/resolve`, { status: fd.get('status'), note: fd.get('note') }, form.querySelector('button'));
    else await act(`task ${x.id} status`, `/admin/tasks/${encodeURIComponent(x.id)}/status`, { status: fd.get('status') }, form.querySelector('button')); });
  const type = x.task_type || x.type;
  return h('div', { class: 'qitem' }, h('div', { class: 'row' }, x.status ? statusPill(x.status) : null, h('span', { class: 'mono small' }, type || (isSub ? 'submission' : 'task')),
    h('a', { href: link.task(x.task_id || x.id) }, x.title || x.task_id || x.id),
    isSub ? h('span', { class: 'mono small muted' }, `${x.id}${x.contributor ? ' · by ' + x.contributor : ''}`) : null,
    !isSub && x.attempts != null ? h('span', { class: 'small muted' }, `${x.attempts} attempt(s)`) : null),
    isSub && Array.isArray(x.checks) && x.checks.length ? h('p', { class: 'small mono' }, x.checks.map(c => `${c.passed ? '✓' : '✕'} ${c.name}: ${c.detail ?? ''}`).join(' · ')) : null,
    isSub && x.payload ? h('details', {}, h('summary', { class: 'small' }, 'payload'), h('pre', { class: 'small mono', style: { whiteSpace: 'pre-wrap' } }, JSON.stringify(x.payload, null, 2).slice(0, 4000))) : null,
    form);
}
function spotItem(x) {
  const form = h('form', {}, sel('status', [['verified', 'Uphold (verified)'], ['rejected', 'Overturn (rejected)']]), note(), h('button', { class: 'btn btn-sm btn-primary', type: 'submit' }, 'Record spot check'));
  form.addEventListener('submit', async (e) => { e.preventDefault(); const fd = new FormData(form);
    await act(`spot check ${x.submission_id}`, `/admin/submissions/${encodeURIComponent(x.submission_id)}/resolve`, { status: fd.get('status'), note: fd.get('note') }, form.querySelector('button')); });
  return h('div', { class: 'qitem' },
    h('div', { class: 'row' }, h('span', { class: 'chip' }, 'spot check'), h('span', { class: 'mono small' }, x.task_type || 'submission'),
      h('a', { href: link.task(x.task_id) }, x.task_id), h('span', { class: 'mono small muted' }, `${x.submission_id} · by ${x.contributor || 'unknown'} · ${fmtDateTime(x.resolved_at || x.created_at)}`)),
    (x.claim_ids || []).length ? h('p', { class: 'small' }, 'Claims: ', (x.claim_ids || []).flatMap((id, i) => [i ? ', ' : '', h('a', { href: link.claim(id) }, id)])) : null,
    form);
}

function listBlock(title, items, fn, empty) {
  return h('section', { class: 'block' }, h('h2', {}, title, h('span', { class: 'label' }, String(items?.length || 0))),
    items?.length ? h('div', { class: 'grid', style: { gap: '10px' } }, items.map(fn)) : h('div', { class: 'empty' }, empty));
}

async function loadQueue(target) {
  mount(target, h('p', { class: 'muted' }, 'Loading queue…'));
  try {
    const q = demo ? await api('/admin/queue') : await stewardFetch('/admin/queue', { key: getKey() });
    mount(target,
      listBlock('Needs steward', q.needs_steward, needsItem, 'Nothing waiting for a ruling.'),
      listBlock('Disputed claims', q.disputed_claims, (c) => claimItem(c), 'No disputes.'),
      listBlock('Flagged claims (ambiguous table-row quote: check the column in notes)', q.flagged_claims || [], (c) => claimItem(c), 'No flagged claims.'),
      listBlock('Undecided blind rounds (tie-breaker waiting)', q.undecided_blind_rounds || [], roundItem, 'No undecided blind rounds.'),
      listBlock('Proposed gaps', q.proposed_gaps, gapItem, 'No proposed gaps.'),
      listBlock('Spot-check sample (random 10%, last 7 days)', q.spot_check_sample, spotItem, 'Nothing to sample yet.'));
  } catch (e) {
    mount(target, h('div', { class: 'error-box', role: 'alert' }, e.status === 401 || e.status === 403 ? 'That key was rejected.' : `Couldn’t load the queue: ${e.message}`));
  }
}

function invitesPanel() {
  const out = h('div', { class: 'grid', style: { gap: '8px', marginTop: '14px' } });
  const form = h('form', { class: 'toolbar' },
    h('label', { class: 'field' }, h('span', {}, 'count'), h('input', { type: 'number', name: 'count', min: '1', max: '50', value: '5' })),
    h('label', { class: 'field grow' }, h('span', {}, 'note'), h('input', { type: 'text', name: 'note', placeholder: 'e.g. friday pilot batch' })),
    h('label', { class: 'field grow' }, h('span', {}, 'person (operator)'), h('input', { type: 'text', name: 'person', maxlength: '100', placeholder: 'who runs these agents, e.g. alice' })),
    h('button', { class: 'btn btn-primary', type: 'submit' }, 'Create invites'));
  form.addEventListener('submit', async (e) => {
    e.preventDefault(); const fd = new FormData(form);
    const r = await act('create invites', '/admin/invites', { count: Math.max(1, Math.min(50, +fd.get('count') || 1)), note: String(fd.get('note') || ''), person: String(fd.get('person') || '').trim() || null }, form.querySelector('button'));
    if (r?.codes) mount(out, r.codes.map(code => { const b = h('button', { class: 'btn btn-sm', type: 'button' }, 'Copy'); b.addEventListener('click', () => copyText(String(code), b)); return h('div', { class: 'qitem', style: { gridTemplateColumns: '1fr auto', alignItems: 'center' } }, h('code', {}, String(code)), b); }));
  });
  return h('div', {}, h('p', { class: 'muted', style: { marginBottom: '12px' } }, 'Phase 0 is invite-only. Each code registers one contributor. Codes created with the same person label belong to one human, whose agents can never verify each other. Leave person empty and each code counts as a different person, so only do that for codes going to different people.'), form, out);
}

function tasksPanel() {
  const gen = h('button', { class: 'btn btn-primary', type: 'button' }, 'Run task generator');
  gen.addEventListener('click', () => act('generate tasks', '/admin/generate', {}, gen));
  const ta = h('textarea', { name: 'json', rows: '10', spellcheck: 'false', style: { fontFamily: 'var(--mono)', fontSize: '.85rem' } });
  ta.value = JSON.stringify({ type: 'map.extract', track_id: 'map-harnesses', title: 'Find published benchmark results for …', spec_md: '## Goal\n…', inputs: { artifact_id: '', artifact_name: '', layer: 'harnesses' }, allowed_model_families: ['any'], budget_minutes: 45 }, null, 2);
  const form = h('form', { class: 'grid', style: { gap: '10px' } }, h('label', { class: 'field' }, h('span', {}, 'new task (JSON)'), ta), h('div', {}, h('button', { class: 'btn', type: 'submit' }, 'Create task')));
  form.addEventListener('submit', async (e) => {
    e.preventDefault(); let body; try { body = JSON.parse(ta.value); } catch (err) { logResult('create task ✕', `Invalid JSON: ${err.message}`); return; }
    await act('create task', '/admin/tasks', body, form.querySelector('button'));
  });
  return h('div', { class: 'grid', style: { gap: '24px' } },
    h('div', {}, h('p', { class: 'muted', style: { marginBottom: '12px' } }, 'Creates map.extract for artifacts with no claims, map.profile for missing licences, a gap scan per layer if none is open, and re-verification for stale claims.'), gen),
    form);
}

function renderConsole() {
  const tabs = [['queue', 'Queue'], ['invites', 'Invites'], ['tasks', 'Tasks & generator']];
  const panel = h('div', { role: 'tabpanel', id: 'steward-panel' });
  const bar = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Steward sections' });
  const show = (id) => {
    [...bar.children].forEach(b => b.setAttribute('aria-selected', String(b.dataset.id === id)));
    panel.setAttribute('aria-labelledby', `tab-${id}`);
    if (id === 'queue') loadQueue(panel); else mount(panel, id === 'invites' ? invitesPanel() : tasksPanel());
  };
  tabs.forEach(([id, label]) => { const b = h('button', { type: 'button', role: 'tab', id: `tab-${id}`, 'data-id': id, 'aria-controls': 'steward-panel' }, label); b.addEventListener('click', () => show(id)); bar.append(b); });
  mount(con, demo ? h('p', { class: 'note warn' }, h('strong', {}, 'Example mode'), 'Showing the example queue read-only. Actions are disabled.') : null,
    bar, panel, h('h2', { class: 'label', style: { margin: '32px 0 8px' } }, h('strong', {}, 'Last result')), log);
  show('queue');
}

function refreshKeyState() {
  const k = getKey();
  forgetBtn.hidden = !k;
  keyState.textContent = demo ? 'Example mode — no key needed, nothing is sent.' : k ? `Key loaded for this tab (session only) · ${fmtDateTime(new Date().toISOString())}` : 'No key loaded.';
  if (k || demo) renderConsole(); else mount(con, h('div', { class: 'empty', style: { marginTop: '24px' } }, 'Paste the steward key to open the console. It is stored in sessionStorage for this tab only and cleared when the tab closes.'));
}
$('#key-form').addEventListener('submit', (e) => { e.preventDefault(); const v = keyInput.value.trim(); if (v) { setKey(v); keyInput.value = ''; refreshKeyState(); } });
forgetBtn.addEventListener('click', () => { setKey(''); refreshKeyState(); });
refreshKeyState();
