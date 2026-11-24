// Reduced motion for both apps. tokens.css zeroes --dur-* and sets --ease to linear when the system asks for reduced motion (unless the page
// chose full) or when data-motion="reduce"; this module is the page's switch and the JS side of the same rule.
const KEY = 'rl.motion';
const MODES = ['auto', 'reduce', 'full'];
const rootEl = () => document.documentElement;
const query = matchMedia('(prefers-reduced-motion: reduce)');
const listeners = new Set();

const stored = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
const store = (mode) => { try { localStorage.setItem(KEY, mode); } catch { /* private mode or blocked storage: the choice lasts for this page only */ } };

export function reducedMotion() {
  const m = rootEl().dataset.motion;
  return m === 'reduce' || (m !== 'full' && query.matches);
}

// a duration token ('--dur-base', 'dur-base' or 'base') in milliseconds, as the page resolves it now
export function ms(token) {
  const name = token.startsWith('--') ? token : token.startsWith('dur-') ? `--${token}` : `--dur-${token}`;
  const v = getComputedStyle(rootEl()).getPropertyValue(name).trim();
  const n = parseFloat(v);
  if (!Number.isFinite(n)) return 0;
  return v.endsWith('ms') ? n : n * 1000;
}

const emit = () => { const r = reducedMotion(); for (const fn of [...listeners]) fn(r); };

export function setMotion(mode) {
  if (!MODES.includes(mode)) throw new RangeError(`setMotion: ${mode} is not one of ${MODES.join(', ')}`);
  if (mode === 'auto') rootEl().removeAttribute('data-motion'); else rootEl().dataset.motion = mode;
  store(mode);
  emit();
}

// fn(reduced) runs when the choice or the system's setting changes; the return value stops it
export function onChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

query.addEventListener('change', () => { if (!rootEl().dataset.motion) emit(); });

// a choice made on an earlier visit applies when the first page script imports this module
{
  const s = stored();
  if (s === 'reduce' || s === 'full') rootEl().dataset.motion = s;
}
