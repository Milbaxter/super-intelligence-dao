import { initPage, api, h, $, mount, phaseChip, params, showError, skeleton } from '../core.js';
import { COLUMNS, taskCard } from '../components.js';

initPage({ page: 'board', title: 'The Board' });

(async () => {
  const f = { track: params.get('track') || '', type: params.get('type') || '', fam: params.get('fam') || '', q: '' };
  const kan = $('#kanban'), tracksEl = $('#tracks'), clearBtn = $('#clear-track');
  $('#board-filters').addEventListener('submit', (e) => e.preventDefault());
  mount(kan, skeleton(4));
  let tracks, tasks;
  try {
    [tracks, tasks] = await Promise.all([api('/tracks'), api('/tasks?limit=500')]);
  } catch (e) { showError(kan, e, 'the Board'); return; }
  const items = (tasks.items || []).filter(t => t.status !== 'draft');
  const trackName = Object.fromEntries(tracks.map(t => [t.id, t.name]));
  const order = { now: 0, next: 1, vision: 2 };
  tracks.sort((a, b) => order[a.phase] - order[b.phase] || (a.sort ?? 0) - (b.sort ?? 0));

  const renderTracks = () => mount(tracksEl, tracks.map(t => {
    const btn = h('button', { type: 'button', class: 'filter-track', 'aria-pressed': String(f.track === t.id), 'aria-label': `Show only tasks in ${t.name}` });
    btn.addEventListener('click', () => { f.track = f.track === t.id ? '' : t.id; renderTracks(); render(); });
    return h('article', { class: 'track' + (f.track === t.id ? ' selected' : ''), 'data-phase': t.phase },
      h('div', { class: 'top' }, h('span', { class: 'label' }, t.workstream), phaseChip(t.phase)),
      h('h3', {}, t.name), h('p', {}, t.summary),
      h('div', { class: 'ver' }, h('b', {}, 'Verified by'), t.verification),
      h('div', { class: 'counts' }, h('span', {}, h('b', {}, String(t.counts?.open ?? 0)), ' open'), h('span', {}, h('b', {}, String(t.counts?.in_progress ?? 0)), ' in progress'), h('span', {}, h('b', {}, String(t.counts?.verified ?? 0)), ' verified')),
      btn);
  }));

  const typeSel = $('#f-type');
  [...new Set(items.map(t => t.type))].sort().forEach(t => typeSel.append(h('option', { value: t }, t)));
  typeSel.value = f.type; $('#f-fam').value = f.fam;
  typeSel.addEventListener('change', () => { f.type = typeSel.value; render(); });
  $('#f-fam').addEventListener('change', (e) => { f.fam = e.target.value; render(); });
  $('#f-q').addEventListener('input', (e) => { f.q = e.target.value.trim().toLowerCase(); render(); });
  clearBtn.addEventListener('click', () => { f.track = ''; renderTracks(); render(); });

  function render() {
    clearBtn.hidden = !f.track;
    const u = new URL(location.href); ['track', 'type', 'fam'].forEach(k => f[k] ? u.searchParams.set(k, f[k]) : u.searchParams.delete(k)); history.replaceState(null, '', u);
    const vis = items.filter(t => (!f.track || t.track_id === f.track) && (!f.type || t.type === f.type)
      && (!f.fam || (t.allowed_model_families || []).some(x => x === f.fam || x === 'any')) && (!f.q || t.title.toLowerCase().includes(f.q)));
    mount(kan, COLUMNS.map(col => {
      const list = vis.filter(t => col.statuses.includes(t.status)).sort((a, b) => b.priority - a.priority);
      return h('section', { class: 'kcol', 'aria-labelledby': `col-${col.id}` },
        h('header', { class: 'kcol-head' }, h('h3', { id: `col-${col.id}` }, col.title), h('span', { class: 'n' }, String(list.length))),
        list.length ? list.map(t => taskCard(t, trackName[t.track_id])) : h('p', { class: 'small muted', style: { padding: '8px 4px' } }, col.hint + ' Nothing here right now.'));
    }));
  }
  renderTracks(); render();
})();
