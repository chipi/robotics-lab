// The robot page's panels and layouts (look-and-feel U22): which cards are shown, which are folded, how wide the joints column and the cards are,
// kept as named layouts in this browser (libs/web/layout/store.js: rl.layouts.control, never the server). A module, loaded by app.js the first time
// a robot page opens, so the phone overview (the page's first load) fetches neither this nor the store.
//
// The store's control shape is {panels: {open: {}}, widths: {}}: both are free maps of scalars. `open` holds a card's fold (readiness, alarms, parts:
// true or false) and `hidden:<id>` (true when the card is hidden); `widths` holds `joints` and `cards` in px. An absent key is the default, so the
// default layout is the empty one and a reset is the store's own defaults. A layout saved before the fit card went (its `fit` key) loads: a key
// naming no panel is never read.
import { createLayoutStore, DEFAULTS } from '/lib/layout/store.js';
import { createLayoutMenu, FIRST, clone } from '/lib/layout/menu.js';

const PANELS = [
  { id: 'readiness', label: 'Readiness', tab: 'Overview', fold: true },
  { id: 'alarms', label: 'Alarms, last 60 s', tab: 'Overview', fold: true },
  { id: 'parts', label: 'Parts', tab: 'Overview', fold: true },
  { id: 'body', label: 'Body summary', tab: 'Overview' },
  { id: 'joints', label: 'Joints', tab: 'Body' },
];
const WIDTHS = [
  { id: 'joints', label: 'Joints column', min: 240, max: 560, step: 20, dflt: 340, prop: '--rp-joints-w' },
  { id: 'cards', label: 'Overview card, at least', min: 320, max: 640, step: 20, dflt: 420, prop: '--rp-card-min' },
];

// host: the robot page; setOpen(head, open): app.js's fold, which keeps S.open too
export function mount({ page, setOpen }) {
  const store = createLayoutStore({ app: 'control' });
  const card = (id) => page.querySelector(`[data-panel="${id}"]`);
  let state = store.get();

  const hiddenKey = (id) => 'hidden:' + id;
  const isHidden = (s, id) => s.panels.open[hiddenKey(id)] === true;
  const wOf = (s, w) => (Number.isFinite(s.widths[w.id]) ? Math.min(w.max, Math.max(w.min, s.widths[w.id])) : w.dflt);

  function apply(s) {
    for (const p of PANELS) {
      const c = card(p.id);
      if (!c) continue;
      c.hidden = isHidden(s, p.id);
      const head = p.fold && c.querySelector('button[data-collapse]');
      if (head) { const want = s.panels.open[p.id] !== false; if ((head.getAttribute('aria-expanded') === 'true') !== want) setOpen(head, want); }
    }
    for (const w of WIDTHS) page.style.setProperty(w.prop, wOf(s, w) + 'px');
    page.querySelector('.bodygrid').classList.toggle('solo', isHidden(s, 'joints'));
    page.querySelector('#rp-layout-empty').hidden = !PANELS.filter((p) => p.tab === 'Overview').every((p) => isHidden(s, p.id));
  }

  const rows = PANELS.flatMap((p, i) => (i && PANELS[i - 1].tab === p.tab ? [p] : [{ group: p.tab + ' tab' }, p]));
  const M = createLayoutMenu({
    store, id: 'rp-layout-menu', trigger: page.querySelector('#rp-layout'), mount: (menu) => page.querySelector('.strip').append(menu), sizeTarget: page,
    rows, widths: WIDTHS, wOf,
    isShown: (s, id) => !isHidden(s, id),
    setShown: (s, id, shown) => { if (shown) delete s.panels.open[hiddenKey(id)]; else s.panels.open[hiddenKey(id)] = true; },
    reset: () => store.save(FIRST, clone(DEFAULTS.control)),
    onChange: (s) => { state = s; apply(s); },
  });
  const { change, commit } = M;

  // a fold the viewer clicked is part of the layout
  function folded(key, open) {
    if (!PANELS.some((p) => p.id === key && p.fold)) return;
    change((s) => { s.panels.open[key] = open; });
  }

  apply(state);
  // what the palette's verbs use (palette-verbs.js): the same writes as the menu, but an error reaches the caller instead of the menu's status line
  const act = {
    panels: PANELS.map((p) => ({ id: p.id, label: p.label, tab: p.tab, fold: !!p.fold })),
    isHidden: (id) => isHidden(state, id),
    isFolded: (id) => state.panels.open[id] === false,
    setHidden: (id, hide) => commit((s) => { if (hide) s.panels.open[hiddenKey(id)] = true; else delete s.panels.open[hiddenKey(id)]; }),
    setFolded: (id, fold) => commit((s) => { s.panels.open[id] = !fold; }),
    ...M.actions,
  };
  return { toggle: M.toggle, folded, act, get open() { return M.open; } };
}
