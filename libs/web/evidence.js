// Evidence links (step 4.5, U17 and U24): a URL that opens a run at a moment, `#scene=<s>&run=<robot/scene/run>&view=3d&t=<s>&focus=robot`.
// `t` is the playhead in seconds and was the link between the two apps already; `focus=robot` asks the 3D camera to frame the robot at that
// moment (U12's fit). Any other `focus` value is ignored. The Observatory makes and reads the link, Mission Control makes it, so the format
// lives here and nowhere else: both apps serve this file at /lib/evidence.js. Pure, but for copyText's clipboard.

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

// The Observatory's 3D page at a moment of one run, from another page: origin is the Observatory's, runKey is `<robot>/<scene>/<run>` (a goal
// run's run_key). No time reads as the run's start; a key that is not three parts makes no link (null) rather than a wrong one.
export function evidenceHref({ origin, runKey, t, focus = 'robot' }) {
  const parts = typeof runKey === 'string' ? runKey.split('/') : [];
  if (parts.length !== 3 || !parts.every(Boolean)) return null;
  const at = Number.isFinite(+t) && t !== null && t !== '' ? +t : 0;
  return momentLink({ loc: { origin, pathname: '/web/three/' }, scene: parts[1], run: runKey, view: '3d', t: Math.max(0, at), focus });
}

// the clipboard write may be refused (no permission, not a secure context): the caller shows what happened
export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (_) { return false; }
}
