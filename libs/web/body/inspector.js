// The model inspector (look-and-feel row 25): the body's parts as a list, each with its joint and the joint's value now, a state badge for a
// joint that is not ok. It draws no scene: onSelect hands the page the link, which calls body.highlight / body.isolate as it likes.
// Keyboard: the list takes focus; Up and Down move the cursor, Home and End jump, Enter (or Space) selects; a click selects too.
import { glyph, label } from '../status.js';

let sheet = false;
const needSheet = () => {
  if (sheet || typeof document === 'undefined') return;
  sheet = true;
  const l = document.createElement('link');
  l.rel = 'stylesheet'; l.href = new URL('./inspector.css', import.meta.url).href;
  document.head.append(l);
};

const plain = (v) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(3) : '–');

// `format(value, part)` -> the text of a joint's value (default: three decimals); `onSelect(link, part)`
export function mountInspector(el, body, { onSelect, format = plain } = {}) {
  needSheet();
  const parts = body.parts(), rows = new Map();
  const uid = 'insp' + Math.random().toString(36).slice(2, 7);
  const list = document.createElement('ul');
  list.className = 'insp-list'; list.setAttribute('role', 'listbox'); list.tabIndex = 0; list.setAttribute('aria-label', 'Parts of the model');
  let cursor = 0, picked = null;

  parts.forEach((p, i) => {
    const li = document.createElement('li');
    li.className = 'insp-row'; li.id = `${uid}-${i}`; li.setAttribute('role', 'option'); li.dataset.link = p.link;
    li.setAttribute('aria-selected', 'false');
    li.innerHTML = '<span class="insp-link"></span><span class="insp-joint"></span><span class="insp-value num"></span><span class="insp-state"></span>';
    li.children[0].textContent = p.link;
    li.children[1].textContent = p.joint ?? '';
    li.children[2].textContent = '–';
    li.addEventListener('click', () => { move(i); choose(i); list.focus(); });
    list.append(li);
    rows.set(p.link, li);
  });
  el.replaceChildren(list);

  function move(i) {
    if (!parts.length) return;
    cursor = Math.min(Math.max(i, 0), parts.length - 1);
    for (const [n, li] of rows) li.classList.toggle('insp-cursor', n === parts[cursor].link);
    const li = rows.get(parts[cursor].link);
    list.setAttribute('aria-activedescendant', li.id);
    li.scrollIntoView?.({ block: 'nearest' });
  }
  function mark(link) {
    picked = link;
    for (const [n, li] of rows) li.setAttribute('aria-selected', String(n === link));
  }
  function choose(i) {
    mark(parts[i].link);
    onSelect?.(parts[i].link, parts[i]);
  }
  list.addEventListener('keydown', (e) => {
    const step = { ArrowDown: () => move(cursor + 1), ArrowUp: () => move(cursor - 1), Home: () => move(0), End: () => move(parts.length - 1),
                   Enter: () => choose(cursor), ' ': () => choose(cursor) }[e.key];
    if (!step) return;
    e.preventDefault();
    step();
  });
  move(0);

  return {
    // joint values { joint: value } (the page's pose argument); the states are the body's own (health)
    update(values = {}) {
      const states = body.healthOf();
      for (const p of parts) {
        const li = rows.get(p.link);
        li.children[2].textContent = p.joint && p.type !== 'fixed' ? format(values[p.joint], p) : '–';
        const state = states[p.joint]?.state ?? 'ok', slot = li.children[3];
        if (state === 'ok') { slot.replaceChildren(); continue; }
        slot.innerHTML = '<span class="ui-badge"><span class="ui-glyph" aria-hidden="true"></span><span></span></span>';
        slot.firstChild.dataset.status = state;
        slot.firstChild.children[0].textContent = glyph(state);
        slot.firstChild.children[1].textContent = label(state);
      }
    },
    // programmatic: marks the link and moves the cursor to it; onSelect is for the user's choice, so it does not fire
    select(link) {
      const i = parts.findIndex((p) => p.link === link);
      if (i < 0) { mark(null); return; }
      move(i); mark(link);
    },
    selected: () => picked,
    dispose() { el.replaceChildren(); },
  };
}
