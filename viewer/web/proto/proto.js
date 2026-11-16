// The prototype of UX round 1 (RFC-0011, the operator 2026-11-16): the left panel regrouped by the question it answers
// (World, Body, Senses, Mind, Other values) beside the current one, and the Explore view in the right panel with its first
// kind, the robot's body. Real data: one run's streams and joint angles, the robot's description and meshes (data/).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const deg = (r) => (r * 180 / Math.PI).toFixed(1) + '°';
const [{ run, joints: samples }, robot] = await Promise.all([fetch('data/run.json').then((r) => r.json()), fetch('data/robot.json').then((r) => r.json())]);
const S = { left: 'proposed', pose: 'recorded', t: run.t1 * 0.5, hand: {}, sel: null, hidden: new Set(), isolated: null };

// ---- the robot's chains, from its joint tree: each joint off the root starts one (a leg, the head) --------------------
const byParent = {};
for (const j of robot.joints) (byParent[j.parent] ||= []).push(j);
function chainOf(first) { const out = [], walk = (j) => { out.push(j); for (const c of byParent[j.child] || []) walk(c); }; walk(first); return out; }
const pretty = (s) => s.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
function chainName(js) {
  const n = js.filter((j) => j.type !== 'fixed').map((j) => j.name);
  if (n.every((x) => x.startsWith('left_'))) return 'Left leg';
  if (n.every((x) => x.startsWith('right_'))) return 'Right leg';
  if (n.some((x) => /neck|head/.test(x))) return 'Head';
  return pretty(js[0].child);
}
const chains = (byParent[robot.root] || []).map((j) => { const js = chainOf(j); return { name: chainName(js), joints: js.filter((x) => x.type !== 'fixed') }; })
  .filter((c) => c.joints.length);
const jointByName = Object.fromEntries(robot.joints.map((j) => [j.name, j]));
const linkJoint = Object.fromEntries(robot.joints.map((j) => [j.child, j]));

function sampleAt(t) {
  let lo = 0, hi = samples.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (samples[m].t <= t) lo = m; else hi = m - 1; }
  return samples[lo]?.v || {};
}
const values = () => (S.pose === 'recorded' ? sampleAt(S.t) : S.hand);

// ---- the left panel -----------------------------------------------------------------------------------------------
const STREAM = Object.fromEntries(run.streams.map((s) => [s.id, s]));
const NAMES = { 'scene.boxes': 'Walls and furniture', 'scene.hazards': 'Drop zones', 'belief.pose': 'Pose', 'belief.track': 'Track',
  'truth.pose': 'Pose', 'truth.track': 'Track', 'sensors.depth.floor': 'Floor', 'sensors.depth.obstacle': 'Obstacle',
  'sensors.depth.overhead': 'Overhead', 'sensors.depth.below': 'Below the floor', 'sensors.raw': 'Raw depth frame', 'sensors.tilt': 'Tilt',
  'world.grid': 'Map grid', 'world.obstacles': 'Remembered obstacles', 'world.drops': 'Remembered drops', 'plan.path': 'Plan', events: 'Decisions and events' };
const COLORS = { belief: 'var(--c-belief)', truth: 'var(--c-truth)', drop: 'var(--c-drop)', obst: 'var(--c-obst)' };
function srow(id, cls = '') {
  const s = STREAM[id] || { missing: true, count: 0 };
  const c = id.startsWith('truth') ? COLORS.truth : id.startsWith('belief') ? COLORS.belief : /drop|hazard|below/.test(id) ? COLORS.drop : /obst/.test(id) ? COLORS.obst : 'var(--text-faint)';
  return `<div class="row ${cls} ${s.missing ? 'missing' : ''}"><span class="sw" style="background:${c}"></span>${esc(NAMES[id] || id)}<span class="n mono">${s.missing ? 'not in this run' : s.count}</span></div>`;
}
const sig = (name) => run.signals.find((x) => x.name === name);
function sigrow(name, label) {
  const d = sig(name);
  return d ? `<div class="row sub"><span class="sw" style="background:var(--text-faint)"></span>${esc(label || name)}<span class="n">${esc(d.unit || '')}</span></div>` : '';
}
function current() {           // the real app, this run, at this playhead: its left column (the streams tree above, the timeline's lanes below)
  return `<div class="hint" style="padding:8px 10px">The app today, this run (a screenshot of the real page): the streams tree, then the timeline's lanes.</div>
    <img src="data/current-left.png" alt="miniview's left column today" style="display:block;width:100%">`;
}
// sections open or closed: Body open, the rest closed, until the viewer chooses (remembered in this browser)
const OPEN_DEFAULT = { world: false, body: true, senses: false, mind: false, other: false };
let OPEN = { ...OPEN_DEFAULT }, ANGLES = true;
try { OPEN = { ...OPEN_DEFAULT, ...JSON.parse(localStorage.getItem('proto.open') || '{}') }; ANGLES = localStorage.getItem('proto.angles') !== 'off'; } catch (_) { /* no storage */ }
const save = () => { try { localStorage.setItem('proto.open', JSON.stringify(OPEN)); localStorage.setItem('proto.angles', ANGLES ? 'on' : 'off'); } catch (_) { /* no storage */ } };
function section(id, title, sub, count, body, extra = '') {
  const open = OPEN[id];
  return `<div class="sec"><h3 class="fold" data-fold="${id}" aria-expanded="${open}"><span class="chev">${open ? '▾' : '▸'}</span>${title}
      <span class="sub">${sub}</span><span class="cnt">${open ? '' : count}</span>${extra}</h3>${open ? body : ''}</div>`;
}
function proposed() {
  const v = values();
  const imu = ['pitch_deg', 'roll_deg', 'pitch_rate_dps'];
  const used = new Set([...imu, 'qw', 'qx', 'qy', 'qz', ...robot.joints.map((j) => 'joint_' + j.name)]);
  const other = run.signals.filter((d) => !used.has(d.name));
  const verdict = run.verdict || run.status;
  const nJoints = chains.reduce((a, c) => a + c.joints.length, 0);
  const angleToggle = OPEN.body ? `<button class="mini" data-angles title="Show or hide the joints' angles">${ANGLES ? 'hide angles' : 'show angles'}</button>` : '';
  return `<div class="runhead"><div class="t">${esc(run.robot?.name || 'robot')} · ${esc(run.kind || 'run')}</div>
      <div class="s"><span class="pill sim">simulated</span><span class="pill ok">${esc(verdict)}</span>${esc(run.scene)} · ${(run.t1 - run.t0).toFixed(1)} s</div></div>
    ${section('world', 'World', 'what was really there', '4 streams', `${srow('scene.boxes')}${srow('scene.hazards')}
      <div class="grp">Truth <span class="pill sim">simulator only</span></div>${srow('truth.pose', 'sub')}${srow('truth.track', 'sub')}`)}
    ${section('body', 'Body <span class="badge-new">new</span>', 'what the robot is', `${nJoints} joints`, `
      <div class="row"><span class="sw" style="background:var(--new)"></span>3D model<span class="n">${robot.links.length} parts</span></div>
      ${chains.map((c) => `<div class="grp">${esc(c.name)}<span class="n">${c.joints.length} joints</span></div>` + c.joints.map((j) =>
        `<div class="row sub" data-joint="${j.name}"><span class="sw" style="background:var(--new)"></span>${esc(j.name)}${ANGLES ? `<span class="val mono">${deg(v[j.name] ?? 0)}</span>` : ''}</div>`).join('')).join('')}`, angleToggle)}
    ${section('senses', 'Senses', 'what it perceived', '9 streams', `<div class="grp">Depth</div>${srow('sensors.depth.floor', 'sub')}${srow('sensors.depth.obstacle', 'sub')}
      ${srow('sensors.depth.below', 'sub')}${srow('sensors.depth.overhead', 'sub')}${srow('sensors.raw', 'sub')}<div class="grp">IMU</div>${srow('sensors.tilt', 'sub')}
      ${sigrow('pitch_deg', 'Pitch')}${sigrow('roll_deg', 'Roll')}${sigrow('pitch_rate_dps', 'Pitch rate')}`)}
    ${section('mind', 'Mind', 'what it believed and decided', '7 streams', `<div class="grp">Belief</div>${srow('belief.pose', 'sub')}${srow('belief.track', 'sub')}
      ${srow('world.grid')}${srow('world.obstacles')}${srow('world.drops')}${srow('plan.path')}${srow('events')}`)}
    ${section('other', 'Other values', 'the navigator’s own', `${other.length}`, other.map((d) => sigrow(d.name)).join(''))}
    <div class="note"><b>The same groups</b> order the timeline's lanes below and the Moment tab's values on the right, so a joint is in
      Body everywhere (today the 14 joints would be 14 more flat rows in each).</div>`;
}
function renderLeft() { $('left').innerHTML = S.left === 'proposed' ? proposed() : current(); }

// ---- the body: meshes per link, placed by forward kinematics (the same as miniview.kinematics) -------------------------
function parseSTL(buf) {
  const dv = new DataView(buf), n = dv.getUint32(80, true), pos = new Float32Array(n * 9);
  for (let i = 0; i < n; i++) for (let k = 0; k < 9; k++) pos[i * 9 + k] = dv.getFloat32(84 + i * 50 + 12 + k * 4, true);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.computeVertexNormals();
  return g;
}
const q4 = (q) => new THREE.Quaternion(q[1], q[2], q[3], q[0]);                         // ours are [w, x, y, z]
const box = $('body3d');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
box.prepend(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.005, 20);
camera.up.set(0, 0, 1);
camera.position.set(0.32, -0.42, 0.22);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0, 0.0);
scene.add(new THREE.HemisphereLight(0xffffff, 0x444455, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(1, -1, 2);
scene.add(sun);
const grid = new THREE.GridHelper(0.6, 12, 0x666a73, 0x3b3d43);
grid.rotation.x = Math.PI / 2;
grid.position.z = -0.115;
scene.add(grid);
const links = {};
const geoms = {};
await Promise.all([...new Set(robot.links.flatMap((l) => l.visuals.map((v) => v.mesh)))].map(async (m) => {
  geoms[m] = parseSTL(await (await fetch('data/' + m)).arrayBuffer());
}));
for (const l of robot.links) {
  const g = new THREE.Group();
  g.userData.link = l.name;
  for (const v of l.visuals) {
    const mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(v.rgba[0], v.rgba[1], v.rgba[2]), roughness: 0.6, metalness: 0.05 });
    const mesh = new THREE.Mesh(geoms[v.mesh], mat);
    mesh.position.set(...v.origin.pos);
    mesh.quaternion.copy(q4(v.origin.quat));
    mesh.userData.link = l.name;
    g.add(mesh);
  }
  scene.add(g);
  links[l.name] = g;
}
function place() {
  const v = values(), poses = { [robot.root]: [new THREE.Vector3(0, 0, 0), new THREE.Quaternion()] };
  for (const j of robot.joints) {                                     // the description lists joints from the root out
    const [pp, pq] = poses[j.parent];
    let lp = new THREE.Vector3(...j.origin.pos), lq = q4(j.origin.quat);
    if (j.type === 'revolute' || j.type === 'continuous') {
      const a = Math.min(Math.max(v[j.name] ?? 0, j.lower ?? -Infinity), j.upper ?? Infinity);
      lq = lq.clone().multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(...j.axis).normalize(), a));
    }
    poses[j.child] = [pp.clone().add(lp.applyQuaternion(pq)), pq.clone().multiply(lq)];
  }
  for (const [n, [p, q]] of Object.entries(poses)) { links[n]?.position.copy(p); links[n]?.quaternion.copy(q); }
  for (const [n, g] of Object.entries(links)) {
    g.visible = !S.hidden.has(n) && (!S.isolated || S.isolated === n);
    for (const m of g.children) m.material.emissive?.setHex(n === S.sel ? 0x3a5fa0 : 0x000000);
  }
}
function resize() {
  const w = box.clientWidth, h = box.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(box);
(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

const ray = new THREE.Raycaster();
renderer.domElement.addEventListener('click', (e) => {
  const r = renderer.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  const hit = ray.intersectObjects(Object.values(links), true).find((h) => h.object.visible);
  select(hit ? hit.object.userData.link : null, '3d');
});
// hovering a part lights it and shows a pointer: it can be clicked
let hover = null;
renderer.domElement.addEventListener('pointermove', (e) => {
  const r = renderer.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  const hit = ray.intersectObjects(Object.values(links), true).find((h) => h.object.visible);
  const now = hit ? hit.object.userData.link : null;
  if (now === hover) return;
  hover = now;
  renderer.domElement.style.cursor = hover ? 'pointer' : 'grab';
  for (const [n, g] of Object.entries(links)) for (const m of g.children) m.material.emissive?.setHex(n === S.sel ? 0x3a5fa0 : n === hover ? 0x2a2a2a : 0x000000);
  $('hint3d').textContent = hover ? `${hover} · click for details` : 'drag · scroll · click';
});
function focusOn(link) {
  const p = new THREE.Vector3();
  links[link].getWorldPosition(p);
  controls.target.copy(p);
  camera.position.copy(p.clone().add(new THREE.Vector3(0.18, -0.24, 0.12)));
}

// ---- the Explore panel ----------------------------------------------------------------------------------------------
// a part's details: what moves it, what it hangs from and carries, its meshes, where it is relative to the trunk now
function partDetails(link) {
  const j = linkJoint[link], v = values(), lk = robot.links.find((l) => l.name === link);
  const kids = (byParent[link] || []).map((c) => c.child);
  const p = links[link].position, r = links[robot.root].position;
  const meshes = [...new Set(lk.visuals.map((x) => x.mesh.split('/').pop().replace(/\.stl$/, '')))];
  return `<div class="t">${esc(link)}</div>
    <div class="s">${j ? (j.type === 'fixed' ? `fixed to <b>${esc(j.parent)}</b>` : `moved by the joint <b>${esc(j.name)}</b>`) : 'the root: the trunk, placed by the run’s pose'}</div>
    ${j && j.type !== 'fixed' ? `<div class="kv"><span>joint type, axis</span><span class="mono">${esc(j.type)}, [${j.axis.map((a) => a.toFixed(0)).join(' ')}]</span></div>
      <div class="kv"><span>angle now</span><span class="mono">${deg(v[j.name] ?? 0)}</span></div>
      <div class="kv"><span>limits</span><span class="mono">${deg(j.lower)} … ${deg(j.upper)}</span></div>` : ''}
    <div class="kv"><span>hangs from</span><span class="mono">${j ? esc(j.parent) : '—'}</span></div>
    <div class="kv"><span>carries</span><span class="mono">${kids.length ? kids.map(esc).join(', ') : 'nothing'}</span></div>
    <div class="kv"><span>from the trunk</span><span class="mono">${[p.x - r.x, p.y - r.y, p.z - r.z].map((c) => (c * 100).toFixed(1)).join(', ')} cm</span></div>
    <div class="kv"><span>meshes (${lk.visuals.length})</span><span class="mono" style="text-align:right">${meshes.map(esc).join(', ')}</span></div>
    <div class="acts"><button class="btn" data-act="focus">Focus</button><button class="btn" data-act="isolate">${S.isolated === link ? 'Unisolate' : 'Isolate'}</button>
      <button class="btn" data-act="hide">Hide</button><button class="btn" data-act="clear">Close</button></div>`;
}
function select(link, from) {
  S.sel = link;
  $('isolate').disabled = $('hide').disabled = !link;
  place();
  $('partinfo').innerHTML = link ? partDetails(link) : '<span class="s">Click a part of the body, or a row of the parts below, to see what it is.</span>';
  $('partinfo').classList.toggle('picked', !!link);
  renderBelow();
  if (link && from === '3d') document.querySelector(`#belowexplore [data-link="${CSS.escape(link)}"]`)?.scrollIntoView({ block: 'nearest' });
}
function renderBelow() {
  const v = values();
  const tree = (name, depth) => {
    const kids = (byParent[name] || []);
    return `<div class="row ${S.sel === name ? 'sel' : ''}" data-link="${name}" style="padding-left:${10 + depth * 12}px">${esc(name)}
        <button class="eye" data-eye="${name}">${S.hidden.has(name) ? 'show' : 'hide'}</button></div>`
      + (S.sel === name ? `<div class="inline-detail" style="margin-left:${10 + depth * 12}px">${partDetails(name)}</div>` : '')
      + kids.map((j) => tree(j.child, depth + 1)).join('');
  };
  const sliders = S.pose === 'hand' ? '<div class="sec"><h3>Pose by hand</h3>' + chains.map((c) => `<div class="grp">${esc(c.name)}</div>` + c.joints.map((j) =>
    `<div class="slider"><label>${esc(j.name)}<span class="mono">${deg(v[j.name] ?? 0)}</span></label>
     <input type="range" min="${j.lower}" max="${j.upper}" step="0.01" value="${v[j.name] ?? 0}" data-hand="${j.name}"></div>`).join('')).join('') + '</div>' : '';
  $('belowexplore').innerHTML = sliders + `<div class="sec tree"><h3>Parts <span class="sub">${robot.links.length} links, ${robot.joints.length} joints</span></h3>${tree(robot.root, 0)}</div>
    <div class="note"><b>Explore</b> is a kind of detail view: the body is its first kind. A depth frame, the map or a decision could open here later, the same way.</div>`;
}
function renderTimeline() {
  $('timeline').innerHTML = S.pose === 'recorded'
    ? `<label style="display:flex;color:var(--text-dim);font-size:12px">Playhead<span class="mono" style="margin-left:auto;color:var(--text)">${S.t.toFixed(2)} s</span></label>
       <input type="range" id="playhead" min="${run.t0}" max="${run.t1}" step="0.05" value="${S.t}">`
    : '<div class="hint">By hand: the sliders below pose the body; the run is not changed.</div>';
}
function refresh() { renderLeft(); renderTimeline(); renderBelow(); place(); if (S.sel) select(S.sel); }

document.addEventListener('input', (e) => {
  if (e.target.id === 'playhead') { S.t = +e.target.value; renderLeft(); place(); $('timeline').querySelector('.mono').textContent = S.t.toFixed(2) + ' s'; if (S.sel) select(S.sel); }
  if (e.target.dataset.hand) { S.hand[e.target.dataset.hand] = +e.target.value; e.target.previousElementSibling.querySelector(".mono").textContent = deg(+e.target.value); place(); renderLeft(); }
});
document.addEventListener('click', (e) => {
  const t = e.target;
  if (t.closest('#leftmode button')) { S.left = t.dataset.v; for (const b of $('leftmode').children) b.classList.toggle('on', b === t); renderLeft(); }
  if (t.closest('#posemode button')) { S.pose = t.dataset.v; if (S.pose === 'hand') S.hand = { ...sampleAt(S.t) }; for (const b of $('posemode').children) b.classList.toggle('on', b === t); refresh(); }
  if (t.closest('#theme button')) { document.documentElement.dataset.theme = t.dataset.v; for (const b of $('theme').children) b.classList.toggle('on', b === t); }
  if (t.closest('#tabs button')) { const b = t.closest('button'); for (const x of $('tabs').children) x.classList.toggle('on', x === b); for (const p of document.querySelectorAll('.tabpane')) p.classList.toggle('on', p.id === 't-' + b.dataset.t); }
  if (t.id === 'expand') { $('main').classList.toggle('wide'); t.textContent = $('main').classList.contains('wide') ? 'Narrow' : 'Expand'; }
  if (t.id === 'isolate' && S.sel) { S.isolated = S.isolated === S.sel ? null : S.sel; t.textContent = S.isolated ? 'Unisolate' : 'Isolate'; place(); }
  if (t.id === 'hide' && S.sel) { S.hidden.add(S.sel); renderBelow(); place(); }
  if (t.id === 'showall') { S.hidden.clear(); S.isolated = null; $('isolate').textContent = 'Isolate'; renderBelow(); place(); }
  if (t.dataset.eye) { const n = t.dataset.eye; S.hidden.has(n) ? S.hidden.delete(n) : S.hidden.add(n); renderBelow(); place(); return; }
  const fold = t.closest('[data-fold]');
  if (fold && !t.closest('[data-angles]')) { OPEN[fold.dataset.fold] = !OPEN[fold.dataset.fold]; save(); renderLeft(); return; }
  if (t.closest('[data-angles]')) { ANGLES = !ANGLES; save(); renderLeft(); return; }
  const act = t.closest('[data-act]')?.dataset.act;
  if (act && S.sel) {
    if (act === 'focus') focusOn(S.sel);
    if (act === 'isolate') { S.isolated = S.isolated === S.sel ? null : S.sel; $('isolate').textContent = S.isolated ? 'Unisolate' : 'Isolate'; place(); select(S.sel); }
    if (act === 'hide') { S.hidden.add(S.sel); place(); select(S.sel); }
    if (act === 'clear') select(null);
    return;
  }
  const lr = t.closest('[data-link]'); if (lr) select(lr.dataset.link);
  const jr = t.closest('[data-joint]'); if (jr) { const j = jointByName[jr.dataset.joint]; select(j.child); for (const x of document.querySelectorAll('#tabs button')) if (x.dataset.t === 'explore') x.click(); }
});
// the theme: the system's until chosen; the 3D background follows it
function applyTheme() {
  const t = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  for (const b of $('theme').children) b.classList.toggle('on', b.dataset.v === t);
  renderer.setClearColor(getComputedStyle(document.documentElement).getPropertyValue('--bg-viewport').trim() || '#202125');
}
document.addEventListener('click', (e) => { if (e.target.closest('#theme button')) requestAnimationFrame(applyTheme); });
applyTheme();
$('runchip').textContent = `${run.key} · ${run.robot?.name} · ${run.kind} · ${run.verdict}`;
refresh();
window.__proto = { S, chains: chains.map((c) => ({ name: c.name, joints: c.joints.map((j) => j.name) })), ready: true };
