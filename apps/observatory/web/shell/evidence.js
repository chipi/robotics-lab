// Evidence links (step 4.5, U17): a URL that opens a run at a moment, `#scene=<s>&run=<robot/scene/run>&view=3d&t=<s>&focus=robot`.
// `t` is the playhead in seconds and was the link between the two apps already; `focus=robot` asks the 3D camera to frame the robot at that
// moment (U12's fit). Any other `focus` value is ignored. Mission Control builds the same string (U24), so the format lives here and nowhere else.

export const FOCUS = ['robot'];

// the hash's moment: { t: seconds | null, focus: 'robot' | null }
export function parseMoment(hash) {
  const h = new URLSearchParams(String(hash).replace(/^#/, ''));
  const t = h.get('t'), f = h.get('focus');
  return { t: t !== null && t !== '' && Number.isFinite(+t) ? +t : null, focus: FOCUS.includes(f) ? f : null };
}

// loc = { origin, pathname }; the key order is fixed so a link reads the same wherever it was made
export function momentLink({ loc, scene, run, view, t, focus }) {
  const q = new URLSearchParams({ scene, run, view, t: String(+(+t).toFixed(3)) });
  if (FOCUS.includes(focus)) q.set('focus', focus);
  return `${loc.origin}${loc.pathname}#${q}`;
}

// the clipboard write may be refused (no permission, not a secure context): the caller shows what happened
export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (_) { return false; }
}
