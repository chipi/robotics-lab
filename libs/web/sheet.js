// A stylesheet that sits next to a module, linked the first time the module is used (a page that never opens the menu or the palette never asks for it).
const done = new Set();
export function needSheet(moduleUrl, file) {
  if (typeof document === 'undefined') return;
  const href = new URL(file, moduleUrl).href;
  if (done.has(href)) return;
  done.add(href);
  if ([...document.querySelectorAll('link[rel="stylesheet"]')].some((l) => l.href === href)) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet'; l.href = href;
  document.head.append(l);
}
