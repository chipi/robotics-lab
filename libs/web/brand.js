// The apps' names and addresses: step 5 renames the products by editing this one file.
// href is where the app lives behind the Observatory's one origin; on its own port Mission Control is at '/' (see hrefOf).
export const APPS = { control: { name: 'Mission Control', href: '/control/' }, observatory: { name: 'miniview', href: '/' } };

// The address of an app from the page it is shown on: a page under /control/ is Mission Control behind the Observatory, so Mission Control is at '/control/'
// and the Observatory at '/'. Any other page is an app on its own origin, where Mission Control is at '/'; a link to the other app is only meaningful behind the proxy.
export function hrefOf(key, path = location.pathname) {
  const behind = path === '/control' || path.startsWith('/control/');
  return key === 'control' ? (behind ? APPS.control.href : '/') : APPS.observatory.href;
}

// The top bar's two content slots. Mission Control keeps STOP as static HTML in the same bar, so this fills the brand and nav slots only and
// refuses (throws) a slot that is, holds or sits in a STOP element: it never renders, moves or hides STOP.
//   el: the bar, holding [data-slot="brand"] and [data-slot="nav"] (and, for the app to fill, [data-slot="theme"])
//   app: a key of APPS; nav: [{label, href, current?}]
//   themeControl: an element the caller hands over to go into the theme slot; left alone when absent
const STOP = '[data-stop], .stops';

function slot(el, name) {
  const s = el.querySelector(`[data-slot="${name}"]`);
  if (!s) throw new Error(`mountTopBar: no [data-slot="${name}"] in the bar`);
  if (s.closest(STOP) || s.querySelector(STOP)) throw new Error(`mountTopBar: the ${name} slot is, holds or sits in a STOP element`);
  return s;
}

export function mountTopBar(el, { app, nav = [], themeControl = null } = {}) {
  const a = Object.hasOwn(APPS, app) ? APPS[app] : null;
  if (!a) throw new Error(`mountTopBar: unknown app ${app}`);
  const brand = slot(el, 'brand'), navSlot = slot(el, 'nav'), theme = themeControl ? slot(el, 'theme') : null;
  if (themeControl && (themeControl.matches(STOP) || themeControl.querySelector(STOP) || themeControl.closest(STOP))) throw new Error('mountTopBar: the theme control is or holds STOP');

  const link = (text, href, cls) => {
    const x = document.createElement('a');
    x.href = href; x.textContent = text;
    if (cls) x.className = cls;
    return x;
  };
  const home = link('', hrefOf(app), 'ui-brand');
  const mark = document.createElement('span');
  mark.className = 'ui-brand-mark'; mark.setAttribute('aria-hidden', 'true');
  home.append(mark, a.name);
  brand.replaceChildren(home);
  navSlot.replaceChildren(...nav.map((n) => {
    const x = link(n.label, n.href);
    if (n.current) x.setAttribute('aria-current', 'page');
    return x;
  }));
  if (theme) theme.replaceChildren(themeControl);
  return { brand, nav: navSlot, theme: el.querySelector('[data-slot="theme"]') };
}
