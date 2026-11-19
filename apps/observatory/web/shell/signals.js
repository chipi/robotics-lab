// The Signals view (ADR-0013, UXS-001 "Signals"): a robot's named values over time, in the viewport of a run that has no
// pose. One chart per numeric signal (a line, its range in the label), one band per text signal (a coloured stretch per
// value, labelled), stacked, sharing one time axis and the playhead. A click or drag on a plot seeks, as on the timeline.
// Drawn as SVG from the store's columns (`sig.t`, `sig.v[name]`); colours are tokens, so both themes work.

const NS = 'http://www.w3.org/2000/svg';
const LABEL_W = 168;
const NICE = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1800, 3600];
const LEGO = { black: '#454545', blue: '#3b6fe0', green: '#34a853', yellow: '#e0b800', red: '#e04a3a', white: '#d4d4d4', brown: '#8b5a2b' };

const hash = (s) => [...String(s)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 100003, 7);
export const sigHue = (name) => (hash(name) * 47) % 360;
// a signal's colour: its hue, a lightness that reads on the theme's background
export const sigColor = (name) => `hsl(${sigHue(name)} 62% ${document.documentElement.dataset.theme === 'light' ? 40 : 62}%)`;
const bandColor = (v) => LEGO[String(v).toLowerCase()] || `hsl(${sigHue(v)} 45% 50%)`;

const fmt = (v) => (v == null ? '—' : typeof v === 'number' ? String(+v.toFixed(Math.abs(v) >= 100 ? 1 : 2)).replace('-', '−') : String(v));

function el(tag, cls, attrs = {}, ns) {
  const e = ns ? document.createElementNS(NS, tag) : document.createElement(tag);
  if (cls) e.setAttribute('class', cls);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

// the index of the last sample at or before t (0 when t is earlier), -1 for no samples
function sampleAt(ts, t) {
  if (!ts.length) return -1;
  let a = 0, b = ts.length;
  while (a < b) { const m = (a + b) >> 1; if (ts[m] <= t) a = m + 1; else b = m; }
  return Math.max(0, a - 1);
}
export { sampleAt };

// the points of a line: every sample when they fit the plot, else the extremes of each pixel column (the shape, not the count)
function linePath(ts, vs, xOf, yOf, W) {
  const parts = [];
  if (ts.length <= 2 * W) {
    let pen = false;
    for (let i = 0; i < ts.length; i++) {
      const v = vs[i];
      if (v == null) { pen = false; continue; }
      parts.push(`${pen ? 'L' : 'M'}${xOf(ts[i]).toFixed(1)} ${yOf(v).toFixed(1)}`);
      pen = true;
    }
    return parts.join('');
  }
  const lo = new Map(), hi = new Map();
  for (let i = 0; i < ts.length; i++) {
    const v = vs[i];
    if (v == null) continue;
    const c = Math.floor(xOf(ts[i]));
    if (!lo.has(c) || v < vs[lo.get(c)]) lo.set(c, i);
    if (!hi.has(c) || v > vs[hi.get(c)]) hi.set(c, i);
  }
  let first = true;
  for (const c of [...lo.keys()].sort((a, b) => a - b)) {
    for (const i of lo.get(c) === hi.get(c) ? [lo.get(c)] : [lo.get(c), hi.get(c)].sort((a, b) => a - b)) {
      parts.push(`${first ? 'M' : 'L'}${xOf(ts[i]).toFixed(1)} ${yOf(vs[i]).toFixed(1)}`);
      first = false;
    }
  }
  return parts.join('');
}

// the stretches of equal text: [{t0, t1, v}], a stretch ending where the next value starts (the last at the run's end)
function bands(ts, vs, tEnd) {
  const out = [];
  for (let i = 0; i < ts.length; i++) {
    const v = vs[i];
    if (v == null) continue;
    const last = out[out.length - 1];
    if (last && last.v === v && last.end === i - 1) { last.end = i; continue; }
    out.push({ t0: ts[i], v, end: i });
  }
  out.forEach((b, k) => { b.t1 = k + 1 < out.length ? out[k + 1].t0 : Math.max(tEnd, ts[b.end]); });
  return out;
}

export function createSignalsView(host, { seek }) {
  const scroll = el('div', 'sg-scroll');
  host.appendChild(scroll);
  let rows = [], span = [0, 1], model = null, W = 400, drag = null;

  const xOf = (t) => ((t - span[0]) / (span[1] - span[0])) * W;
  const tOf = (px) => span[0] + (px / W) * (span[1] - span[0]);

  function axis() {
    const ax = el('div', 'sg-ax'), pps = W / (span[1] - span[0]);
    const step = NICE.find((s) => s * pps >= 64) || 3600;
    const lab = el('div', 'sg-axl');
    ax.appendChild(lab);
    const track = el('div', 'sg-axp');
    for (let t = Math.ceil(span[0] / step - 1e-9) * step; t <= span[1] + 1e-9; t += step) {
      const tk = el('span', 'sg-tk');
      tk.style.left = `${xOf(t).toFixed(1)}px`;
      tk.textContent = +t.toFixed(2);
      track.appendChild(tk);
    }
    ax.appendChild(track);
    return ax;
  }

  // model: {run, sig, ids: [stream ids shown, in outliner order], selected, t}
  function render(m) {
    model = m;
    rows = [];
    scroll.textContent = '';
    const { run, sig } = m;
    const pad = Math.max(0.05, 0.012 * (run.t1 - run.t0));
    span = run.t1 > run.t0 ? [run.t0 - pad, run.t1 + pad] : [run.t0 - 0.5, run.t0 + 0.5];
    W = Math.max(120, scroll.clientWidth - LABEL_W - 2);
    const streams = new Map((run.streams || []).map((s) => [s.id, s]));
    const shown = m.ids.map((id) => streams.get(id)).filter(Boolean);
    if (!shown.length) {
      const e = el('div', 'sg-empty');
      e.textContent = run.samples ? 'No signal is shown: switch some on in the Signals group.' : 'No samples yet.';
      scroll.appendChild(e);
      return;
    }
    scroll.appendChild(axis());
    const numeric = shown.filter((s) => s.kind !== 'text').length, texts = shown.length - numeric;
    const TEXT_H = 40;
    const H = Math.max(54, Math.min(96, Math.floor((scroll.clientHeight - 22 - texts * (TEXT_H + 1) - numeric) / Math.max(1, numeric))));
    for (const s of shown) rows.push(row(s, sig, s.kind === 'text' ? TEXT_H : H, m));
    update(m.t);
  }

  function row(s, sig, H, m) {
    const name = s.name, col = sig.v[name] || [], ts = sig.t;
    const r = el('div', 'sg' + (m.selected === s.id ? ' sel' : ''), { 'data-sig': s.id, 'data-kind': s.kind || 'number' });
    const lab = el('div', 'sg-l');
    const nm = el('span', 'nm'); nm.textContent = name; nm.title = s.id;
    const sw = el('i', 'sw'); sw.style.background = sigColor(name);
    const val = el('span', 'val'); val.setAttribute('data-val', '');
    const u = el('span', 'u'); u.textContent = s.unit || '';
    const head = el('div', 'sg-h'); head.append(sw, nm);
    const cur = el('div', 'sg-c'); cur.append(val, u);
    lab.append(head, cur);
    const plot = el('div', 'sg-p');
    plot.style.height = `${H}px`;
    const svg = el('svg', '', { width: W, height: H, viewBox: `0 0 ${W} ${H}` }, true);
    plot.appendChild(svg);
    r.append(lab, plot);
    scroll.appendChild(r);
    const o = { id: s.id, name, kind: s.kind || 'number', col, ts, val, svg, H, plot, ph: null, dot: null };
    if (o.kind === 'text') {
      const g = el('g', '', {}, true);
      for (const b of bands(ts, col, m.run.t1)) {
        const x0 = xOf(b.t0), w = Math.max(1.5, xOf(b.t1) - x0 - 1);
        const rect = el('rect', 'band', { x: x0.toFixed(1), y: 2, width: w.toFixed(1), height: H - 4, rx: 2, fill: bandColor(b.v) }, true);
        g.appendChild(rect);
        const room = Math.floor((w - 8) / 6.2);
        if (room >= 2) {
          const tx = el('text', 'bandl', { x: (x0 + 5).toFixed(1), y: H / 2 + 4 }, true);
          tx.textContent = String(b.v).length <= room ? String(b.v) : String(b.v).slice(0, room - 1) + '…';
          g.appendChild(tx);
        }
      }
      svg.appendChild(g);
    } else {
      let lo = Infinity, hi = -Infinity;
      for (const v of col) if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; }
      if (lo === Infinity) { lo = 0; hi = 1; }
      if (hi === lo) { const d = Math.abs(lo) * 0.1 || 1; lo -= d; hi += d; }
      const yOf = (v) => H - 5 - ((v - lo) / (hi - lo)) * (H - 10);
      o.yOf = yOf;
      for (const f of [0, 0.5, 1]) {
        svg.appendChild(el('line', 'gridl', { x1: 0, x2: W, y1: yOf(lo + f * (hi - lo)).toFixed(1), y2: yOf(lo + f * (hi - lo)).toFixed(1) }, true));
      }
      svg.appendChild(el('path', 'line', { d: linePath(ts, col, xOf, yOf, W), stroke: sigColor(name) }, true));
      const rng = el('div', 'sg-r');
      const rHi = el('span'); rHi.textContent = fmt(hi);
      const rLo = el('span'); rLo.textContent = fmt(lo);
      rng.append(rHi, rLo);
      plot.appendChild(rng);
      o.dot = el('circle', 'dot', { r: 3.5, fill: sigColor(name) }, true);
      svg.appendChild(o.dot);
    }
    o.ph = el('line', 'ph', { y1: 0, y2: H }, true);
    svg.appendChild(o.ph);
    return o;
  }

  // the playhead and the values at t (cheap: no rebuild)
  function update(t) {
    if (!model) return;
    const { sig } = model, i = sampleAt(sig.t, t);
    host.dataset.t = t;
    host.dataset.sample = i;
    for (const o of rows) {
      const v = i >= 0 ? o.col[i] : null;
      o.val.textContent = fmt(v);
      const x = xOf(t).toFixed(1);
      o.ph.setAttribute('x1', x); o.ph.setAttribute('x2', x);
      if (o.dot) {
        const ok = typeof v === 'number';
        o.dot.setAttribute('visibility', ok ? 'visible' : 'hidden');
        if (ok) { o.dot.setAttribute('cx', xOf(sig.t[i]).toFixed(1)); o.dot.setAttribute('cy', o.yOf(v).toFixed(1)); }
      }
    }
  }

  // seeking: a press or a drag on any plot
  const timeAt = (e, plot) => {
    const r = plot.getBoundingClientRect();
    const t = tOf(Math.min(Math.max(e.clientX - r.left, 0), r.width) * (W / r.width));
    return Math.min(Math.max(t, model.run.t0), model.run.t1);
  };
  scroll.addEventListener('pointerdown', (e) => {
    const plot = e.target.closest('.sg-p');
    if (e.button !== 0 || !plot || !model) return;
    drag = plot;
    plot.setPointerCapture(e.pointerId);
    seek(timeAt(e, plot));
  });
  scroll.addEventListener('pointermove', (e) => { if (drag && model && drag.hasPointerCapture(e.pointerId)) seek(timeAt(e, drag)); });
  scroll.addEventListener('pointerup', () => { drag = null; });

  return { render, update, rows: () => rows, width: () => W };
}
