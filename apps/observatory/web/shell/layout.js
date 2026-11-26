// The workbench's panels and layouts (look-and-feel U16): which panels are shown, which are folded, how wide the two columns are and where the splitter sits,
// kept as named layouts in this browser (libs/web/layout/store.js: rl.layouts.observatory, never the server). The menu is the shared one (libs/web/layout/menu.js), at compact density.
//
// The store's observatory shape is {panels: {left, right, open: {}, angles}, widths: {left, right}}. `open` is a free map of scalars: it holds the left panel's
// open sections (what miniview.left kept), and here `hidden:<id>` / `fold:<id>` (true) for the streams and the properties and `split` (px) for the splitter.
// An absent key is the default, so a reset is the defaults and an old layout from before this unit loads as it was.
import { createLayoutStore, DEFAULTS } from '/lib/layout/store.js';
import { createLayoutMenu, FIRST, clone } from '/lib/layout/menu.js';

// the shell's right column was always 280 px; the store's own default (320) would move it on the first load
const SHAPE = { ...DEFAULTS.observatory, widths: { left: 280, right: 280 } };
const PANELS = [
  { id: 'left', label: 'Left column' },
  { id: 'streams', label: 'Streams', sub: true, fold: true },
  { id: 'props', label: 'Properties', sub: true, fold: true },
  { id: 'right', label: 'Inspector: Moment, Selection, Explore, Decided' },
];
const WIDTHS = [
  { id: 'left', label: 'Left column', min: 200, max: 480, step: 20, prop: '--lay-left' },
  { id: 'right', label: 'Inspector', min: 240, max: 560, step: 20, prop: '--lay-right' },
];
const SPLIT = { min: 120, step: 24 };

let store = null;
const st = () => (store ||= createLayoutStore({ app: 'observatory', defaults: SHAPE }));

// the shell's own reads and writes (it kept these in miniview.left): the sections a viewer left open and the joint-angle switch
export function prefs() { const s = st().get(); return { open: s.panels.open, angles: s.panels.angles }; }
export function savePrefs(p) {
  try {
    const next = clone(st().get());
    if (p.open) Object.assign(next.panels.open, p.open);
    if (typeof p.angles === 'boolean') next.panels.angles = p.angles;
    st().save(st().current() || FIRST, next);
  } catch { /* a layout that cannot be saved is the viewer's to retry from the menu */ }
}

const isShown = (s, id) => (id === 'left' || id === 'right' ? s.panels[id] !== false : s.panels.open['hidden:' + id] !== true);
const isFolded = (s, id) => s.panels.open['fold:' + id] === true;
const wOf = (s, w) => (Number.isFinite(s.widths[w.id]) ? Math.min(w.max, Math.max(w.min, s.widths[w.id])) : SHAPE.widths[w.id]);

// host: .app; button: the viewport header's Layout button; left and split: the left column and its splitter; onApply(): the shell re-reads the sections and the angle switch
export function mountLayout({ host, button, left, split, onApply }) {
  const S = st();
  let state = S.get();

  function apply(s) {
    host.classList.toggle('lay-no-left', !isShown(s, 'left'));
    host.classList.toggle('lay-no-right', !isShown(s, 'right'));
    for (const id of ['streams', 'props']) {
      host.classList.toggle('lay-no-' + id, !isShown(s, id));
      host.classList.toggle('lay-fold-' + id, isFolded(s, id));
    }
    for (const w of WIDTHS) host.style.setProperty(w.prop, wOf(s, w) + 'px');
    const sp = s.panels.open.split;
    if (Number.isFinite(sp)) left.style.setProperty('--split', Math.max(SPLIT.min, sp) + 'px'); else left.style.removeProperty('--split');
    split.setAttribute('aria-valuenow', String(Math.round(Number.isFinite(sp) ? sp : left.querySelector('.region')?.getBoundingClientRect().height ?? 0)));
  }

  const M = createLayoutMenu({
    store: S, id: 'lay-menu', trigger: button, mount: (menu) => document.body.append(menu), sizeTarget: host, share: true, isolateKeys: true, place,
    rows: PANELS, widths: WIDTHS, wOf,
    isShown, setShown: (s, id, shown) => {
      if (id === 'left' || id === 'right') s.panels[id] = shown;
      else if (shown) delete s.panels.open['hidden:' + id]; else s.panels.open['hidden:' + id] = true;
    },
    isFolded, setFold: (s, id, fold) => { if (fold) s.panels.open['fold:' + id] = true; else delete s.panels.open['fold:' + id]; },
    reset: () => S.save(FIRST, clone(SHAPE)),
    onChange: (s) => { state = s; apply(s); onApply?.(s); },
  });
  const { change, commit } = M;

  // --- the splitter: dragged (the shell moves it), then kept; or moved by the arrow keys ---
  split.setAttribute('role', 'separator'); split.setAttribute('aria-orientation', 'horizontal'); split.setAttribute('tabindex', '0');
  split.setAttribute('aria-label', 'Resize the streams and the properties');
  const splitNow = () => parseFloat(left.style.getPropertyValue('--split')) || left.querySelector('.region').getBoundingClientRect().height;
  split.addEventListener('pointerup', () => { const v = parseFloat(left.style.getPropertyValue('--split')); if (Number.isFinite(v)) change((s) => { s.panels.open.split = Math.round(v); }); });
  split.addEventListener('keydown', (ev) => {
    const d = ev.key === 'ArrowUp' ? -1 : ev.key === 'ArrowDown' ? 1 : 0;
    if (!d) return;
    ev.preventDefault(); ev.stopPropagation();
    const max = left.getBoundingClientRect().height - 125;
    change((s) => { s.panels.open.split = Math.round(Math.min(Math.max(SPLIT.min, splitNow() + d * SPLIT.step), Math.max(SPLIT.min, max))); });
  });

  function place(menu) {
    const r = button.getBoundingClientRect(), w = Math.min(380, innerWidth - 16);
    menu.style.width = w + 'px';
    menu.style.left = Math.max(8, Math.min(r.right - w, innerWidth - w - 8)) + 'px';
    menu.style.top = r.bottom + 4 + 'px';
    menu.style.maxHeight = `calc(100dvh - ${r.bottom + 12}px)`;
  }
  button.addEventListener('click', () => M.toggle());
  addEventListener('resize', () => { if (M.open) place(M.menu); });

  apply(state);
  // what the palette's verbs use (verbs.js): the menu's writes, but an error reaches the caller instead of the menu's status line
  const act = {
    panels: PANELS.map((p) => ({ id: p.id, label: p.label, fold: !!p.fold })),
    isHidden: (id) => !isShown(state, id),
    isFolded: (id) => isFolded(state, id),
    setHidden: (id, hide) => commit((s) => {
      if (id === 'left' || id === 'right') s.panels[id] = !hide;
      else if (hide) s.panels.open['hidden:' + id] = true; else delete s.panels.open['hidden:' + id];
    }),
    setFolded: (id, fold) => commit((s) => { if (fold) s.panels.open['fold:' + id] = true; else delete s.panels.open['fold:' + id]; }),
    ...M.actions,
  };
  return { toggle: M.toggle, act, get open() { return M.open; } };
}
