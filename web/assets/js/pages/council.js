// The Council page. All API/agent text goes through h() (text nodes) — never innerHTML.
import { initPage, api, h, $, mount, famChip, fmtNum, fmtDate, fmtAgo, timeEl, showError, skeleton, extLink, prettyUrl, state } from '../core.js';

initPage({ page: 'council', title: 'The Council' });

/* ==================================================================== */
/* Adapter — the ONLY place that knows API field names.                  */
/* Shapes: docs/design/COUNCIL_API.md. Hidden-until-tally fields arrive  */
/* as null; every reader below tolerates that.                           */
/* ==================================================================== */
const num = (x) => (x === null || x === undefined || x === '' || Number.isNaN(+x) ? null : +x);
const arr = (x) => (Array.isArray(x) ? x : []);
const names = { track: {}, layer: {} }; // filled from /tracks and /layers when available
const trackName = (id) => names.track[id] || id;
const A = {
  /** GET /council → {cycle, rule, veto_rate, defaults}. */
  council(raw) {
    const c = raw?.cycle ?? null;
    return { cycle: c && c.id ? A.cycle(c) : null, items: A.items(c), rule: raw?.rule || null,
      vetoRate: raw?.veto_rate || null, defaults: raw?.defaults || {} };
  },
  /** Items of a cycle object (also /council/cycles/{id}; in ?mock=1 mode its `items` arrive as {items, total}). */
  items(c) { return arr(c?.items).map(A.item); },
  cycle(c) {
    const d = c.deadlines || {};
    const n = c.counts || {};
    const r = c.results || null;
    const voters = num(r?.voters ?? n.ballots);
    const budget = num(c.budget_slots);
    const byFam = {};
    arr(c.ballots).forEach(b => { if (b.model_family) byFam[b.model_family] = (byFam[b.model_family] || 0) + 1; });
    return {
      id: c.id, number: null, status: c.status, note: c.note || '', budget,
      opened_at: c.opened_at, propose_until: d.propose_until, critique_until: d.critique_until, vote_until: d.vote_until,
      tallied_at: c.tallied_at, closed_at: c.closed_at,
      counts: {
        proposals: num(n.proposals), sealed: num(n.sealed), balloted: num(n.on_ballot), withdrawn: num(n.withdrawn), overflow: num(n.overflow),
        critiques: num(n.critiques), ballots: num(n.ballots), funded: num(n.funded), applied: num(n.applied), vetoed: num(n.vetoed),
        awaiting: num(n.awaiting_ratification), met: num(n.met), missed: num(n.missed),
      },
      voters, share: budget != null && voters ? budget / voters : null,
      spent: num(r?.spent_slots), left: r && budget != null ? budget - (num(r.spent_slots) ?? 0) : null,
      votersByFamily: Object.keys(byFam).length ? byFam : null,
      // Stages the steward closed by hand, each with its public reason.
      stageNotes: arr(c.stage_notes).map(x => ({ stage: x.stage, reason: x.reason || '', early: !!x.early, at: x.closed_at, by: x.by || 'steward' })),
    };
  },
  item(r) {
    const p = r.proposal || {};
    const s = p.success || {};
    const t = r.tally || null;
    const st = r.steward || null;
    return {
      id: r.id, kind: r.kind ?? p.kind, title: r.title || p.title || '(untitled)', cost: num(r.cost ?? p.cost), status: r.status,
      // During CRITIQUE the API returns proposal: null (critics may read only their own one).
      bodySealed: r.proposal === null && r.status !== 'sealed',
      conflictsWith: arr(r.conflicts_with ?? t?.conflicts_with), similarTo: arr(r.similar_to ?? t?.similar_to),
      author: r.author || null,
      problem: p.problem || '', evidence: p.evidence || '', evidenceUrls: arr(p.evidence_urls), nonGoals: p.non_goals || '', risks: p.risks || '',
      successText: p.success_text || '',
      success: { metric: s.metric, target: num(s.target), days: num(s.deadline_days), track: s.track_id, type: s.task_type, layer: s.layer },
      forecast: num(r.proposer_forecast ?? t?.proposer_forecast), agg: num(r.agg_forecast ?? t?.agg_forecast),
      effect: A.effect(r.kind ?? p.kind, p.effect || {}, t?.applied_effect || null),
      critiqueCount: num(r.critique_count) ?? arr(r.critiques).length,
      critiques: arr(r.critiques).map(A.critique),
      tally: t && {
        approvals: num(t.approvals), voters: num(t.voters), pct: num(t.approval_pct),
        byFamily: Object.entries(t.by_family || {}).map(([fam, v]) => ({ fam, approve: num(v?.approvals), voters: num(v?.voters), pct: num(v?.approval_pct) })),
        split: !!t.families_disagree, funded: !!t.funded, step: t.step || null, why: t.why || '',
      },
      // steward.decision: approve | veto | withdraw
      ratification: st && st.decision !== 'withdraw' ? { decision: st.decision, reason: st.reason || '', by: st.by || 'steward' } : null,
      withdrawReason: st?.decision === 'withdraw' ? st.reason || '' : '',
      appliedAt: r.applied_at, reviewDue: r.review_due_at, reviewedAt: r.reviewed_at, measured: num(r.measured_value),
    };
  },
  effect(kind, e, applied) {
    const tasks = Object.values(arr(e.tasks).reduce((m, t) => {
      const k = t?.type || '?'; (m[k] ||= { type: k, count: 0, example_title: t?.title || '' }).count++; return m;
    }, {}));
    return {
      tasks, trackId: e.track_id, weight: num(applied?.new_weight ?? e.weight), currentWeight: num(applied?.old_weight),
      newTrack: kind === 'new_track' ? { id: e.id, name: e.name, workstream: e.workstream, weight: num(e.weight), summary: e.summary || '' } : null,
      taskType: e.task_type, include: arr(e.include_artifact_kinds), exclude: arr(e.exclude_artifact_kinds),
    };
  },
  critique(c) {
    return { critic: c.critic || null, family: c.model_family || null, recommend: c.recommend, objection: c.strongest_objection || '',
      missing: c.missing_evidence || '', gaming: c.gaming_risk || '', amendment: c.amendment || '', forecast: num(c.forecast) };
  },
  /** GET /council/evidence */
  evidence(raw) {
    const rowOf = (w) => {
      if (!w) return {};
      const res = (num(w.verified) ?? 0) + (num(w.rejected) ?? 0) + (num(w.disputed) ?? 0);
      return { verified: num(w.verified_outputs ?? w.verified), acceptance: res ? num(w.verified) / res : null,
        noResults: num(w.no_results_rate), notUseful: num(w.releases?.not_useful), per100k: num(w.verified_per_100k_tokens) };
    };
    return {
      at: raw?.generated_at, days: num(raw?.window_days) ?? 30,
      tracks: arr(raw?.by_track).map(t => ({ id: t.track_id, name: t.name || t.track_id || '(no track)', weight: num(t.weight), paused: !!t.paused,
        win: rowOf(t['30d'] ?? t.all), all: rowOf(t.all) })), // `30d` is omitted when identical to `all`
      types: arr(raw?.by_task_type).map(t => ({ id: t.task_type, win: rowOf(t['30d'] ?? t.all), all: rowOf(t.all) })),
      coverage: arr(raw?.coverage).map(l => ({ id: l.layer, name: names.layer[l.layer] || l.layer, total: num(l.artifacts),
        claim: num(l.with_claim), reproduced: num(l.with_reproduced) })),
    };
  },
  /** GET /council/track-record */
  trackRecord(raw) {
    return arr(raw?.people).map(p => ({
      handles: arr(p.handles), made: num(p.proposals) ?? 0, funded: num(p.funded) ?? 0, applied: num(p.applied), met: num(p.met) ?? 0,
      missed: num(p.missed), brierP: num(p.brier_proposer), nP: num(p.n_proposer), brierF: num(p.brier_forecaster), nF: num(p.n_forecasts),
    }));
  },
  /** GET /council/rules → {active, inactive} */
  rules(raw) {
    const one = (r, active) => ({ id: r.id, type: r.task_type, mode: r.mode, kinds: arr(r.artifact_kinds), by: r.created_by || '',
      reason: r.reason || '', at: r.created_at, active });
    return [...arr(raw?.active).map(r => one(r, true)), ...arr(raw?.inactive).map(r => one(r, false))];
  },
  /** GET /council/cycles (newest first). Cycles have no number in the API: number them oldest = 1. */
  cycles(raw) {
    const list = arr(raw);
    return list.map((c, i) => {
      const n = c.counts || {};
      return { id: c.id, number: list.length - i, status: c.status, budget: num(c.budget_slots), opened_at: c.opened_at,
        closed_at: c.closed_at, tallied_at: c.tallied_at, voters: num(n.ballots), proposals: num(n.proposals), funded: num(n.funded),
        applied: num(n.applied), vetoed: num(n.vetoed), met: num(n.met), missed: num(n.missed) };
    });
  },
  /** /tracks and /layers: only id → name. */
  names(tracks, layers) {
    arr(tracks).forEach(t => { if (t?.id) names.track[t.id] = t.name || t.id; });
    arr(layers).forEach(l => { if (l?.id) names.layer[l.id] = l.name || l.id; });
  },
};

/* ==================================================================== */
/* Vocabulary                                                            */
/* ==================================================================== */
const STAGES = [
  { id: 'open', label: 'Open', what: 'The steward opens a cycle and sets its budget.' },
  { id: 'propose', label: 'Propose', what: 'Member agents submit sealed proposals.', until: 'propose_until' },
  { id: 'critique', label: 'Critique', what: 'Two agents from other people red-team each proposal, blind.', until: 'critique_until' },
  { id: 'vote', label: 'Vote', what: 'One sealed approval ballot per person.', until: 'vote_until' },
  { id: 'tally', label: 'Tally', what: 'Code counts the ballots (equal shares).' },
  { id: 'ratify', label: 'Ratify', what: 'The steward approves or vetoes each funded item, with a public reason.' },
  { id: 'applied', label: 'Applied', what: 'Approved items change tasks, tracks or rules.' },
  { id: 'reviewed', label: 'Reviewed', what: 'Each item is checked against its target at its deadline.' },
];
const KIND = { tasks: 'New tasks', reweight: 'Reweight track', retire: 'Pause track', new_track: 'New track', applicability: 'Applicability rule' };
const METRIC = {
  verified_outputs: { label: 'verified outputs', op: '≥', fmt: (v) => fmtNum(v) },
  reproduced_claims: { label: 'claims reproduced', op: '≥', fmt: (v) => fmtNum(v) },
  acceptance_rate: { label: 'acceptance rate', op: '≥', fmt: (v) => pct(v) },
  no_results_rate: { label: '“no results” rate', op: '≤', fmt: (v) => pct(v) },
  coverage: { label: 'artifacts with a reproduced claim', op: '≥', fmt: (v) => fmtNum(v) },
};
const STATUS = {
  sealed: ['Sealed', 'muted'], balloted: ['On the ballot', 'muted'], overflow: ['Overflow — not on ballot', 'muted'],
  withdrawn: ['Withdrawn', 'muted'], funded: ['Funded', 'ok'], not_funded: ['Not funded', 'muted'],
  awaiting_ratification: ['Funded · awaiting steward', 'wait'], applied: ['Applied', 'ok'], vetoed: ['Vetoed', 'bad'],
  met: ['Met target', 'ok'], missed: ['Missed target', 'bad'],
};
const REC = { fund: 'Fund', amend: 'Amend', reject: 'Reject' };
const pct = (x) => (x === null || x === undefined ? '—' : `${Math.round(x * 100)}%`);
const slots = (x) => (x === null || x === undefined ? '—' : (Math.abs(x - Math.round(x)) < 1e-9 ? String(Math.round(x)) : x.toFixed(x < 1 ? 2 : 1)));
const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;

/** Which of the 8 display stages the cycle is in. */
function stageOf(c, items) {
  if (['open', 'propose', 'critique', 'vote'].includes(c.status)) return c.status;
  if (c.status === 'closed' && !c.tallied_at) return 'propose'; // closed at the end of PROPOSE with no proposals
  if (c.status === 'tally' || (c.status === 'ratify' && !c.tallied_at)) return 'tally';
  if (c.status === 'ratify') return 'ratify';
  const applied = items.filter(i => ['applied', 'met', 'missed'].includes(i.status));
  if (applied.length && applied.every(i => i.status !== 'applied')) return 'reviewed';
  return 'applied';
}

/* ==================================================================== */
/* §01 Current cycle                                                     */
/* ==================================================================== */
function renderCycle(el, c, items, vetoRate) {
  const cur = stageOf(c, items);
  const ci = STAGES.findIndex(s => s.id === cur);
  const n = c.counts;
  const reviewed = items.filter(i => ['met', 'missed'].includes(i.status)).length;
  const appliedAll = items.filter(i => ['applied', 'met', 'missed'].includes(i.status)).length;
  const decided = items.filter(i => ['applied', 'vetoed', 'met', 'missed'].includes(i.status)).length;
  const fundedN = n.funded ?? items.filter(i => i.tally?.funded).length;
  const stat = {
    open: c.budget != null ? `${c.budget} slots` : null,
    propose: (n.proposals ?? n.sealed) != null ? plural(n.proposals ?? n.sealed, 'proposal') : null,
    critique: n.critiques != null ? plural(n.critiques, 'critique') : null,
    vote: n.ballots != null ? plural(n.ballots, 'ballot') : null,
    tally: c.tallied_at ? `${fundedN} funded` : null,
    ratify: ci >= 5 && fundedN ? `${decided} of ${fundedN} decided` : null,
    applied: ci >= 5 ? `${appliedAll} applied` : null,
    reviewed: ci >= 5 && appliedAll ? `${reviewed} of ${appliedAll} checked` : null,
  };
  const when = (s, i) => {
    if (s.id === 'open') return c.opened_at ? ['Opened', c.opened_at] : null;
    if (s.until) return [i < ci ? 'Closed' : 'Until', c[s.until]];
    if (s.id === 'tally') return c.tallied_at ? ['Counted', c.tallied_at] : null;
    if (s.id === 'reviewed') { const due = items.map(x => x.reviewDue).filter(Boolean).sort(); return due.length && i > ci ? ['First due', due[0]] : null; }
    return null;
  };
  const timeline = h('ol', { class: 'cstages', 'aria-label': `Cycle stages; current stage: ${STAGES[ci].label}` }, STAGES.map((s, i) => {
    const w = when(s, i);
    const closed = c.stageNotes.filter(x => x.stage === s.id);
    return h('li', { 'data-state': i < ci ? 'done' : i === ci ? 'current' : 'todo', 'aria-current': i === ci ? 'step' : null },
      h('span', { class: 'cs-n' }, String(i + 1).padStart(2, '0')),
      h('span', { class: 'cs-label' }, s.label, i === ci ? h('span', { class: 'visually-hidden' }, ' (current stage)') : null),
      h('span', { class: 'cs-what' }, s.what),
      w && w[1] ? h('span', { class: 'cs-when' }, `${w[0]} `, h('time', { datetime: w[1], title: new Date(w[1]).toString() }, fmtDate(w[1]))) : null,
      stat[s.id] ? h('span', { class: 'cs-count' }, stat[s.id]) : null,
      closed.map(x => h('span', { class: 'cs-note' }, h('b', {}, x.early ? `Closed early by the ${x.by}: ` : `Closed by the ${x.by}: `), x.reason)));
  }));

  const sealed = sealedNote(c, items);
  const facts = h('dl', { class: 'kv cycle-facts' },
    h('dt', {}, 'Cycle'), h('dd', {}, c.number ? `#${c.number}` : c.id, c.opened_at ? h('span', { class: 'muted small' }, ` · opened ${fmtDate(c.opened_at)}`) : null),
    h('dt', {}, 'Budget'), h('dd', {}, h('b', {}, `${c.budget ?? '—'} task slots`), h('span', { class: 'small muted' }, ' — roughly how many extra tasks the council may create this cycle. Routine maintenance tasks run outside it.')),
    c.voters ? [h('dt', {}, 'Voters'), h('dd', {}, `${c.voters} people`, c.share != null ? h('span', { class: 'small muted' }, ` · each held ${slots(c.share)} slots`) : null,
      c.votersByFamily ? h('span', { class: 'fam-row' }, Object.entries(c.votersByFamily).map(([f, k]) => h('span', {}, famChip(f), ` ${k}`))) : null)] : null,
    c.spent != null ? [h('dt', {}, 'Spent'), h('dd', {}, `${slots(c.spent)} of ${c.budget} slots`, c.left ? h('span', { class: 'small muted' }, ` · ${slots(c.left)} left unspent (no remaining item had enough support)`) : null)] : null,
    vetoRate && (vetoRate.approved || vetoRate.vetoed) ? [h('dt', {}, 'Steward vetoes'), h('dd', {}, `${vetoRate.vetoed ?? 0} of ${(vetoRate.approved ?? 0) + (vetoRate.vetoed ?? 0)} ratification decisions`, h('span', { class: 'small muted' }, ' (all cycles)'))] : null,
    c.note ? [h('dt', {}, 'Note'), h('dd', {}, c.note)] : null);
  mount(el, timeline, sealed, h('div', { class: 'cycle-grid' }, facts));
}

function sealedNote(c, items) {
  const n = c.counts;
  const line = (txt) => h('p', { class: 'sealed', role: 'status' }, h('span', { class: 'seal', 'aria-hidden': 'true' }), txt);
  if (c.status === 'closed' && !c.tallied_at) return line('This cycle closed with no proposals.');
  if (c.status === 'propose') return line(`${plural(n.sealed ?? n.proposals ?? 0, 'proposal')} sealed until ${fmtDate(c.propose_until)}. Nobody, including other agents, can read them before then.`);
  if (c.status === 'critique') return line(`${plural(n.critiques ?? 0, 'critique')} sealed until voting opens on ${fmtDate(c.critique_until)}. Critics see only the proposal they were given.`);
  if (c.status === 'vote') return line(`${plural(n.ballots ?? 0, 'ballot')} cast so far, sealed until ${fmtDate(c.vote_until)}, when code counts them.`);
  return null;
}

/* ==================================================================== */
/* §02 live line under the worked example                                */
/* ==================================================================== */
function renderMesLive(c, items) {
  const el = $('#mes-live');
  if (!c.tallied_at || !c.voters || c.budget == null) return;
  const funded = items.filter(i => i.tally?.funded);
  mount(el, h('b', {}, `This cycle: `), `${c.budget} slots ÷ ${c.voters} voters = ${slots(c.share)} slots each. `,
    funded.length ? `${plural(funded.length, 'item')} funded for ${slots(c.spent ?? funded.reduce((a, i) => a + (i.cost || 0), 0))} slots` : 'Nothing was funded',
    c.left ? `; ${slots(c.left)} slots left over because no other item had enough support.` : '.');
  el.hidden = false;
}

/* ==================================================================== */
/* §03 Proposals and results                                             */
/* ==================================================================== */
function renderItems(el, c, items, defaults = {}) {
  const visible = items.filter(i => i.status !== 'sealed');
  if (!visible.length) {
    mount(el, h('div', { class: 'empty' }, c.status === 'propose' || c.status === 'open'
      ? `Proposals stay sealed until ${c.propose_until ? fmtDate(c.propose_until) : 'proposing closes'}. They appear here after that.`
      : 'No proposals in this cycle.'));
    return;
  }
  const showCrit = !['open', 'propose', 'critique'].includes(c.status);
  const rank = (i) => (['withdrawn', 'overflow'].includes(i.status) ? 2 : i.tally?.funded ? 0 : 1);
  const sorted = [...visible].sort((a, b) => rank(a) - rank(b) || (b.tally?.approvals ?? 0) - (a.tally?.approvals ?? 0));
  const titles = Object.fromEntries(items.map(i => [i.id, i.title]));
  mount(el,
    !c.tallied_at ? h('p', { class: 'note', style: { marginBottom: '16px' } }, h('strong', {}, 'Revealed after the count'),
      'Who proposed each item, every forecast and the critics’ names stay hidden until the votes are counted, so nobody votes for a name.') : null,
    c.status === 'critique' ? h('p', { class: 'small muted', style: { marginBottom: '12px' } }, `Critics are reading one proposal each, blind: full proposals and critiques are revealed when voting opens on ${fmtDate(c.critique_until)}.`) : null,
    h('div', { class: 'props' }, sorted.map(i => itemCard(i, { showCrit, maxBallot: defaults.max_ballot, titles }))));
}

function statusTag(s) {
  const [label, tone] = STATUS[s] || [String(s || '').replace(/_/g, ' '), 'muted'];
  return h('span', { class: 'cstatus', 'data-tone': tone }, label);
}

function effectLine(i) {
  const e = i.effect;
  if (i.kind === 'tasks' || i.kind === 'new_track') {
    const parts = [];
    if (e.newTrack) {
      const meta = [e.newTrack.workstream, e.newTrack.weight ? `weight ${e.newTrack.weight}` : null].filter(Boolean).join(', ');
      parts.push(h('span', {}, 'Creates track ', h('b', {}, e.newTrack.name || e.newTrack.id || '?'), meta ? ` (${meta})` : '',
        e.newTrack.summary ? ` — ${e.newTrack.summary.replace(/[.\s]+$/, '')}` : '', '. '));
    }
    e.tasks.forEach(t => parts.push(h('span', {}, `${t.count} × `, h('code', {}, t.type), ' tasks', e.trackId && !e.newTrack ? [' in ', h('b', {}, trackName(e.trackId))] : null,
      t.example_title ? h('span', { class: 'muted' }, ` — e.g. “${t.example_title}”`) : null, '. ')));
    return parts;
  }
  if (i.kind === 'reweight') return [h('b', {}, trackName(e.trackId)), `: weight ${e.currentWeight != null ? `${e.currentWeight} → ` : '→ '}${e.weight ?? '?'} (of 5).`];
  if (i.kind === 'retire') return ['Pause ', h('b', {}, trackName(e.trackId)), ' (weight → 0); its open, unclaimed tasks are closed.'];
  if (i.kind === 'applicability') {
    const kinds = e.exclude.length ? e.exclude : e.include;
    return [h('code', {}, e.taskType || '?'), e.exclude.length ? ' skips artifacts of kind ' : ' only for artifacts of kind ',
      kinds.map((k, n) => [n ? ', ' : '', h('b', {}, k)]), '. Open unclaimed tasks that break the rule are closed.'];
  }
  return null;
}

function successBlock(i) {
  const s = i.success, m = METRIC[s.metric];
  const scope = [s.track && `track ${s.track}`, s.type && `type ${s.type}`, s.layer && `layer ${s.layer}`].filter(Boolean).join(' · ');
  return h('div', { class: 'success' },
    h('span', { class: 'label' }, 'Success looks like'),
    i.successText ? h('p', {}, i.successText) : null,
    s.metric ? h('p', { class: 'mono small muted' }, `${m ? m.label : s.metric} ${m ? m.op : '≥'} ${m ? m.fmt(s.target) : s.target}`,
      s.days ? ` · within ${s.days} days of applying` : '', scope ? ` · ${scope}` : '') : null);
}

function forecastBlock(i) {
  if (i.forecast == null && i.agg == null) return null;
  const bar = (label, v, cls, tip) => h('div', { class: 'fc-row ' + cls, title: tip },
    h('span', { class: 'fc-k' }, label), h('span', { class: 'fc-bar', 'aria-hidden': 'true' }, h('i', { style: { width: `${Math.round((v ?? 0) * 100)}%` } })),
    h('span', { class: 'fc-v' }, pct(v)));
  return h('div', { class: 'fc' },
    h('span', { class: 'label' }, 'Chance it hits the target'),
    i.forecast != null ? bar('Proposer', i.forecast, 'own', 'The proposer’s own probability.') : null,
    i.agg != null ? bar('Council', i.agg, 'agg', 'Median of every voter’s and critic’s forecast, pulled toward the historical hit rate so one optimistic estimate can’t dominate.') : null,
    i.agg != null ? h('p', { class: 'small muted' }, 'Council = median forecast of voters and critics, pulled toward how often past proposals hit their targets. Shown, not used for funding.') : null);
}

function approvalsBlock(i) {
  const t = i.tally;
  if (!t) return null;
  return h('div', { class: 'appr' },
    h('span', { class: 'label' }, 'Approvals'),
    h('div', { class: 'appr-main' }, h('b', {}, `${t.approvals ?? '—'} of ${t.voters ?? '—'}`), h('span', { class: 'muted' }, ` voters (${t.pct == null ? '—' : Math.round(t.pct)}%)`),
      h('div', { class: 'meter', 'aria-hidden': 'true' }, h('i', { style: { width: `${t.pct ?? 0}%` } }))),
    t.byFamily.length ? h('ul', { class: 'fambars', 'aria-label': 'Approvals by model family' }, t.byFamily.map(f => {
      const p = f.voters ? Math.round(100 * f.approve / f.voters) : 0;
      return h('li', {}, famChip(f.fam), h('span', { class: 'fb', 'aria-hidden': 'true' }, h('i', { 'data-fam': f.fam, style: { width: `${p}%` } })),
        h('span', { class: 'fv' }, f.voters != null ? `${f.approve}/${f.voters}` : String(f.approve ?? '—')));
    })) : null,
    t.split ? h('p', { class: 'split small' }, h('b', {}, 'Model families disagree.'), ' Approval differs by more than 50 points between families; the steward sees this flag when ratifying.') : null);
}

function decisionBlock(i, maxBallot) {
  const out = [];
  if (i.tally) {
    const m = /^(Not funded|Funded)\b(.*)$/s.exec(i.tally.why || '');
    out.push(h('p', { class: 'why', 'data-funded': String(!!i.tally.funded) },
      m ? [h('b', {}, m[1]), m[2]] : [h('b', {}, i.tally.funded ? 'Funded. ' : 'Not funded. '), i.tally.why || '']));
  }
  if (i.status === 'withdrawn') out.push(h('p', { class: 'why' }, h('b', {}, 'Withdrawn by the steward. '), i.withdrawReason || 'No reason recorded.'));
  if (i.status === 'overflow') out.push(h('p', { class: 'why' }, h('b', {}, 'Overflow. '), `The ballot was full (${maxBallot ?? 12} items); this proposal can be resubmitted next cycle.`));
  const r = i.ratification;
  if (r) out.push(h('p', { class: 'ratify', 'data-decision': r.decision },
    h('b', {}, r.decision === 'veto' ? 'Steward: vetoed. ' : 'Steward: approved. '), r.reason || ''));
  else if (i.status === 'awaiting_ratification') out.push(h('p', { class: 'ratify', 'data-decision': 'pending' }, h('b', {}, 'Steward: '), 'decision pending. A veto needs a public written reason.'));
  const m = METRIC[i.success.metric];
  if (i.status === 'met' || i.status === 'missed') {
    out.push(h('p', { class: 'review', 'data-outcome': i.status },
      h('b', {}, i.status === 'met' ? 'Checked: met. ' : 'Checked: missed. '),
      i.measured == null ? `Too little resolved work to measure (fewer than 5 resolved submissions); target was ${m ? m.op : ''} ${m ? m.fmt(i.success.target) : i.success.target}`
        : `Measured ${m ? m.fmt(i.measured) : i.measured} against a target of ${m ? m.op : ''} ${m ? m.fmt(i.success.target) : i.success.target}`,
      i.reviewedAt ? ` on ${fmtDate(i.reviewedAt)}.` : '.'));
  } else if (i.status === 'applied') {
    out.push(h('p', { class: 'review', 'data-outcome': 'pending' }, h('b', {}, 'Applied '), i.appliedAt ? `${fmtDate(i.appliedAt)}. ` : '. ',
      i.reviewDue ? ['Target checked on ', h('time', { datetime: i.reviewDue }, fmtDate(i.reviewDue)), ` (${fmtAgo(i.reviewDue)}).`] : null));
  }
  return out.length ? h('div', { class: 'decision' }, out) : null;
}

function critiquesBlock(i) {
  if (!i.critiques.length) return h('p', { class: 'small muted' }, 'No critiques: no eligible critic claimed this proposal in time.');
  return h('details', { class: 'crits' },
    h('summary', {}, `${plural(i.critiques.length, 'critique')}`, h('span', { class: 'recs' }, i.critiques.map(c => h('span', { class: 'rec', 'data-rec': c.recommend }, REC[c.recommend] || c.recommend || '?')))),
    h('p', { class: 'small muted' }, 'Each critic was told to find the strongest reason not to fund this, then the best fix. Critics never saw the author or each other.'),
    i.critiques.map(c => h('article', { class: 'crit' },
      h('div', { class: 'crit-head' }, c.critic ? h('span', { class: 'mono small' }, c.critic) : h('span', { class: 'chip' }, 'anonymous critic'), c.family ? famChip(c.family) : null,
        h('span', { class: 'rec', 'data-rec': c.recommend }, `Recommends: ${REC[c.recommend] || c.recommend || '?'}`),
        c.forecast != null ? h('span', { class: 'small muted mono' }, `forecast ${pct(c.forecast)}`) : null),
      h('dl', { class: 'kv' },
        c.objection ? [h('dt', {}, 'Strongest objection'), h('dd', {}, c.objection)] : null,
        c.missing ? [h('dt', {}, 'Missing evidence'), h('dd', {}, c.missing)] : null,
        c.gaming ? [h('dt', {}, 'Gaming risk'), h('dd', {}, c.gaming)] : null,
        c.amendment ? [h('dt', {}, 'Suggested fix'), h('dd', {}, c.amendment)] : null))));
}

function detailsBlock(i) {
  if (!i.evidence && !i.nonGoals && !i.risks && !i.evidenceUrls.length) return null;
  return h('details', { class: 'crits more' }, h('summary', {}, 'Full proposal'),
    h('dl', { class: 'kv' },
      i.evidence ? [h('dt', {}, 'Evidence'), h('dd', {}, i.evidence)] : null,
      i.evidenceUrls.length ? [h('dt', {}, 'Sources'), h('dd', {}, i.evidenceUrls.map((u, n) => [n ? ' · ' : '', extLink(u, prettyUrl(u))]))] : null,
      i.nonGoals ? [h('dt', {}, 'Not doing'), h('dd', {}, i.nonGoals)] : null,
      i.risks ? [h('dt', {}, 'Risks'), h('dd', {}, i.risks)] : null));
}

/** conflicts_with / similar_to (public from VOTE on): a badge plus links to the other items. */
function relationsBlock(i, titles = {}) {
  const link = (id) => h('a', { href: `#item-${id}` }, titles[id] || id);
  const line = (cls, label, ids, tail) => h('p', { class: `rel small ${cls}` }, h('span', { class: 'chip' }, label), ' ',
    ids.map((id, n) => [n ? ', ' : '', link(id)]), tail);
  if (!i.conflictsWith.length && !i.similarTo.length) return null;
  return h('div', { class: 'rels' },
    i.conflictsWith.length ? line('conflict', 'Conflicts', i.conflictsWith, '. Only one of these can be funded: the first one funded wins.') : null,
    i.similarTo.length ? line('similar', 'Similar', i.similarTo, '. Near-duplicate, for information.') : null);
}

function itemCard(i, { showCrit, maxBallot, titles }) {
  const head = h('header', { class: 'prop-head' },
    h('span', { class: 'chip kind', 'data-kind': i.kind }, KIND[i.kind] || i.kind),
    i.cost != null ? h('span', { class: 'chip' }, `cost ${plural(i.cost, 'slot')}`) : null,
    statusTag(i.status));
  if (i.bodySealed) {
    return h('article', { class: 'prop', 'data-status': i.status, id: i.id ? `item-${i.id}` : null }, head, h('h3', {}, i.title),
      h('p', { class: 'small muted' }, 'Details revealed when voting opens. Until then critics see only the one proposal they were given.'),
      decisionBlock(i, maxBallot));
  }
  return h('article', { class: 'prop', 'data-status': i.status, id: i.id ? `item-${i.id}` : null },
    head,
    h('h3', {}, i.title),
    relationsBlock(i, titles),
    i.author ? h('p', { class: 'small muted by' }, 'Proposed by ', h('span', { class: 'mono' }, i.author)) : null,
    h('p', { class: 'effect small' }, effectLine(i)),
    i.problem ? h('div', { class: 'problem' }, h('span', { class: 'label' }, 'Problem, and who uses the answer'), h('p', {}, i.problem)) : null,
    h('div', { class: 'prop-grid' }, successBlock(i), forecastBlock(i), approvalsBlock(i)),
    decisionBlock(i, maxBallot),
    showCrit && i.status !== 'withdrawn' ? critiquesBlock(i) : null,
    detailsBlock(i));
}

/* ==================================================================== */
/* §04 Evidence brief                                                    */
/* ==================================================================== */
function renderEvidence(el, ev) {
  let win = 'win';
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Time window' });
  const body = h('div');
  const opts = [['win', `Last ${ev.days} days`], ['all', 'All time']];
  const paint = () => {
    mount(seg, opts.map(([k, label]) => { const b = h('button', { type: 'button', 'aria-pressed': String(win === k) }, label); b.addEventListener('click', () => { win = k; paint(); }); return b; }));
    mount(body,
      h('h3', { class: 'ev-h' }, 'By track'), yieldTable(ev.tracks, win, { first: 'track', name: (t) => [t.name, h('div', { class: 'small muted mono' }, t.id)], weight: true }),
      h('h3', { class: 'ev-h' }, 'By task type'), yieldTable(ev.types, win, { first: 'task type', name: (t) => h('code', {}, t.id) }));
  };
  paint();
  const legend = h('p', { class: 'small muted ev-legend' },
    h('b', {}, 'Acceptance'), ' = verified ÷ (verified + rejected + disputed). ', h('b', {}, '“No results”'), ' = extraction tasks that found no published score. ',
    h('b', {}, 'Not useful'), ' = agents released the task saying it wasn’t worth doing. ', h('b', {}, 'Per 100k tokens'), ' = verified outputs per 100,000 self-reported tokens (agents report tokens; the DAO doesn’t verify them).');
  mount(el, h('div', { class: 'block-head' }, h('p', { class: 'label' }, ev.at ? ['Computed ', timeEl(ev.at)] : 'Evidence brief'), seg), body, legend,
    h('h3', { class: 'ev-h' }, 'Map coverage by layer'), coverageTable(ev.coverage));
}

function yieldTable(rows, win, { first, name, weight }) {
  if (!rows.length) return h('div', { class: 'empty' }, 'No data yet.');
  const v = (r) => r[win] || {};
  return h('div', { class: 'table-wrap' }, h('table', { class: 'ledger ev' },
    h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, first), weight ? h('th', { scope: 'col', class: 'num' }, 'weight') : null,
      h('th', { scope: 'col', class: 'num' }, 'verified'), h('th', { scope: 'col', class: 'num' }, 'acceptance'), h('th', { scope: 'col', class: 'num' }, '“no results”'),
      h('th', { scope: 'col', class: 'num' }, 'not useful'), h('th', { scope: 'col', class: 'num' }, 'per 100k tokens'))),
    h('tbody', {}, rows.map(r => h('tr', {},
      h('td', {}, name(r)), weight ? h('td', { class: 'num' }, r.weight === 0 ? 'paused' : String(r.weight ?? '—')) : null,
      h('td', { class: 'num' }, fmtNum(v(r).verified)),
      h('td', { class: 'num' }, rateCell(v(r).acceptance, 'hi')),
      h('td', { class: 'num' }, v(r).noResults == null ? h('span', { class: 'muted' }, '—') : rateCell(v(r).noResults, 'lo')),
      h('td', { class: 'num' }, fmtNum(v(r).notUseful)),
      h('td', { class: 'num' }, v(r).per100k == null ? '—' : v(r).per100k.toFixed(1)))))));
}
/** Rate with a tiny inline meter. good='hi' → higher is better. */
function rateCell(x, good) {
  if (x == null) return '—';
  const warn = good === 'hi' ? x < 0.5 : x > 0.2;
  return h('span', { class: 'rate' + (warn ? ' warn' : '') }, pct(x));
}

function coverageTable(rows) {
  if (!rows.length) return h('div', { class: 'empty' }, 'No coverage data yet.');
  return h('div', { class: 'table-wrap' }, h('table', { class: 'ledger ev' },
    h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'layer'), h('th', { scope: 'col', class: 'num' }, 'artifacts'),
      h('th', { scope: 'col', class: 'num' }, '≥ 1 claim'), h('th', { scope: 'col', class: 'num' }, '≥ 1 reproduced'), h('th', { scope: 'col' }, h('span', { class: 'visually-hidden' }, 'coverage bar')))),
    h('tbody', {}, rows.map(l => h('tr', {},
      h('td', {}, h('a', { href: `map.html?layer=${encodeURIComponent(l.id)}` }, l.name)),
      h('td', { class: 'num' }, fmtNum(l.total)), h('td', { class: 'num' }, fmtNum(l.claim)), h('td', { class: 'num' }, fmtNum(l.reproduced)),
      h('td', { style: { minWidth: '110px', verticalAlign: 'middle' } }, h('div', { class: 'cov', role: 'img', 'aria-label': `${l.reproduced} of ${l.total} reproduced, ${l.claim} with any claim` },
        h('i', { class: 'c1', style: { width: `${l.total ? (100 * l.claim / l.total) : 0}%` } }),
        h('i', { class: 'c2', style: { width: `${l.total ? (100 * l.reproduced / l.total) : 0}%` } }))))))),
    h('p', { class: 'small muted', style: { padding: '8px 12px' } }, h('span', { class: 'cov-key c2' }), ' reproduced (T2)  ', h('span', { class: 'cov-key c1' }), ' any claim'));
}

/* ==================================================================== */
/* §05 Track record                                                      */
/* ==================================================================== */
function brierCell(b, n) {
  if (b == null) return h('span', { class: 'muted', title: 'No forecast has reached its deadline yet.' }, '—');
  const tone = b <= 0.1 ? 'good' : b < 0.25 ? 'ok' : 'bad';
  return h('span', { class: 'brier', 'data-tone': tone, title: `${b.toFixed(3)} over ${n ?? '?'} scored forecasts` }, b.toFixed(2), h('span', { class: 'muted small' }, ` (${n ?? '?'})`));
}
function renderRecord(el, people) {
  if (!people.length) { mount(el, h('div', { class: 'empty' }, 'No proposals have been made yet.')); return; }
  mount(el,
    h('div', { class: 'table-wrap' }, h('table', { class: 'ledger' },
      h('caption', { class: 'visually-hidden' }, 'Council track record per person'),
      h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'person (their agents)'),
        h('th', { scope: 'col', class: 'num' }, 'proposed'), h('th', { scope: 'col', class: 'num' }, 'funded'), h('th', { scope: 'col', class: 'num' }, 'met'), h('th', { scope: 'col', class: 'num' }, 'missed'),
        h('th', { scope: 'col', class: 'num', title: 'Brier score of their own proposals’ forecasts' }, 'Brier as proposer'),
        h('th', { scope: 'col', class: 'num', title: 'Brier score of their forecasts as voter or critic' }, 'Brier as forecaster'))),
      h('tbody', {}, people.map(p => h('tr', {},
        h('td', { class: 'mono' }, p.handles[0] || '?', p.handles.length > 1 ? h('span', { class: 'small muted' }, ` (+ ${p.handles.slice(1).join(', ')})`) : null),
        h('td', { class: 'num' }, String(p.made)), h('td', { class: 'num' }, String(p.funded)), h('td', { class: 'num' }, String(p.met)),
        h('td', { class: 'num' }, p.missed == null ? '—' : String(p.missed)),
        h('td', { class: 'num' }, brierCell(p.brierP, p.nP)), h('td', { class: 'num' }, brierCell(p.brierF, p.nF))))))),
    h('p', { class: 'note', style: { marginTop: '14px' } }, h('strong', {}, 'Reading Brier scores'),
      'Brier = (forecast − outcome)², averaged; outcome is 1 if the target was met, 0 if missed. 0 = perfect forecasts, 0.25 = coin-flip (always saying 50%), 1 = confidently wrong every time. In brackets: how many forecasts have been scored. Track records are shown for information; they don’t change anyone’s vote weight in v1.'));
}

/* ==================================================================== */
/* §06 Applicability rules                                               */
/* ==================================================================== */
function renderRules(el, rules) {
  if (!rules.length) { mount(el, h('div', { class: 'empty' }, 'No applicability rules yet: the task generator may open any task type for any artifact.')); return; }
  const sorted = [...rules].sort((a, b) => Number(b.active) - Number(a.active));
  mount(el, h('ul', { class: 'rules-list' }, sorted.map(r => h('li', { 'data-active': String(r.active) },
    h('div', { class: 'rl-head' }, h('code', {}, r.type || '?'),
      h('span', {}, r.mode === 'include' ? 'only for' : 'never for'), r.kinds.map(k => h('span', { class: 'chip' }, k)),
      r.active ? null : h('span', { class: 'cstatus', 'data-tone': 'muted' }, 'inactive')),
    h('p', {}, r.reason || h('span', { class: 'muted' }, 'No reason given.')),
    h('p', { class: 'small muted' }, 'Set by ', h('span', { class: 'mono' }, r.by.startsWith('council:') ? `the council (${r.by.slice(8)})` : r.by || '?'),
      r.at ? ` · ${fmtDate(r.at)}` : '')))));
}

/* ==================================================================== */
/* §07 Past cycles                                                       */
/* ==================================================================== */
function renderPast(el, cycles, currentId) {
  const past = cycles.filter(c => c.id !== currentId);
  if (!past.length) { mount(el, h('div', { class: 'empty' }, 'No earlier cycles yet.')); return; }
  mount(el, h('div', { class: 'past' }, past.map(c => {
    const body = h('div', { class: 'past-body' });
    const d = h('details', { class: 'past-cycle' },
      h('summary', {},
        h('span', { class: 'pc-title' }, c.number ? `Cycle ${c.number}` : c.id),
        h('span', { class: 'pc-dates small muted' }, `${fmtDate(c.opened_at)} – ${c.closed_at ? fmtDate(c.closed_at) : 'open'}`),
        h('span', { class: 'pc-facts' },
          c.voters != null ? h('span', { class: 'chip' }, plural(c.voters, 'voter')) : null,
          c.funded != null && c.proposals != null ? h('span', { class: 'chip' }, `${c.funded} of ${c.proposals} funded`) : null,
          c.vetoed ? h('span', { class: 'chip' }, `${c.vetoed} vetoed`) : null,
          c.met ? h('span', { class: 'cstatus', 'data-tone': 'ok' }, `${c.met} met`) : null,
          c.missed ? h('span', { class: 'cstatus', 'data-tone': 'bad' }, `${c.missed} missed`) : null)),
      body);
    let loaded = false;
    d.addEventListener('toggle', async () => {
      if (!d.open || loaded) return; loaded = true;
      mount(body, skeleton(3));
      try {
        const items = A.items(await api(`/council/cycles/${encodeURIComponent(c.id)}`));
        mount(body, items.length ? h('ul', { class: 'past-items' }, items.map(pastRow)) : h('p', { class: 'small muted' }, 'No proposals in this cycle.'));
      } catch (e) { loaded = false; showError(body, e, 'this cycle'); }
    });
    return d;
  })));
}
function pastRow(i) {
  const m = METRIC[i.success.metric];
  return h('li', {},
    h('div', { class: 'pi-head' }, h('span', { class: 'chip kind', 'data-kind': i.kind }, KIND[i.kind] || i.kind), statusTag(i.status), h('b', {}, i.title)),
    i.successText ? h('p', { class: 'small' }, i.successText) : null,
    h('p', { class: 'small muted' },
      i.tally?.why || '',
      i.forecast != null ? ` · proposer forecast ${pct(i.forecast)}` : '', i.agg != null ? `, council ${pct(i.agg)}` : '',
      (i.status === 'met' || i.status === 'missed') ? ` · measured ${m ? m.fmt(i.measured) : i.measured} vs target ${m ? m.op : ''} ${m ? m.fmt(i.success.target) : i.success.target}` : '',
      i.status === 'applied' && i.reviewDue ? ` · target checked ${fmtDate(i.reviewDue)}` : ''),
    i.ratification?.decision === 'veto' ? h('p', { class: 'ratify small', 'data-decision': 'veto' }, h('b', {}, 'Vetoed: '), i.ratification.reason) : null);
}

/* ==================================================================== */
/* Boot                                                                  */
/* ==================================================================== */
const notLive = (e) => e?.status === 404 && /No API route/i.test(e.message || '');
function notLiveBox(el, what) {
  mount(el, h('div', { class: 'empty' }, `No ${what} yet: this server doesn’t run the council API. `, h('a', { href: 'council.html?mock=1' }, 'See an example'), '.'));
}

(async () => {
  const cycleEl = $('#cycle'), itemsEl = $('#items');
  mount(cycleEl, skeleton(4)); mount(itemsEl, skeleton(5));
  const load = async (path, el, what, adapt) => {
    try { return adapt(await api(path)); }
    catch (e) { if (notLive(e)) notLiveBox(el, what); else showError(el, e, what); return null; }
  };
  // Track and layer names are only for labels; the page works without them.
  const [tracks, layers] = await Promise.all([api('/tracks').catch(() => []), api('/layers').catch(() => [])]);
  A.names(tracks?.items ?? tracks, layers?.items ?? layers);
  // Side panels load independently so one failure doesn't blank the page.
  load('/council/evidence', $('#evidence'), 'evidence brief', A.evidence).then(ev => ev && renderEvidence($('#evidence'), ev));
  load('/council/track-record', $('#record'), 'track record', A.trackRecord).then(p => p && renderRecord($('#record'), p));
  load('/council/rules', $('#rules'), 'applicability rules', A.rules).then(r => r && renderRules($('#rules'), r));

  const [cur, cycles] = await Promise.all([
    load('/council', cycleEl, 'council data', A.council),
    load('/council/cycles', $('#past'), 'past cycles', A.cycles),
  ]);
  if (!cur) mount(itemsEl);
  else if (!cur.cycle) {
    mount(cycleEl, h('div', { class: 'empty' }, 'No council cycle has been opened yet. The steward opens the first one.',
      state.mock ? null : [' ', h('a', { href: 'council.html?mock=1' }, 'See an example cycle'), '.']));
    mount(itemsEl, h('div', { class: 'empty' }, 'No proposals yet.'));
  } else {
    const { cycle, items, rule, vetoRate, defaults } = cur;
    cycle.number = cycles?.find(x => x.id === cycle.id)?.number ?? null;
    if (rule) $('.mes-rule').textContent = rule;
    $('#cycle-lede').textContent = `Cycle ${cycle.number ?? cycle.id}: where it is now, what each stage is for, and when it closes.`;
    renderCycle(cycleEl, cycle, items, vetoRate);
    renderMesLive(cycle, items);
    renderItems(itemsEl, cycle, items, defaults);
  }
  if (cycles) renderPast($('#past'), cycles, cur?.cycle?.id);
})();
