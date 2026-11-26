// Explore, kind "Map" (UXS-001): the world grid in force at the playhead, enlarged, in the robot's own map frame: the occupancy cells, the obstacle
// memory and the drops, the plan in force, the belief pose, the semantic map's objects and the operator's areas (the `site` event) when the run
// has them. Drag to pan, scroll or the buttons to zoom, click a cell for its value and where it is. Plain canvas; the colours are the page's
// theme tokens and the semantic map's own (shell/semantic.js).
import { LANDMARK_MIN } from './semantic.js';

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
const LAYERS = [['obstacles', 'Obstacles'], ['drops', 'Drops'], ['plan', 'Plan'], ['objects', 'Objects'], ['areas', 'Areas']];
export const CELL_NAME = { '?': 'unknown', '.': 'free', '#': 'occupied' };

export function createMapView(host, { data }) {
  const S = { view: null, key: null, cell: null, point: null, shown: false, why: null, layers: Object.fromEntries(LAYERS.map(([k]) => [k, true])), w: 0, h: 0, grid: null, d: null };
  host.innerHTML = `<div class="xdtop"><div class="seg sm" role="group" aria-label="Layers" data-x="layers">${LAYERS.map(([k, n]) => `<button data-layer="${k}" aria-pressed="true">${n}</button>`).join('')}</div>
      <span class="grow"></span><button class="btn" data-zoom="out" aria-label="Zoom out">−</button><button class="btn" data-zoom="in" aria-label="Zoom in">+</button><button class="btn" data-zoom="fit">Fit</button></div>
    <div class="xmsg" data-x="msg" hidden></div>
    <div class="xmapwrap" data-x="wrap"><canvas data-x="cv" tabindex="0" aria-label="The map. Drag to pan, scroll to zoom, click a cell for its value."></canvas></div>
    <div class="xs" data-x="info"></div>
    <div class="xpart" data-x="cell"></div>`;
  const $ = (k) => host.querySelector(`[data-x="${k}"]`), cv = $('cv'), css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const grid = () => S.d?.world?.grid;
  const px = (x) => (x - S.view.cx) * S.view.k + S.w / 2, py = (y) => S.h / 2 - (y - S.view.cy) * S.view.k;
  const mx = (sx) => (sx - S.w / 2) / S.view.k + S.view.cx, my = (sy) => (S.h / 2 - sy) / S.view.k + S.view.cy;

  // the box that holds what is to be seen (the grid, the areas, the belief), the view that fits it
  function fit() {
    const g = grid(), xs = [], ys = [];
    if (g) { xs.push(g.origin[0], g.origin[0] + g.w * g.res); ys.push(g.origin[1], g.origin[1] + g.h * g.res); }
    for (const a of S.d?.areas || []) for (const [x, y] of a.polygon) { xs.push(x); ys.push(y); }
    if (S.d?.belief) { xs.push(S.d.belief[0]); ys.push(S.d.belief[1]); }
    if (!xs.length || !S.w) return;
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    S.view = { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, k: Math.min(S.w / Math.max(x1 - x0, 0.1), S.h / Math.max(y1 - y0, 0.1)) * 0.94 };
  }
  function size() {
    const w = Math.max(200, Math.min($('wrap').clientWidth || 320, 900)), h = Math.round(Math.max(220, Math.min(w * 0.8, 560))), dpr = window.devicePixelRatio || 1;
    cv.style.width = w + 'px'; cv.style.height = h + 'px';
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const first = !S.w || !S.view;
    S.w = w; S.h = h;
    if (first) fit();
  }

  function follow() {
    const d = data();
    S.d = d;
    if (!d.runId) return say('Open a run to see its map.');
    if (!d.ticks) return say('This run has no ticks, so no map.');
    if (d.worldStream?.missing !== false && !d.world) return say('This run has no world grid (the robot did not record its map).');
    if (!d.world) return say(`No map yet at ${d.t.toFixed(2)} s: the first one comes later in the run.`);
    S.shown = true; S.why = null;
    $('msg').hidden = true; $('wrap').hidden = false; $('cell').hidden = false;
    if (S.key !== d.runId) { S.key = d.runId; S.view = null; S.cell = null; S.point = null; S.grid = null; }
    size();
    paint(); paintInfo(); paintCell();
  }
  function say(text) {
    S.shown = false; S.why = text;
    $('msg').hidden = false; $('msg').textContent = text; $('wrap').hidden = true; $('cell').hidden = true; $('info').textContent = '';
  }

  // the grid as an image of its own (one pixel a cell), kept for the snapshot in force
  function gridImage(world) {
    if (S.grid?.world === world) return S.grid;
    const g = world.grid, off = document.createElement('canvas');
    off.width = g.w; off.height = g.h;
    const c = off.getContext('2d'), im = c.createImageData(g.w, g.h);
    const free = css('--data-free'), occ = css('--data-occupied'), rgb = (hex) => { const v = parseInt(hex.slice(1, 7), 16); return [v >> 16, (v >> 8) & 255, v & 255]; };
    const F = rgb(free), O = rgb(occ), n = { '?': 0, '.': 0, '#': 0 };
    for (let j = 0; j < g.h; j++) for (let i = 0; i < g.w; i++) {
      const ch = g.cells[j * g.w + i], o = ((g.h - 1 - j) * g.w + i) * 4;       // row 0 of the cells is the lowest y: the image's last row
      n[ch] = (n[ch] || 0) + 1;
      const col = ch === '#' ? O : ch === '.' ? F : null;
      if (col) { im.data[o] = col[0]; im.data[o + 1] = col[1]; im.data[o + 2] = col[2]; im.data[o + 3] = 255; }
    }
    c.putImageData(im, 0, 0);
    return (S.grid = { world, off, n });
  }

  function paint() {
    const d = S.d, g = d.world.grid, c = cv.getContext('2d'), dpr = window.devicePixelRatio || 1, L = S.layers;
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.fillStyle = css('--surface-1'); c.fillRect(0, 0, S.w, S.h);
    const img = gridImage(d.world);
    c.imageSmoothingEnabled = false;
    c.drawImage(img.off, px(g.origin[0]), py(g.origin[1] + g.h * g.res), g.w * g.res * S.view.k, g.h * g.res * S.view.k);
    const cellPx = g.res * S.view.k;
    if (cellPx >= 7) {                                                    // the cell lines, once a cell is big enough to have edges
      c.strokeStyle = css('--scene-grid'); c.lineWidth = 1; c.beginPath();
      for (let i = 0; i <= g.w; i++) { const x = Math.round(px(g.origin[0] + i * g.res)) + 0.5; c.moveTo(x, py(g.origin[1])); c.lineTo(x, py(g.origin[1] + g.h * g.res)); }
      for (let j = 0; j <= g.h; j++) { const y = Math.round(py(g.origin[1] + j * g.res)) + 0.5; c.moveTo(px(g.origin[0]), y); c.lineTo(px(g.origin[0] + g.w * g.res), y); }
      c.stroke();
    }
    c.strokeStyle = css('--line-strong'); c.lineWidth = 1; c.strokeRect(px(g.origin[0]) + 0.5, py(g.origin[1] + g.h * g.res) + 0.5, g.w * g.res * S.view.k, g.h * g.res * S.view.k);
    const dot = (list, color, r) => { c.fillStyle = color; for (const [x, y] of list || []) { c.beginPath(); c.arc(px(x), py(y), r, 0, 6.2832); c.fill(); } };
    const dotR = Math.max(2, Math.min(cellPx * 0.4, 5));
    if (L.areas) for (const a of d.areas || []) {
      c.strokeStyle = c.fillStyle = css('--data-area'); c.lineWidth = 2; c.setLineDash([6, 4]); c.beginPath();
      a.polygon.forEach(([x, y], n) => (n ? c.lineTo(px(x), py(y)) : c.moveTo(px(x), py(y))));
      c.closePath(); c.stroke(); c.setLineDash([]);
      const cx = a.polygon.reduce((s, p) => s + p[0], 0) / a.polygon.length, cy = a.polygon.reduce((s, p) => s + p[1], 0) / a.polygon.length;
      c.font = '12px ' + (css('--font-ui') || 'sans-serif'); c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText(a.name, px(cx), py(cy));
    }
    if (L.obstacles) dot(d.world.obstacles, css('--data-obstacle'), dotR);
    if (L.drops) dot(d.world.drops, css('--data-drop'), dotR);
    if (L.objects) for (const o of d.objects || []) {
      const hex = css(o.landmark >= LANDMARK_MIN ? '--data-landmark' : '--data-object');
      c.strokeStyle = c.fillStyle = hex; c.lineWidth = 2;
      let top = null;
      for (const [x, y, hx, hy, yaw, , z1] of o.parts) {
        const cs = Math.cos(yaw), sn = Math.sin(yaw), q = [[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]].map(([u, v]) => [px(x + cs * u - sn * v), py(y + sn * u + cs * v)]);
        c.globalAlpha = o.confirmed ? 0.35 : 0.12; c.beginPath(); q.forEach((p, n) => (n ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1]))); c.closePath(); c.fill();
        c.globalAlpha = o.confirmed ? 1 : 0.5; c.stroke(); c.globalAlpha = 1;
        if (!top || z1 >= top[2]) top = [x, y, z1];
      }
      if (o.confirmed && top) { c.font = '11px ' + (css('--font-ui') || 'sans-serif'); c.textAlign = 'center'; c.textBaseline = 'bottom'; c.fillText(o.kind, px(top[0]), py(top[1]) - 4); }
    }
    if (L.plan && d.plan?.path?.length) {
      c.strokeStyle = css('--data-plan'); c.lineWidth = 2.5; c.lineJoin = 'round'; c.beginPath();
      d.plan.path.forEach(([x, y], n) => (n ? c.lineTo(px(x), py(y)) : c.moveTo(px(x), py(y))));
      c.stroke();
    }
    if (d.belief) {
      const [x, y, yaw] = d.belief, r = Math.max(5, (d.radius || 0.08) * S.view.k);
      c.fillStyle = css('--data-belief'); c.strokeStyle = css('--scene-select'); c.lineWidth = 1.5;
      c.beginPath(); c.arc(px(x), py(y), r, 0, 6.2832); c.fill(); c.stroke();
      c.beginPath(); c.moveTo(px(x), py(y)); c.lineTo(px(x) + Math.cos(yaw) * r * 1.8, py(y) - Math.sin(yaw) * r * 1.8); c.stroke();
    }
    if (S.cell) {
      const [i, j] = S.cell;
      c.strokeStyle = css('--scene-select'); c.lineWidth = 2;
      c.strokeRect(px(g.origin[0] + i * g.res), py(g.origin[1] + (j + 1) * g.res), cellPx, cellPx);
    }
  }
  function paintInfo() {
    const d = S.d, g = d.world.grid, n = gridImage(d.world).n;
    $('info').textContent = `map ${d.worldN} of ${d.worldCount} · at ${(+d.world.t).toFixed(2)} s · ${g.w} × ${g.h} cells of ${g.res} m · ${n['.'] || 0} free, ${n['#'] || 0} occupied, ${n['?'] || 0} unknown · `
      + `${d.world.obstacles?.length || 0} obstacle points, ${d.world.drops?.length || 0} drops${d.plan ? `, a plan of ${d.plan.path?.length || 0} points` : ''}${d.objects?.length ? `, ${d.objects.length} objects` : ''}${d.areas?.length ? `, ${d.areas.length} areas` : ''}`;
  }
  function cellOut() {
    const g = grid();
    if (S.point && !S.cell) return { inside: false, x: S.point[0], y: S.point[1] };
    if (!S.cell) return null;
    const [i, j] = S.cell, near = (list) => (list || []).filter(([x, y]) => Math.floor((x - g.origin[0]) / g.res) === i && Math.floor((y - g.origin[1]) / g.res) === j).length;
    return { inside: true, i, j, value: g.cells[j * g.w + i], name: CELL_NAME[g.cells[j * g.w + i]] || 'other', x: +(g.origin[0] + (i + 0.5) * g.res).toFixed(4), y: +(g.origin[1] + (j + 0.5) * g.res).toFixed(4),
      obstacle_points: near(S.d.world.obstacles), drop_points: near(S.d.world.drops) };
  }
  function paintCell() {
    const o = cellOut(), kv = (k, v) => `<div class="kv"><span class="k">${k}</span><span class="v">${v}</span></div>`;
    if (!o) { $('cell').innerHTML = '<span class="xs">Click the map to see a cell.</span>'; return; }
    if (!o.inside) { $('cell').innerHTML = `<div class="xt">Outside the grid</div>` + kv('Map frame', `x ${o.x.toFixed(3)} m, y ${o.y.toFixed(3)} m`); return; }
    $('cell').innerHTML = `<div class="xt">Cell ${o.i}, ${o.j}</div><div class="xs">column, row from the lowest y</div>`
      + kv('Value', `${esc(o.name)} <span class="mono">(${esc(o.value)})</span>`) + kv('Centre', `x ${o.x} m, y ${o.y} m in the map frame`)
      + kv('Obstacle points', String(o.obstacle_points)) + kv('Drop points', String(o.drop_points));
  }

  function zoomAt(f, sx = S.w / 2, sy = S.h / 2) {
    if (!S.shown) return false;
    const x = mx(sx), y = my(sy), k = Math.min(Math.max(S.view.k * f, 5), 4000);
    S.view.k = k; S.view.cx = x - (sx - S.w / 2) / k; S.view.cy = y + (sy - S.h / 2) / k;
    paint();
    return true;
  }
  const at = (e) => { const b = cv.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top]; };
  function pickAt(sx, sy) {
    const g = grid(), x = mx(sx), y = my(sy), i = Math.floor((x - g.origin[0]) / g.res), j = Math.floor((y - g.origin[1]) / g.res);
    S.point = [x, y];
    S.cell = i >= 0 && j >= 0 && i < g.w && j < g.h ? [i, j] : null;
    paint(); paintCell();
    return cellOut();
  }
  let down = null;
  cv.addEventListener('pointerdown', (e) => { if (!S.shown) return; cv.setPointerCapture?.(e.pointerId); down = { x: e.clientX, y: e.clientY, cx: S.view.cx, cy: S.view.cy, moved: false }; });
  cv.addEventListener('pointermove', (e) => {
    if (!down) return;
    const dx = e.clientX - down.x, dy = e.clientY - down.y;
    if (!down.moved && Math.hypot(dx, dy) < 4) return;
    down.moved = true; cv.style.cursor = 'grabbing';
    S.view.cx = down.cx - dx / S.view.k; S.view.cy = down.cy + dy / S.view.k;
    paint();
  });
  cv.addEventListener('pointerup', (e) => {
    const was = down; down = null; cv.style.cursor = '';
    if (was && !was.moved) pickAt(...at(e));
  });
  cv.addEventListener('pointercancel', () => { down = null; cv.style.cursor = ''; });
  cv.addEventListener('wheel', (e) => { if (!S.shown) return; e.preventDefault(); zoomAt(Math.exp(-e.deltaY * 0.0015), ...at(e)); }, { passive: false });
  cv.addEventListener('keydown', (e) => {
    if (!S.shown) return;
    const step = 30 / S.view.k, mv = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key];
    if (mv) { e.preventDefault(); S.view.cx += mv[0]; S.view.cy += mv[1]; paint(); }
    else if (e.key === '+' || e.key === '=') zoomAt(1.25);
    else if (e.key === '-') zoomAt(0.8);
  });
  host.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.layer) { S.layers[b.dataset.layer] = !S.layers[b.dataset.layer]; b.setAttribute('aria-pressed', S.layers[b.dataset.layer]); if (S.shown) paint(); }
    else if (b.dataset.zoom === 'in') zoomAt(1.25);
    else if (b.dataset.zoom === 'out') zoomAt(0.8);
    else if (b.dataset.zoom === 'fit' && S.shown) { fit(); paint(); }
  });
  new ResizeObserver(() => { if (S.shown && host.offsetParent) { const w = S.w; size(); if (w !== S.w) paint(); } }).observe($('wrap'));
  new MutationObserver(() => { if (S.shown) { S.grid = null; paint(); } }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] });

  return {
    follow,
    zoom: (f) => zoomAt(f),
    fit() { if (!S.shown) return false; fit(); paint(); return true; },
    setLayer(name, on) { if (!(name in S.layers)) return false; S.layers[name] = !!on; host.querySelector(`[data-layer="${name}"]`).setAttribute('aria-pressed', !!on); if (S.shown) paint(); return true; },
    pickAt: (sx, sy) => (S.shown ? pickAt(sx, sy) : null),
    state() {
      const d = S.d, g = S.shown ? grid() : null;
      return { shown: S.shown, why: S.why, worldT: g ? d.world.t : null, worldN: g ? d.worldN : null, worldCount: d?.worldCount ?? null, w: g?.w ?? null, h: g?.h ?? null, res: g?.res ?? null,
        counts: g ? { ...gridImage(d.world).n } : null, obstacles: g ? d.world.obstacles.length : 0, drops: g ? d.world.drops.length : 0, plan: g ? d.plan?.path?.length ?? 0 : 0,
        belief: g ? d.belief : null, objects: g ? d.objects?.length ?? 0 : 0, areas: g ? (d.areas || []).map((a) => a.name) : [], view: S.view && { ...S.view }, layers: { ...S.layers }, cell: S.shown ? cellOut() : null };
    },
    // where a point of the map is on the screen, in client pixels: to click a cell or an object by its coordinates
    screenOfPoint(x, y) { if (!S.shown) return null; const b = cv.getBoundingClientRect(); return [b.left + px(x), b.top + py(y)]; },
    canvas: () => cv,
  };
}
