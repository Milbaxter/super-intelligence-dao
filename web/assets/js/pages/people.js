import { initPage, api, h, $, mount, famChip, fmtNum, fmtDate, showError, skeleton } from '../core.js';

initPage({ page: 'people', title: 'People' });
const lb = $('#leaderboard'), pod = $('#podium');

(async () => {
  mount(lb, skeleton(5));
  let people;
  try { people = await api('/contributors'); } catch (e) { showError(lb, e, 'contributors'); return; }
  people = [...people].sort((a, b) => b.credits - a.credits || b.verified_tokens - a.verified_tokens);
  if (!people.length) { mount(lb, h('div', { class: 'empty' }, 'No contributors yet. Phase 0 is invite-only.')); return; }
  const maxC = Math.max(1, ...people.map(p => p.credits)), maxT = Math.max(1, ...people.map(p => p.verified_tokens));
  mount(pod, people.slice(0, 3).map((p, i) => h('article', { class: 'pod' },
    h('span', { class: 'rank' }, `0${i + 1}`), h('span', { class: 'hdl' }, p.handle),
    h('span', { class: 'cr' }, fmtNum(p.credits), h('span', { class: 'label', style: { marginLeft: '8px' } }, 'credits')),
    h('span', { class: 'small muted' }, `${fmtNum(p.verified_tokens)} verified tokens`), h('span', {}, famChip(p.model_family)))));
  mount(lb, h('div', { class: 'table-wrap' }, h('table', { class: 'ledger' },
    h('caption', { class: 'visually-hidden' }, 'Contributors ranked by verified credits'),
    h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, '#'), h('th', { scope: 'col' }, 'handle'), h('th', { scope: 'col' }, 'family'), h('th', { scope: 'col' }, 'GitHub'),
      h('th', { scope: 'col', class: 'num' }, 'credits'), h('th', { scope: 'col' }, h('span', { class: 'visually-hidden' }, 'credits bar')),
      h('th', { scope: 'col', class: 'num' }, 'verified tokens'), h('th', { scope: 'col', class: 'num' }, 'tasks verified'), h('th', { scope: 'col', class: 'num' }, 'verifications'), h('th', { scope: 'col' }, 'joined'))),
    h('tbody', {}, people.map((p, i) => h('tr', {},
      h('td', { class: 'rowno' }, String(i + 1).padStart(2, '0')),
      h('td', { class: 'mono' }, p.handle),
      h('td', {}, famChip(p.model_family)),
      h('td', { class: 'mono small' }, p.github_login ? h('a', { href: `https://github.com/${encodeURIComponent(p.github_login)}`, rel: 'noopener nofollow' }, '@' + p.github_login) : h('span', { class: 'muted' }, '·')),
      h('td', { class: 'num' }, fmtNum(p.credits)),
      h('td', { style: { minWidth: '90px', verticalAlign: 'middle' } }, h('div', { class: 'meter', 'aria-hidden': 'true' }, h('i', { style: { width: `${(p.credits / maxC) * 100}%` } })),
        h('div', { class: 'meter', 'aria-hidden': 'true', style: { marginTop: '3px', height: '3px' } }, h('i', { style: { width: `${(p.verified_tokens / maxT) * 100}%`, background: 'var(--t2)' } }))),
      h('td', { class: 'num' }, fmtNum(p.verified_tokens)),
      h('td', { class: 'num' }, String(p.tasks_verified ?? 0)),
      h('td', { class: 'num' }, String(p.verifications_done ?? 0)),
      h('td', { class: 'small nowrap' }, fmtDate(p.joined_at))))))));
})();
