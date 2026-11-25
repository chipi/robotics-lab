// The timeline's lanes under the scrubber (look-and-feel round 3, ADR-0021). The outliner's sections (World, Body, Senses, Mind, Other values) are header lanes
// that fold to one summary lane: the union of what their streams have, with the worst event or limit of the section on it. An open section shows its streams, each
// with its data inside the bar: a signal draws a sparkline of its values, any other stream the density of its samples, so a dropout is a hole or a thinning, not a
// uniform bar. The streams a run lacks are one quiet line per section. While the playhead sits on an event the lanes it concerns are lit and the rest recede.
// The rows are DOM (a few dozen, for the labels and the keyboard); everything drawn in them is one canvas, so a long run costs a pass over its samples, not nodes.
// Colour: a muted tone per section from the categorical ramp tokens; full colour only for a status (warn, alert, error), the selected stream and the playhead.
// A status is never colour alone: the glyph and the word are in the label (status.js).
import { glyph, label, statusOf } from '/lib/status.js';
import { jointLimits, NEAR } from './sigviz.js';
import { prefs, savePrefs } from './layout.js';

const TONE = { 'sec.world': 4, 'sec.body': 8, 'sec.senses': 5, 'sec.mind': 1 };     // --ramp-cat-N: told apart from the accent, the warn and the error colours in both themes
const toneOf = (id) => (TONE[id] ? `var(--ramp-cat-${TONE[id]})` : 'var(--text-3)');
const RANK = { error: 3, alert: 2, warn: 1 };
const MOTION = /^(reached|leg|tight_pivot|no_survey_turn)$/;
const NEAR_PX = 8;           // the playhead is "on" an event within this many pixels, or half a tick

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const rgbOf = (c) => {
  const h = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(c);
  if (h) { const s = h[1].length === 3 ? [...h[1]].map((x) => x + x).join('') : h[1]; return [0, 2, 4].map((i) => parseInt(s.slice(i, i + 2), 16)); }
  return (String(c).match(/[\d.]+/g) || [128, 128, 128]).slice(0, 3).map(Number);
};
const mix = (a, b, f) => a.map((v, i) => Math.round(v + (b[i] - v) * f));
const rgba = (c, a = 1) => `rgb(${c[0]} ${c[1]} ${c[2]} / ${a})`;
const tokenName = (v) => (/^var\((--[^)]+)\)$/.exec(v) || [])[1];

// the streams an event concerns, as stream-id prefixes: what the robot sensed and planned when it stopped, what moved when it turned. A guess made visible: it
// lights lanes, it never hides data.
export function concerns(ev, isStop) {
  const a = ev.anomaly, related = (Array.isArray(a?.related) ? a.related : []).filter((x) => typeof x === 'string');
  let p;
  if (a) p = a.source === 'harness' ? ['truth.', 'belief.', 'world.'] : ['belief.', 'sensors.', 'plan.'];
  else if (isStop(ev.kind)) p = ['sensors.', 'belief.pose', 'plan.', 'world.'];
  else if (MOTION.test(ev.kind)) p = ['belief.pose', 'truth.pose', 'plan.path', 'signals.joint_'];
  else p = ['belief.pose'];
  return [...p, ...related];
}
const evStatus = (ev) => (ev.anomaly ? statusOf('severity', ev.anomaly.severity) : statusOf('event', ev.kind));

// ctx: run() pres() tree() sel() stream(id) shown(id) name(id) hasTicks() hasSignals() sig() fr() robot() version() span() pct(t) time() events() isStop(kind)
//      gaps() icon(name, px) select(id) tick() - and the elements: wrap (#lanes), left (#lanesL), right (#dlanes), marks (the events and alarms lanes)
export function createLanes(ctx) {
  const { left, right } = ctx;
  let model = [], cv = null, nearIdx = -2, cache = { key: null, map: new Map() };

  // ---- what the streams have: the times of their samples, and for a signal its values -----------------------------------------------------------
  const stats = (ts) => {
    if (ts.length < 3) return { med: 0, regular: false };
    const d = []; for (let i = 1; i < ts.length; i++) d.push(ts[i] - ts[i - 1]);
    d.sort((a, b) => a - b);
    const med = d[d.length >> 1], dev = d.reduce((s, x) => s + Math.abs(x - med), 0) / d.length;
    return { med, regular: med > 0 && dev < 0.5 * med };
  };
  function tickTimes(id, spans) {
    const fr = ctx.fr(), out = [], has = {
      'truth.pose': (i) => !!fr.truth[i], 'sensors.tilt': (i) => !!fr.tilt[i],
      'sensors.depth.floor': (i) => fr.depth[i]?.some((p) => p[3] === 'f'), 'sensors.depth.obstacle': (i) => fr.depth[i]?.some((p) => p[3] === 'o'),
      'sensors.depth.overhead': (i) => fr.depth[i]?.some((p) => p[3] === 'v'),
    }[id] || (() => true);
    for (const [a, b] of fr.ranges) for (let i = a; i < b; i++) if (typeof fr.t[i] === 'number' && has(i)) out.push(fr.t[i]);
    // a span with fewer than two loaded ticks in it (ticks not loaded yet, or a stream that is not the ticks') is drawn solid: its rate is unknown
    const solid = [];
    let j = 0;
    for (const [a, b] of spans) {
      while (j < out.length && out[j] < a - 1e-9) j++;
      let k = j; while (k < out.length && out[k] <= b + 1e-9) k++;
      if (k - j < 2) solid.push([a, b]);
    }
    return { t: out.filter((t) => spans.some(([a, b]) => t >= a - 1e-9 && t <= b + 1e-9)), solid };
  }
  function sampleOf(id) {
    const key = ctx.version(), pres = ctx.pres();
    if (cache.key !== key || cache.pres !== pres) cache = { key, pres, map: new Map() };
    if (cache.map.has(id)) return cache.map.get(id);
    const p = pres?.streams?.[id];
    let s = null;
    if (p) {
      const sg = ctx.sig(), col = id.startsWith('signals.') ? sg.v[id.slice(8)] : null;
      if (col) {
        const t = [], v = [];
        let text = false;
        for (let i = 0; i < sg.t.length; i++) if (col[i] != null) { t.push(sg.t[i]); if (typeof col[i] === 'number') v.push(col[i]); else text = true; }
        // a signal that is not a number (a colour name) has no curve: its lane is the density of its samples
        s = { type: text ? 'ticks' : 'signal', t, v, ...stats(t), spans: p.spans || [], solid: [] };
      } else if (p.times) {
        s = { type: 'times', t: p.times, ...stats(p.times), spans: [] };
      } else if (p.spans && ctx.hasTicks() && ctx.fr().t.length) {
        const k = tickTimes(id, p.spans);
        s = { type: 'ticks', t: k.t, solid: k.solid, ...stats(k.t), spans: p.spans };
      } else s = { type: 'spans', t: [], solid: p.spans || [], med: 0, regular: false, spans: p.spans || [] };
    }
    cache.map.set(id, s);
    return s;
  }
  // a joint that comes within its limits: the same bands the Signals view draws (sigviz.js), summarised for the lane
  function limitFlag(id, s) {
    const lim = s?.type === 'signal' && id.startsWith('signals.joint_') ? jointLimits(ctx.robot(), id.slice(8)) : null;
    if (!lim || !s.v.length) return null;
    const lo = Math.min(...s.v), hi = Math.max(...s.v), near = NEAR * (lim.upper - lim.lower);
    if (hi > lim.upper || lo < lim.lower) return { status: 'error', why: `beyond its ${hi > lim.upper ? 'upper' : 'lower'} limit ${+(hi > lim.upper ? lim.upper : lim.lower).toFixed(3)}`, lim };
    if (hi > lim.upper - near || lo < lim.lower + near) return { status: 'warn', why: `near its ${hi > lim.upper - near ? 'upper' : 'lower'} limit ${+(hi > lim.upper - near ? lim.upper : lim.lower).toFixed(3)}`, lim };
    return null;
  }
  const describe = (id) => {
    const s = sampleOf(id), st = ctx.stream(id);
    if (!s) return st?.missing ? `not in this run: ${st.why || 'missing'}` : '';
    if (s.type === 'signal' && s.v.length) return `${s.v.length} samples, ${+Math.min(...s.v).toFixed(3)} to ${+Math.max(...s.v).toFixed(3)}${st?.unit ? ' ' + st.unit : ''}`;
    if (s.t.length > 1 && s.med) return `${s.t.length} samples, about ${+(1 / s.med).toFixed(1)} Hz`;
    return `${s.t.length || s.solid?.length || 0} ${s.t.length ? 'samples' : 'spans'}`;
  };

  // ---- the model: sections, their lanes, their missing line ---------------------------------------------------------------------------------------
  const isFold = (id, def) => { const v = (prefs().open || {})['lane:' + id]; return typeof v === 'boolean' ? v : def; };
  const isMissOpen = (id) => (prefs().open || {})['lanemiss:' + id] === true;
  function build() {
    const T = ctx.tree(), pres = ctx.pres()?.streams || {}, sel = ctx.sel(), evs = ctx.events(), out = [];
    const keep = (id) => T.nodes[id].leaf && id !== 'events' && id !== 'anomalies' && (pres[id] || ctx.stream(id)?.missing) && (ctx.hasTicks() || !ctx.hasSignals() || !ctx.stream(id)?.missing);
    const ev = evs.map((e, i) => ({ e, i, status: evStatus(e), pre: concerns(e, ctx.isStop) })).filter((x) => RANK[x.status]);
    for (const n of T.tree) {
      if (!n.section) continue;
      const ids = T.leaves(n.id).filter(keep);
      if (!ids.length) continue;
      const lack = (id) => ctx.stream(id)?.missing || !pres[id];
      const live = ids.filter((id) => !lack(id)), miss = ids.filter(lack);
      const holds = sel === n.id || (T.parents[sel] || []).includes(n.id);
      const open = isFold(n.id, holds);
      const flags = live.map((id) => [id, limitFlag(id, sampleOf(id))]).filter(([, f]) => f);
      const mine = ev.filter((x) => live.some((id) => x.pre.some((p) => id.startsWith(p))));
      let worst = null;                         // the section's worst: the highest rank, the earliest of those
      for (const x of mine) if (!worst || RANK[x.status] > RANK[worst.status]) worst = { status: x.status, text: `${x.e.anomaly?.anomaly ?? x.e.kind} at ${x.e.t.toFixed(2)} s`, t: x.e.t };
      for (const [id, f] of flags) if (!worst || RANK[f.status] > RANK[worst.status]) worst = { status: f.status, text: `${ctx.name(id)} ${f.why}`, t: null };
      out.push({ id: n.id, name: n.name, live, miss, open, holds, tone: toneOf(n.id), worst, events: mine, flags: new Map(flags), missOpen: isMissOpen(n.id) });
    }
    return out;
  }
  const flagHtml = (st) => (st ? `<span class="flag" data-status="${st}" aria-hidden="true"><span class="ui-glyph">${glyph(st)}</span></span>` : '');

  // ---- DOM ----------------------------------------------------------------------------------------------------------------------------------------------
  function render() {
    const run = ctx.run();
    if (!run) { clear(); return; }
    model = build();
    const sel = ctx.sel(), L = [], R = [];
    for (const s of model) {
      const word = s.worst ? `. Worst: ${label(s.worst.status)}, ${s.worst.text}` : '';
      const aria = `${s.name}, ${s.live.length} ${s.live.length === 1 ? 'stream' : 'streams'}, ${s.open ? 'open' : 'folded'}${word}`;
      const tone = `style="--tone:${s.tone}"`;
      L.push(`<button class="lane-s${s.holds ? ' has-sel' : ''}" data-fold="${esc(s.id)}" aria-expanded="${s.open}" ${tone} aria-label="${esc(aria)}" title="${esc(aria)}">`
        + `<span class="caret">${ctx.icon('chev', 12)}</span><span class="nm">${esc(s.name)}</span><span class="n">${s.live.length}</span>${flagHtml(s.worst?.status)}</button>`);
      R.push(`<div class="dl sec${s.open ? ' open' : ''}${s.holds ? ' has-sel' : ''}" data-sec="${esc(s.id)}" ${tone}><span class="dl-name" role="button" tabindex="0" data-fold="${esc(s.id)}" aria-expanded="${s.open}">${esc(s.name)}</span></div>`);
      const lane = (id, missing) => {
        const nm = ctx.name(id), f = s.flags.get(id), st = ctx.stream(id), why = missing ? `not in this run${st?.why ? ': ' + st.why : ''}` : describe(id);
        const aria2 = `${nm}${f ? `, ${label(f.status)}: ${f.why}` : ''}${why ? `, ${why}` : ''}`;
        const spark = !missing && id.startsWith('signals.') ? ' spark' : '';
        L.push(`<button class="lane-l${spark}${missing ? ' missing' : ''}${ctx.shown(id) ? '' : ' hid'}${sel === id ? ' sel' : ''}" data-lane="${esc(id)}" data-sec="${esc(s.id)}" ${tone} aria-label="${esc(aria2)}" title="${esc(id + (why ? ' — ' + why : ''))}"${sel === id ? ' aria-current="true"' : ''}>`
          + `<span class="nm">${esc(nm)}</span>${f ? flagHtml(f.status) : ''}${missing ? '<em>not in this run</em>' : ''}</button>`);
        R.push(`<div class="dl${spark}${missing ? ' missing' : ''}${ctx.shown(id) ? '' : ' hid'}${sel === id ? ' sel' : ''}" data-lane="${esc(id)}" data-sec="${esc(s.id)}" ${tone}><span class="dl-name" role="button" tabindex="0" data-lane="${esc(id)}">${esc(nm)}</span></div>`);
      };
      if (s.open) for (const id of s.live) lane(id, false);
      if (s.open && s.miss.length) {
        const n = s.miss.length, txt = `${n} ${n === 1 ? 'stream' : 'streams'} not in this run`;
        L.push(`<button class="lane-m" data-miss="${esc(s.id)}" data-n="${n}" aria-expanded="${s.missOpen}" ${tone}><span class="caret">${ctx.icon('chev', 10)}</span>${txt}</button>`);
        R.push(`<div class="dl miss" data-sec="${esc(s.id)}"></div>`);
        if (s.missOpen) for (const id of s.miss) lane(id, true);
      }
    }
    left.innerHTML = L.join('');
    right.innerHTML = '<canvas class="lanes-cv" aria-hidden="true"></canvas>' + R.join('');
    cv = right.firstChild;
    gapBands();
    paint();
    nearIdx = -2; syncTime();
  }
  function clear() { left.innerHTML = ''; right.innerHTML = ''; cv = null; model = []; }
  const rowOf = (el) => ({ top: el.offsetTop, h: el.offsetHeight });
  // the stretch where the run has ticks but no depth frames, hatched on the Senses block only: the gap is a fact about the depth sensor
  function gapBands() {
    const blk = [...right.querySelectorAll('.dl[data-sec="sec.senses"]')];
    if (!blk.length || !ctx.gaps) return;
    const top = blk[0].offsetTop, bot = blk[blk.length - 1].offsetTop + blk[blk.length - 1].offsetHeight;
    for (const [a, b] of ctx.gaps()) {                  // in percent, so a resize needs no new layout
      const el = document.createElement('span');
      el.className = 'gap'; el.title = `No depth frames ${a.toFixed(2)} – ${b.toFixed(2)} s`;
      el.style.cssText = `left:${ctx.pct(a)}%;width:${ctx.pct(b) - ctx.pct(a)}%;top:${top}px;height:${bot - top}px`;
      right.appendChild(el);
    }
  }

  // ---- drawing --------------------------------------------------------------------------------------------------------------------------------------
  function paint() {
    if (!cv || !model.length) return;
    const W = right.clientWidth, H = right.offsetHeight, dpr = window.devicePixelRatio || 1;
    if (W < 4 || H < 4) return;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = W + 'px'; cv.style.height = H + 'px';
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const [a0, b0] = ctx.span(), secPx = (b0 - a0) / W, xOf = (t) => ((t - a0) / (b0 - a0)) * W;
    const col = { text3: rgbOf(cssVar('--text-3')), accent: rgbOf(cssVar('--accent')), st: {}, soft: {} };
    for (const s of ['warn', 'alert', 'error']) { col.st[s] = rgbOf(cssVar(`--status-${s}`)); col.soft[s] = rgbOf(cssVar(`--status-${s}-soft`)); }
    const tones = {};
    const toneRgb = (v) => (tones[v] ||= (() => { const n = tokenName(v); return mix(rgbOf(n ? cssVar(n) : cssVar('--text-3')), col.text3, 0.3); })());
    const els = new Map([...right.querySelectorAll('.dl')].map((e) => [e, rowOf(e)]));
    for (const [el, r] of els) {
      const secId = el.dataset.sec, s = model.find((m) => m.id === secId), tone = toneRgb(s ? s.tone : 'var(--text-3)');
      if (el.classList.contains('miss')) continue;
      if (el.classList.contains('sec')) { summary(g, s, el.classList.contains('open'), r, xOf, tone, col, secPx); continue; }
      if (el.classList.contains('missing')) continue;
      const id = el.dataset.lane, smp = sampleOf(id), dim = el.classList.contains('hid') ? 0.45 : 1, isSel = id === ctx.sel();
      const c = isSel ? col.accent : tone;
      if (!smp) continue;
      drawStream(g, id, smp, r, W, xOf, secPx, c, dim, col, s.flags.get(id));
    }
  }
  // one stream's data in the band of a row: a numeric signal as a sparkline, anything else as the density of its samples
  function drawStream(g, id, smp, r, W, xOf, secPx, c, dim, col, flag) {
    if (smp.type === 'signal' && smp.v.length) sparkline(g, id, smp, r, W, xOf, secPx, c, dim, col, flag);
    else density(g, smp, r, W, xOf, secPx, c, dim, col);
  }
  const inner = (r) => ({ y0: r.top + 4, y1: r.top + r.h - 4 });
  // a stretch where a regular stream has no samples: hatched and edged, so a gap is a mark and not just fewer ticks
  const gapsOf = (s, secPx) => {
    const out = [];
    if (!s.regular || !s.med) return out;
    const min = Math.max(2.5 * s.med, 6 * secPx);
    for (let i = 1; i < s.t.length; i++) if (s.t[i] - s.t[i - 1] > min) out.push([s.t[i - 1] + 0.5 * s.med, s.t[i] - 0.5 * s.med]);
    return out;
  };
  function hatch(g, x0, x1, y0, y1, col, dim) {
    if (x1 - x0 < 3) return;
    g.save(); g.beginPath(); g.rect(x0, y0, x1 - x0, y1 - y0); g.clip();
    g.strokeStyle = rgba(col.text3, 0.24 * dim); g.lineWidth = 1; g.beginPath();
    for (let x = x0 - (y1 - y0); x < x1; x += 6) { g.moveTo(x, y1); g.lineTo(x + (y1 - y0), y0); }
    g.stroke();
    g.fillStyle = rgba(col.text3, 0.24 * dim); g.fillRect(x0, y0, 1, y1 - y0); g.fillRect(x1 - 1, y0, 1, y1 - y0);
    g.restore();
  }
  function gaps(g, s, r, xOf, secPx, col, dim) {
    const { y0, y1 } = inner(r);
    for (const [a, b] of gapsOf(s, secPx)) hatch(g, xOf(a), xOf(b), y0, y1, col, dim);
  }

  // a section's summary lane: the union of its streams' presence, the events that are a problem as ticks, the worst one as its status chip
  function summary(g, s, open, r, xOf, tone, col, secPx) {
    if (!s) return;
    const iv = [];
    for (const id of s.live) {
      const p = ctx.pres()?.streams?.[id];
      for (const [a, b] of p?.spans || []) iv.push([a, b]);
      for (const t of p?.times || []) iv.push([t - 1.5 * secPx, t + 1.5 * secPx]);
    }
    iv.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const [a, b] of iv) { const l = merged[merged.length - 1]; if (l && a <= l[1] + 1e-9) l[1] = Math.max(l[1], b); else merged.push([a, b]); }
    const { y0, y1 } = inner(r), strips = pick(s.live, 6), many = strips.length >= 2;
    if (!open && s.live.length === 1) {                  // one stream: its own data is the summary, not a band
      const smp = sampleOf(s.live[0]);
      if (smp) drawStream(g, s.live[0], smp, r, right.clientWidth, xOf, secPx, tone, 1, col, s.flags.get(s.live[0]));
      for (const x of s.events) { g.fillStyle = rgba(col.st[x.status], 0.9); g.fillRect(Math.round(xOf(x.e.t)) - 1, y0 + 1, 2, y1 - y0 - 2); }
      if (s.worst?.t != null) chip(g, xOf(s.worst.t), (y0 + y1) / 2, s.worst.status, col);
      return;
    }
    // the union is the band; when the section has several streams, each of up to six is a hairline over it (a signal as a heat strip of its values), so a stream
    // that drops out, or a joint that moves, shows on the folded lane
    const h = many ? y1 - y0 : Math.min(8, y1 - y0 - 4), y = many ? y0 : y0 + (y1 - y0 - h) / 2;
    const top = rgba(tone, open ? 0.34 : many ? 0.5 : 0.8), bot = rgba(tone, open ? 0.16 : many ? 0.28 : 0.5), grad = g.createLinearGradient(0, y, 0, y + h);
    grad.addColorStop(0, top); grad.addColorStop(1, bot);
    for (const [a, b] of merged) {
      const x = xOf(a), w = Math.max(2, xOf(b) - x);
      g.fillStyle = grad; g.beginPath(); g.roundRect(x, y, w, h, 3); g.fill();
      g.fillStyle = rgba(tone, 0.95); g.fillRect(x, y, w, 1.5);
    }
    if (many && !open) strips.forEach((id, i) => strip(g, id, y0 + 1 + (i * (y1 - y0 - 2)) / strips.length, Math.max(1.5, (y1 - y0 - 2) / strips.length - 1), xOf, secPx, tone));
    for (const x of s.events) { g.fillStyle = rgba(col.st[x.status], 0.9); g.fillRect(Math.round(xOf(x.e.t)) - 1, y0 + 1, 2, y1 - y0 - 2); }
    const w = s.worst;
    if (w?.t != null) chip(g, xOf(w.t), (y0 + y1) / 2, w.status, col);
  }
  const pick = (ids, n) => (ids.length <= n ? ids : Array.from({ length: n }, (_, i) => ids[Math.floor((i * ids.length) / n)]));
  function strip(g, id, y, h, xOf, secPx, tone) {
    const s = sampleOf(id), p = ctx.pres()?.streams?.[id];
    if (!s) return;
    if (s.type === 'signal' && s.v.length) {
      const lo = Math.min(...s.v), span = Math.max(...s.v) - lo || 1, sum = new Map();
      for (let i = 0; i < s.t.length; i++) { const k = Math.floor(xOf(s.t[i]) / 2), a = sum.get(k) || [0, 0]; a[0] += (s.v[i] - lo) / span; a[1]++; sum.set(k, a); }
      for (const [k, [v, n]] of sum) { g.fillStyle = rgba(tone, 0.25 + 0.7 * (v / n)); g.fillRect(k * 2, y, 2, h); }
      return;
    }
    g.fillStyle = rgba(tone, 0.8);
    for (const [a, b] of p?.spans || []) g.fillRect(xOf(a), y, Math.max(2, xOf(b) - xOf(a)), h);
    for (const t of p?.times || []) g.fillRect(Math.round(xOf(t)) - 0.5, y, 1.5, h);
  }
  function chip(g, x, y, status, col) {
    g.fillStyle = rgba(col.soft[status]); g.strokeStyle = rgba(col.st[status]); g.lineWidth = 1;
    g.beginPath(); g.roundRect(x - 6.5, y - 6.5, 13, 13, 3); g.fill(); g.stroke();
    g.fillStyle = rgba(col.st[status]); g.font = '700 10px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(glyph(status), x, y + 0.5);
  }
  // the density of a stream's samples, per bucket of about three samples: the height is the share of the samples that should be there; none is a hole
  function density(g, s, r, W, xOf, secPx, c, dim, col) {
    const { y0, y1 } = inner(r), hMax = y1 - y0;
    g.fillStyle = rgba(c, 0.45 * dim);
    const cap = (x, y, w) => { g.fillStyle = rgba(c, 0.95 * dim); g.fillRect(x, y, w, 1.5); g.fillStyle = rgba(c, 0.45 * dim); };
    if (s.solid?.length) for (const [a, b] of s.solid) { const x = xOf(a), w = Math.max(2, xOf(b) - x); g.fillRect(x, y1 - hMax * 0.5, w, hMax * 0.5); cap(x, y1 - hMax * 0.5, w); }
    if (!s.t.length) return;
    gaps(g, s, r, xOf, secPx, col, dim);
    g.fillStyle = rgba(c, 0.45 * dim);
    if (!s.regular) {                                   // a few irregular records (a plan, a map): one tick each
      let last = -9;
      g.fillStyle = rgba(c, 0.9 * dim);
      for (const t of s.t) { const x = Math.round(xOf(t)); if (x - last >= 2) g.fillRect(x - 1, y0 + 1, 2, hMax - 2); last = x; }
      return;
    }
    const B = Math.max(2, (3 * s.med) / secPx), n = Math.ceil(W / B) + 1, counts = new Uint16Array(n), expect = (B * secPx) / s.med;
    const first = new Float32Array(n).fill(Infinity), last = new Float32Array(n).fill(-Infinity), half = (0.5 * s.med) / secPx;
    for (const t of s.t) {
      const x = xOf(t), k = Math.floor(x / B);
      if (k >= 0 && k < n) { counts[k]++; if (x < first[k]) first[k] = x; if (x > last[k]) last[k] = x; }
    }
    // a bucket is drawn from its first sample to its last (each half a sample wide), not across its whole width: the bar ends where the data does
    for (let k = 0; k < n; k++) {
      if (!counts[k]) continue;
      const h = Math.max(2, Math.min(1, counts[k] / expect) * hMax), x0 = Math.round(first[k] - half), x1 = Math.max(x0 + 1, Math.round(last[k] + half));
      g.fillRect(x0, y1 - h, x1 - x0, h);
      cap(x0, y1 - h, x1 - x0);
    }
  }
  // a numeric signal: the line of its values (per pixel column the extremes, so a spike is not lost), the area under it faint, and in a status colour
  // where a joint comes within its limits; a stretch with no value is a break in the line
  function sparkline(g, id, s, r, W, xOf, secPx, c, dim, col, flag) {
    const { y0, y1 } = inner(r), n = Math.ceil(W) + 1, mn = new Float32Array(n).fill(NaN), mx = new Float32Array(n).fill(NaN);
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < s.t.length; i++) {
      const x = Math.floor(xOf(s.t[i])), v = s.v[i];
      if (x < 0 || x >= n) continue;
      if (!(mn[x] <= v)) mn[x] = v;
      if (!(mx[x] >= v)) mx[x] = v;
      if (v < lo) lo = v; if (v > hi) hi = v;
    }
    if (!Number.isFinite(lo)) return;
    const span = hi - lo || 1, yOf = (v) => y1 - ((v - lo) / span) * (y1 - y0), breakPx = Math.max(4, ((s.med || 0) * 3) / secPx);
    gaps(g, s, r, xOf, secPx, col, dim);
    let seg = [];
    const flush = () => {
      if (!seg.length) return;
      g.beginPath(); g.moveTo(seg[0][0], y1); for (const [x, y] of seg) g.lineTo(x, y); g.lineTo(seg[seg.length - 1][0], y1); g.closePath();
      const fill = g.createLinearGradient(0, y0, 0, y1);
      fill.addColorStop(0, rgba(c, 0.45 * dim)); fill.addColorStop(1, rgba(c, 0.06 * dim));
      g.fillStyle = fill; g.fill();
      g.beginPath(); seg.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
      g.strokeStyle = rgba(c, 0.95 * dim); g.lineWidth = 1.5; g.lineJoin = 'round'; g.stroke();
      seg = [];
    };
    let prev = -1e9;
    for (let x = 0; x < n; x++) {
      if (Number.isNaN(mn[x])) continue;
      if (x - prev > breakPx) flush();
      const mid = (mn[x] + mx[x]) / 2;
      if (mx[x] > mn[x]) { g.fillStyle = rgba(c, 0.35 * dim); g.fillRect(x, yOf(mx[x]), 1, Math.max(1, yOf(mn[x]) - yOf(mx[x]))); }
      seg.push([x + 0.5, yOf(mid)]);
      prev = x;
    }
    flush();
    if (flag?.lim) {
      const near = NEAR * (flag.lim.upper - flag.lim.lower);
      for (let x = 0; x < n; x++) {
        if (Number.isNaN(mn[x])) continue;
        const bad = mx[x] > flag.lim.upper || mn[x] < flag.lim.lower ? 'error' : mx[x] > flag.lim.upper - near || mn[x] < flag.lim.lower + near ? 'warn' : null;
        if (!bad) continue;
        g.fillStyle = rgba(col.st[bad], 0.95 * dim);
        const ya = yOf(mx[x]), yb = yOf(mn[x]);
        g.fillRect(x - 0.5, Math.min(ya, yb) - 1, 2, Math.abs(yb - ya) + 3);
      }
    }
  }

  // ---- the playhead on an event --------------------------------------------------------------------------------------------------------------------
  function nearest() {
    const evs = ctx.events(), run = ctx.run();
    if (!evs.length || !run) return -1;
    const [a0, b0] = ctx.span(), W = right.clientWidth || 800, t = ctx.time();
    const tol = Math.max((NEAR_PX * (b0 - a0)) / W, 0.5 * ((run.t1 - run.t0) / Math.max(1, (run.ticks || 2) - 1)));
    let best = -1, d = tol + 1e-9;
    evs.forEach((e, i) => { const x = Math.abs(e.t - t); if (x < d) { d = x; best = i; } });
    return best;
  }
  function syncTime() {
    if (!model.length) return;
    const i = nearest();
    if (i === nearIdx) return;
    nearIdx = i;
    if (i >= 0) ctx.wrap.dataset.near = i; else delete ctx.wrap.dataset.near;
    document.querySelectorAll('.mk.near').forEach((m) => m.classList.remove('near'));
    if (i >= 0) ctx.marks.forEach((m) => m.querySelector(`.mk[data-ev="${i}"]`)?.classList.add('near'));
    const pre = i >= 0 ? concerns(ctx.events()[i], ctx.isStop) : null;
    const hit = (ids) => ids.some((id) => pre.some((p) => id.startsWith(p)));
    for (const el of [...left.children, ...right.querySelectorAll('.dl')]) {
      let on = false, rec = false;
      if (pre && !el.classList.contains('lane-m') && !el.classList.contains('miss') && !el.classList.contains('missing')) {
        const sec = el.dataset.fold || el.dataset.sec, isSec = el.classList.contains('lane-s') || el.classList.contains('sec');
        on = isSec ? hit(model.find((m) => m.id === sec)?.live || []) : hit([el.dataset.lane]);
        rec = !on;
      }
      el.classList.toggle('hl', on); el.classList.toggle('rec', rec);
    }
  }

  // ---- input ----------------------------------------------------------------------------------------------------------------------------------------------
  function toggleFold(id) {
    const s = model.find((m) => m.id === id);
    if (!s) return;
    savePrefs({ open: { ['lane:' + id]: !s.open } });
    render();
    left.querySelector(`[data-fold="${CSS.escape(id)}"]`)?.focus();
  }
  function toggleMiss(id) {
    savePrefs({ open: { ['lanemiss:' + id]: !isMissOpen(id) } });
    render();
    left.querySelector(`[data-miss="${CSS.escape(id)}"]`)?.focus();
  }
  const act = (e) => {
    const f = e.target.closest('[data-fold]'), m = e.target.closest('[data-miss]'), l = e.target.closest('[data-lane]');
    if (f) toggleFold(f.dataset.fold); else if (m) toggleMiss(m.dataset.miss); else if (l && ctx.run()) ctx.select(l.dataset.lane);
  };
  left.addEventListener('click', act);
  right.addEventListener('click', (e) => { if (e.target.closest('.dl-name')) act(e); });
  right.addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.dl-name')) { e.preventDefault(); act(e); } });

  return { render, paint, syncTime, clear };
}
