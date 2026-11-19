// Explore, kind "Depth frame" (UXS-001): the depth frame in force at the playhead, looked at closely. The sensor's rows x cols as a grid of
// cells coloured by distance (or by what the navigator derived from them), each cell's status, and a click for one cell's values. The frame
// is the one GET .../sensor?t= answers (ADR-0014); what the navigator derived from it (floor / obstacle / overhead / below, and where the point
// is in the map frame) is not in that answer, so it is read from the tick that used the frame: the first tick after the frame with a `depth`
// list (the tick's points are the frame's derived points, one per valid zone in the sensor's order, plus one for each no-target zone the
// cliff check put a "below" point at).

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
export const RAW_VALID = [5, 9];            // the sensor's "range valid" statuses
export const NO_TARGET = 255;               // "nothing out there" (duck_lab.nav.cliff)
export const MAX_MM = 4000;                 // the colour scale's far end: the sensor's range
export const KINDS = { f: ['floor', '--c-floor'], o: ['obstacle', '--c-ob'], v: ['overhead', '--c-over'], b: ['below the floor', '--c-drop'] };

// The cell each derived point belongs to, or why they cannot be told apart. Points come in the sensor's cell order: one for each valid
// zone, and, when the cliff check put one, for a no-target zone. Equal to the valid zones: those zones in order. Equal to the valid and the
// no-target zones: every one of them in order. Anything else cannot be assigned to cells, and no guess is made.
export function cellKinds(f, pts) {
  const n = f.rows * f.cols, valid = (k) => RAW_VALID.includes(f.status[k]) && f.distance_mm[k] > 0;
  let nv = 0, nt = 0;
  for (let k = 0; k < n; k++) { if (valid(k)) nv++; else if (f.status[k] === NO_TARGET) nt++; }
  if (pts.length !== nv && pts.length !== nv + nt) return { why: `${pts.length} derived points for ${nv} valid zones and ${nt} with no target: which zone each belongs to is not recorded` };
  const withNoTarget = pts.length === nv + nt && nt > 0, cells = new Array(n).fill(null);
  let p = 0;
  for (let k = 0; k < n; k++) if (valid(k) || (withNoTarget && f.status[k] === NO_TARGET)) cells[k] = pts[p++];
  return { cells };
}
// what a status says: the two the pages call valid, the sensor's "no target", the rest unnamed
export const statusText = (s) => (RAW_VALID.includes(s) ? `${s} (range valid)` : s === NO_TARGET ? `${s} (no target)` : `${s} (not valid)`);

export function createDepthView(host, { api, data }) {
  const S = { frame: null, key: null, askedT: null, busy: false, failed: null, color: 'distance', cell: null, shown: false, why: null, der: null, layout: null };
  host.innerHTML = `<div class="xdtop"><div class="seg sm" role="group" aria-label="Colour the cells by"><button data-color="distance">Distance</button><button data-color="kind">Derived kind</button></div>
      <span class="grow"></span><span class="xs" data-x="info"></span></div>
    <div class="xmsg" data-x="msg" hidden></div>
    <div class="xcvwrap" data-x="wrap"><canvas data-x="cv" tabindex="0" aria-label="The depth frame's cells. Click one for its values, arrow keys move between cells."></canvas></div>
    <div class="xscale" data-x="scale"></div>
    <div class="xs" data-x="note"></div>
    <div class="xpart" data-x="cell"></div>`;
  const $ = (k) => host.querySelector(`[data-x="${k}"]`), cv = $('cv'), css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const distColor = (mm) => `hsl(${Math.round(240 * Math.min(Math.max(mm, 0) / MAX_MM, 1))} 65% 38%)`;
  // the text on a cell: white on the dark distance colours, black or white on a kind colour by its brightness
  const inkOn = (hex) => { const m = /^#([0-9a-f]{6})/i.exec(hex); if (!m) return '#fff'; const v = parseInt(m[1], 16); return ((v >> 16) * 0.299 + ((v >> 8) & 255) * 0.587 + (v & 255) * 0.114) > 150 ? '#000' : '#fff'; };

  const fresh = (f, d) => {
    const count = d.rawStream?.count ?? f?.n;
    return !!f && S.key === d.runId && (f.index === 0 || d.t >= f.t) && (f.next_t != null ? d.t < f.next_t : f.index >= count - 1);
  };
  // the tick that used the frame and what it derived: the first tick at or after the frame (and before the next frame) that carries points
  function derivedFor(f, d) {
    const fr = d.frames;
    if (!fr) return { why: 'the run has no ticks, so no derived points' };
    let k = Math.min(d.i, fr.t.length - 1);
    while (k > 0 && fr.t[k - 1] !== undefined && fr.t[k - 1] >= f.t) k--;
    while (fr.t[k] !== undefined && fr.t[k] < f.t) k++;
    for (; fr.t[k] !== undefined && (f.next_t == null || fr.t[k] < f.next_t); k++) {
      if (fr.depth[k]) return { points: fr.depth[k], tickT: fr.t[k] };
    }
    return { why: fr.t[k] === undefined && k < d.ticks ? 'the ticks after this frame are still loading' : 'no tick after this frame carries points (the navigator did not use it, or the run ended)' };
  }

  async function ask(d) {
    const key = d.runId, t = d.t;
    S.busy = true;
    try {
      const r = await fetch(`${api}runs/${key}/sensor?t=${t}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const f = await r.json();
      if (data().runId !== key) return;
      S.frame = f; S.key = key; S.failed = null;
    } catch (e) { S.failed = String(e.message || e); } finally { S.busy = false; S.askedT = t; }
    follow();
  }

  function follow() {
    const d = data();
    if (!d.runId) return say('Open a run to see its depth frames.');
    if (d.rawStream?.missing !== false) return say('This run has no depth frames (the stream sensors.raw is missing).');
    if (!fresh(S.frame, d) && !S.busy && S.askedT !== d.t) ask(d);
    if (!S.frame || S.key !== d.runId) return say(S.failed ? `The depth frame could not be loaded (${S.failed}).` : 'Loading the depth frame…');
    S.shown = true; S.why = null;
    $('msg').hidden = true; $('wrap').hidden = false; $('scale').hidden = false; $('cell').hidden = false;
    const f = S.frame;
    S.der = derivedFor(f, d);
    S.kinds = S.der.points ? cellKinds(f, S.der.points) : { why: S.der.why };
    if (S.color === 'kind' && !S.kinds.cells) S.color = 'distance';
    if (S.cell && (S.cell[0] >= f.rows || S.cell[1] >= f.cols)) S.cell = null;
    paint();
    paintInfo();
    paintCell();
  }
  function say(text) {
    S.shown = false; S.why = text;
    $('msg').hidden = false; $('msg').textContent = text; $('wrap').hidden = true; $('scale').hidden = true; $('cell').hidden = true; $('note').textContent = ''; $('info').textContent = '';
    for (const b of host.querySelectorAll('[data-color]')) { b.setAttribute('aria-pressed', 'false'); b.disabled = true; }
  }

  function paint() {
    const f = S.frame, wrap = $('wrap'), cs = getComputedStyle(wrap), inner = wrap.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight), w = Math.max(160, Math.min(inner || 320, 520)), dpr = window.devicePixelRatio || 1, cell = w / f.cols, h = cell * f.rows;
    cv.style.width = w + 'px'; cv.style.height = h + 'px';
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    S.layout = { w, h, cell };
    const g = cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    g.font = `${Math.max(9, Math.round(cell * 0.28))}px ui-monospace, monospace`; g.textAlign = 'center'; g.textBaseline = 'middle';
    const byKind = S.color === 'kind' && S.kinds.cells;
    const field = css('--bg-field'), faint = css('--text-faint'), warn = css('--warn'), sel = css('--draw-sel');
    for (let r = 0; r < f.rows; r++) for (let c = 0; c < f.cols; c++) {
      const k = r * f.cols + c, x = c * cell, y = r * cell, mm = f.distance_mm[k], ok = RAW_VALID.includes(f.status[k]);
      const pt = byKind ? S.kinds.cells[k] : null;
      if (byKind && pt) {
        const col = css(KINDS[pt[3]]?.[1] || '--text-dim'); g.fillStyle = col; g.fillRect(x, y, cell, cell); g.fillStyle = inkOn(col); g.fillText(String(mm), x + cell / 2, y + cell / 2);
      } else if (ok && !byKind) {
        g.fillStyle = distColor(mm); g.fillRect(x, y, cell, cell); g.fillStyle = '#fff'; g.fillText(String(mm), x + cell / 2, y + cell / 2);
      } else {
        g.fillStyle = field; g.fillRect(x, y, cell, cell);
        g.strokeStyle = faint; g.lineWidth = 1; g.beginPath();
        for (let o = -cell; o < cell; o += 6) { g.moveTo(x + Math.max(o, 0), y + Math.max(-o, 0)); g.lineTo(x + Math.min(o + cell, cell), y + Math.min(cell - o, cell)); }
        g.stroke();
        g.fillStyle = warn; g.fillText(ok ? String(mm) : 's' + f.status[k], x + cell / 2, y + cell / 2);
      }
      g.strokeStyle = 'rgba(0,0,0,.4)'; g.lineWidth = 1; g.strokeRect(x + 0.5, y + 0.5, cell - 1, cell - 1);
    }
    if (S.cell) { const [r, c] = S.cell; g.strokeStyle = sel; g.lineWidth = 2.5; g.strokeRect(c * cell + 1.5, r * cell + 1.5, cell - 3, cell - 3); }
    for (const b of host.querySelectorAll('[data-color]')) { b.setAttribute('aria-pressed', b.dataset.color === S.color); b.disabled = b.dataset.color === 'kind' && !S.kinds.cells; b.title = b.disabled ? S.kinds.why : ''; }
    // the scale
    if (byKind) {
      const n = {}; for (const p of S.kinds.cells) if (p) n[p[3]] = (n[p[3]] || 0) + 1;
      $('scale').innerHTML = Object.entries(KINDS).map(([k, [name, v]]) => `<span class="xsw"><i style="background:var(${v})"></i>${esc(name)} ${n[k] || 0}</span>`).join('') + '<span class="xsw"><i class="hatch"></i>no point</span>';
    } else {
      const stops = Array.from({ length: 9 }, (_, i) => `${distColor((i * MAX_MM) / 8)} ${(i * 100) / 8}%`).join(', ');
      $('scale').innerHTML = `<div class="xbar" style="background:linear-gradient(to right, ${stops})"></div><div class="xticks"><span>0</span><span>1 m</span><span>2 m</span><span>3 m</span><span>${MAX_MM / 1000} m+</span></div><span class="xsw"><i class="hatch"></i>status not valid</span>`;
    }
  }
  function paintInfo() {
    const f = S.frame;
    $('info').textContent = `frame ${f.index + 1} of ${f.n} · ${f.rows} × ${f.cols} · at ${(+f.t).toFixed(3)} s`;
    $('note').textContent = S.der.points
      ? (S.kinds.cells ? `Derived kinds and map points are those of the tick at ${(+S.der.tickT).toFixed(2)} s, the first to use this frame.` : `No derived kinds: ${S.kinds.why}.`)
      : `No derived kinds: ${S.der.why}.`;
  }
  function cellOut(r, c) {
    const f = S.frame, k = r * f.cols + c, pt = S.kinds.cells?.[k] || null, mm = f.distance_mm[k];
    return { row: r, col: c, mm, status: f.status[k], valid: RAW_VALID.includes(f.status[k]), kind: pt ? KINDS[pt[3]]?.[0] ?? pt[3] : null,
      point: pt ? { x: pt[0], y: pt[1], height: pt[2] } : null, why: pt ? null : S.kinds.why || null };
  }
  function paintCell() {
    if (!S.cell) { $('cell').innerHTML = '<span class="xs">Click a cell of the grid to see its values.</span>'; return; }
    const o = cellOut(...S.cell), kv = (k, v) => `<div class="kv"><span class="k">${k}</span><span class="v">${v}</span></div>`;
    $('cell').innerHTML = `<div class="xt">Cell row ${o.row}, column ${o.col}</div><div class="xs">row 0 is the top of the sensor's view, column 0 the left</div>`
      + kv('Distance', `${o.mm} mm`) + kv('Status', esc(statusText(o.status)))
      + kv('Kind', o.kind ? esc(o.kind) : S.kinds.cells ? 'none (no point was made for this zone)' : `not derived (${esc(S.kinds.why)})`)
      + kv('Map point', o.point ? `x ${o.point.x} m, y ${o.point.y} m, height ${o.point.height} m` : 'none');
  }

  function pick(r, c) {
    if (!S.shown) return null;
    const f = S.frame;
    S.cell = r == null ? null : [Math.max(0, Math.min(f.rows - 1, r)), Math.max(0, Math.min(f.cols - 1, c))];
    paint(); paintCell();
    return S.cell && cellOut(...S.cell);
  }
  cv.addEventListener('click', (e) => {
    const b = cv.getBoundingClientRect(), { cell } = S.layout;
    pick(Math.floor((e.clientY - b.top) / cell), Math.floor((e.clientX - b.left) / cell));
  });
  cv.addEventListener('keydown', (e) => {
    const d = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[e.key];
    if (!d || !S.shown) return;
    e.preventDefault();
    const [r, c] = S.cell || [0, 0];
    pick(S.cell ? r + d[0] : 0, S.cell ? c + d[1] : 0);
  });
  host.addEventListener('click', (e) => {
    const b = e.target.closest('[data-color]');
    if (b && !b.disabled) { S.color = b.dataset.color; if (S.shown) paint(); }
  });
  new ResizeObserver(() => { if (S.shown && host.offsetParent) paint(); }).observe($('wrap'));
  new MutationObserver(() => { if (S.shown) paint(); }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] });

  return {
    follow, pick,
    setColor(c) { if (c !== 'distance' && c !== 'kind') return false; if (c === 'kind' && !S.kinds?.cells) return false; S.color = c; if (S.shown) paint(); return true; },
    state() {
      const f = S.frame;
      return { shown: S.shown, why: S.why, loading: S.busy, color: S.color, index: S.shown ? f.index : null, n: S.shown ? f.n : null, t: S.shown ? f.t : null, rows: S.shown ? f.rows : null, cols: S.shown ? f.cols : null,
        distance_mm: S.shown ? f.distance_mm : null, status: S.shown ? f.status : null, derived: S.shown ? !!S.kinds.cells : false, derivedWhy: S.shown ? S.kinds.why || null : null, tickT: S.shown ? S.der.tickT ?? null : null,
        cell: S.shown && S.cell ? cellOut(...S.cell) : null,
        kinds: S.shown && S.kinds.cells ? S.kinds.cells.map((p) => p && p[3]) : null };
    },
    // where a cell is on the screen, in client pixels: to click a cell by its row and column
    screenOfCell(r, c) {
      if (!S.shown) return null;
      const b = cv.getBoundingClientRect(), { cell } = S.layout;
      return [b.left + (c + 0.5) * cell, b.top + (r + 0.5) * cell];
    },
    canvas: () => cv,
  };
}
