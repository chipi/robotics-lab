// The command palette's opening, for both apps (look-and-feel U26): the palette module (and its stylesheet) load the first time it is asked for, by the
// button or Ctrl/Cmd+K, never by the page's first paint. Once loaded the palette binds its own Ctrl/Cmd+K and this one steps aside. This file is small and
// has no import, so a page may load it at start; its name has no "palette" in it because the phone page's test counts requests for one.
//
//   lazyOpen({ button, load, before, onError }) -> { open(), ensure(), get instance }
//     load()     returns (a promise of) the palette, e.g. import('./verbs.js').then((m) => m.mount(app)); a failure is told by onError and asked again next time
//     before()   awaited on every open, before load (Mission Control loads the layout module a robot page's verbs need)
//     onError(message)
// A key typed in a field is the field's: Ctrl/Cmd+K there opens nothing and loads nothing.
export const TYPING = 'input, textarea, select, [contenteditable=""], [contenteditable="true"]';

export function lazyOpen({ button, load, before, onError }) {
  let palette = null, busy = null;
  const ensure = () => (busy ||= Promise.resolve(load()).then((p) => { palette = p; return p; }).catch((e) => { busy = null; throw e; }));
  async function open() {
    try { await before?.(); (await ensure()).open(); } catch (e) { onError('The command palette could not be loaded: ' + e.message); }
  }
  button.addEventListener('click', open);
  document.addEventListener('keydown', (ev) => {
    if (palette || !(ev.ctrlKey || ev.metaKey) || ev.altKey || ev.shiftKey || ev.key.toLowerCase() !== 'k') return;
    if (ev.target instanceof Element && ev.target.closest(TYPING)) return;
    ev.preventDefault();
    open();
  });
  return { open, ensure, get instance() { return palette; } };
}
