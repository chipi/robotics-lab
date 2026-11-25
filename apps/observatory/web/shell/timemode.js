// The Observatory's time as a named mode (step 4.5, U14): Live (the viewer follows the edge of a run still being written) or Replay (anywhere
// else, and every finished run), how far behind the edge the viewer is, the way back to live, and jumps between event marks by kind.
// The shell owns `M.t` and draws; this module mirrors M.t into libs/web/time/timemodel.js (the one time model), which says the mode and
// the gap, and paints the mode control. Live and Replay are the Observatory's only (RFC-0023 D1: Mission Control is now, a run is replayed here).
import { createTimeModel } from '/lib/time/timemodel.js';
import { glyph } from '/lib/status.js';

const LEAVE = 1e-5;       // how far short of the edge "stay here, stop following" parks the model; the model leaves live only by a seek away from the edge

// el = the #timemode element, jumps = the jump controls' (shown while a run is open); goLive() = what the Return to live button does; marks() = [{t, kind}] of the events a jump may land on
export function createTimeMode({ el, jumps, goLive, marks }) {
  let tm = null, kind = '', off = null;
  const $ = (sel) => el.querySelector(sel);

  const word = (status, text) => `<span class="ui-badge" data-status="${status}"><span class="ui-glyph" aria-hidden="true">${glyph(status)}</span><span class="ui-word">${text}</span></span>`;
  function paint() {
    jumps.hidden = !tm;
    if (!tm) { el.hidden = true; return; }
    const s = tm.state, live = s.mode === 'live';
    el.hidden = false;
    el.dataset.mode = s.mode;
    $('#tm-badge').innerHTML = live ? word('live', 'Live') : word('neutral', 'Replay');
    const gap = s.canLive && !live ? s.behind_s : 0;
    $('#tm-behind').textContent = gap > 0.005 ? `${gap.toFixed(1)} s behind` : '';
    $('#tm-golive').hidden = !(s.canLive && !live);
  }

  const api = {
    // a run opened: Live when it is still being written. `t` is where the shell put the playhead
    open(run, t) {
      off?.();
      tm = createTimeModel({ mode: run.status === 'live' ? 'live' : 'replay', t0: run.t0, t1: run.t1 });
      off = tm.on('change', paint);
      api.seen(t, run.status === 'live' && t >= run.t1 - 1e-6);
      paint();
    },
    close() { off?.(); off = tm = null; paint(); },
    // the run grew (or ended); `t` is the shell's playhead, which a following shell has already moved to the edge
    range(run, t, following) {
      if (!tm) return;
      tm.setRange(run.t0, run.t1);
      if (run.status !== 'live') tm.finish();
      api.seen(t, following);
    },
    // the shell's playhead is at t; following = it got there by following the edge, not by the viewer's doing
    seen(t, following) {
      if (!tm) return;
      tm.seek(t, { source: following ? 'follow' : 'user' });
      if (!following && tm.state.mode === 'live') api.follow(false);
    },
    // the Follow live switch: on is the way back to live, off parks the viewer where they are
    follow(on) {
      if (!tm) return;
      if (on) tm.goLive();
      else if (tm.state.mode === 'live') tm.seek(Math.max(tm.state.t0, tm.state.t1 - LEAVE), { source: 'user' });
    },
    // the time of the next (dir > 0) or previous mark, of `k` (default: the chosen kind, '' = any); t stays when there is none
    jump(t, dir, k = kind) {
      if (!tm) return t;
      tm.seek(t, { source: 'follow' });
      return tm.jump(marks(), dir, k || undefined);
    },
    get kind() { return kind; },
    set kind(k) { kind = k || ''; },
    get state() { return tm ? tm.state : null; },
    // the part of the script's state about time
    out() {
      const s = tm?.state;
      return s ? { mode: s.mode, can_live: s.canLive, behind_s: s.canLive ? +s.behind_s.toFixed(2) : 0 } : null;
    },
  };
  $('#tm-golive').onclick = () => goLive();
  return api;
}
