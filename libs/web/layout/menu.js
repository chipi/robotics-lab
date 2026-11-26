// The Layout menu both apps share (look-and-feel U26, on layout/store.js): which panels are shown, how wide the columns are, the saved layouts, and
// (the Observatory) export and import as JSON. The app keeps what is its own: what a panel is, how a layout is applied to the page, where the menu sits.
// The menu is built once and its values are set in place, so a repaint never takes the focus from a control. It loads libs/web/layout/menu.css itself.
//
//   createLayoutMenu({ store, id, trigger, mount, rows, widths, sizeTarget, isShown, setShown, isFolded, setFold, wOf, reset, share, onChange, place, isolateKeys })
//   (isFolded and setFold are optional: only a panel row with fold: true and a setFold shows the Fold box)
//     store         the layout store (createLayoutStore)
//     id            the menu element's id
//     trigger       the button that opens it (aria-expanded, and where the focus goes back to); the app binds its click to toggle()
//     mount(menu)   puts the menu in the page
//     rows          what the Panels section lists, in order: { group: 'text' } is a heading; { id, label, sub?, fold? } is a panel (fold adds a Fold box)
//     widths        [{ id, label, min, max, step, prop }]: a slider each; dragging sets `prop` (px) on `sizeTarget` live, releasing saves it
//     isShown(state, id), setShown(draft, id, shown), isFolded(state, id), setFold(draft, id, fold): the app's meaning of a panel's state in the store's shape
//     wOf(state, w)  the width to show for a slider
//     reset()       saves the defaults (the "Reset to default" button and the "Default layout" entry)
//     share         true adds the export and import of a layout as JSON text
//     onChange(state)   after the store changed (a save, a load, a reset): the app applies the layout to its page
//     place()       called as the menu opens (a popover that follows its button); isolateKeys: no key typed in the menu reaches the page's shortcuts
// -> { menu, toggle(on), sync(), commit(edit), change(edit), run(fn, said), status, resetNow, actions, get state, get open }
// `actions` is what a palette verb needs of the menu: saved(), saveAs(name), load(name), reset(); a throw reaches the caller instead of the status line.
import { needSheet } from '../sheet.js';

export const FIRST = 'default';      // the name a change is saved under while no layout of the viewer's is in use
export const clone = (v) => JSON.parse(JSON.stringify(v));

const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (v === false || v == null) continue; if (k === 'class') e.className = v; else e.setAttribute(k, v === true ? '' : v); }
  e.append(...kids.flat().filter((k) => k != null));
  return e;
};

export function createLayoutMenu({ store, id, trigger, mount, rows, widths, sizeTarget, isShown, setShown, isFolded, setFold, wOf, reset, share = false,
  onChange, place, isolateKeys = false }) {
  needSheet(import.meta.url, './menu.css');
  let state = store.get();

  const menu = el('div', { id, class: 'laymenu', role: 'group', 'aria-label': 'Panels and layouts', hidden: true });
  const status = el('div', { id: 'lay-status', class: 'hint', role: 'status' });
  const shows = {}, folds = {}, ranges = {};
  const panels = rows.filter((r) => r.id);

  function run(fn, said) {
    try { const out = fn(); status.textContent = said ? said(out) : ''; } catch (e) { status.textContent = e.message; }
  }
  // a change to the current layout: written to the one in use, or to the first one when none is
  function commit(edit) {
    const next = clone(state);
    edit(next);
    store.save(store.current() || FIRST, next);
  }
  const change = (edit) => run(() => commit(edit));
  const resetNow = () => { reset(); };

  const panelRows = rows.map((r) => {
    if (!r.id) return el('div', { class: 'laygroup' }, r.group);
    shows[r.id] = el('input', { type: 'checkbox', id: 'lay-show-' + r.id });
    shows[r.id].addEventListener('change', () => change((s) => setShown(s, r.id, shows[r.id].checked)));
    const line = [el('label', { class: 'inline', for: 'lay-show-' + r.id }, shows[r.id], r.label)];
    if (r.fold && setFold) {
      folds[r.id] = el('input', { type: 'checkbox', id: 'lay-fold-' + r.id });
      folds[r.id].addEventListener('change', () => change((s) => setFold(s, r.id, folds[r.id].checked)));
      line.push(el('label', { class: 'inline dim', for: 'lay-fold-' + r.id }, folds[r.id], 'Fold'));
    }
    return el('div', { class: 'layline' + (r.sub ? ' sub' : '') }, line);
  });
  const sizes = widths.map((w) => {
    const r = el('input', { type: 'range', id: 'lay-w-' + w.id, min: w.min, max: w.max, step: w.step });
    const out = el('span', { class: 'mono dim' });
    r.addEventListener('input', () => { sizeTarget.style.setProperty(w.prop, r.value + 'px'); out.textContent = r.value + ' px'; });
    r.addEventListener('change', () => change((s) => { s.widths[w.id] = Number(r.value); }));
    ranges[w.id] = { r, out };
    return el('div', { class: 'layrow' }, el('label', { for: r.id }, w.label), r, out);
  });

  const list = el('select', { id: 'lay-list', 'aria-label': 'Saved layouts' });
  list.addEventListener('change', () => run(() => { if (list.value) store.load(list.value); else resetNow(); }));
  const name = el('input', { id: 'lay-name', placeholder: 'Name', 'aria-label': 'Name for the layout', maxlength: 60 });
  const btn = (bid, text, extra = '') => el('button', { id: bid, class: 'btn sm' + extra, type: 'button' }, text);
  const save = btn('lay-save', 'Save as');
  save.addEventListener('click', () => run(() => { const n = store.save(name.value, state); name.value = ''; return n; }, (n) => `Saved as ${n}.`));
  const del = btn('lay-delete', 'Delete');
  del.addEventListener('click', () => run(() => { const n = store.current(); if (n) store.remove(n); }, () => 'Deleted. The default layout is back.'));
  const resetBtn = btn('lay-reset', 'Reset to default');
  resetBtn.addEventListener('click', () => run(resetNow, () => 'Back to the default layout.'));
  const close = btn('lay-close', 'Close', ' ghost');
  close.addEventListener('click', () => toggle(false));

  const sharing = [];
  if (share) {
    const json = el('textarea', { id: 'lay-json', rows: 4, spellcheck: 'false', 'aria-label': 'A layout as JSON, to copy out or paste in', placeholder: 'Export fills this; paste a layout here to import it' });
    const exp = btn('lay-export', 'Export');
    exp.addEventListener('click', () => run(() => {
      if (!store.current()) store.save(FIRST, state);
      json.value = store.exportJSON();
      json.focus(); json.select();
      return store.current();
    }, (n) => `Exported ${n}. Copy the text.`));
    const imp = btn('lay-import', 'Import');
    imp.addEventListener('click', () => run(() => { const n = store.importJSON(json.value); json.value = ''; return n; }, (n) => `Imported as ${n}.`));
    sharing.push(el('div', { class: 'laygroup' }, 'Share'), json, el('div', { class: 'layline' }, exp, imp));
  }

  menu.append(
    el('div', { class: 'layhead' }, el('h3', {}, 'Layout'), close),
    el('div', { class: 'laygroup' }, 'Panels'), ...panelRows,
    el('div', { class: 'laysizes' }, el('div', { class: 'laygroup' }, 'Sizes'), ...sizes),      // an app may hide the sizes where its columns stack (a phone)
    el('div', { class: 'laygroup' }, 'Saved layouts'),
    el('div', { class: 'layline' }, list, del),
    el('div', { class: 'layline' }, name, save),
    el('div', { class: 'layline' }, resetBtn),
    ...sharing,
    status,
  );
  mount(menu);

  function sync() {
    for (const p of panels) {
      shows[p.id].checked = isShown(state, p.id);
      if (p.fold && setFold) { folds[p.id].checked = isFolded(state, p.id); folds[p.id].disabled = !isShown(state, p.id); }
    }
    for (const w of widths) { const v = wOf(state, w); ranges[w.id].r.value = v; ranges[w.id].out.textContent = v + ' px'; }
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
  store.onChange((cur, s) => { state = s; sync(); onChange(s); });

  function toggle(on) {
    const open = on ?? menu.hidden;
    menu.hidden = !open;
    trigger.setAttribute('aria-expanded', String(open));
    if (open) { place?.(menu, trigger); shows[panels[0].id].focus(); } else trigger.focus();
  }
  menu.addEventListener('keydown', (ev) => {
    if (isolateKeys) ev.stopPropagation();
    if (ev.key === 'Escape') { ev.stopPropagation(); toggle(false); }
  });
  if (isolateKeys) trigger.addEventListener('keydown', (ev) => { if (ev.key === ' ' || ev.key === 'Enter') ev.stopPropagation(); });

  sync();
  const actions = {
    saved: () => store.list().filter((n) => n !== FIRST),
    saveAs: (n) => store.save(n, state),
    load: (n) => store.load(n),
    reset: resetNow,
  };
  return { menu, toggle, sync, commit, change, run, status, resetNow, actions, get state() { return state; }, get open() { return !menu.hidden; } };
}
