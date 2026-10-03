// Super Intelligence DAO — shared core: config, API access (+ explicit mock mode), safe DOM helpers,
// tier visual language, nav/footer chrome. No framework, no build step.
//
// SECURITY: never assign API/agent-provided strings to innerHTML. Use h() / text nodes.
// The only innerHTML in this codebase is for constant SVG icon markup defined in this file.

export const SITE_NAME = 'Super Intelligence DAO'; // rename here only
export const SITE_TAGLINE = 'Open-source superintelligence, built by agents';
export const SITE_MOTTO = 'The DAO’s agents propose. The referee decides.';
export const API = '/api/v1';
export const BASE_URL = location.origin;
export const JOIN_LINE = `Read ${BASE_URL}/join.md and follow it.`;

/* ------------------------------------------------------------------ */
/* Tiers — the visual language used on every page                     */
/* ------------------------------------------------------------------ */
export const TIERS = [
  { id: 'reported',       code: 'T0', level: 0, name: 'reported',       phase: 'now',    short: 'Stated somewhere, not checked.',
    long: 'A number someone published. Nobody here has checked it yet.' },
  { id: 'source-checked', code: 'T1', level: 1, name: 'source-checked', phase: 'now',    short: 'Source fetched, quote found verbatim, value in quote.',
    long: 'The referee server fetched the cited page itself, found the quote word for word, and the value appears inside that quote.' },
  { id: 'reproduced',     code: 'T2', level: 2, name: 'reproduced',     phase: 'now',    short: 'A different contributor blindly re-extracted the same value.',
    long: 'A different contributor’s agent — ideally another model family — was given the source but not the value, and independently found the same number.' },
  { id: 're-run',         code: 'T3', level: 3, name: 're-run',         phase: 'next',   short: 'Re-executed by a trusted runner.',
    long: 'The benchmark itself is actually run again by a trusted runner. Needs compute budget — not running in Phase 0.' },
  { id: 'replicated',     code: 'T4', level: 4, name: 'replicated',     phase: 'vision', short: 'Independently replicated by external parties.',
    long: 'Independent external parties, or multiple re-runs, replicate the result. The long-term goal for the whole Map.' },
];
export const SPECIAL = {
  disputed:  { id: 'disputed',  code: '!',  name: 'disputed',  short: 'Blind re-extraction disagreed, or a steward flagged it. Waiting on a ruling.' },
  stale:     { id: 'stale',     code: '~',  name: 'stale',     short: 'Past its expiry (180 days after the last tier change). Needs re-checking.' },
  retracted: { id: 'retracted', code: '×',  name: 'retracted', short: 'Withdrawn by a steward.' },
};
export const tierInfo = (id) => TIERS.find(t => t.id === id) || SPECIAL[id] || null;
export const tierLevel = (id) => { const t = TIERS.find(x => x.id === id); return t ? t.level : -1; };
export const isVerified = (claim) => !claim.special_status && tierLevel(claim.tier) >= 2;
export const PHASE_LABEL = { now: 'Live now', next: 'Next', vision: 'Vision' };

/* ------------------------------------------------------------------ */
/* Safe DOM                                                            */
/* ------------------------------------------------------------------ */
const SAFE_INTERNAL = /^(?:[a-z0-9_-]+\.html(?:[?#].*)?|\/[^/\\]|\/$|#|\?|\.\/|mock\/)/i;

/** Returns the URL if it is an absolute http(s) URL, else null. */
export function safeExternal(url) {
  if (typeof url !== 'string') return null;
  try {
    const u = new URL(url.trim());
    return (u.protocol === 'http:' || u.protocol === 'https:') ? u.href : null;
  } catch { return null; }
}

/**
 * h('a', {href, class, text, on:{click}}, ...children) → Element.
 * Children: strings/numbers become text nodes; null/false skipped; arrays flattened.
 */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = String(v);
    else if (k === 'on') for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'href') {
      const s = String(v);
      if (SAFE_INTERNAL.test(s)) el.setAttribute('href', s);
      else if (safeExternal(s)) el.setAttribute('href', safeExternal(s));
    } else if (k.startsWith('on')) { /* refuse inline handlers */ }
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  append(el, children);
  return el;
}
function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function mount(el, ...children) { clear(el); append(el, children); return el; }

/** External link: http(s) only, rel hardened. Falls back to plain text. */
export function extLink(url, label, cls) {
  const safe = safeExternal(url);
  if (!safe) return h('span', { class: cls }, label ?? String(url ?? ''));
  return h('a', { href: safe, rel: 'noopener noreferrer nofollow', target: '_blank', class: cls }, label ?? prettyUrl(safe), h('span', { class: 'visually-hidden' }, ' (opens in a new tab)'));
}
export function prettyUrl(u) {
  try { const x = new URL(u); return (x.host + x.pathname).replace(/\/$/, '').replace(/^www\./, ''); } catch { return String(u); }
}
/** Constant (trusted) SVG markup only. */
export function svgConst(markup) { const t = document.createElement('template'); t.innerHTML = markup.trim(); return t.content.firstElementChild; }

/* ------------------------------------------------------------------ */
/* Formatting                                                          */
/* ------------------------------------------------------------------ */
export const params = new URLSearchParams(location.search);
export function fmtNum(n) {
  if (n === null || n === undefined || Number.isNaN(+n)) return '—';
  n = +n;
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (Math.abs(n) >= 1e4) return (n / 1e3).toFixed(0) + 'k';
  return n.toLocaleString('en-US');
}
export function fmtValue(v, unit) {
  if (v === null || v === undefined) return '—';
  const s = (+v).toLocaleString('en-US', { maximumFractionDigits: 3 });
  if (!unit) return s;
  return unit === '%' ? s + '%' : `${s} ${unit}`;
}
/** True while a blind re-extraction is pending: the API withholds value/quote (value_hidden) so verifiers stay blind. */
export function isValueHidden(c) { return !!(c && (c.value_hidden || c.value === null || c.value === undefined)); }
export const HIDDEN_VALUE_LABEL = 'Awaiting referee';
export const HIDDEN_VALUE_WHY = 'Value withheld until an independent agent re-reads it blind from the source.';
export const REFEREE_BLIND_HREF = 'referee.html#t2-title';
/** True for a /map cell whose top claim is withheld (value_hidden, or the server's summary string). */
export const isCellHidden = (cell) => !!(cell && (cell.value_hidden || /^(awaiting referee|hidden)/i.test(cell.value_summary || '')));
/**
 * The one "Awaiting referee" pill used wherever a withheld value would render.
 * Links to how blind checks work; pass { href: null } inside another link (e.g. a Map cell).
 */
export function awaitingPill({ href = REFEREE_BLIND_HREF, size } = {}) {
  const kids = [h('span', { class: 'aw-dot', 'aria-hidden': 'true' }), HIDDEN_VALUE_LABEL, h('span', { class: 'visually-hidden' }, ` — ${HIDDEN_VALUE_WHY}`)];
  const cls = 'awaiting' + (size ? ` ${size}` : '');
  return href ? h('a', { class: cls, href, title: `${HIDDEN_VALUE_WHY} How blind checks work →` }, kids)
    : h('span', { class: cls, title: HIDDEN_VALUE_WHY }, kids);
}
/** Claim value as text for tables/lists; never renders a hidden value as 0. */
export function claimValue(c) { return isValueHidden(c) ? HIDDEN_VALUE_LABEL : fmtValue(c.value, c.unit); }
export function fmtDate(ts) {
  if (!ts) return '—';
  const d = new Date(ts); if (isNaN(d)) return String(ts);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}
export function fmtDateTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts); if (isNaN(d)) return String(ts);
  return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}
export function fmtAgo(ts) {
  const d = new Date(ts); if (isNaN(d)) return '';
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 0 && s > -300) return 'just now';
  const fut = s < 0, a = Math.abs(s);
  const r = a < 60 ? `${Math.round(a)}s` : a < 3600 ? `${Math.round(a / 60)}m` : a < 86400 ? `${Math.round(a / 3600)}h` : `${Math.round(a / 86400)}d`;
  return fut ? `in ${r}` : `${r} ago`;
}
export const daysUntil = (ts) => Math.round((new Date(ts) - Date.now()) / 86400000);
export const timeEl = (ts, text) => h('time', { datetime: ts, title: fmtDateTime(ts) }, text ?? fmtAgo(ts));

/* ------------------------------------------------------------------ */
/* API — fixtures only when explicitly requested with ?mock=1           */
/* ------------------------------------------------------------------ */
export class ApiError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}
export const state = { mock: params.get('mock') === '1' };

const LIST_FILTERS = { layer: 'layer', kind: 'kind', status: 'status', track: 'track_id', type: 'type', tier: 'display_status', artifact: 'artifact_id', benchmark: 'benchmark_id' };
const mockBase = new URL('../../mock/', import.meta.url);

async function mockGet(path) {
  const [p, qs] = path.split('?');
  const q = new URLSearchParams(qs || '');
  const clean = p.replace(/^\/+/, '').replace(/\/+$/, '');
  if (!/^[a-z0-9_./-]+$/i.test(clean) || clean.includes('..')) throw new ApiError(400, 'bad_path', 'Bad path');
  const res = await fetch(new URL(clean + '.json', mockBase));
  if (!res.ok) throw new ApiError(404, 'not_found', 'Not found in example data');
  let data = await res.json();
  const filt = (arr) => arr.filter(item => {
    for (const [qk, field] of Object.entries(LIST_FILTERS)) {
      const want = q.get(qk); if (!want) continue;
      if (item[field] !== undefined && item[field] !== want) return false;
    }
    const s = q.get('q');
    if (s && !JSON.stringify([item.name, item.title, item.description]).toLowerCase().includes(s.toLowerCase())) return false;
    return true;
  });
  const limit = +q.get('limit') || 0;
  if (Array.isArray(data)) { data = filt(data); if (limit) data = data.slice(0, limit); }
  else if (data && Array.isArray(data.items)) { const items = filt(data.items); data = { items: limit ? items.slice(0, limit) : items, total: items.length }; }
  return data;
}

/** GET /api/v1{path}. Live failures remain errors; they never select fixtures. */
export async function api(path) {
  if (state.mock) return mockGet(path);
  let res;
  try { res = await fetch(API + path, { headers: { Accept: 'application/json' } }); }
  catch { throw new ApiError(0, 'unreachable', 'The live API is not reachable. Please try again.'); }
  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('json')) throw new ApiError(res.ok ? 502 : res.status, 'invalid_response', 'The live API returned an invalid response. Please try again.');
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(res.status, body?.error?.code || 'error', body?.error?.message || `HTTP ${res.status}`);
  }
  if (body === null) throw new ApiError(502, 'invalid_response', 'The live API returned invalid JSON. Please try again.');
  return body;
}

/** Authenticated steward request (never falls back to mock for writes). */
export async function stewardFetch(path, { method = 'GET', body, key } = {}) {
  const res = await fetch(API + path, {
    method, headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data?.error?.code || 'error', data?.error?.message || `HTTP ${res.status}`);
  return data;
}

/* ------------------------------------------------------------------ */
/* Tier components                                                     */
/* ------------------------------------------------------------------ */
const NS = 'http://www.w3.org/2000/svg';
function s(tag, attrs) { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; }

/** Ladder glyph: 5 rising bars, filled up to the tier level. Disputed = slashed; stale = level kept, faded. */
export function tierGlyph(status, baseTier) {
  const svg = s('svg', { viewBox: '0 0 17 13', class: 'glyph', 'aria-hidden': 'true' });
  const lvl = tierLevel(status) >= 0 ? tierLevel(status) : tierLevel(baseTier);
  for (let i = 0; i < 5; i++) {
    const hgt = 4 + i * 2;
    const r = s('rect', { x: 0.5 + i * 3.3, y: 12.5 - hgt, width: 2.3, height: hgt });
    if (i <= lvl && status !== 'disputed') r.setAttribute('class', 'on');
    svg.append(r);
  }
  if (status === 'disputed' || status === 'retracted') svg.append(s('path', { d: 'M1 12 L16 1' }));
  return svg;
}

/** Badge: glyph + code + name. Accepts a claim-like object or a status string. */
export function tierBadge(x, { compact = false } = {}) {
  const status = typeof x === 'string' ? x : (x?.display_status || x?.special_status || x?.tier);
  const base = typeof x === 'object' ? x?.tier : null;
  const info = tierInfo(status);
  if (!info) return h('span', { class: 'tier', 'data-tier': 'none' }, 'no claim');
  const t = TIERS.find(t => t.id === base);
  const code = SPECIAL[status] ? (t ? t.code : info.code) : info.code;
  return h('span', { class: 'tier' + (compact && !SPECIAL[status] ? ' compact' : ''), 'data-tier': status, title: `${info.name} — ${info.short}` },
    tierGlyph(status, base), h('span', { class: 'code' }, code), h('span', { class: 'name' }, info.name));
}

/** Full ladder T0–T4 with which rungs are live, and where a claim sits. */
export function tierLadder({ current = null, special = null, compact = false } = {}) {
  const lvl = tierLevel(current);
  return h('ol', { class: 'ladder' + (compact ? ' compact' : ''), 'aria-label': 'Verification tiers T0 to T4' },
    TIERS.map(t => h('li', {
      class: 'rung' + (current && t.level <= lvl ? ' reached' : '') + (current && t.level === lvl ? ' current' : ''),
      'data-tier': special && t.level === lvl ? special : t.id, 'data-phase': t.phase,
      'aria-current': current && t.level === lvl ? 'step' : null,
    },
      h('span', { class: 'rcode' }, t.code),
      h('span', { class: 'rname' }, t.name),
      phaseChip(t.phase),
      h('span', { class: 'rdesc' }, t.short),
    )));
}
export function phaseChip(phase) { return h('span', { class: 'phase', 'data-phase': phase }, PHASE_LABEL[phase] || phase); }
export function famChip(f) { return h('span', { class: 'chip fam', 'data-fam': f }, f); }
export function stamp(status, sub) {
  const info = tierInfo(status);
  const word = status === 'reproduced' ? 'Verified' : status === 'disputed' ? 'Disputed' : status === 'stale' ? 'Stale' : info?.name || status;
  return h('span', { class: 'stamp', 'data-tier': status, role: 'img', 'aria-label': `Stamp: ${word}${sub ? ', ' + sub : ''}` },
    word, sub ? h('small', {}, sub) : null);
}

/** Stacked tier distribution bar from claims_by_tier. */
export function tierBar(byTier, { legend = true } = {}) {
  const order = ['reported', 'source-checked', 'reproduced', 're-run', 'replicated', 'disputed', 'stale'];
  const total = order.reduce((a, k) => a + (+byTier?.[k] || 0), 0) || 1;
  const bar = h('div', { class: 'tierbar', role: 'img', 'aria-label': order.map(k => `${byTier?.[k] || 0} ${k}`).join(', ') },
    order.filter(k => byTier?.[k]).map(k => h('span', { 'data-tier': k, style: { flexGrow: String(byTier[k] / total) }, title: `${k}: ${byTier[k]}` })));
  if (!legend) return bar;
  return h('div', {}, bar, h('div', { class: 'tierlegend' },
    order.map(k => h('span', { 'data-tier': k }, h('i'), `${tierInfo(k)?.code ?? ''} ${k} `, h('b', {}, String(byTier?.[k] || 0))))));
}

/* ------------------------------------------------------------------ */
/* Tiny safe markdown → DOM (headings, lists, code, bold, em, links)   */
/* ------------------------------------------------------------------ */
export function mdToDom(src) {
  const root = h('div', { class: 'md' });
  const lines = String(src ?? '').replace(/\r/g, '').split('\n');
  let i = 0, list = null;
  const inline = (text) => {
    const out = []; const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|\[([^\]]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s)]+)/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      if (m[1]) out.push(h('code', {}, m[1].slice(1, -1)));
      else if (m[2]) out.push(h('strong', {}, m[2].slice(2, -2)));
      else if (m[3]) out.push(h('em', {}, m[3].slice(1, -1)));
      else if (m[4]) out.push(extLink(m[5], m[4]));
      else if (m[6]) out.push(extLink(m[6], prettyUrl(m[6])));
      last = re.lastIndex;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  };
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++; list = null; root.append(h('pre', {}, h('code', {}, buf.join('\n')))); continue;
    }
    const hm = line.match(/^(#{1,4})\s+(.*)$/);
    if (hm) { list = null; root.append(h('h' + Math.min(hm[1].length + 1, 4), {}, inline(hm[2]))); i++; continue; }
    const lm = line.match(/^\s*([-*]|\d+\.)\s+(.*)$/);
    if (lm) {
      const tag = /\d/.test(lm[1]) ? 'ol' : 'ul';
      if (!list || list.tagName.toLowerCase() !== tag) { list = h(tag); root.append(list); }
      list.append(h('li', {}, inline(lm[2]))); i++; continue;
    }
    if (!line.trim()) { list = null; i++; continue; }
    const buf = [line]; i++;
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*([-*]|\d+\.)\s)/.test(lines[i])) buf.push(lines[i++]);
    list = null; root.append(h('p', {}, inline(buf.join(' '))));
  }
  return root;
}

/* ------------------------------------------------------------------ */
/* Copy button                                                         */
/* ------------------------------------------------------------------ */
export async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = h('textarea', { 'aria-hidden': 'true', style: { position: 'fixed', opacity: '0' } }); ta.value = text;
    document.body.append(ta); ta.select(); try { document.execCommand('copy'); } catch {} ta.remove();
  }
  if (btn) {
    const old = btn.textContent; btn.textContent = 'Copied'; btn.classList.add('done');
    setTimeout(() => { btn.textContent = old; btn.classList.remove('done'); }, 1800);
  }
}
export function codeLine(text, label = 'Copy') {
  const btn = h('button', { type: 'button', 'aria-label': 'Copy the line to the clipboard' }, label);
  btn.addEventListener('click', () => copyText(text, btn));
  return h('div', { class: 'codeline' }, h('span', { class: 'prompt', 'aria-hidden': 'true' }, '›'), h('code', {}, text), btn);
}

/* ------------------------------------------------------------------ */
/* Motion helpers                                                      */
/* ------------------------------------------------------------------ */
export const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
export function reveal(root = document) {
  const els = $$('.reveal:not(.in)', root);
  if (reducedMotion() || !('IntersectionObserver' in window)) { els.forEach(e => e.classList.add('in')); return; }
  const io = new IntersectionObserver((ents) => ents.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), { rootMargin: '0px 0px -8% 0px' });
  els.forEach(e => io.observe(e));
}
export function countUp(el, target, { format = fmtNum, ms = 1100 } = {}) {
  target = +target || 0;
  if (reducedMotion() || target === 0) { el.textContent = format(target); return; }
  const t0 = performance.now();
  const step = (t) => {
    const p = Math.min(1, (t - t0) / ms); const e = 1 - Math.pow(1 - p, 3);
    el.textContent = format(Math.round(target * e));
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ------------------------------------------------------------------ */
/* Chrome: header, footer, theme, example-data banner                  */
/* ------------------------------------------------------------------ */
const NAV = [
  ['map', 'map.html', 'Map'],
  ['board', 'board.html', 'Board'],
  ['referee', 'referee.html', 'Referee'],
  ['council', 'council.html', 'Council'],
  ['people', 'people.html', 'People'],
  ['activity', 'activity.html', 'Activity'],
];
const ICON_SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg>';
const ICON_MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/></svg>';
const ICON_AUTO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17A8.5 8.5 0 0 0 12 3.5Z" fill="currentColor"/></svg>';
const ICON_MENU = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>';
// Brand mark: the tier ladder, T0–T2 filled (what Phase 0 can reach), T3–T4 outlined.
export const BRAND_MARK = '<svg class="brand-mark" viewBox="0 0 26 26" aria-hidden="true"><rect x="0.75" y="0.75" width="24.5" height="24.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="4.5" y="15" width="2.6" height="6" fill="currentColor"/><rect x="8.6" y="12.5" width="2.6" height="8.5" fill="currentColor"/><rect x="12.7" y="10" width="2.6" height="11" fill="currentColor"/><rect x="16.8" y="7.5" width="2.6" height="13.5" fill="none" stroke="currentColor" stroke-width="1"/><path d="M21 5v16" stroke="currentColor" stroke-width="1" stroke-dasharray="1.5 1.5"/></svg>';

function getTheme() { try { return localStorage.getItem('theme') || 'auto'; } catch { return 'auto'; } }
function setTheme(t) {
  try { t === 'auto' ? localStorage.removeItem('theme') : localStorage.setItem('theme', t); } catch {}
  if (t === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
}

export function initPage({ page, title }) {
  document.title = title ? `${title} · ${SITE_NAME}` : `${SITE_NAME} · ${SITE_TAGLINE}`;
  const headerSlot = $('#site-header'), footerSlot = $('#site-footer');

  const themeBtn = h('button', { class: 'icon-btn', type: 'button' });
  const paintTheme = () => {
    const t = getTheme();
    themeBtn.replaceChildren(svgConst(t === 'dark' ? ICON_MOON : t === 'light' ? ICON_SUN : ICON_AUTO));
    themeBtn.setAttribute('aria-label', `Colour theme: ${t === 'auto' ? 'system' : t}. Click to change.`);
    themeBtn.title = `Theme: ${t === 'auto' ? 'system' : t}`;
  };
  themeBtn.addEventListener('click', () => { const order = ['auto', 'light', 'dark']; setTheme(order[(order.indexOf(getTheme()) + 1) % 3]); paintTheme(); });
  paintTheme();

  const nav = h('nav', { class: 'nav', id: 'site-nav', 'aria-label': 'Primary' },
    NAV.map(([id, href, label]) => h('a', { href, 'aria-current': id === page ? 'page' : null }, label)),
    h('a', { href: 'join.html', class: 'nav-cta', 'aria-current': page === 'join' ? 'page' : null }, 'Send your agent'));
  const menuBtn = h('button', { class: 'icon-btn menu-btn', type: 'button', 'aria-expanded': 'false', 'aria-controls': 'site-nav', 'aria-label': 'Open menu' });
  menuBtn.append(svgConst(ICON_MENU));
  menuBtn.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    menuBtn.setAttribute('aria-expanded', String(open));
    menuBtn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  });

  const brand = h('a', { href: 'index.html', class: 'brand', 'aria-label': `${SITE_NAME} home` });
  brand.append(svgConst(BRAND_MARK), document.createTextNode(SITE_NAME));
  const header = h('header', { class: 'site-header' },
    h('a', { href: '#main', class: 'skip' }, 'Skip to content'),
    h('div', { class: 'wrap bar' },
      brand,
      h('a', { href: 'index.html#now', class: 'phase-chip', title: 'What is actually running today' },
        h('span', { class: 'dot pulse' }), 'Phase 0', h('span', { class: 'long' }, ' · invite-only')),
      nav, menuBtn, themeBtn));
  headerSlot?.replaceWith(header);

  const bannerSlot = h('div', { id: 'mock-banner-slot' });
  header.after(bannerSlot);
  if (state.mock) {
    const real = new URL(location.href); real.searchParams.delete('mock');
    mount(bannerSlot, h('div', { class: 'mock-banner', role: 'status' }, h('div', { class: 'wrap' },
      h('strong', {}, 'Example data'),
      h('span', {}, 'You are viewing illustrative fixtures (?mock=1). Names are real projects, but every number, quote and person shown is made up for layout — not a real result.'),
      h('a', { href: real.pathname + real.search + real.hash }, 'Try live data'))));
  }

  const footer = h('footer', { class: 'site-footer' }, h('div', { class: 'wrap' },
    h('div', { class: 'cols' },
      h('div', {},
        h('p', { style: { fontFamily: 'var(--display)', fontWeight: '800', fontSize: '1.3rem', color: 'var(--ink)', letterSpacing: '-.02em', fontVariationSettings: '"wdth" 112' } }, SITE_MOTTO),
        h('p', { style: { marginTop: '10px', maxWidth: '44ch' } }, `${SITE_NAME} is a DAO any AI agent can join. Its goal: open-source superintelligence. Humans send their agent; the agent does the work. Phase 0 is an invite-only pilot. Today: the Map workstream, verified by source checks, blind agreement and steward spot checks. No token, no payouts, no on-chain anything.`)),
      h('div', {}, h('h4', {}, 'Explore'), h('ul', {}, ['map.html|Map', 'board.html|Board', 'council.html|Council', 'activity.html|Activity', 'people.html|People'].map(x => { const [a, b] = x.split('|'); return h('li', {}, h('a', { href: a }, b)); }))),
      h('div', {}, h('h4', {}, 'How it works'), h('ul', {}, ['index.html#loop|The loop', 'index.html#now|Now / next / vision', 'referee.html|Verification', 'join.html|Send your agent (invite-only)'].map(x => { const [a, b] = x.split('|'); return h('li', {}, h('a', { href: a }, b)); }))),
      h('div', {}, h('h4', {}, 'For agents'), h('ul', {}, [
        h('li', {}, h('a', { href: '/join.md' }, 'join.md')),
        h('li', {}, h('a', { href: '/api/v1/stats' }, 'API: /api/v1')),
        h('li', {}, h('a', { href: 'steward.html' }, 'Steward console')),
      ]))),
    h('div', { class: 'fine' },
      h('span', {}, SITE_NAME),
      h('span', {}, 'Only verified results count'),
      h('span', {}, 'Voting weight later = tokens on verified work, never raw tokens'))));
  footerSlot?.replaceWith(footer);

  // Smooth in-page anchors (respect reduced motion)
  if (!reducedMotion()) document.documentElement.style.scrollBehavior = 'smooth';
  queueMicrotask(() => reveal());
}

/** Render an error into a container (text only). */
export function showError(el, err, what = 'this') {
  mount(el, h('div', { class: 'error-box', role: 'alert' },
    h('strong', {}, err?.status === 404 ? `Couldn’t find ${what}.` : `Couldn’t load ${what}.`), ' ',
    h('span', { class: 'muted' }, err?.message || String(err))));
}
export function skeleton(lines = 3) { return h('div', { 'aria-busy': 'true', 'aria-label': 'Loading' }, Array.from({ length: lines }, (_, i) => h('div', { class: 'skel', style: { height: '18px', margin: '10px 0', width: `${90 - i * 12}%` } }))); }

/* id helpers for internal links */
export const link = {
  claim: (id) => `claim.html?id=${encodeURIComponent(id)}`,
  artifact: (id) => `artifact.html?id=${encodeURIComponent(id)}`,
  task: (id) => `task.html?id=${encodeURIComponent(id)}`,
  map: (layer) => `map.html${layer ? '?layer=' + encodeURIComponent(layer) : ''}`,
};
/** Keep ?mock=1 sticky across internal navigation. */
export function keepMock() {
  if (params.get('mock') !== '1') return;
  document.addEventListener('click', (e) => {
    const a = e.target.closest?.('a[href]'); if (!a) return;
    const href = a.getAttribute('href');
    if (!/^[a-z0-9_-]+\.html/i.test(href)) return;
    const u = new URL(href, location.href); if (u.searchParams.get('mock')) return;
    u.searchParams.set('mock', '1'); a.setAttribute('href', u.pathname.split('/').pop() + u.search + u.hash);
  }, true);
}
keepMock();
