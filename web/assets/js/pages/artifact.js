import { SITE_NAME, initPage, api, h, $, mount, tierBadge, tierBar, link, params, showError, extLink, prettyUrl, fmtDate, state } from '../core.js';
import { claimsTable, gapCard, taskCard } from '../components.js';

initPage({ page: 'map', title: 'Artifact' });
const head = $('#art-head'), body = $('#art-body');
const id = params.get('id');

(async () => {
  if (!id) { mount(head, h('h1', {}, 'Artifact')); showError(body, { status: 404, message: 'No artifact id in the URL.' }, 'this artifact'); return; }
  let a;
  try { a = await api(`/artifacts/${encodeURIComponent(id)}`); }
  catch (e) { mount(head, h('h1', {}, 'Artifact not found')); showError(body, e, 'this artifact'); return; }
  document.title = `${a.name} · Artifact · ${SITE_NAME}`;
  const claims = a.claims || [];
  const byTier = {};
  claims.forEach(c => { const k = c.display_status || c.tier; byTier[k] = (byTier[k] || 0) + 1; });
  const verified = claims.filter(c => !c.special_status && ['reproduced', 're-run', 'replicated'].includes(c.tier)).length;

  mount(head,
    h('p', { class: 'crumbs' }, h('a', { href: 'map.html' }, 'Map'), '/', h('a', { href: link.map(a.layer) + `#layer-${encodeURIComponent(a.layer)}` }, a.layer), '/', h('span', {}, a.id)),
    h('h1', { style: { marginTop: '18px' } }, a.name),
    a.description ? h('p', { class: 'lede' }, a.description) : null,
    h('div', { class: 'art-meta' },
      h('span', { class: 'chip' }, a.kind), h('span', { class: 'chip' }, `layer: ${a.layer}`),
      a.license ? h('span', { class: 'chip' }, `licence: ${a.license}`) : h('span', { class: 'chip', style: { borderStyle: 'dashed' }, title: 'Unknown — a map.profile task can fill it' }, 'licence: unknown'),
      a.open_weights === 1 || a.open_weights === true ? h('span', { class: 'chip' }, 'open weights') : null,
      a.latest_version ? h('span', { class: 'chip' }, `latest ${a.latest_version}${a.latest_release_date ? ' · ' + fmtDate(a.latest_release_date) : ''}`) : null,
      a.best_tier ? tierBadge(a.best_tier) : null),
    h('div', { class: 'art-links' },
      a.url ? extLink(a.url, `↗ ${prettyUrl(a.url)}`) : null,
      a.repo_url && a.repo_url !== a.url ? extLink(a.repo_url, `↗ repo`) : null));

  const main = h('div', {},
    h('section', { class: 'block' }, h('h2', {}, 'Claims', h('span', { class: 'label' }, `${claims.length} total · ${verified} verified`)),
      claims.length ? claimsTable(claims, { showArtifact: false }) : h('div', { class: 'empty' }, 'No claims yet. This is a gap: a ', h('code', {}, 'map.extract'), ' task can find published results for it.')),
    h('section', { class: 'block' }, h('h2', {}, 'Gaps', h('span', { class: 'label' }, 'missing evidence and capabilities')),
      a.gaps?.length ? h('div', { class: 'gaps' }, a.gaps.map(gapCard)) : h('div', { class: 'empty' }, 'No gaps recorded for this artifact.')),
    h('section', { class: 'block' }, h('h2', {}, 'Tasks', h('span', { class: 'label' }, 'on the Board')),
      a.tasks?.length ? h('div', { class: 'grid grid-2', style: { gap: '10px' } }, a.tasks.map(t => taskCard(t))) : h('div', { class: 'empty' }, 'No tasks for this artifact right now.')));

  const aside = h('aside', {},
    h('div', { class: 'panel' }, h('div', { class: 'panel-head' }, h('span', { class: 'label' }, h('strong', {}, 'Evidence profile'))),
      h('div', { class: 'panel-body' }, claims.length ? tierBar(byTier) : h('p', { class: 'small muted' }, 'Nothing on record yet.'))),
    h('div', { class: 'panel' }, h('div', { class: 'panel-body' }, h('dl', { class: 'kv' },
      h('dt', {}, 'id'), h('dd', { class: 'mono small' }, a.id),
      h('dt', {}, 'source'), h('dd', { class: 'small' }, a.source || '—'),
      h('dt', {}, 'updated'), h('dd', {}, fmtDate(a.updated_at))))),
    state.mock ? h('p', { class: 'note warn' }, h('strong', {}, 'Example data'), 'The project is real; its claims, values and tasks here are illustrative fixtures.') : null);
  mount(body, main, aside);
})();
