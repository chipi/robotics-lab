// The Observatory's palette verbs (look-and-feel U18, on libs/web/palette): views and frame, the 3D camera, time, panels and layouts, theme, open a scene or a
// run, the link to this moment, overlays and streams. The shell loads this on the first Ctrl/Cmd+K or press of the palette button and hands it `app`.
// The Observatory has no STOP and no robot action: every verb is plain, and none acts on a robot. The script API (window.miniview) does the work wherever it
// has a call for it; `app` carries only what it has not: the model (read), play, the way back to live, theme, the layout's `act`.
import { createRegistry } from '/lib/palette/registry.js';
import { createPalette } from '/lib/palette/palette.js';

const OVERLAYS = [
  ['coords', 'the coordinate system and grid', ['axes', 'grid']],
  ['gizmo', 'the axis gizmo', ['axes']],
  ['legend', 'the legend', ['key']],
  ['hazards_top', 'the real hazards over the model', ['obstacles']],
  ['floor', 'the floor', ['3d', 'shadow']],
  ['ghost', 'the belief ghost', ['body']],
  ['trail', 'the trail', ['path']],
  ['xray', 'the x-ray body', ['body']],
  ['inspector', 'the model inspector', ['body']],
];
const CAM_VIEWS = [['iso', 'Iso'], ['top', 'Top'], ['front', 'Front'], ['side', 'Side']];
const CAM_FOLLOW = [['off', 'Off'], ['position', 'Position'], ['heading', 'Heading'], ['pose', 'Pose']];
const word = (k) => String(k).replace(/_/g, ' ');

export function verbSpecs(app) {
  const out = [];
  const mv = window.miniview, M = app.M, run = M.run && M.runId ? M.run : null;
  // the palette closes before a verb runs, so an error has nowhere to show but the page's own message: console only would be a silent failure
  const add = (spec, fn) => out.push({ keywords: [], danger: 'none', ...spec, run: async () => { try { await fn(); } catch (e) { app.say(e?.message || String(e), true); } } });
  const press = (sel) => { const b = document.querySelector(sel); if (!b) throw new Error('That control is not on the page now.'); b.click(); };

  const views = app.views();
  const labelOf = { top: 'Top', three: 'Three views', '3d': '3D', eye: 'Eye', chase: 'Chase', watch: 'Eye and top together' };
  for (const [v, text] of views) {
    if (v === M.view) continue;
    add({ id: `view.${v}`, title: `View: ${labelOf[v] || text}`, section: 'View', keywords: ['layout', 'camera', 'switch'] }, () => mv.setView(v));
  }
  if (document.getElementById('frameSeg')) {
    const eyeView = ['eye', 'chase', 'watch'].includes(M.view);
    if (M.frame !== 'world') add({ id: 'frame.world', title: 'Frame: World', section: 'View', keywords: ['truth', 'scene'] }, () => mv.setFrame('world'));
    if (M.frame !== 'map' && !eyeView) add({ id: 'frame.map', title: 'Frame: Map', section: 'View', keywords: ['robot', 'belief'] }, () => mv.setFrame('map'));
  }
  if (run) add({ id: 'view.fit', title: 'Fit the run in the view', section: 'View', keywords: ['zoom', 'frame'], hotkey: 'F' }, () => app.fit());

  // the 3D camera's own controls (three/app.js); they exist only while the 3D view is up
  const cam = document.getElementById('camCtl');
  if (run && cam && !cam.hidden) {
    for (const [k, t] of CAM_VIEWS) add({ id: `cam.view.${k}`, title: `Camera: ${t} view`, section: 'Camera', keywords: ['preset', 'angle'] }, () => press(`#camCtl [data-cam="${k}"]`));
    add({ id: 'cam.fit-scene', title: 'Camera: fit the whole scene', section: 'Camera', keywords: ['frame', 'zoom out'] }, () => press('#camCtl [data-cam="fit-scene"]'));
    add({ id: 'cam.fit-robot', title: 'Camera: fit the robot', section: 'Camera', keywords: ['frame', 'zoom in', 'focus'] }, () => press('#camCtl [data-cam="fit-robot"]'));
    for (const [k, t] of CAM_FOLLOW) add({ id: `cam.follow.${k}`, title: `Camera follow: ${t}`, section: 'Camera', keywords: ['track', 'chase'] }, () => press(`#camCtl [data-follow="${k}"]`));
  }

  if (run) {
    add(M.play.on ? { id: 'time.pause', title: 'Pause', section: 'Time', keywords: ['stop playing'], hotkey: 'Space' } : { id: 'time.play', title: 'Play', section: 'Time', keywords: ['start', 'resume'], hotkey: 'Space' }, () => app.play(!M.play.on));
    if (app.canLive()) add({ id: 'time.live', title: 'Return to live', section: 'Time', keywords: ['follow', 'edge', 'now'] }, () => app.goLive());
    add({ id: 'time.start', title: 'Seek to the start', section: 'Time', keywords: ['beginning', 'first'], hotkey: 'Home' }, () => mv.setTime(run.t0));
    add({ id: 'time.end', title: 'Seek to the end', section: 'Time', keywords: ['last'], hotkey: 'End' }, () => mv.setTime(run.t1));
    add({ id: 'time.next', title: 'Next event', section: 'Time', keywords: ['jump', 'mark'], hotkey: '.' }, () => mv.jump(1, ''));
    add({ id: 'time.prev', title: 'Previous event', section: 'Time', keywords: ['jump', 'mark', 'back'], hotkey: ',' }, () => mv.jump(-1, ''));
    for (const k of [...new Set(run.events.map((e) => e.kind))].filter((k) => M.kinds[k] !== false)) {
      add({ id: `time.next.${k}`, title: `Next ${word(k)} event`, section: 'Time', keywords: ['jump', k] }, () => mv.jump(1, k));
      add({ id: `time.prev.${k}`, title: `Previous ${word(k)} event`, section: 'Time', keywords: ['jump', 'back', k] }, () => mv.jump(-1, k));
    }
    add({ id: 'link.copy', title: 'Copy link to this moment', section: 'Share', keywords: ['evidence', 'url', 'share', 'permalink'] }, async () => {
      const link = mv.momentLink();
      if (!link) throw new Error('There is no run open to link to.');
      try { await navigator.clipboard.writeText(link); } catch (_) { throw new Error(`The browser would not copy it. The link: ${link}`); }
      app.say('Link to this moment copied.');
    });
  }

  const lay = app.layout;
  if (lay) {
    for (const p of lay.panels) {
      if (lay.isHidden(p.id)) add({ id: `panel.show.${p.id}`, title: `Show panel: ${p.label}`, section: 'Panels', keywords: ['unhide'] }, () => lay.setHidden(p.id, false));
      else add({ id: `panel.hide.${p.id}`, title: `Hide panel: ${p.label}`, section: 'Panels', keywords: ['remove'] }, () => lay.setHidden(p.id, true));
      if (p.fold && !lay.isHidden(p.id)) {
        if (lay.isFolded(p.id)) add({ id: `panel.unfold.${p.id}`, title: `Unfold panel: ${p.label}`, section: 'Panels', keywords: ['expand', 'open'] }, () => lay.setFolded(p.id, false));
        else add({ id: `panel.fold.${p.id}`, title: `Fold panel: ${p.label}`, section: 'Panels', keywords: ['collapse', 'close'] }, () => lay.setFolded(p.id, true));
      }
    }
    add({ id: 'layout.save', title: 'Save layout', section: 'Layouts', keywords: ['save as', 'arrangement'] }, () => {
      const taken = new Set(lay.saved());
      let n = 1;
      while (taken.has(`Layout ${n}`)) n++;
      app.say(`Saved as ${lay.saveAs(`Layout ${n}`)}.`);
    });
    for (const name of lay.saved()) add({ id: `layout.load.${name}`, title: `Load layout: ${name}`, section: 'Layouts', keywords: ['arrangement'] }, () => lay.load(name));
    add({ id: 'layout.reset', title: 'Reset layout to default', section: 'Layouts', keywords: ['arrangement', 'panels'] }, () => { lay.reset(); app.say('Back to the default layout.'); });
  }

  add({ id: 'theme.toggle', title: `Switch to ${M.theme === 'light' ? 'dark' : 'light'} theme`, section: 'View', keywords: ['theme', 'dark', 'light', 'appearance'] }, () => app.theme());

  add({ id: 'nav.scenes', title: 'Go to all scenes and runs', section: 'Go to', keywords: ['list', 'home', 'back'] }, () => mv.scenes());
  for (const s of M.index?.scenes ?? []) {
    add({ id: `scene.open.${s.id}`, title: `Open scene: ${s.id}`, section: 'Go to', keywords: [s.name ?? '', 'scene'].filter(Boolean) }, () => mv.load(s.id));
    for (const r of s.runs) {
      add({ id: `run.open.${r.key}`, title: `Open run: ${s.id} / ${r.id}`, section: 'Go to', keywords: [r.key, r.kind ?? '', r.status ?? '', r.verdict ?? '', 'run'].filter(Boolean) }, () => mv.load(s.id, r.key));
    }
  }

  for (const [name, label, kw] of OVERLAYS) {
    if (!(name in M.ov)) continue;
    add({ id: `overlay.${name}`, title: `${M.ov[name] ? 'Hide' : 'Show'} ${label}`, section: 'Overlays', keywords: ['overlay', ...kw] }, () => mv.setOverlay(name, !M.ov[name]));
  }
  if (run) {
    add({ id: 'overlay.rel', title: `${M.rel.belief_truth ? 'Hide' : 'Show'} the belief to truth line`, section: 'Overlays', keywords: ['overlay', 'relation', 'error'] }, () => mv.setRelation('belief_truth', !M.rel.belief_truth));
    for (const s of run.streams ?? []) {
      if (s.missing) continue;
      const on = app.shown(s.id);
      add({ id: `stream.${on ? 'hide' : 'show'}.${s.id}`, title: `${on ? 'Hide' : 'Show'} stream: ${s.id}`, section: 'Streams', keywords: [s.name ?? '', 'layer', 'visible'].filter(Boolean) }, () => mv.setVisible(s.id, !on));
    }
  }
  return out;
}

// the registry is rebuilt from the verbs at each listing, so what is offered always follows the page's state; the palette needs only list() and onChange()
export function mount(app) {
  const registry = {
    list(ctx) { const r = createRegistry(); for (const s of verbSpecs(app)) r.register(s); return r.list(ctx); },
    onChange: () => () => {},
  };
  return createPalette({ registry });
}
