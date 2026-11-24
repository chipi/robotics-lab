// The one status vocabulary of both apps (ADR-0021). A status is never colour alone: each one has a glyph that reads without colour,
// a word, and the three colours tokens.css defines (--status-<name>, -soft, -on). ui.css draws the badge from [data-status].
//
// Glyphs (aria-hidden next to the word; every shape differs, so a colour-blind reader and a grey screenshot still tell them apart):
//   ok      check mark       info    letter i       warn    triangle     alert   diamond      error   cross
//   unknown question mark    stale   quarter clock  neutral dash         live    filled dot (ui.css pulses it; still under reduced motion)
export const STATUS = ['ok', 'info', 'warn', 'alert', 'error', 'unknown', 'stale', 'neutral', 'live'];

const GLYPH = { ok: '✓', info: 'ℹ', warn: '▲', alert: '◆', error: '✕', unknown: '?', stale: '◔', neutral: '–', live: '●' };
const LABEL = { ok: 'ok', info: 'info', warn: 'warning', alert: 'alert', error: 'error', unknown: 'unknown', stale: 'stale', neutral: 'neutral', live: 'live' };

const table = (o) => {
  const m = new Map();
  for (const [status, values] of Object.entries(o)) for (const v of values.split(' ')) m.set(v, status);
  return m;
};

// A run's verdict and a goal's state share one vocabulary, so one table (the operator's decision of 2026-11-24: a correct end is neutral, colour
// only for a problem). Today's Mission Control colours every goal state but running, queued, reached and done as a warning; this table splits
// those by how bad they are.
const VERDICT = table({
  ok: 'reached done evaluated',
  info: 'running queued',
  neutral: 'ended no_frontier_left cancelled refused not_found',
  warn: 'timeout stalled',
  alert: 'stopped_by_guardrail trapped',
  error: 'failed interrupted',
});

// What each other kind maps to, and the code it was read from:
//   severity   critical, major -> error; minor -> warn; info -> neutral          shell.js SEVERITY (error, error, warn, text-dim)
//   event      cliff_stop -> error; reflex_stop, trapped -> alert; refused -> warn; reached -> ok;
//              tight_pivot, leg, no_survey_turn -> neutral                        shell.js KINDS (red, orange/pink-red, amber, green, the rest)
//              the other event kinds are unknown; an anomaly event takes its severity (kind 'severity'), not a status of its own
//   conn       live -> live; reconnecting, lost, offline -> error; online -> ok  app.js connect() (live is the green chip, reconnecting the red one)
const KINDS = {
  verdict: VERDICT,
  goal_state: VERDICT,
  severity: table({ error: 'critical major', warn: 'minor', neutral: 'info' }),
  event: table({ error: 'cliff_stop', alert: 'reflex_stop trapped', warn: 'refused', ok: 'reached', neutral: 'tight_pivot leg no_survey_turn' }),
  conn: table({ live: 'live', error: 'reconnecting lost offline', ok: 'online' }),
};

export function statusOf(kind, value) {
  const t = Object.hasOwn(KINDS, kind) ? KINDS[kind] : null;
  return (t && typeof value === 'string' && t.get(value)) || 'unknown';
}

export const statusVar = (status) => `var(--status-${STATUS.includes(status) ? status : 'unknown'})`;
export const glyph = (status) => GLYPH[STATUS.includes(status) ? status : 'unknown'];
export const label = (status) => LABEL[STATUS.includes(status) ? status : 'unknown'];
