// What the Signals view draws besides a line (step 4.5, U15, ADR-0021): threshold bands, state-duration bars and the token ramps.
// signals.js calls these from short hooks; the colours are the tokens' (--status-*, --ramp-*), never a hand-made value, so both themes work.
// A status band is never colour alone: it has a label with its glyph and its word (status.js), and a title for a pointer.
import { glyph, label } from '/lib/status.js';

const NS = 'http://www.w3.org/2000/svg';
const svgEl = (tag, attrs = {}) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
};
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const num = (v) => String(+v.toFixed(3));

// ---- ramps -----------------------------------------------------------------------------------------------------------------------------------
const hex = (c) => {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(c);
  if (!m) return [128, 128, 128];
  const h = m[1].length === 3 ? [...m[1]].map((x) => x + x).join('') : m[1];
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
};
// a sequential or diverging ramp as a function of f in [0, 1], read from the tokens when asked (so it follows the theme); the nine stops are
// uniform in OKLab (the token test measures that), so a straight mix between two neighbours stays uniform enough for a canvas
export function seqScale(name = 'seq') {
  const stops = Array.from({ length: 9 }, (_, i) => hex(cssVar(`--ramp-${name}-${i + 1}`)));
  return (f) => {
    const x = Math.min(Math.max(Number.isFinite(f) ? f : 0, 0), 1) * 8, i = Math.min(7, Math.floor(x)), u = x - i;
    return `rgb(${stops[i].map((a, k) => Math.round(a + (stops[i + 1][k] - a) * u)).join(' ')})`;
  };
}
// black or white ink for a colour a canvas has filled, by the colour's lightness
export function inkOn(color) {
  const [r, g, b] = (String(color).match(/[\d.]+/g) || [128, 128, 128]).slice(0, 3).map((v) => {
    const c = Number(v) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.18 ? 'rgb(0 0 0)' : 'rgb(255 255 255)';
}
// the categorical ramp, by number (a signal's name) or by order of first appearance (a state)
export const catVar = (i) => `var(--ramp-cat-${(Math.abs(i) % 8) + 1})`;

// ---- state-duration bars ---------------------------------------------------------------------------------------------------------------------
// a numeric signal that only takes two to four whole values (a lock, a mode number) is a state, not a curve (the caller leaves out a signal with a unit)
export function isDiscrete(col) {
  const seen = new Set();
  for (const v of col) {
    if (v == null) continue;
    if (typeof v !== 'number' || !Number.isInteger(v)) return false;
    seen.add(v);
    if (seen.size > 4) return false;
  }
  return seen.size >= 2;
}
// spans = [{t0, t1, v}]; one rect per span in its state's colour, the state's label when it fits, the state and its duration as the title
export function drawStates(g, spans, { xOf, H, fmt }) {
  const colour = new Map();
  for (const b of spans) {
    if (!colour.has(b.v)) colour.set(b.v, colour.size);
    const x0 = xOf(b.t0), w = Math.max(1.5, xOf(b.t1) - x0 - 1), text = fmt(b.v);
    const rect = svgEl('rect', { class: 'band', x: x0.toFixed(1), y: 2, width: w.toFixed(1), height: H - 4, rx: 2, fill: catVar(colour.get(b.v)), 'data-state': String(b.v) });
    const title = svgEl('title');
    title.textContent = `${text} · ${(b.t1 - b.t0).toFixed(1)} s`;
    rect.appendChild(title);
    g.appendChild(rect);
    const room = Math.floor((w - 8) / 6.2);
    if (room >= 2) {
      const tx = svgEl('text', { class: 'bandl', x: (x0 + 5).toFixed(1), y: H / 2 + 4 });
      tx.textContent = text.length <= room ? text : text.slice(0, room - 1) + '…';
      g.appendChild(tx);
    }
  }
}

// ---- threshold bands -------------------------------------------------------------------------------------------------------------------------
const NEAR = 0.1;   // warn: inside a limit, within this share of the limits' span; error: beyond it. The data has no alert level, so none is drawn

// a joint signal (`joint_<name>`) in a robot description's joints; limits are the description's own (RFC-0011), null for a joint with none
export function jointLimits(robot, signal) {
  const j = signal.startsWith('joint_') && (robot?.joints || []).find((x) => x.name === signal.slice(6));
  return j && Number.isFinite(j.lower) && Number.isFinite(j.upper) && j.upper > j.lower ? { lower: j.lower, upper: j.upper } : null;
}
// the plot's range, widened so the error band beyond each limit has room to show
export function limitRange(lim, lo, hi) {
  const pad = NEAR * (lim.upper - lim.lower);
  return [Math.min(lo, lim.lower - pad), Math.max(hi, lim.upper + pad)];
}
// bands under the line: error beyond each limit, warn just inside it; each labelled with its glyph and word, the limits as dashed lines
export function drawLimits(svg, lim, { yOf, W, H }) {
  const near = NEAR * (lim.upper - lim.lower), top = (v) => Math.min(Math.max(yOf(v), 0), H);
  const zones = [
    ['error', 'upper', 0, top(lim.upper), `beyond the upper limit ${num(lim.upper)}`],
    ['warn', 'upper', top(lim.upper), top(lim.upper - near), `near the upper limit ${num(lim.upper)}`],
    ['warn', 'lower', top(lim.lower + near), top(lim.lower), `near the lower limit ${num(lim.lower)}`],
    ['error', 'lower', top(lim.lower), H, `beyond the lower limit ${num(lim.lower)}`],
  ];
  for (const [status, side, y0, y1, why] of zones) {
    const r = svgEl('rect', { class: 'tband', x: 0, y: y0.toFixed(1), width: W, height: Math.max(0, y1 - y0).toFixed(1), fill: `var(--status-${status}-soft)`, 'data-status': status, 'data-side': side });
    const t = svgEl('title');
    t.textContent = `${label(status)}: ${why}`;
    r.appendChild(t);
    svg.appendChild(r);
  }
  for (const [side, v] of [['upper', lim.upper], ['lower', lim.lower]]) {
    const y = yOf(v);
    svg.appendChild(svgEl('line', { class: 'tlim', x1: 0, x2: W, y1: y.toFixed(1), y2: y.toFixed(1), 'data-limit': num(v), 'data-side': side }));
    const up = side === 'upper', gap = 3;
    for (const [status, word, dy] of [['error', 'beyond', up ? -gap : 10], ['warn', 'near', up ? 10 : -gap]]) {
      const ty = y + dy;
      if (ty < 9 || ty > H - 2) continue;
      const tx = svgEl('text', { class: 'tbl', x: W - 4, y: ty.toFixed(1), 'data-status': status });
      tx.textContent = `${glyph(status)} ${word} ${num(v)}`;
      svg.appendChild(tx);
    }
  }
}
