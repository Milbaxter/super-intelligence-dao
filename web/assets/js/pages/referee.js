import { initPage, api, h, $, mount, tierLadder, tierBar, tierBadge, SPECIAL, state } from '../core.js';

initPage({ page: 'referee', title: 'The Referee' });

// Big ladder: show the full ladder with rung descriptions, "reached" up to the highest live tier.
const ladder = tierLadder({ current: 'reproduced' });
ladder.querySelector('[aria-current]')?.removeAttribute('aria-current');
ladder.querySelectorAll('.rung.current').forEach(r => r.classList.remove('current'));
mount($('#big-ladder'), h('p', { class: 'label', style: { marginBottom: '10px' } }, h('strong', {}, 'Filled rungs'), ' = running in Phase 0'), ladder);

mount($('#special-states'), Object.values(SPECIAL).map(s => h('div', { class: 'card', 'data-tier': s.id, style: { display: 'grid', gap: '8px', borderLeft: '4px solid var(--tc)' } },
  h('div', {}, tierBadge(s.id)), h('p', { class: 'small' }, s.short))));

(async () => {
  try {
    const s = await api('/stats');
    mount($('#live-tiers'), tierBar(s.claims_by_tier || {}));
    mount($('#live-state'), state.mock ? 'example data' : 'live');
  } catch { mount($('#live-tiers'), h('p', { class: 'small muted' }, 'Live counts unavailable.')); }
})();
