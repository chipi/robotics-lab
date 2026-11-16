// Explore (UXS-001, RFC-0011 §3.3): the right panel's detail view for looking closely at one thing. Its first kind is the
// robot's body: the description's meshes placed by its forward kinematics (robot.js), posed as recorded at the playhead or
// by hand, parts picked in the body or in the list of parts, with their details; isolate, hide, focus. three.js is loaded
// when Explore first opens (the 2D page does not otherwise need it).
import { chainsOf, linkPoses } from './robot.js';
import { createBody } from './robotbody.js';

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
const deg = (r) => (r == null ? '—' : `${(r * 180 / Math.PI).toFixed(1)}°`);

export function createExplore(el, { api, robotDesc, recorded, hasRun, t }) {
  const S = { robot: null, desc: null, pose: 'recorded', hand: {}, sel: null, hidden: new Set(), isolated: null, wide: false, why: null, loading: false };
  let THREE = null, view = null, robots = null;
  const byParent = () => { const b = {}; for (const j of S.desc?.joints || []) (b[j.parent] ||= []).push(j); return b; };
  const jointOf = (link) => (S.desc?.joints || []).find((j) => j.child === link) || null;
  const values = () => (S.pose === 'hand' || !hasRun() ? S.hand : recorded());

  el.innerHTML = `<div class="xtop">
      <select id="xwhat" aria-label="What to explore"></select>
      <div class="seg sm" role="group" aria-label="Pose"><button data-pose="recorded">As recorded</button><button data-pose="hand">By hand</button></div>
      <span class="grow"></span><button class="btn" id="xwide" title="Give the explorer more room">Expand</button></div>
    <div class="xbody" id="xbody"><div class="xover"><button class="btn" id="xiso" disabled>Isolate</button><button class="btn" id="xhide" disabled>Hide</button>
      <button class="btn" id="xall">Show all</button><span class="grow"></span><span class="hint" id="xhint">drag · scroll · click a part</span></div></div>
    <div class="xmsg" id="xmsg" hidden></div>
    <div class="xpart" id="xpart"></div>
    <div class="xbelow" id="xbelow"></div>`;
  const $ = (id) => el.querySelector('#' + id);

  async function listRobots() {
    robots ||= await fetch(`${api}robots`).then((r) => (r.ok ? r.json() : [])).catch(() => []);
    $('xwhat').innerHTML = robots.map((r) => `<option value="robot:${esc(r.name)}" ${r.name === S.robot ? 'selected' : ''}>Robot body: ${esc(r.label || r.name)}</option>`).join('')
      + '<option disabled>Depth frame (later)</option><option disabled>Map (later)</option>';
  }

  async function open(robot) {
    await listRobots();
    const name = robot || S.robot || robots[0]?.name || null;
    if (!name) return message('No robot has a description yet (robots/<robot>/robot.urdf).');
    if (name !== S.robot) {
      S.loading = true;
      const desc = await robotDesc(name);
      S.robot = name; S.desc = desc; S.sel = null; S.hidden.clear(); S.isolated = null;
      S.hand = Object.fromEntries((desc?.joints || []).filter((j) => j.type !== 'fixed').map((j) => [j.name, 0]));
      await listRobots();
      if (!desc) { S.loading = false; return message(`No description for the robot ${name}.`); }
      await build();
      S.loading = false;
    }
    if (!hasRun()) S.pose = 'hand';
    render();
  }

  function message(text) { S.why = text; $('xmsg').hidden = false; $('xmsg').textContent = text; $('xbody').hidden = true; render(); }

  // ---- the body in 3D ---------------------------------------------------------------------------------------------------
  async function build() {
    THREE ||= await import('three');
    const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');
    const missing = S.desc.meshes_missing || [];
    if (missing.length === new Set(S.desc.links.flatMap((l) => l.visuals.map((v) => v.mesh))).size) {
      return message(`The meshes of ${S.robot} are not generated (make robots).`);
    }
    $('xmsg').hidden = true; $('xbody').hidden = false; S.why = missing.length ? `${missing.length} meshes missing (make robots)` : null;
    if (!view) {
      const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
      renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
      $('xbody').prepend(renderer.domElement);
      const camera = new THREE.PerspectiveCamera(35, 1, 0.005, 20);
      camera.up.set(0, 0, 1);
      const controls = new OrbitControls(camera, renderer.domElement);
      const scene = new THREE.Scene();
      // the viewport's colour, from the theme's tokens (followed when the theme changes)
      const bg = () => new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue('--bg-viewport').trim() || '#202125');
      scene.background = bg();
      new MutationObserver(() => { scene.background = bg(); if (view) view.dirty = true; }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] });
      scene.add(new THREE.HemisphereLight(0xffffff, 0x444455, 1.6));
      const sun = new THREE.DirectionalLight(0xffffff, 1.6);
      sun.position.set(1, -1, 2);
      scene.add(sun);
      view = { renderer, camera, controls, scene, links: {}, root: new THREE.Group(), ray: new THREE.Raycaster(), hover: null, dirty: true };
      scene.add(view.root);
      controls.addEventListener('change', () => (view.dirty = true));
      new ResizeObserver(resize).observe($('xbody'));
      const loop = () => { requestAnimationFrame(loop); if (!el.hidden && view.dirty) { view.dirty = false; renderer.render(scene, camera); } };
      loop();
      bindPicking();
    }
    view.root.clear();
    view.body = await createBody(THREE, S.desc, api);
    view.root.add(view.body.root);
    view.links = view.body.links;
    place();
    frame();
  }
  // the camera on the whole body (or the picked part)
  function frame(link) {
    const box = new THREE.Box3().setFromObject(link ? view.links[link] : view.root), c = box.getCenter(new THREE.Vector3()), r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.02);
    view.controls.target.copy(c);
    view.camera.position.copy(c.clone().add(new THREE.Vector3(1.3, -1.7, 0.9).normalize().multiplyScalar(r / Math.sin((view.camera.fov * Math.PI) / 360) * 0.85)));
    view.controls.update(); view.dirty = true;
  }
  function resize() {
    if (!view) return;
    const b = $('xbody'), w = b.clientWidth, h = b.clientHeight;
    if (!w || !h) return;
    view.renderer.setSize(w, h, false); view.camera.aspect = w / h; view.camera.updateProjectionMatrix(); view.dirty = true;
  }
  // every part where the forward kinematics put it, shown or hidden, the picked one lit
  function place() {
    if (!view?.body || !S.desc) return;
    view.body.pose(values());
    for (const [n, g] of Object.entries(view.links)) {
      g.visible = !S.hidden.has(n) && (!S.isolated || S.isolated === n);
      for (const m of g.children) m.material.emissive?.setHex(n === S.sel ? 0x3a5fa0 : n === view.hover ? 0x2a2a2a : 0x000000);
    }
    view.dirty = true;
  }
  function bindPicking() {
    const cv = view.renderer.domElement;
    const hit = (e) => {
      const r = cv.getBoundingClientRect();
      view.ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), view.camera);
      return view.ray.intersectObjects(Object.values(view.links), true).find((h) => h.object.visible)?.object.userData.link || null;
    };
    let down = null;
    cv.addEventListener('pointerdown', (e) => (down = [e.clientX, e.clientY]));
    cv.addEventListener('click', (e) => { if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 4) select(hit(e), true); });
    cv.addEventListener('pointermove', (e) => {
      const now = hit(e);
      if (now === view.hover) return;
      view.hover = now; cv.style.cursor = now ? 'pointer' : 'grab';
      $('xhint').textContent = now ? `${now} · click for details` : 'drag · scroll · click a part';
      place();
    });
  }

  // ---- the panel ----------------------------------------------------------------------------------------------------
  function details(link) {
    const j = jointOf(link), kids = (byParent()[link] || []).map((c) => c.child), lk = S.desc.links.find((l) => l.name === link), v = values();
    const poses = linkPoses(S.desc, v), p = poses[link]?.pos || [0, 0, 0];
    const meshes = [...new Set(lk.visuals.map((x) => x.mesh.split('/').pop().replace(/\.stl$/i, '')))];
    const kv = (k, val) => `<div class="kv"><span class="k">${k}</span><span class="v">${val}</span></div>`;
    return `<div class="xt">${esc(link)}</div>
      <div class="xs">${j ? (j.type === 'fixed' ? `fixed to <b>${esc(j.parent)}</b>` : `moved by the joint <b>${esc(j.name)}</b>`) : 'the root: placed by the run’s pose'}</div>`
      + (j && j.type !== 'fixed' ? kv('Joint', `${esc(j.type)}, axis [${j.axis.map((a) => +a.toFixed(2)).join(' ')}]`) + kv('Angle now', deg(v[j.name] ?? 0)) + kv('Limits', `${deg(j.lower)} … ${deg(j.upper)}`) : '')
      + kv('Hangs from', j ? esc(j.parent) : '—') + kv('Carries', kids.length ? kids.map(esc).join(', ') : 'nothing')
      + kv('From the root', `${p.map((c) => (c * 100).toFixed(1)).join(', ')} cm`) + kv(`Meshes (${lk.visuals.length})`, meshes.map(esc).join(', ') || 'none')
      + `<div class="xacts"><button class="btn" data-act="focus">Focus</button><button class="btn" data-act="isolate">${S.isolated === link ? 'Unisolate' : 'Isolate'}</button>`
      + `<button class="btn" data-act="hide">Hide</button><button class="btn" data-act="close">Close</button></div>`;
  }
  function render() {
    for (const b of el.querySelectorAll('[data-pose]')) {
      b.setAttribute('aria-pressed', b.dataset.pose === S.pose);
      b.disabled = b.dataset.pose === 'recorded' && !hasRun();
    }
    $('xwide').textContent = S.wide ? 'Narrow' : 'Expand';
    if (!S.desc) { $('xpart').innerHTML = ''; $('xbelow').innerHTML = ''; return; }
    $('xiso').disabled = $('xhide').disabled = !S.sel;
    $('xiso').textContent = S.isolated ? 'Unisolate' : 'Isolate';
    $('xpart').innerHTML = S.sel ? details(S.sel) : `<span class="xs">Click a part of the body, or a row of the parts below, to see what it is.${S.why ? ` <b>${esc(S.why)}</b>` : ''}</span>`;
    $('xpart').classList.toggle('picked', !!S.sel);
    const bp = byParent(), v = values();
    const tree = (name, d) => `<div class="xrow ${S.sel === name ? 'sel' : ''} ${S.hidden.has(name) ? 'hid' : ''}" data-link="${esc(name)}" style="padding-left:${8 + d * 12}px">`
      + `<span class="nm">${esc(name)}</span><button class="mini" data-eye="${esc(name)}">${S.hidden.has(name) ? 'show' : 'hide'}</button></div>`
      + (bp[name] || []).map((j) => tree(j.child, d + 1)).join('');
    const sliders = S.pose === 'hand' ? `<div class="xsec"><div class="xh">Pose by hand</div>` + chainsOf(S.desc).map((c) => `<div class="xg">${esc(c.name)}</div>`
      + c.joints.map((j) => `<label class="xsl"><span>${esc(j.name)}</span><span class="mono" data-val="${esc(j.name)}">${deg(v[j.name] ?? 0)}</span>`
        + `<input type="range" min="${j.lower ?? -Math.PI}" max="${j.upper ?? Math.PI}" step="0.01" value="${v[j.name] ?? 0}" data-hand="${esc(j.name)}" aria-label="${esc(j.name)}"></label>`).join('')).join('')
      + '<button class="btn" data-act="zero">All to zero</button></div>'
      : `<div class="xsec"><div class="xs">As recorded at ${t().toFixed(2)} s: the body follows the timeline.</div></div>`;
    $('xbelow').innerHTML = sliders + `<div class="xsec"><div class="xh">Parts <span class="xs">${S.desc.links.length} links, ${S.desc.joints.filter((j) => j.type !== 'fixed').length} joints</span></div>${tree(S.desc.root, 0)}</div>`;
  }
  function select(link, from3d = false) {
    S.sel = link && view?.links[link] ? link : null;
    place(); render();
    if (S.sel && from3d) el.querySelector(`[data-link="${CSS.escape(S.sel)}"]`)?.scrollIntoView({ block: 'nearest' });
    return S.sel;
  }

  el.addEventListener('input', (e) => {
    const j = e.target.dataset.hand;
    if (!j) return;
    S.hand[j] = +e.target.value;
    const out = el.querySelector(`[data-val="${CSS.escape(j)}"]`);
    if (out) out.textContent = deg(S.hand[j]);
    place();
    if (S.sel) $('xpart').innerHTML = details(S.sel);
  });
  el.addEventListener('change', (e) => { if (e.target.id === 'xwhat' && e.target.value.startsWith('robot:')) open(e.target.value.slice(6)); });
  el.addEventListener('click', (e) => {
    const b = e.target.closest('button, .xrow');
    if (!b) return;
    if (b.dataset.pose) return setPose(b.dataset.pose);
    if (b.id === 'xwide') { S.wide = !S.wide; document.querySelector('.app')?.classList.toggle('xwide', S.wide); render(); return; }
    if (b.id === 'xiso' || b.dataset.act === 'isolate') { if (S.sel) S.isolated = S.isolated === S.sel ? null : S.sel; place(); render(); return; }
    if (b.id === 'xhide' || b.dataset.act === 'hide') { if (S.sel) S.hidden.add(S.sel); place(); render(); return; }
    if (b.id === 'xall') { S.hidden.clear(); S.isolated = null; place(); render(); return; }
    if (b.dataset.eye) { const n = b.dataset.eye; S.hidden.has(n) ? S.hidden.delete(n) : S.hidden.add(n); place(); render(); return; }
    if (b.dataset.act === 'focus' && S.sel) { frame(S.sel); return; }
    if (b.dataset.act === 'close') { select(null); return; }
    if (b.dataset.act === 'zero') { for (const k in S.hand) S.hand[k] = 0; place(); render(); return; }
    if (b.dataset.link) select(b.dataset.link);
  });
  function setPose(p) {
    if (p !== 'recorded' && p !== 'hand') return false;
    if (p === 'recorded' && !hasRun()) return false;
    if (p === 'hand' && S.pose !== 'hand' && hasRun()) Object.assign(S.hand, recorded());       // by hand starts from the recorded pose
    S.pose = p; place(); render();
    return true;
  }

  return {
    open,
    // the playhead moved: a recorded pose follows it
    pose() { if (S.pose === 'recorded' && S.desc) { place(); if (S.sel) $('xpart').innerHTML = details(S.sel); const n = el.querySelector('.xbelow .xs'); if (n) n.textContent = `As recorded at ${t().toFixed(2)} s: the body follows the timeline.`; } },
    select, setPose,
    setJoint(name, value) { if (!S.desc?.joints.some((j) => j.name === name && j.type !== 'fixed')) return false; setPose('hand'); S.hand[name] = +value; place(); render(); return true; },
    hide(link, on = true) { if (!view?.links[link]) return false; on ? S.hidden.add(link) : S.hidden.delete(link); place(); render(); return true; },
    isolate(link) { if (link && !view?.links[link]) return false; S.isolated = link || null; place(); render(); return true; },
    state() {
      return { robot: S.robot, kind: S.robot ? 'robot body' : null, pose: S.pose, selected: S.sel, hidden: [...S.hidden], isolated: S.isolated, why: S.why, loading: S.loading,
        links: S.desc?.links.length ?? 0, drawn: view ? Object.values(view.links).filter((g) => g.children.length).length : 0,
        values: S.desc ? Object.fromEntries(Object.entries(values()).map(([k, x]) => [k, +x.toFixed(4)])) : {},
        poses: S.desc ? linkPoses(S.desc, values()) : {} };
    },
    snapshot() { if (!view) return null; view.renderer.render(view.scene, view.camera); return view.renderer.domElement.toDataURL('image/png'); },
    // where a part's centre (its bounding box's) is on the screen, in client pixels: to click a part by name
    screenOf(link) {
      if (!view?.links[link]) return null;
      const c = new THREE.Box3().setFromObject(view.links[link]).getCenter(new THREE.Vector3()).project(view.camera);
      const r = view.renderer.domElement.getBoundingClientRect();
      return [r.left + ((c.x + 1) / 2) * r.width, r.top + ((1 - c.y) / 2) * r.height];
    },
  };
}
