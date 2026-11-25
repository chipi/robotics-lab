// Mission Control's command-palette verbs (look-and-feel U25): navigation, panels and layouts, the theme, and STOP first. Loaded by app.js the first
// time the palette is asked for (Ctrl/Cmd+K or the top-bar button), so the phone overview fetches neither this nor libs/web/palette.
//
// No verb starts a goal, takes over, takes a lease or moves a robot: the only verbs that touch a robot are STOP and STOP ALL, and they press the
// page's own STOP buttons, so they take the same path (and the same toast) as a tap and run on the first Enter, never confirmed.
// The verbs are derived from the app's state each time the palette lists them, so a new robot or a saved layout is there without any bookkeeping.
import { createRegistry } from '/lib/palette/registry.js';
import { createPalette } from '/lib/palette/palette.js';

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// app: {robots(), route(), tabs, hashOf(id, tab), stopRobotId(), layout() -> layout.js's `act` or null, behindObservatory(), observatoryHref(), go(hash), visit(href),
//       stop(), stopAll(), theme(), themeNow(), toast(msg, isError)}
export function verbSpecs(app) {
  const out = [];
  // the palette closes before a verb runs, so an error has nowhere to show but the page's toast: console only would be a silent failure
  const add = (spec, fn) => out.push({ keywords: [], danger: 'none', ...spec, run: async () => { try { await fn(); } catch (e) { app.toast(e?.message || String(e), true); } } });

  const rid = app.stopRobotId();
  if (rid) add({ id: 'stop.robot', title: `STOP ${rid}`, section: 'Stop', danger: 'stop', keywords: ['halt'] }, () => app.stop());
  add({ id: 'stop.all', title: 'STOP ALL', section: 'Stop', danger: 'stop', keywords: ['halt', 'every robot'] }, () => app.stopAll());

  add({ id: 'nav.overview', title: 'Go to the robots overview', section: 'Go to', keywords: ['robots', 'home', 'back', 'list'] }, () => app.go(''));
  for (const r of app.robots()) {
    add({ id: `nav.robot.${r.id}`, title: `Open ${r.id}`, section: 'Go to', keywords: [r.label ?? '', 'robot', 'page'].filter(Boolean) }, () => app.go(app.hashOf(r.id)));
    for (const tab of app.tabs.filter((t) => t !== 'overview')) {
      add({ id: `nav.tab.${r.id}.${tab}`, title: `${r.id}: ${cap(tab)} tab`, section: 'Go to', keywords: [r.label ?? '', 'robot'].filter(Boolean) }, () => app.go(app.hashOf(r.id, tab)));
    }
  }
  if (app.behindObservatory()) {
    add({ id: 'nav.observatory', title: 'Open the Observatory', section: 'Go to', keywords: ['miniview', 'runs', 'replay'] }, () => app.visit(app.observatoryHref()));
  }

  const lay = app.layout();
  if (lay && app.route()) {
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
      app.toast(`Saved as ${lay.saveAs(`Layout ${n}`)}.`);
    });
    for (const name of lay.saved()) add({ id: `layout.load.${name}`, title: `Load layout: ${name}`, section: 'Layouts', keywords: ['arrangement'] }, () => lay.load(name));
    add({ id: 'layout.reset', title: 'Reset layout to default', section: 'Layouts', keywords: ['arrangement', 'panels'] }, () => { lay.reset(); app.toast('Back to the default layout.'); });
  }

  add({ id: 'theme.toggle', title: `Switch to ${app.themeNow() === 'light' ? 'dark' : 'light'} theme`, section: 'View', keywords: ['theme', 'dark', 'light', 'appearance'] }, () => app.theme());
  return out;
}

// the registry is rebuilt from the verbs at each listing; the palette only needs list() and onChange()
export function mount(app) {
  const registry = {
    list(ctx) { const r = createRegistry(); for (const s of verbSpecs(app)) r.register(s); return r.list(ctx); },
    onChange: () => () => {},
  };
  // preselect false: STOP is the first row, but an Enter on open runs nothing until a key or the arrows choose a row
  return createPalette({ registry, preselect: false });
}
