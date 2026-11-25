// The robot page's readiness card (look-and-feel U23): named checks, each computed from a field GET /robots/{id} already carries, so no new route.
// A field the view does not carry reads "unknown", never ok: an absent value is not a pass. Loaded by app.js the first time a robot page opens, so
// the phone overview (the page's first load) does not fetch it. Pure apart from paint(), which builds the card from what app.js hands it.

// The server raises low_battery (major) under 20 % (nxt.py), so the same line is an error here; a threshold of the card's own comes with B2.
const LOW_BATTERY_PCT = 20;
const has = (v) => v !== undefined;
const row = (id, what, status, val) => ({ id, what, status, val });

// r: the robot view; fit: app.js's fitChecks(r), for the alarm window it already counts. Returns one check per named requirement, in the card's order.
export function checks(r, fit = []) {
  const l = r.lock, st = r.status;
  const out = [];
  out.push(!has(r.online) ? row('online', 'Online', 'unknown', 'the robot view does not say')
    : r.online ? row('online', 'Online', 'ok', 'answering')
    : row('online', 'Online', 'error', r.last_seen_age_s != null ? `offline: it has not answered for ${r.last_seen_age_s} s` : 'offline: it has not answered yet'));
  out.push(!l ? row('gate', 'Its gate answers', 'unknown', 'no lock in the robot view')
    : l.unreachable ? row('gate', 'Its gate answers', 'error', 'its gate does not answer') : row('gate', 'Its gate answers', 'ok', 'answers'));
  out.push(!l || l.unreachable ? row('free', 'Nobody holds it', 'unknown', 'not known')
    : l.holder ? row('free', 'Nobody holds it', 'warn', `held by ${l.holder}${r.goal_run != null ? `: goal run #${r.goal_run}` : ''}`) : row('free', 'Nobody holds it', 'ok', 'free'));
  out.push(!st || st.link == null ? row('link', 'Link to the robot', 'unknown', 'its status carries no link')
    : row('link', 'Link to the robot', 'ok', String(st.link)));
  out.push(!st || typeof st.battery_pct !== 'number' ? row('battery', `Battery at least ${LOW_BATTERY_PCT} %`, 'unknown', 'it reports no battery')
    : st.battery_pct < LOW_BATTERY_PCT ? row('battery', `Battery at least ${LOW_BATTERY_PCT} %`, 'error', `${Math.round(st.battery_pct)} %`)
    : row('battery', `Battery at least ${LOW_BATTERY_PCT} %`, 'ok', `${Math.round(st.battery_pct)} %`));
  const set = st && st.flags ? Object.entries(st.flags).filter(([, v]) => v).map(([k]) => k) : null;
  out.push(!set ? row('flags', 'No status flag set', 'unknown', 'its status carries no flags')
    : set.length ? row('flags', 'No status flag set', 'error', set.join(', ')) : row('flags', 'No status flag set', 'ok', 'none'));
  const alarm = fit.find((c) => c.id === 'alarms');
  out.push(!has(r.alarms) || !alarm ? row('alarms', 'No major or critical alarm in the last 60 s', 'unknown', 'the robot view carries no alarms')
    : alarm.ok === false ? row('alarms', 'No major or critical alarm in the last 60 s', 'error', alarm.val) : row('alarms', 'No major or critical alarm in the last 60 s', 'ok', 'none'));
  out.push(!Array.isArray(r.guardrails) ? row('guardrails', 'Guardrails declared', 'unknown', 'the robot view carries none')
    : r.guardrails.length ? row('guardrails', 'Guardrails declared', 'ok', `${r.guardrails.length} must-not rule${r.guardrails.length === 1 ? '' : 's'}`)
    : row('guardrails', 'Guardrails declared', 'warn', 'none declared'));
  out.push(!has(r.profile) ? row('profile', 'Settings known', 'unknown', 'the robot view carries no profile')
    : r.profile === null ? row('profile', 'Settings known', 'neutral', "the robot's own file")
    : row('profile', 'Settings known', 'ok', r.profile.version != null ? `version ${r.profile.version}, ${r.profile.variant} variant` : `the robot's own file, ${r.profile.variant} variant`));
  return out;
}

// The verdict: the worst check decides; any unknown with nothing worse says so instead of "ready".
const ORDER = ['error', 'warn', 'unknown'];
const WORD = { ok: 'ready', warn: 'check first', error: 'not ready', unknown: 'not known' };
export function overall(list) {
  const status = ORDER.find((s) => list.some((c) => c.status === s)) || 'ok';
  return { status, word: WORD[status], passed: list.filter((c) => c.status === 'ok' || c.status === 'neutral').length, of: list.length };
}

// host, sum: the card's body and its head's count; h, badge: app.js's element builder and status badge (badge(status, word, attrs, wordAttrs));
// label(status): the status's own word, status.js's when it loaded
export function paint({ host, sum, list, h, badge, label }) {
  const v = overall(list);
  sum.textContent = `${v.passed} of ${v.of}`;
  sum.className = 'sum ' + (v.status === 'ok' ? 'ok' : v.status === 'error' ? 'bad' : '');
  host.replaceChildren(
    h('div', { class: 'readyhead' }, badge(v.status, v.word, { id: 'readiness-overall' }), h('span', { class: 'faint' }, 'from what the robot reports; an unknown is not a pass')),
    h('ul', { id: 'readiness-checks', class: 'checks' }, list.map((c) => h('li', { 'data-check': c.id, 'data-status': c.status },
      badge(c.status, label(c.status), { class: 'ui-badge ready-badge' }), h('span', { class: 'what' }, c.what), h('span', { class: 'val' }, c.val)))));
}
