// The command palette (look-and-feel row 22). Ctrl/Cmd+K opens it, never from a key typed in an input; type to filter, Up/Down move,
// Enter runs, Esc closes and focus goes back to what opened it. A verb with danger 'confirm' needs a second Enter (confirm.js); a 'stop' verb
// is listed first and runs on the first Enter. A verb's `hotkey` is shown, not bound: the app owns its keys. The palette starts no goal.
import { arm } from '../confirm.js';
import { reducedMotion } from '../motion.js';
import { registry as defaultRegistry } from './registry.js';
import { needSheet } from '../sheet.js';
import { TYPING } from '../lazy.js';

const RECENT_KEY = 'rl.palette.recent';
const RECENT_MAX = 8;


// -1 when `query` is not a subsequence of `text`; else a score, higher is better: a prefix, a word start and a run of letters count more
export function fuzzy(query, text) {
  const q = query.toLowerCase().replace(/\s+/g, ''), t = text.toLowerCase();
  if (!q) return 0;
  let ti = 0, score = 0, run = 0;
  for (let qi = 0; qi < q.length; qi++) {
    const at = t.indexOf(q[qi], ti);
    if (at < 0) return -1;
    const wordStart = at === 0 || /[^a-z0-9]/.test(t[at - 1]);
    run = at === ti && qi > 0 ? run + 1 : 0;
    score += 1 + run * 2 + (wordStart ? 3 : 0) - Math.min(at - ti, 5) * 0.2;
    ti = at + 1;
  }
  return score + (t.startsWith(q) ? 10 : 0) - t.length * 0.01;
}

const match = (q, v) => {
  const s = fuzzy(q, v.title);
  if (s >= 0) return s + 5;
  const k = Math.max(-1, ...v.keywords.map((w) => fuzzy(q, w)), fuzzy(q, v.section));
  return k < 0 ? -1 : k;
};

// createPalette({host, registry, storage, context, preselect}) -> {open, close, toggle, isOpen, dispose}
// `context()` is what each verb's when(ctx) and run(ctx) get; `storage` keeps the recent verbs under rl.palette.recent.
// `preselect` (default true) selects the first row when the palette opens or the query is empty; false leaves nothing selected until a key, an arrow or a typed
// query chooses a row, so an Enter on open runs nothing (Mission Control, whose first row is STOP).
export function createPalette({ host = document.body, registry = defaultRegistry, storage, context = () => ({}), preselect = true } = {}) {
  const store = storage ?? (() => { try { return localStorage; } catch { return null; } })();
  const uid = 'pal' + Math.random().toString(36).slice(2, 7);
  let root = null, input = null, listbox = null, status = null;
  let shown = [], cursor = 0, opener = null, wires = [], armedId = null, running = false;

  const recent = () => { try { const r = JSON.parse(store?.getItem(RECENT_KEY) ?? '[]'); return Array.isArray(r) ? r.filter((x) => typeof x === 'string') : []; } catch { return []; } };
  const remember = (id) => {
    try { store?.setItem(RECENT_KEY, JSON.stringify([id, ...recent().filter((x) => x !== id)].slice(0, RECENT_MAX))); } catch { /* storage blocked: recents last for this page only */ }
  };

  function build() {
    needSheet(import.meta.url, './palette.css');
    root = document.createElement('div');
    root.className = 'pal'; root.hidden = true;
    root.innerHTML = `<div class="pal-scrim"></div>
      <div class="pal-box" role="dialog" aria-modal="true" aria-label="Command palette">
        <input class="pal-input ui-input" type="text" role="combobox" aria-expanded="true" aria-autocomplete="list" aria-label="Type a command" autocomplete="off" spellcheck="false" placeholder="Type a command">
        <ul class="pal-list" role="listbox" aria-label="Commands"></ul>
        <div class="pal-status" role="status" aria-live="polite"></div>
      </div>`;
    const box = root.querySelector('.pal-box');
    input = root.querySelector('input'); listbox = root.querySelector('ul'); status = root.querySelector('.pal-status');
    listbox.id = `${uid}-list`; input.setAttribute('aria-controls', listbox.id);
    root.querySelector('.pal-scrim').addEventListener('click', close);
    // a mouse press must not move focus off the input: a blur would disarm a confirm button before its second press
    listbox.addEventListener('mousedown', (e) => e.preventDefault());
    input.addEventListener('input', () => render(true));
    box.addEventListener('keydown', onBoxKey);
    host.append(root);
  }

  function ordered(q) {
    const ctx = context();
    const all = registry.list(ctx);
    if (!q.trim()) {
      const r = recent(), rank = (v) => { const i = r.indexOf(v.id); return i < 0 ? r.length : i; };
      const stops = all.filter((v) => v.danger === 'stop'), rest = all.filter((v) => v.danger !== 'stop');
      return [...stops, ...rest.map((v, i) => [v, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map((x) => x[0])];
    }
    const scored = all.map((v, i) => ({ v, i, s: match(q, v) })).filter((x) => x.s >= 0);
    scored.sort((a, b) => (b.v.danger === 'stop') - (a.v.danger === 'stop') || b.s - a.s || a.i - b.i);
    return scored.map((x) => x.v);
  }

  function disarmAll() {
    for (const w of wires) w.off();
    wires = [];
    armedId = null;
  }

  // confirm.js has no "cancel": a disarm is a teardown, so the button is armed again for its next first press
  function wire(w) {
    w.off = arm(w.b, { armedLabel: 'Press Enter again to confirm', onConfirm: () => { armedId = null; runVerb(w.v); } });
  }
  function cancelArmed(keep) {
    for (const w of wires) if (w.b !== keep && w.b.hasAttribute('data-armed')) { w.off(); wire(w); }
    if (!keep) armedId = null;
  }

  function render(resetCursor) {
    if (!root) return;
    disarmAll();
    shown = ordered(input.value);
    if (resetCursor || cursor >= shown.length) cursor = preselect || input.value.trim() ? 0 : -1;
    listbox.replaceChildren(...shown.map((v, i) => row(v, i)));
    status.textContent = shown.length ? `${shown.length} command${shown.length === 1 ? '' : 's'}` : 'No matching command';
    mark();
  }

  function row(v, i) {
    const li = document.createElement('li');
    li.className = 'pal-row'; li.id = `${uid}-${i}`; li.setAttribute('role', 'option'); li.dataset.verb = v.id; li.dataset.danger = v.danger;
    li.setAttribute('aria-selected', 'false');
    const title = document.createElement('span'); title.className = 'pal-title'; title.textContent = v.title;
    const sec = document.createElement('span'); sec.className = 'pal-section'; sec.textContent = v.section;
    li.append(title, sec);
    if (v.hotkey) { const k = document.createElement('kbd'); k.className = 'pal-key'; k.textContent = v.hotkey; li.append(k); }
    if (v.danger === 'confirm') {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'pal-confirm'; b.tabIndex = -1; b.textContent = 'Confirm';
      b.setAttribute('aria-label', `Confirm ${v.title}`);
      const w = { b, v, off: null };
      wire(w); wires.push(w);
      b.addEventListener('click', () => { armedId = b.hasAttribute('data-armed') ? v.id : null; });
      li.append(b);
    }
    li.addEventListener('click', (e) => { move(i, e.target.closest('.pal-confirm')); if (!e.target.closest('.pal-confirm')) activate(); });
    return li;
  }

  function mark() {
    [...listbox.children].forEach((li, i) => {
      const on = i === cursor;
      li.setAttribute('aria-selected', String(on));
      li.classList.toggle('is-active', on);
    });
    const li = listbox.children[cursor];
    if (li) { input.setAttribute('aria-activedescendant', li.id); li.scrollIntoView({ block: 'nearest', behavior: reducedMotion() ? 'auto' : 'smooth' }); }
    else input.removeAttribute('aria-activedescendant');
  }

  function move(i, keep) {
    if (!shown.length) return;
    const n = (i + shown.length) % shown.length;
    if (n !== cursor) cancelArmed(keep);
    cursor = n;
    mark();
  }

  async function runVerb(v) {
    if (running) return;
    running = true;
    close();
    if (v.danger !== 'stop') remember(v.id);
    try { await v.run(context()); } catch (err) { console.error(`palette verb ${v.id} failed`, err); } finally { running = false; }
  }

  function activate() {
    const v = shown[cursor];
    if (!v) return;
    if (v.danger !== 'confirm') { runVerb(v); return; }
    listbox.children[cursor].querySelector('.pal-confirm').click();
  }

  function onBoxKey(e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); move(cursor + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(cursor < 0 ? shown.length - 1 : cursor - 1); }
    else if (e.key === 'Home' && !input.value) { e.preventDefault(); move(0); }
    else if (e.key === 'End' && !input.value) { e.preventDefault(); move(shown.length - 1); }
    else if (e.key === 'Enter') { e.preventDefault(); activate(); }
    else if (e.key === 'Tab') e.preventDefault();
    else if (e.key === 'Escape') {
      e.preventDefault(); e.stopPropagation();
      // confirm.js already disarmed on this Esc (capture phase); the first Esc only cancels the pending confirm
      if (armedId) render(false); else close();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); close(); }
  }

  function open() {
    if (!root) build();
    if (!root.hidden) return;
    opener = document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null;
    input.value = ''; cursor = preselect ? 0 : -1;
    root.hidden = false;
    render(true);
    input.focus();
  }

  function close() {
    if (!root || root.hidden) return;
    disarmAll();
    root.hidden = true;
    const back = opener; opener = null;
    if (back && back.isConnected) back.focus();
  }

  const isOpen = () => !!root && !root.hidden;
  const toggle = () => (isOpen() ? close() : open());

  const onDocKey = (e) => {
    if (!((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k')) return;
    if (isOpen()) return;
    if (e.target instanceof Element && e.target.closest(TYPING)) return;
    e.preventDefault();
    open();
  };
  document.addEventListener('keydown', onDocKey);
  const off = registry.onChange(() => { if (isOpen()) render(false); });

  return {
    open, close, toggle, isOpen,
    dispose() { close(); document.removeEventListener('keydown', onDocKey); off(); root?.remove(); root = null; },
  };
}
