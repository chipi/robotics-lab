// Two-press confirm for a dangerous button that is not STOP. STOP is one tap, never confirmed, so arm() refuses it.
// arm(button, {ms, armedLabel, onConfirm}) installs the behaviour and returns a function that disarms and removes it.
// Style lives in confirm.css (button[data-armed]); the page links it.
const STOP_SELECTOR = '[data-stop], .stops';
let live = null;

// one polite region for every armed button, so the screen reader hears the changed label
function announce(text) {
  if (!live || !live.isConnected) {
    live = document.createElement('div');
    live.setAttribute('role', 'status');
    live.setAttribute('aria-live', 'polite');
    live.className = 'ui-confirm-live';
    document.body.append(live);
  }
  live.textContent = text;
}

export function arm(button, { ms = 6000, armedLabel = 'Press again to confirm', onConfirm } = {}) {
  if (button.closest(STOP_SELECTOR)) throw new Error('confirm.arm: STOP is never confirmed (the button is or is inside [data-stop] / .stops)');
  if (typeof onConfirm !== 'function') throw new TypeError('confirm.arm: onConfirm must be a function');
  let timer = null;
  let saved = null;

  const disarm = () => {
    if (!saved) return;
    clearTimeout(timer);
    timer = null;
    document.removeEventListener('keydown', onKey, true);
    button.replaceChildren(...saved);
    saved = null;
    button.removeAttribute('data-armed');
    announce('');
  };
  const onKey = (e) => { if (e.key === 'Escape') disarm(); };
  const onClick = () => {
    if (!saved) {
      saved = [...button.childNodes];
      button.replaceChildren(armedLabel);
      button.setAttribute('data-armed', '');
      document.addEventListener('keydown', onKey, true);
      timer = setTimeout(disarm, ms);
      announce(armedLabel);
      return;
    }
    disarm();
    onConfirm();
  };

  button.addEventListener('click', onClick);
  button.addEventListener('blur', disarm);
  return () => {
    disarm();
    button.removeEventListener('click', onClick);
    button.removeEventListener('blur', disarm);
  };
}
