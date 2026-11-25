// The robot page's panels and layouts (look-and-feel U22): which cards are shown, which are folded, how wide the joints column and the cards are,
// kept as named layouts in this browser (libs/web/layout/store.js: rl.layouts.control, never the server). A module, loaded by app.js the first time
// a robot page opens, so the phone overview (the page's first load) fetches neither this nor the store.
//
// The store's control shape is {panels: {open: {}}, widths: {}}: both are free maps of scalars. `open` holds a card's fold (readiness, alarms, parts:
// true or false) and `hidden:<id>` (true when the card is hidden); `widths` holds `joints` and `cards` in px. An absent key is the default, so the
// default layout is the empty one and a reset is the store's own defaults. A layout saved before the fit card went (its `fit` key) loads: a key
// naming no panel is never read.
import { createLayoutStore, DEFAULTS } from '/lib/layout/store.js';

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
const FIRST = 'default';      // the name a change is saved under while no layout of the viewer's is in use

const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (v === false || v == null) continue; if (k === 'class') e.className = v; else e.setAttribute(k, v === true ? '' : v); }
  e.append(...kids.flat().filter((k) => k != null));
  return e;
};

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

  // --- the menu: built once, then its values are set in place so a repaint never takes the focus from a control ---
  const menu = el('div', { id: 'rp-layout-menu', class: 'laymenu', role: 'group', 'aria-label': 'Panels and layouts', hidden: true });
  const status = el('div', { id: 'lay-status', class: 'hint', role: 'status' });
  const boxes = {}, ranges = {};
  const checks = [];
  let lastTab = null;
  for (const p of PANELS) {
    if (p.tab !== lastTab) { checks.push(el('div', { class: 'laygroup' }, p.tab + ' tab')); lastTab = p.tab; }
    boxes[p.id] = el('input', { type: 'checkbox', id: 'lay-show-' + p.id });
    boxes[p.id].addEventListener('change', () => change((s) => { if (boxes[p.id].checked) delete s.panels.open[hiddenKey(p.id)]; else s.panels.open[hiddenKey(p.id)] = true; }));
    checks.push(el('label', { class: 'inline', for: 'lay-show-' + p.id }, boxes[p.id], p.label));
  }
  const sizes = WIDTHS.map((w) => {
    const r = el('input', { type: 'range', id: 'lay-w-' + w.id, min: w.min, max: w.max, step: w.step });
    const out = el('span', { class: 'mono dim' });
    r.addEventListener('input', () => { page.style.setProperty(w.prop, r.value + 'px'); out.textContent = r.value + ' px'; });
    r.addEventListener('change', () => change((s) => { s.widths[w.id] = Number(r.value); }));
    ranges[w.id] = { r, out };
    return el('div', { class: 'layrow' }, el('label', { for: r.id }, w.label), r, out);
  });
  const resetNow = () => store.save(FIRST, JSON.parse(JSON.stringify(DEFAULTS.control)));
  const list = el('select', { id: 'lay-list', 'aria-label': 'Saved layouts' });
  list.addEventListener('change', () => run(() => { if (list.value) store.load(list.value); else resetNow(); }));
  const name = el('input', { id: 'lay-name', placeholder: 'Name', 'aria-label': 'Name for the layout', maxlength: 60 });
  const save = el('button', { id: 'lay-save', class: 'btn sm', type: 'button' }, 'Save as');
  save.addEventListener('click', () => run(() => { store.save(name.value, state); name.value = ''; }, (n) => `Saved as ${n}.`));
  const del = el('button', { id: 'lay-delete', class: 'btn sm', type: 'button' }, 'Delete');
  del.addEventListener('click', () => run(() => { const n = store.current(); if (n) store.remove(n); }, () => 'Deleted. The default layout is back.'));
  const reset = el('button', { id: 'lay-reset', class: 'btn sm', type: 'button' }, 'Reset to default');
  reset.addEventListener('click', () => run(resetNow, () => 'Back to the default layout.'));
  const close = el('button', { id: 'lay-close', class: 'btn sm ghost', type: 'button' }, 'Close');
  close.addEventListener('click', () => toggle(false));
  menu.append(
    el('div', { class: 'layhead' }, el('h3', {}, 'Layout'), close),
    el('div', { class: 'laygroup' }, 'Panels'), ...checks,
    el('div', { class: 'laygroup' }, 'Sizes'), ...sizes,
    el('div', { class: 'laygroup' }, 'Saved layouts'),
    el('div', { class: 'row' }, el('label', { class: 'sr', for: 'lay-list' }, 'Saved layouts'), list, del),
    el('div', { class: 'row' }, name, save),
    el('div', { class: 'row' }, reset),
    status,
  );
  page.querySelector('.strip').append(menu);

  function sync() {
    for (const p of PANELS) boxes[p.id].checked = !isHidden(state, p.id);
    for (const w of WIDTHS) { const v = wOf(state, w); ranges[w.id].r.value = v; ranges[w.id].out.textContent = v + ' px'; }
    const cur = store.current(), names = store.list();
    const sig = JSON.stringify([cur, names]);
    if (list.dataset.sig !== sig) {
      list.dataset.sig = sig;
      list.replaceChildren(el('option', { value: '' }, 'Default layout'), ...names.filter((n) => n !== FIRST).map((n) => el('option', { value: n }, n)));
    }
    list.value = cur && cur !== FIRST && names.includes(cur) ? cur : '';
    del.disabled = !cur || cur === FIRST;
    if (!store.durable) status.textContent = 'This browser keeps no storage for the page, so the layout lasts until you close the tab.';
  }

  function run(fn, said) {
    try { const out = fn(); status.textContent = said ? said(out) : ''; } catch (e) { status.textContent = e.message; }
  }
  // a change to the current layout: written to the one in use, or to the first one when none is
  function commit(edit) {
    const next = JSON.parse(JSON.stringify(state));
    edit(next);
    store.save(store.current() || FIRST, next);
  }
  function change(edit) { run(() => commit(edit)); }
  store.onChange((cur, s) => { state = s; apply(s); sync(); });

  // a fold the viewer clicked is part of the layout
  function folded(key, open) {
    if (!PANELS.some((p) => p.id === key && p.fold)) return;
    change((s) => { s.panels.open[key] = open; });
  }

  function toggle(on) {
    const open = on ?? menu.hidden;
    menu.hidden = !open;
    const b = page.querySelector('#rp-layout');
    b.setAttribute('aria-expanded', String(open));
    if (open) boxes[PANELS[0].id].focus(); else b.focus();
  }
  menu.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { ev.stopPropagation(); toggle(false); } });

  apply(state);
  sync();
  // what the palette's verbs use (palette-verbs.js): the same writes as the menu, but an error reaches the caller instead of the menu's status line
  const act = {
    panels: PANELS.map((p) => ({ id: p.id, label: p.label, tab: p.tab, fold: !!p.fold })),
    isHidden: (id) => isHidden(state, id),
    isFolded: (id) => state.panels.open[id] === false,
    setHidden: (id, hide) => commit((s) => { if (hide) s.panels.open[hiddenKey(id)] = true; else delete s.panels.open[hiddenKey(id)]; }),
    setFolded: (id, fold) => commit((s) => { s.panels.open[id] = !fold; }),
    saved: () => store.list().filter((n) => n !== FIRST),
    saveAs: (n) => store.save(n, state),
    load: (n) => store.load(n),
    reset: resetNow,
  };
  return { toggle, folded, act, get open() { return !menu.hidden; } };
}
