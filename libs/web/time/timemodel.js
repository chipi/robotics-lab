// The time of a run, as one pure state machine: no DOM, no clock, no app state. The caller feeds it wall time (tick) and the run's range
// (setRange) and reads `state`. Times are run seconds.
//
// Live: the model follows the run's edge (t1). Only a model created with mode 'live' can ever be live (`canLive`); a model created as
// 'replay' is a finished run, and goLive() on it does nothing and says so (returns false, canLive stays false). finish() is how a growing
// run ends: it clears canLive and leaves live mode where the viewer is.
// Seeking away from the edge leaves live for replay; `behind_s` is how far the viewer is behind the edge (0 unless canLive).
export const SPEEDS = [0.25, 0.5, 1, 2, 4, 8];
const EPS = 1e-6;      // the shell's own tolerance for "at the same time"

export function createTimeModel({ mode = 'replay', t0 = 0, t1 = 0, playing = false, speed = 1, loop = false } = {}) {
  if (!Number.isFinite(t0) || !Number.isFinite(t1) || t1 < t0) throw new Error(`bad time range [${t0}, ${t1}]`);
  let canLive = mode === 'live';
  const s = { mode: canLive ? 'live' : 'replay', t: canLive ? t1 : t0, t0, t1, playing: !!playing, speed: SPEEDS.includes(speed) ? speed : 1, loop: !!loop };
  const listeners = new Set();
  const clamp = (v) => Math.min(s.t1, Math.max(s.t0, v));
  const view = () => ({ ...s, canLive, atEdge: s.t >= s.t1 - EPS, behind_s: canLive ? Math.max(0, s.t1 - s.t) : 0 });

  // one change event per call that changed the state, never one per field
  const change = (fn) => {
    const before = JSON.stringify(view());
    const out = fn();
    const after = view();
    if (JSON.stringify(after) !== before) for (const l of [...listeners]) l(after);
    return out;
  };

  const seek = (t, { source } = {}) => change(() => {
    if (!Number.isFinite(+t)) return s.t;
    s.t = clamp(+t);
    // the follow itself ("following") and a seek to the edge keep live; any other seek away from the edge leaves it
    if (s.mode === 'live' && source !== 'follow' && s.t < s.t1 - EPS) s.mode = 'replay';
    return s.t;
  });

  return {
    get state() { return view(); },
    seek,
    // dtWall in wall seconds; live follows the edge and has nothing to advance
    tick(dtWall) {
      return change(() => {
        if (s.mode === 'live' || !s.playing || !(dtWall > 0)) return s.t;
        let t = s.t + dtWall * s.speed;
        if (t >= s.t1) {
          const span = s.t1 - s.t0;
          if (s.loop && span > 0) t = s.t0 + ((t - s.t1) % span);
          else { t = s.t1; s.playing = false; }
        }
        s.t = t;
        return s.t;
      });
    },
    play() {
      change(() => {
        if (s.mode === 'live') { s.playing = true; return; }
        if (s.t >= s.t1 - EPS) s.t = s.t0;       // play at the end starts over, as the shell does
        s.playing = true;
      });
    },
    pause() { change(() => { s.playing = false; }); },
    // a speed outside SPEEDS is refused (false), not snapped: the caller picks from the list
    setSpeed(v) {
      if (!SPEEDS.includes(v)) return false;
      change(() => { s.speed = v; });
      return true;
    },
    setLoop(on) { change(() => { s.loop = !!on; }); },
    // the run grew (or was laid out): live follows the new edge, replay keeps its time and falls further behind
    setRange(t0, t1) {
      if (!Number.isFinite(t0) || !Number.isFinite(t1) || t1 < t0) throw new Error(`bad time range [${t0}, ${t1}]`);
      change(() => {
        s.t0 = t0; s.t1 = t1;
        s.t = s.mode === 'live' ? t1 : clamp(s.t);
      });
    },
    // back to following the edge; false (and nothing changes) when the run cannot be live
    goLive() {
      if (!canLive) return false;
      change(() => { s.mode = 'live'; s.t = s.t1; });
      return true;
    },
    // the growing run ended: it can no longer be live; the time stays where it is
    finish() { change(() => { canLive = false; s.mode = 'replay'; }); },
    // marks: [{t, kind}]; dir > 0 (or 'next') the first mark after now, dir < 0 (or 'prev') the last one before; with `kind`, only that kind.
    // At the ends it stays. Returns the time after the jump.
    jump(marks, dir, kind) {
      const fwd = dir === 'next' || dir > 0;
      const ts = (marks || []).filter((m) => (kind === undefined || kind === null || m.kind === kind) && m.t >= s.t0 && m.t <= s.t1).map((m) => m.t);
      const t = fwd ? Math.min(...ts.filter((x) => x > s.t + EPS)) : Math.max(...ts.filter((x) => x < s.t - EPS));
      return Number.isFinite(t) ? seek(t, { source: 'jump' }) : s.t;
    },
    on(name, fn) {
      if (name !== 'change') throw new Error(`unknown event ${name}`);
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}
