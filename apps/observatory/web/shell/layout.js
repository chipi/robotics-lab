// The workbench's panels and layouts (look-and-feel U16): which panels are shown, which are folded, how wide the two columns are and where the splitter sits,
// kept as named layouts in this browser (libs/web/layout/store.js: rl.layouts.observatory, never the server). The menu is Mission Control's (U22), at compact density.
//
// The store's observatory shape is {panels: {left, right, open: {}, angles}, widths: {left, right}}. `open` is a free map of scalars: it holds the left panel's
// open sections (what miniview.left kept), and here `hidden:<id>` / `fold:<id>` (true) for the streams and the properties and `split` (px) for the splitter.
// An absent key is the default, so a reset is the defaults and an old layout from before this unit loads as it was.
import { createLayoutStore, DEFAULTS } from '/lib/layout/store.js';

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
const FIRST = 'default';      // the name a change is saved under while no layout of the viewer's is in use
const SPLIT = { min: 120, step: 24 };

let store = null;
const st = () => (store ||= createLayoutStore({ app: 'observatory', defaults: SHAPE }));
const clone = (v) => JSON.parse(JSON.stringify(v));

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

const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (v === false || v == null) continue; if (k === 'class') e.className = v; else e.setAttribute(k, v === true ? '' : v); }
  e.append(...kids.flat().filter((k) => k != null));
  return e;
};

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

  // --- the menu: built once, then its values are set in place so a repaint never takes the focus from a control ---
  const menu = el('div', { id: 'lay-menu', class: 'laymenu', role: 'group', 'aria-label': 'Panels and layouts', hidden: true });
  const status = el('div', { id: 'lay-status', class: 'hint', role: 'status' });
  const shows = {}, folds = {}, ranges = {};
  const panelRows = PANELS.map((p) => {
    shows[p.id] = el('input', { type: 'checkbox', id: 'lay-show-' + p.id });
    shows[p.id].addEventListener('change', () => change((s) => {
      if (p.id === 'left' || p.id === 'right') s.panels[p.id] = shows[p.id].checked;
      else if (shows[p.id].checked) delete s.panels.open['hidden:' + p.id]; else s.panels.open['hidden:' + p.id] = true;
    }));
    const row = [el('label', { class: 'inline', for: 'lay-show-' + p.id }, shows[p.id], p.label)];
    if (p.fold) {
      folds[p.id] = el('input', { type: 'checkbox', id: 'lay-fold-' + p.id });
      folds[p.id].addEventListener('change', () => change((s) => { if (folds[p.id].checked) s.panels.open['fold:' + p.id] = true; else delete s.panels.open['fold:' + p.id]; }));
      row.push(el('label', { class: 'inline dim', for: 'lay-fold-' + p.id }, folds[p.id], 'Fold'));
    }
    return el('div', { class: 'layline' + (p.sub ? ' sub' : '') }, row);
  });
  const sizes = WIDTHS.map((w) => {
    const r = el('input', { type: 'range', id: 'lay-w-' + w.id, min: w.min, max: w.max, step: w.step });
    const out = el('span', { class: 'mono dim' });
    r.addEventListener('input', () => { host.style.setProperty(w.prop, r.value + 'px'); out.textContent = r.value + ' px'; });
    r.addEventListener('change', () => change((s) => { s.widths[w.id] = Number(r.value); }));
    ranges[w.id] = { r, out };
    return el('div', { class: 'layrow' }, el('label', { for: r.id }, w.label), r, out);
  });
  const resetNow = () => S.save(FIRST, clone(SHAPE));
  const list = el('select', { id: 'lay-list', 'aria-label': 'Saved layouts' });
  list.addEventListener('change', () => run(() => { if (list.value) S.load(list.value); else resetNow(); }));
  const name = el('input', { id: 'lay-name', placeholder: 'Name', 'aria-label': 'Name for the layout', maxlength: 60 });
  const save = el('button', { id: 'lay-save', class: 'btn sm', type: 'button' }, 'Save as');
  save.addEventListener('click', () => run(() => { const n = S.save(name.value, state); name.value = ''; return n; }, (n) => `Saved as ${n}.`));
  const del = el('button', { id: 'lay-delete', class: 'btn sm', type: 'button' }, 'Delete');
  del.addEventListener('click', () => run(() => { const n = S.current(); if (n) S.remove(n); }, () => 'Deleted. The default layout is back.'));
  const reset = el('button', { id: 'lay-reset', class: 'btn sm', type: 'button' }, 'Reset to default');
  reset.addEventListener('click', () => run(resetNow, () => 'Back to the default layout.'));
  const close = el('button', { id: 'lay-close', class: 'btn sm ghost', type: 'button' }, 'Close');
  close.addEventListener('click', () => toggle(false));
  const json = el('textarea', { id: 'lay-json', rows: 4, spellcheck: 'false', 'aria-label': 'A layout as JSON, to copy out or paste in', placeholder: 'Export fills this; paste a layout here to import it' });
  const exp = el('button', { id: 'lay-export', class: 'btn sm', type: 'button' }, 'Export');
  exp.addEventListener('click', () => run(() => {
    if (!S.current()) S.save(FIRST, state);
    json.value = S.exportJSON();
    json.focus(); json.select();
    return S.current();
  }, (n) => `Exported ${n}. Copy the text.`));
  const imp = el('button', { id: 'lay-import', class: 'btn sm', type: 'button' }, 'Import');
  imp.addEventListener('click', () => run(() => { const n = S.importJSON(json.value); json.value = ''; return n; }, (n) => `Imported as ${n}.`));
  menu.append(
    el('div', { class: 'layhead' }, el('h3', {}, 'Layout'), close),
    el('div', { class: 'laygroup' }, 'Panels'), ...panelRows,
    el('div', { class: 'laygroup' }, 'Sizes'), ...sizes,
    el('div', { class: 'laygroup' }, 'Saved layouts'),
    el('div', { class: 'layline' }, list, del),
    el('div', { class: 'layline' }, name, save),
    el('div', { class: 'layline' }, reset),
    el('div', { class: 'laygroup' }, 'Share'),
    json,
    el('div', { class: 'layline' }, exp, imp),
    status,
  );
  document.body.append(menu);

  function sync() {
    for (const p of PANELS) {
      shows[p.id].checked = isShown(state, p.id);
      if (p.fold) { folds[p.id].checked = isFolded(state, p.id); folds[p.id].disabled = !isShown(state, p.id); }
    }
    for (const w of WIDTHS) { const v = wOf(state, w); ranges[w.id].r.value = v; ranges[w.id].out.textContent = v + ' px'; }
    const cur = S.current(), names = S.list();
    const sig = JSON.stringify([cur, names]);
    if (list.dataset.sig !== sig) {
      list.dataset.sig = sig;
      list.replaceChildren(el('option', { value: '' }, 'Default layout'), ...names.filter((n) => n !== FIRST).map((n) => el('option', { value: n }, n)));
    }
    list.value = cur && cur !== FIRST && names.includes(cur) ? cur : '';
    del.disabled = !cur || cur === FIRST;
    if (!S.durable) status.textContent = 'This browser keeps no storage for the page, so the layout lasts until you close the tab.';
  }

  function run(fn, said) {
    try { const out = fn(); status.textContent = said ? said(out) : ''; } catch (e) { status.textContent = e.message; }
  }
  // a change to the current layout: written to the one in use, or to the first one when none is
  function commit(edit) {
    const next = clone(state);
    edit(next);
    S.save(S.current() || FIRST, next);
  }
  function change(edit) { run(() => commit(edit)); }
  S.onChange((cur, s) => { state = s; apply(s); sync(); onApply?.(s); });

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

  function place() {
    const r = button.getBoundingClientRect(), w = Math.min(380, innerWidth - 16);
    menu.style.width = w + 'px';
    menu.style.left = Math.max(8, Math.min(r.right - w, innerWidth - w - 8)) + 'px';
    menu.style.top = r.bottom + 4 + 'px';
    menu.style.maxHeight = `calc(100dvh - ${r.bottom + 12}px)`;
  }
  function toggle(on) {
    const open = on ?? menu.hidden;
    menu.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    if (open) { place(); shows[PANELS[0].id].focus(); } else button.focus();
  }
  button.addEventListener('click', () => toggle());
  // the shell's keys (Space plays, the arrows step) are not for a control in the menu or on its button
  menu.addEventListener('keydown', (ev) => { ev.stopPropagation(); if (ev.key === 'Escape') toggle(false); });
  button.addEventListener('keydown', (ev) => { if (ev.key === ' ' || ev.key === 'Enter') ev.stopPropagation(); });
  addEventListener('resize', () => { if (!menu.hidden) place(); });

  apply(state);
  sync();
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
    saved: () => S.list().filter((n) => n !== FIRST),
    saveAs: (n) => S.save(n, state),
    load: (n) => S.load(n),
    reset: resetNow,
  };
  return { toggle, act, get open() { return !menu.hidden; } };
}
