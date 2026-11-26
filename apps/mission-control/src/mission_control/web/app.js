"use strict";
/* Mission Control's page (RFC-0014 step 1). Plain JS, no build, no library. Everything it does is a call of the API
   in CONTRACT.md and the event stream; nothing works only here. Data goes into the page by textContent, never as HTML. */

const API = "api/v1";       // relative: the page is served at / by Mission Control and at /control/ behind the Observatory (RFC-0024 step 3)
const $ = (id) => document.getElementById(id);
const TERMINAL = ["reached", "done", "refused", "not_found", "timeout", "stalled", "stopped_by_guardrail", "cancelled", "interrupted", "failed"];   // the navigator contract's ends (runfile.navcontract)

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}

const S = {
  robots: [], robot: null, sites: [], site: null, objects: [], areas: [], map: null, goals: [], runs: [], run: null,
  mode: "point", draft: [], target: null, ready: false, es: null, lastConn: null, token: null, open: {},
};

// The shared kit (libs/web) loads after the page works and on its own: a module that fails to load leaves the static page, STOP and STOP ALL included,
// exactly as it is, and each use below falls back to plain text.
const KIT = {};
function loadKit() {
  const one = (key, url) => import(url).then((m) => { KIT[key] = m; }).catch((e) => { KIT[key + "Error"] = e.message; });
  return Promise.all([one("status", "/lib/status.js"), one("brand", "/lib/brand.js"), one("motion", "/lib/motion.js"), one("lazy", "/lib/lazy.js")]).then(() => { if (KIT.lazy) wirePalette(); paintKit(); });
}

// A freshness check with the signature of libs/web/time/freshness.js (U6, built at the same time): replace this with an import of it.
const freshness = (ageS, { staleAfterS = 5, offlineAfterS = 30 } = {}) => (ageS == null || ageS >= offlineAfterS ? "offline" : ageS >= staleAfterS ? "stale" : "fresh");

async function api(method, path, body) {
  const headers = { ...(body === undefined ? {} : { "Content-Type": "application/json" }), ...(S.token ? { Authorization: "Bearer " + S.token } : {}) };
  const res = await fetch(API + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await res.json();
  if (!j.ok) {
    if (res.status === 401) $("tokenbox").hidden = false;          // this server wants a token (RFC-0014 section 3.9); STOP never does
    const e = new Error(j.error.message); e.code = j.error.code; e.data = j.error; throw e;
  }
  return j;
}

function setKids(el, ...kids) { el.replaceChildren(...kids.flat().filter((k) => k != null && k !== false)); }

const ICONS = {
  check: "M5 12.5l4.5 4.5L19 7.5", x: "M6 6l12 12|M18 6L6 18", dot: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z", chev: "M9 6l6 6-6 6",
  lock: "M7 11h10a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2z|M8 11V7a4 4 0 0 1 8 0v4",
  pencil: "M4 20h4L19 9l-4-4L4 16v4z", history: "M3 12a9 9 0 1 0 3-6.7L3 8|M3 3v5h5M12 7v5l3 2", close: "M6 6l12 12|M18 6L6 18",
};
function icon(name, cls) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); s.setAttribute("class", "ico " + (cls || ""));
  for (const d of ICONS[name].split("|")) { const p = document.createElementNS("http://www.w3.org/2000/svg", "path"); p.setAttribute("d", d); s.append(p); }
  return s;
}

// Rebuild what is inside `box`, and give the focus back to the control that had it (the one with the same data-fk): the page repaints on every
// event, and a keyboard user must not lose their place to it.
function keepFocus(box, build) {
  const a = document.activeElement, key = a && box.contains(a) ? a.dataset.fk : null;
  build();
  if (key) { const again = [...box.querySelectorAll("[data-fk]")].find((e) => e.dataset.fk === key); if (again) again.focus(); }
}

// A collapsible section built by script: a head button (aria-expanded, aria-controls) and its body. What the user opened or closed is in S.open,
// so a repaint keeps it. The static sections of index.html are opened and closed in place by the same click handler.
function fold(key, dflt, headKids, body, cls) {
  const open = S.open[key] ?? dflt, id = "fold-" + key.replace(/[^\w-]/g, "-");
  body.id = id; body.hidden = !open;
  return [h("button", { class: "shead " + (cls || ""), type: "button", "data-collapse": key, "data-fk": "fold:" + key, "aria-expanded": String(open), "aria-controls": id }, icon("chev", "chev"), headKids), body];
}

let toastTimer = null;
function toast(msg, err) {
  const t = $("toast");
  t.textContent = msg; t.className = err ? "err" : ""; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, err ? 7000 : 3500);
}
// The one answer to "is the Observatory this page's own origin" (Mission Control is served at /control/ there): the top bar, the evidence links and the
// palette's Observatory verb all ask it.
const behindObservatory = () => location.pathname === "/control" || location.pathname.startsWith("/control/");
const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };

// A dangerous action that is not STOP needs a second press (libs/web/confirm.js, U8). The module and its style load on the first press, so the
// phone overview fetches neither. A press that cannot load them does nothing: the safe side. STOP, STOP ALL and the alarm's stop never come here.
let confirmLoad = null;
function loadConfirm() {
  confirmLoad ||= Promise.all([import("/lib/confirm.js"), new Promise((ok, no) => {
    const l = h("link", { rel: "stylesheet", href: "/lib/confirm.css" });
    l.onload = ok; l.onerror = () => no(new Error("confirm.css")); document.head.append(l);
  })]).then(([m]) => m).catch((e) => { confirmLoad = null; throw e; });
  return confirmLoad;
}
function dangerous(button, onConfirm, armedLabel = "Sure?") {
  button._dangerous = true;
  const first = guard(async () => {
    button.removeEventListener("click", first);
    let m;
    try { m = await loadConfirm(); }
    catch (e) { button.addEventListener("click", first); throw new Error("The confirm step could not be loaded, so nothing was done."); }
    m.arm(button, { ms: 6000, armedLabel, onConfirm: guard(onConfirm) });
    button.click();                   // this press is the first of the two: it arms
  });
  button.addEventListener("click", first);
  return button;
}

// --- status badges and freshness (ADR-0021) ----------------------------------------------------------------
function badge(status, word, attrs, wordAttrs) {
  const g = KIT.status ? KIT.status.glyph(status) : "";
  return h("span", { class: "ui-badge", "data-status": status, ...attrs }, h("span", { class: "ui-glyph", "aria-hidden": "true" }, g), h("span", wordAttrs, word));
}
// a goal's or run's state: glyph, word and status colour; the id is on the word, so its text is the state alone
function stateBadge(state, id) {
  if (!KIT.status) return h("span", { class: "state " + state, id }, state);
  return badge(KIT.status.statusOf("goal_state", state), state, { class: "ui-badge state", "data-state": state }, { id });
}

// How old a robot's state is. A state event stamps it; a load of the robot stamps it with the age the server read it at (last_seen_age_s).
const stamp = (r, prev) => { r.state_at = Math.max(prev || 0, r.last_seen_age_s == null ? 0 : Date.now() - r.last_seen_age_s * 1000) || null; };
const ageS = (r) => (r.state_at == null ? null : Math.max(0, (Date.now() - r.state_at) / 1000));
const freshOf = (r) => (r.online === false ? "offline" : freshness(ageS(r)));
function ageText(r) {
  const a = ageS(r), st = freshOf(r) === "offline" ? "offline" : "stale", g = KIT.status ? KIT.status.glyph(st) : "";
  const how = a == null ? "no state yet" : a < 90 ? `${Math.round(a)} s old` : `${Math.round(a / 60)} min old`;
  return `${g} ${st}, ${how}`.trim();
}
// the dimmed values of a robot whose state is old, and the one age that says how old
const dimOf = (r) => (freshOf(r) === "fresh" ? "" : "ui-stale-value");
const ageEl = (r) => (freshOf(r) === "fresh" ? null : h("span", { class: "ui-stale-age", "data-age": r.id, "data-status": freshOf(r) }, ageText(r)));

// Actions that need a fresh state of the robot are disabled with the reason beside them. STOP, STOP ALL and the alarm panel's stop are never
// among them: nothing here touches them (they are static HTML, and a stale or silent robot is exactly when STOP is needed).
function applyFreshness() {
  const r = robot(), fr = r ? freshOf(r) : "fresh";
  const why = fr === "fresh" ? "" : `${r.id}'s state is ${fr === "offline" ? "missing" : "stale"}, so a goal cannot start until it is fresh. STOP still works.`;
  for (const b of document.querySelectorAll("[data-needs-fresh]")) { b.disabled = !!why; if (why) b.title = why; else b.removeAttribute("title"); }
  const note = $("goal-fresh");
  note.hidden = !why; if (note.textContent !== why) note.textContent = why;
}
function tickFreshness() {
  let changed = false;
  for (const r of S.robots) { const f = freshOf(r); if (r.fresh_seen !== f) changed = true; }
  if (changed) { renderRobots(); return; }
  for (const el of document.querySelectorAll("[data-age]")) { const r = S.robots.find((x) => x.id === el.dataset.age); if (r) el.textContent = ageText(r); }
  applyFreshness();
}
setInterval(tickFreshness, 1000);

// the connection chip: live is yellow with the live dot; reconnecting reads as an error (status.js, kind conn)
function paintConn() {
  const w = S.conn || "connecting", st = KIT.status ? KIT.status.statusOf("conn", w) : "unknown", box = $("connbox");
  $("conn").textContent = w; box.dataset.status = st;
  box.firstElementChild.textContent = KIT.status ? KIT.status.glyph(st) : "";
}
// the top bar's brand and nav slots; STOP, the chips and the theme button are the page's own markup and are not touched
function paintBar() {
  if (!KIT.brand) return;
  const nav = [{ label: "Robots", href: "#", current: !route() }];
  if (behindObservatory()) nav.unshift({ label: KIT.brand.APPS.observatory.name, href: KIT.brand.APPS.observatory.href });
  try { KIT.brand.mountTopBar(document.querySelector("header.top"), { app: "control", nav }); } catch (e) { KIT.brandError = e.message; }   // the static bar stays
}
function paintKit() { paintBar(); paintConn(); renderRuns(); renderRunDetail(); renderRobots(); }

// --- theme -----------------------------------------------------------------------------------------------
function effectiveTheme() {
  return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
}
// rl.theme is the key both apps share; mc-theme is the old one, read once when rl.theme is not there yet and not written again
try {
  const t = localStorage.getItem("rl.theme") || localStorage.getItem("mc-theme");
  if (t) { document.documentElement.dataset.theme = t; if (!localStorage.getItem("rl.theme")) localStorage.setItem("rl.theme", t); }
} catch (e) { /* storage may be off */ }
try { S.token = localStorage.getItem("mc-token") || null; } catch (e) { /* storage may be off */ }
$("theme").addEventListener("click", () => {
  const next = effectiveTheme() === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("rl.theme", next); } catch (e) { /* ignore */ }
  requestDraw();
});

// --- loading ---------------------------------------------------------------------------------------------
const robot = () => S.robots.find((r) => r.id === S.robot) || null;

async function loadRobots() {
  const list = (await api("GET", "/robots")).robots, before = new Map(S.robots.map((r) => [r.id, r.state_at]));
  S.robots = await Promise.all(list.map(async (r) => (await api("GET", "/robots/" + r.id)).robot));
  S.robots.forEach(seedAlarms);
  const now = Date.now();
  for (const r of S.robots) { r.lock_at = now; stamp(r, before.get(r.id)); }
  if (!robot() && S.robots.length) await selectRobot(S.robots[0].id, true);
  renderRobots();
}

async function refreshRobot(id) {
  const i = S.robots.findIndex((r) => r.id === id);
  if (i < 0) return loadRobots();
  const prev = S.robots[i].state_at;
  S.robots[i] = (await api("GET", "/robots/" + id)).robot;
  seedAlarms(S.robots[i]);
  S.robots[i].lock_at = Date.now();
  stamp(S.robots[i], prev);
  renderRobots();
  if (id === S.robot && S.robots[i].site !== S.site) await loadSite();
}

async function selectRobot(id, quiet) {
  S.robot = id;
  S.runs = []; S.run = null;
  const r = robot();
  S.site = r ? r.site : null;
  S.map = null;
  if (r && r.capabilities.map) { try { S.map = (await api("GET", `/robots/${id}/map`)).map; } catch (e) { S.map = null; } }
  await Promise.all([loadSite(), loadRuns()]);
  if (!quiet) renderRobots();
  renderAll();
}

async function loadSites() { S.sites = (await api("GET", "/sites")).sites; renderSites(); }

async function loadSite() {
  if (S.site) {
    [S.objects, S.areas] = await Promise.all([api("GET", `/sites/${S.site}/objects`).then((j) => j.objects),
                                              api("GET", `/sites/${S.site}/areas`).then((j) => j.areas)]);
  } else { S.objects = []; S.areas = []; }
  renderSites(); renderAreas(); renderGoalFields(); requestDraw();
}

async function loadGoals() { S.goals = (await api("GET", "/goals")).goals; renderLibrary(); }

async function loadRuns() {
  if (!S.robot) return;
  S.runs = (await api("GET", `/goal-runs?robot=${S.robot}`)).runs.slice(0, 8);
  if (!S.run) { const live = S.runs.find((r) => !TERMINAL.includes(r.state)); S.run = (live || S.runs[0] || {}).id || null; }
  renderRuns();
  if (S.run) await loadRunDetail(S.run);
}

let detail = null;
async function loadRunDetail(id) {
  detail = (await api("GET", "/goal-runs/" + id)).run;
  renderRunDetail();
}

// --- robots ----------------------------------------------------------------------------------------------
function lockText(r) { return r.lock && r.lock.holder ? r.lock.holder : "free"; }

// who holds the robot, from the gate's who: the holder, since when, the lease, and what is left of it (counted from when it was read)
function holderText(r) {
  const l = r.lock || {};
  if (l.unreachable) return "gate unreachable";
  if (!l.holder) return "free";
  const since = l.since ? new Date(l.since * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : null;
  const left = l.expires_in_s != null ? Math.max(0, Math.round(l.expires_in_s - (Date.now() - (r.lock_at || Date.now())) / 1000)) : null;
  return [l.holder, since && "since " + since, "lease " + l.lease_id, left != null && `expires in ${left} s`].filter(Boolean).join(" · ");
}

function renderRobots() {
  const box = $("robot-list");
  box.replaceChildren(...S.robots.map((r) => {
    const st = r.status || {}, p = st.pose, fr = freshOf(r), dim = dimOf(r);
    r.fresh_seen = fr;
    return h("div", { class: "robotcard" }, h("button", { class: "robot", type: "button", id: "robot-" + r.id, "data-online": String(r.online), "aria-pressed": String(r.id === S.robot),
      onclick: guard(() => selectRobot(r.id)) },
      h("div", { class: "name" }, h("span", { class: "dot" + (r.online ? " on" : "") }), r.label, " ", h("span", { class: "faint mono" }, r.id)),
      h("div", { class: "kv" + (fr === "fresh" ? "" : " ui-stale"), "data-fresh": fr },
        h("span", {}, "", h("b", { class: "online" }, r.online ? "online" : "offline")),
        h("span", {}, "lock ", h("b", { class: "lock" }, lockText(r))),
        h("span", {}, "mode ", h("b", { class: dim }, st.mode || "-")),
        h("span", {}, "battery ", h("b", { class: dim }, st.battery_pct != null ? st.battery_pct + "%" : "-")),
        h("span", {}, "pose ", h("b", { class: "mono " + dim }, p ? `${p.x.toFixed(2)}, ${p.y.toFixed(2)}` : "-")),
        h("span", {}, "site ", h("b", {}, r.site || "none")),
        r.goal_run ? h("span", {}, "run ", h("b", {}, "#" + r.goal_run)) : null,
        ageEl(r)),
      h("div", { class: "holder faint" }, holderText(r))),
      h("a", { class: "open", href: "#robot/" + r.id, "data-robot": r.id }, "Open the robot's page"));
  }));
  const r = robot();
  $("stop-robot").textContent = r ? "STOP " + r.id : "STOP";
  $("stop-robot").disabled = !r;
  applyFreshness();
  renderRobotPage();
}

// --- the robot's page (RFC-0023 D3): #robot/<id>[/<tab>]; Overview and Parts are built from what GET /robots/{id} gives and the alarm feed ----
const TABS = ["overview", "body", "modules", "settings", "calibration"];
function route() {
  const m = /^#robot\/([^/]+)(?:\/([a-z]+))?$/.exec(location.hash);
  return m ? { id: decodeURIComponent(m[1]), tab: TABS.includes(m[2]) ? m[2] : "overview" } : null;
}
const routeId = () => (route() || {}).id ?? null;
const routeTab = () => (route() || {}).tab ?? null;
const hashOf = (id, tab) => "#robot/" + encodeURIComponent(id) + (tab && tab !== "overview" ? "/" + tab : "");
const goTab = (tab) => { if (routeId() != null) location.hash = hashOf(routeId(), tab); };

// The alarm check the readiness card counts: a minor alarm is not a reason, a major or critical one in the last minute is. ok is true or false; the other
// checks are readiness.js's own, from the robot view.
// now: the render's one clock, so the verdict and the Alarms card agree at the window's edge
function alarmChecks(r, now = Date.now() / 1000) {
  const bad = S.alarms.filter((x) => x.robot === r.id && now - x.at <= ALARM_WINDOW_S && SEV.indexOf(x.a.severity) >= SEV.indexOf("major"));
  let alarm = null, w = null;
  if (bad.length) {
    w = bad.reduce((a, x) => (SEV.indexOf(x.a.severity) >= SEV.indexOf(a.a.severity) ? x : a));
    alarm = `${w.a.severity} alarm ${w.a.anomaly}: ${w.a.summary || ""} (${ago(w.at)}${bad.length > 1 ? `, ${bad.length} in the last minute` : ""})`;
  }
  return [{ id: "alarms", ok: !alarm, what: "No major or critical alarm in the last 60 s", val: alarm || "none", alarm: w }];
}
// A sensor's reading for the facts line: a range in cm (or that nothing is in range), else the colour's name or the value.
const sensorText = (v) => ("range_m" in v ? (v.range_m == null ? "nothing in range" : Math.round(v.range_m * 100) + " cm") : v.label ?? v.value ?? "-");

function applyTab(tab) {
  for (const b of document.querySelectorAll(".tabs .tab")) {
    const on = b.dataset.tab === tab;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
    $("rp-" + b.dataset.tab).hidden = !on;
  }
  const open = stOpenDrawer();
  if (open && open.dataset.tab !== tab) stCloseDrawers();
}

function paintPicker() {
  const sel = $("rp-picker"), sig = S.robots.map((x) => x.id + "\n" + x.label).join("\n");
  if (sel.dataset.sig !== sig) { sel.dataset.sig = sig; setKids(sel, S.robots.map((x) => h("option", { value: x.id }, `${x.label} (${x.id})`))); }
  sel.value = routeId();
}

// The facts line under the title: mode, battery, each sensor the robot reports, who holds it. Repainted on its own at every state event, so a
// reading is not five seconds old; the rest of the page is not rebuilt that often (an open settings form would be lost).
function paintFacts(r) {
  const st = r.status || {}, pr = r.profile, held = holderText(r);
  const fr = freshOf(r), dim = dimOf(r);
  $("rp-facts").classList.toggle("ui-stale", fr !== "fresh");
  setKids($("rp-facts"),
    h("span", {}, "mode ", h("b", { class: dim }, st.mode || "-")),
    h("span", {}, "battery ", h("b", { class: dim }, st.battery_pct != null ? st.battery_pct + "%" : "-")),
    ...Object.entries(st.sensors || {}).map(([k, v]) => h("span", { "data-sensor": k }, k + " ", h("b", { class: dim }, sensorText(v)))),
    h("span", {}, "held by ", h("b", { id: "rp-holder" }, held === "free" ? "nobody" : held)),
    pr ? h("span", {}, "runs ", h("b", {}, pr.variant), " variant") : null,
    h("span", {}, "settings ", h("b", {}, !pr ? "none" : pr.version != null ? "version " + pr.version : "the robot's own file")),
    ageEl(r));
}

function renderRobotPage() {
  const rt = route(), id = rt && rt.id;
  $("robot-page").hidden = !rt;
  document.querySelector("main.page").hidden = !!rt;
  $("rp-crumbs").hidden = !rt;
  document.body.classList.toggle("on-robot", !!rt);
  paintBar();
  if (!rt) { closeBody(); stCloseDrawers(); requestDraw(); return; }
  const r = S.robots.find((x) => x.id === id);
  if (r && S.robot !== id) { guard(() => selectRobot(id, true))(); return; }
  applyTab(rt.tab);
  loadLayout();
  paintPicker();
  const chip = $("verdict");
  setKids($("rp-title"), r ? [r.label, " ", h("span", { class: "faint mono" }, r.id)] : S.ready ? `No robot "${id}"` : "Loading");
  if (!r) {
    chip.hidden = true; chip.removeAttribute("data-status");
    for (const k of ["facts", "alarms-body", "alarms-sum", "parts-body", "parts-sum", "body-sum", "readiness-body", "readiness-sum", "joints-body", "joints-sum", "modules-body", "settings-body", "calibration-body"]) setKids($("rp-" + k));
    stForget();
    closeBody();
    return;
  }
  const pr = r.profile, now = Date.now() / 1000;
  paintFacts(r);
  const badge = $("tab-settings-badge");
  badge.hidden = !(pr && pr.version != null);
  badge.textContent = pr && pr.version != null ? "v" + pr.version : "";

  const recent = S.alarms.filter((x) => x.robot === r.id && now - x.at <= ALARM_WINDOW_S).reverse();
  setKids($("rp-alarms-sum"), recent.length ? plural(recent.length, "alarm") : "none");
  setKids($("rp-alarms-body"), recent.length
    ? h("ul", { class: "alarmrows" }, recent.map((x) => h("li", {}, h("span", { class: "sev sev-" + x.a.severity }, x.a.severity),
      h("span", { class: "what" }, `${x.a.anomaly}: ${x.a.summary || ""}`), h("span", { class: "faint" }, ago(x.at)), momentLink(runKeyOf(x.watch), x.a.t))))
    : h("div", { class: "empty" }, "No alarms in the last minute. A major or critical one makes the robot not ready for 60 s."));

  const parts = pr ? pr.subsystems : null;
  setKids($("rp-parts-sum"), parts ? plural(parts.length, "subsystem") : "");
  setKids($("rp-parts-body"), !pr ? h("div", { class: "empty" }, "No profile: this robot's file holds the robot itself, so it lists no parts.")
    : !parts.length ? h("div", { class: "empty" }, "The profile lists no parts.")
    : h("div", { class: "twrap" }, h("table", { class: "t" },
      h("thead", {}, h("tr", {}, ["Part", "Does", "Check", "State"].map((x) => h("th", {}, x)))),
      h("tbody", {}, parts.map((s) => h("tr", { "data-part": s.name },
        h("td", { class: "k" }, s.name), h("td", {}, s.what || ""),
        h("td", { class: "v inh" }, s.check.kind + (s.check.socket ? " " + s.check.socket : ""),
          s.logs ? h("div", {}, "logs " + s.logs) : null, (s.conflicts || []).length ? h("div", {}, "conflicts with " + s.conflicts.join(", ")) : null),
        h("td", {}, h("span", { class: "tag" }, "not reported"))))))));
  paintReadiness(r, now);
  paintProfile(r);
  paintBody(r);
}

// The body (RFC-0024 step 2): libs/web's component in bodyview.js, loaded only when the Body tab of a robot with a description is open.
// Posed from the robot's live joint angles, each joint coloured by the worst alarm in the last minute that names it. The joint table and the
// Overview's Body card read the same states and need no three.js: only /lib/body/body.js, which holds the rule.
const descs = {}, descErr = {}, descBusy = {}, bodyErr = {};      // robot id -> its description (null when it has none), why it could not be read
let bodyMod = null, bodyFor = null;        // the module once loaded; the robot whose body is mounted or being mounted
let jointMod = null, jointErr = null, jointBusy = false;

async function loadDesc(id) {
  if (descBusy[id]) return;
  descBusy[id] = true;
  try { descs[id] = (await api("GET", `/robots/${id}/description`)).description; } catch (e) { descs[id] = null; descErr[id] = e.message; }
  if (routeId() === id) renderRobotPage();
}

function loadJointLib() {
  if (jointBusy) return;
  jointBusy = true;
  import("/lib/body/body.js").then((m) => { jointMod = m; renderRobotPage(); }).catch((e) => { jointErr = `The joint states could not be loaded: ${e.message}`; renderRobotPage(); });
}

async function openBody(id) {
  closeBody();
  bodyFor = id;
  try {
    bodyMod ||= await import("./bodyview.js");
    if (bodyFor !== id) return;
    await bodyMod.mount($("rp-body-view"), id, descs[id], API + "/", S.token ? { headers: { Authorization: "Bearer " + S.token } } : undefined);
    const r = S.robots.find((x) => x.id === id);
    if (bodyFor === id && r) paintBody(r);
  } catch (e) {
    bodyErr[id] = e.message;
    if (bodyFor === id) { const r = S.robots.find((x) => x.id === id); if (r) paintBody(r); }
  }
}

function paintBody(r) {
  if (!jointMod) { loadJointLib(); setKids($("rp-joints-body"), h("div", { class: "empty" }, jointErr || "Loading")); return; }
  if (!(r.id in descs)) { loadDesc(r.id); return; }
  const d = descs[r.id], now = Date.now() / 1000, live = (r.status || {}).joints || {};
  const alarms = S.alarms.filter((x) => x.robot === r.id).map((x) => ({ t: x.at, a: x.a }));
  const states = jointMod.jointStates(alarms, now, ALARM_WINDOW_S), bad = Object.entries(states);
  const names = [...new Set([...(d ? d.joints.filter((j) => j.type !== "fixed").map((j) => j.name) : []), ...Object.keys(live), ...Object.keys(states)])];
  const drawable = !!d && d.links.some((l) => l.visuals.some((v) => !d.meshes_missing.includes(v.mesh)));
  const note = descErr[r.id] ? `The body could not be loaded: ${descErr[r.id]}` : bodyErr[r.id] ? `The body could not be loaded: ${bodyErr[r.id]}`
    : !d ? "No 3D model: this robot's file holds the robot itself, so it has no description."
    : !drawable ? `The description's ${plural(d.meshes_missing.length, "mesh")} ${d.meshes_missing.length === 1 ? "is" : "are"} not built on this machine (make robots): nothing to draw.` : null;
  setKids($("rp-body-note"), note);
  $("rp-body-view").hidden = !drawable;
  const lines = bad.map(([j, s]) => h("li", { class: s.state === "error" ? "sev-major" : "sev-minor" }, `${j}: ${s.state}, ${s.anomaly}`));
  setKids($("rp-body-joints"), lines);
  setKids($("rp-joints-sum"), names.length ? `${names.length}${bad.length ? `, ${bad.length} not ok` : ""}` : "");
  setKids($("rp-joints-body"), names.length
    ? h("table", { class: "t" }, h("thead", {}, h("tr", {}, ["Joint", "Angle", "State"].map((x) => h("th", {}, x)))),
      h("tbody", {}, names.map((j) => { const s = states[j], a = live[j];
        return h("tr", { "data-joint": j, "data-state": s ? s.state : "ok" }, h("td", { class: "k" }, j),
          h("td", { class: "v inh" }, typeof a === "number" ? a.toFixed(2) + " rad" : "-"),
          h("td", { class: s ? (s.state === "error" ? "bad" : "warn") : "ok" }, s ? `${s.state}, ${s.anomaly}` : "ok")); })))
    : h("div", { class: "empty" }, "This robot reports no joints."));
  setKids($("rp-body-sum"), note ? h("div", { class: "dim" }, note)
    : !names.length ? h("div", { class: "dim" }, "This robot reports no joints.")
    : [h("div", { class: bad.length ? "" : "ok" }, bad.length ? `${bad.length} of ${plural(names.length, "joint")} not ok:` : `All ${plural(names.length, "joint")} ok.`),
      bad.length ? h("ul", { class: "list bodyjoints" }, lines.map((li) => li.cloneNode(true))) : null,
      h("div", { class: "dim" }, "A joint turns the warn or the error colour for a minute after an alarm names it, and is listed by name.")]);
  if (routeTab() !== "body" || !drawable) { if (bodyFor) closeBody(); return; }
  if (bodyFor !== r.id) { openBody(r.id); return; }
  if (bodyMod) bodyMod.update(live, alarms, now, ALARM_WINDOW_S);
}

function closeBody() {
  if (bodyMod) bodyMod.unmount();
  bodyFor = null;
}

$("rp-back").addEventListener("click", () => { location.hash = ""; });
$("rp-picker").addEventListener("change", (ev) => { location.hash = hashOf(ev.target.value, routeTab()); });
window.addEventListener("hashchange", renderRobotPage);
setInterval(() => { if (routeId()) renderRobotPage(); }, 5000);

for (const b of document.querySelectorAll(".tabs .tab")) b.addEventListener("click", () => goTab(b.dataset.tab));
$("robot-page").querySelector(".tabs").addEventListener("keydown", (ev) => {
  const i = TABS.indexOf(document.activeElement && document.activeElement.dataset.tab);
  const to = { ArrowRight: (i + 1) % TABS.length, ArrowLeft: (i + TABS.length - 1) % TABS.length, Home: 0, End: TABS.length - 1 }[ev.key];
  if (i < 0 || to === undefined) return;
  ev.preventDefault();
  $("tab-" + TABS[to]).focus();
  goTab(TABS[to]);
});

// The robot page's panels and layouts (layout.js, with libs/web/layout/store.js): loaded the first time a robot page opens, never by the overview.
let layoutMod = null, layoutBusy = null;
function loadLayout() {
  layoutBusy ||= import("./layout.js").then((m) => { layoutMod = m.mount({ page: $("robot-page"), setOpen }); })
    .catch((e) => { toast("The layout could not be loaded: " + e.message, true); });   // not retried: the page repaints every 5 s and would toast every time
  return layoutBusy;
}
$("rp-layout").addEventListener("click", async () => { await loadLayout(); if (layoutMod) layoutMod.toggle(); });

// The readiness card (readiness.js): loaded the first time a robot page opens, never by the overview; a repaint of the page paints it once loaded.
let readyMod = null, readyBusy = null;
function loadReadiness() {
  readyBusy ||= import("./readiness.js").then((m) => { readyMod = m; renderRobotPage(); })
    .catch((e) => { setKids($("rp-readiness-body"), h("div", { class: "empty" }, "The readiness card could not be loaded: " + e.message)); });
  return readyBusy;
}
function paintReadiness(r, now) {
  if (!readyMod) { loadReadiness(); return; }
  const fit = alarmChecks(r, now);
  readyMod.paint({ host: $("rp-readiness-body"), sum: $("rp-readiness-sum"), chip: $("verdict"), list: readyMod.checks(r, fit), h, badge, label: (s) => (KIT.status ? KIT.status.label(s) : s) });
  const w = fit.find((c) => c.id === "alarms").alarm, held = r.lock && r.lock.holder && r.goal_run != null ? runKeyOfRun(r.goal_run) : null;
  const into = (check, link) => { const li = link && document.querySelector(`#readiness-checks [data-check="${check}"]`); if (li) li.append(link); };
  into("alarms", w && momentLink(runKeyOf(w.watch), w.a.t));
  into("free", held && momentLink(held, 0));
}

// --- evidence links (look-and-feel U24): "open in the Observatory at this moment", in the one format both apps share (libs/web/evidence.js) ----------
// Mission Control stands at /control/ behind the Observatory on one origin, so the Observatory is this page's own origin there; on a port of its own it is
// somewhere the page cannot know, and no link is shown (the alarm keeps its watch link, which points at the address the adapter was configured with).
// evidence.js loads the first time a link is to be drawn, and the empty slots drawn meanwhile fill in place: the phone overview, with no run or alarm in view, never fetches it.
let evidenceMod = null, evidenceBusy = null, evidenceWarned = false, evidenceTries = 0;
const slots = new WeakMap();      // an evidence slot -> what it stands for while evidence.js loads
function loadEvidence() {
  // a failed import is kept by the browser for its address, so a retry asks for a new one (the module has no state of its own to duplicate)
  evidenceBusy ||= import(evidenceTries++ ? `/lib/evidence.js?retry=${evidenceTries}` : "/lib/evidence.js").then((m) => { evidenceMod = m; }).catch((e) => {
    // reset so the next repaint tries again; the slots stop waiting (the alarm's own watch link, else nothing) and the failure is said once
    evidenceBusy = null;
    if (!evidenceWarned) { evidenceWarned = true; toast("The Observatory links could not be loaded: " + e.message, true); }
  }).then(fillSlots);
}
// a loaded module turns each waiting slot into its link in place: only the slots change, so nothing else in the repainted box (a half-typed name) is rebuilt
function fillSlots() {
  for (const s of document.querySelectorAll(".evidence-slot")) {
    const o = slots.get(s), link = o && ((evidenceMod && evidenceLink(o.runKey, o.t)) || o.fallback);
    if (link) s.replaceWith(link); else s.remove();
  }
}
// an alarm's watch address is `<observatory>/watch/<run_key>#t=<s>`: the run key is robot/scene/run
const runKeyOf = (watch) => (typeof watch === "string" ? (/\/watch\/([^#?]+)/.exec(watch) || [])[1] || null : null);
// the run key of a goal run this page has listed (the robot view carries only the run's number)
const runKeyOfRun = (id) => (S.runs.find((x) => x.id === id) || {}).run_key || null;
function evidenceLink(runKey, t) {
  const href = evidenceMod.evidenceHref({ origin: location.origin, runKey, t });
  return href ? h("a", { class: "btn sm evidence", href, target: "_blank", rel: "noopener" }, "Open in the Observatory at this moment") : null;
}
// t: seconds into the run; a missing time is the run's start. fallback: what stands in when there is no evidence link (null: nothing)
function momentLink(runKey, t, fallback = null) {
  if (!runKey || !behindObservatory()) return fallback;
  if (!evidenceMod) {
    loadEvidence();
    const slot = h("span", { class: "evidence-slot" });
    slots.set(slot, { runKey, t, fallback });
    return slot;
  }
  return evidenceLink(runKey, t) || fallback;
}

// The command palette (palette-verbs.js, with libs/web/palette): loaded the first time it is asked for, by Ctrl/Cmd+K or the top-bar button, never by the
// overview; /lib/lazy.js (small, loaded with the kit) does the asking and holds the typing guard. Its verbs press STOP's own buttons for STOP; none starts a
// goal or takes a robot.
function wirePalette() {
  KIT.lazy.lazyOpen({
    button: $("palette-btn"), onError: (m) => toast(m, true),
    before: () => (route() ? loadLayout() : undefined),           // the panel and layout verbs need it, and a robot page loads it anyway
    load: () => import("./palette-verbs.js").then((m) => m.mount({
      robots: () => S.robots, route, tabs: TABS, hashOf, stopRobotId: () => (robot() || {}).id ?? null,
      layout: () => (layoutMod ? layoutMod.act : null),
      observatoryHref: () => (KIT.brand ? KIT.brand.APPS.observatory.href : "/"), behindObservatory,
      go: (hash) => { location.hash = hash; }, visit: (href) => location.assign(href),
      stop: () => $("stop-robot").click(), stopAll: () => $("stop-all").click(),
      theme: () => $("theme").click(), themeNow: effectiveTheme, toast,
    })),
  });
}

function setOpen(head, open) {
  head.setAttribute("aria-expanded", String(open));
  const body = $(head.getAttribute("aria-controls"));
  if (body) body.hidden = !open;
  S.open[head.dataset.collapse] = open;
}
document.addEventListener("click", (ev) => {
  const head = ev.target.closest("button[data-collapse]");
  if (head) { setOpen(head, head.getAttribute("aria-expanded") !== "true"); if (layoutMod) layoutMod.folded(head.dataset.collapse, head.getAttribute("aria-expanded") === "true"); return; }
  const go = ev.target.closest("[data-goto-tab]");
  if (go) goTab(go.dataset.gotoTab);
});

// --- sites and areas -------------------------------------------------------------------------------------
function renderSites() {
  const sel = $("site-sel");
  sel.replaceChildren(h("option", { value: "" }, "(no site)"), ...S.sites.map((s) => h("option", { value: s.id }, `${s.name} (${s.kind})`)));
  sel.value = S.site || "";
  const site = S.sites.find((s) => s.id === S.site), d = site && site.dock_pose;
  $("site-dock").textContent = !site ? "" : !d ? "No dock yet: the first run sets it."
    : `Dock set ${d.set_from === "placed_start" ? "from the first placed start" : d.set_from === "robot_pose" ? "from the robot's own pose at its first run" : "at"}`
      + ` (${d.x.toFixed(2)}, ${d.y.toFixed(2)}${d.yaw != null ? ", " + Math.round(d.yaw * 180 / Math.PI) + " deg" : ""})${d.robot ? " by " + d.robot : ""}.`;
}

$("site-sel").addEventListener("change", guard(async (ev) => {
  const site = ev.target.value || null;
  const r = robot();
  if (!r) return;
  try { await api("PUT", `/robots/${r.id}/site`, { site }); }
  catch (e) { ev.target.value = S.site || ""; throw e; }
  S.site = site; await refreshRobot(r.id); await loadSite();
}));

$("site-create").addEventListener("click", guard(async () => {
  const j = await api("POST", "/sites", { name: $("site-name").value, kind: $("site-kind").value });
  $("site-name").value = ""; $("site-kind").value = "";
  await loadSites();
  toast(`Site ${j.site.name} created. Pick it above to put the robot there.`);
}));

function renderAreas() {
  const box = $("area-list");
  // An event redraws the page; a list that did not change is left alone, or the redraw would disarm a Delete the operator has just pressed
  // (a removed focused button blurs, and a blur disarms).
  const sig = JSON.stringify([S.site, S.areas.map((a) => [a.id, a.name, a.type, a.objects.length])]);
  if (box.dataset.sig === sig && box.firstChild) return;
  box.dataset.sig = "";
  if (!S.site) { box.replaceChildren(h("div", { class: "dim" }, "Pick a site for this robot to see and draw its areas.")); return; }
  if (!S.areas.length) { box.replaceChildren(h("div", { class: "dim" }, "No areas yet: " + "none defined.")); return; }
  box.dataset.sig = sig;
  box.replaceChildren(h("ul", { class: "list" }, S.areas.map((a) => {
    const del = dangerous(h("button", { class: "btn sm danger", type: "button", "data-area": a.id, "data-action": "delete" }, "Delete"),
      async () => { await api("DELETE", `/sites/${S.site}/areas/${a.id}`); await loadSite(); });
    const name = h("input", { class: "grow", value: a.name, "aria-label": "Area name", "data-area": a.id, onchange: guard(async (ev) => {
      try { await api("PUT", `/sites/${S.site}/areas/${a.id}`, { name: ev.target.value }); } catch (e) { ev.target.value = a.name; throw e; }
      await loadSite();
    }) });
    return h("li", {}, h("div", { class: "row" }, name, del),
      h("div", { class: "faint", style: "font-size:12px" }, `${a.type || "no type"} · ${a.objects.length} object(s)`));
  })));
}

function setMode(mode) {
  S.mode = mode;
  if (mode !== "draw") S.draft = [];
  $("area-draw").setAttribute("aria-pressed", String(mode === "draw"));
  $("area-draft").hidden = mode !== "draw";
  $("g-place-tap").setAttribute("aria-pressed", String(mode === "place"));
  renderHint(); requestDraw();
}

function renderHint() {
  const r = robot();
  $("maphint").textContent = S.mode === "draw"
    ? `Drawing an area: tap the map to place corners (${S.draft.length} so far; at least 3), then name it and save.`
    : S.mode === "place" ? "Tap the map where the robot stands: that is its start pose. Set which way it faces beside it."
    : r && r.capabilities.navigator ? "Tap the map to set a point goal, then press Run now." : "This robot has no navigator: it cannot take goals.";
  $("area-draft-hint").textContent = `${S.draft.length} corner(s). Tap the map for more.`;
  $("area-save").disabled = S.draft.length < 3;
  $("area-undo").disabled = !S.draft.length;
}

$("area-draw").addEventListener("click", () => {
  if (!S.site) { toast("Pick a site for this robot first.", true); return; }
  setMode(S.mode === "draw" ? "point" : "draw");
});
$("area-cancel").addEventListener("click", () => setMode("point"));
$("area-undo").addEventListener("click", () => { S.draft.pop(); renderHint(); requestDraw(); });
$("area-save").addEventListener("click", guard(async () => {
  await api("POST", `/sites/${S.site}/areas`, { name: $("area-name").value, type: $("area-type").value.trim() || null, outline: S.draft });
  $("area-name").value = ""; $("area-type").value = "";
  setMode("point"); await loadSite();
}));

$("export").addEventListener("click", guard(async () => {
  if (!S.site) throw new Error("Pick a site first.");
  const bundle = (await api("POST", `/sites/${S.site}/export`)).bundle;
  const a = h("a", { href: URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" })), download: `${S.site}.mc-site.json` });
  document.body.append(a); a.click(); a.remove();
  toast(`Exported ${bundle.areas.length} area(s) and ${bundle.objects.length} named object(s).`);
}));

$("import-file").addEventListener("change", guard(async (ev) => {
  const file = ev.target.files[0];
  ev.target.value = "";
  if (!file) return;
  if (!S.site) throw new Error("Pick a site first.");
  let bundle;
  try { bundle = JSON.parse(await file.text()); } catch (e) { throw new Error("That file is not JSON."); }
  const rep = (await api("POST", `/sites/${S.site}/import`, { bundle })).imported;
  await loadSite();
  toast(`Imported: ${rep.areas.created.length} area(s) new, ${rep.areas.updated.length} updated, ${rep.objects.created.length + rep.objects.labelled.length} named object(s)` +
        (rep.objects.skipped.length ? `, ${rep.objects.skipped.length} skipped` : "") + ".");
}));

// --- the goal form ---------------------------------------------------------------------------------------
function areaOptions(blank) {
  return [blank ? h("option", { value: "" }, blank) : null, ...S.areas.map((a) => h("option", { value: a.id }, a.name))];
}

function renderGoalFields() {
  const kind = $("g-kind").value, box = $("g-fields");
  const keep = { x: $("g-x") && $("g-x").value, y: $("g-y") && $("g-y").value };
  if (kind === "point") {
    box.replaceChildren(h("div", { class: "row" },
      h("label", { class: "inline" }, "x ", h("input", { id: "g-x", type: "number", step: "0.05", style: "width:90px", value: keep.x || "" })),
      h("label", { class: "inline" }, "y ", h("input", { id: "g-y", type: "number", step: "0.05", style: "width:90px", value: keep.y || "" })),
      h("span", { class: "dim", style: "font-size:12px" }, "metres, site frame; or tap the map")));
  } else if (kind === "go_to_object") {
    box.replaceChildren(h("div", { class: "row" },
      h("select", { id: "g-objby", "aria-label": "Find the object by" }, h("option", { value: "kind" }, "kind"), h("option", { value: "label" }, "label"), h("option", { value: "id" }, "id")),
      h("input", { id: "g-obj", class: "grow", placeholder: "fridge", "aria-label": "Object kind, label or id" }),
      h("select", { id: "g-objarea", "aria-label": "Only in this area" }, areaOptions("any area"))));
  } else if (kind === "go_to_area") {
    box.replaceChildren(h("select", { id: "g-area", "aria-label": "Area" }, areaOptions(null)));
  } else if (kind === "explore") {
    box.replaceChildren(h("select", { id: "g-scope", "aria-label": "Explore" }, h("option", { value: "" }, "the whole site"), ...areaOptions(null).slice(1)));
  } else {
    box.replaceChildren(h("div", {}, h("div", { class: "dim", style: "font-size:12px" }, "Areas (none ticked: the whole site)"),
      ...S.areas.map((a) => h("label", { class: "inline" }, h("input", { type: "checkbox", class: "g-inv-area", value: a.id }), a.name))));
  }
}
$("g-kind").addEventListener("change", renderGoalFields);

// A start pose (navigator contract 1.5): the robot cannot read where it stands, so the operator says. Unticked, a run starts where the robot's map does.
function startPose() {
  const x = parseFloat($("g-px").value), y = parseFloat($("g-py").value), deg = parseFloat($("g-pyaw").value);
  return $("g-place").checked && !Number.isNaN(x) && !Number.isNaN(y) && !Number.isNaN(deg) ? { x, y, yaw: deg * Math.PI / 180 } : null;
}
function startBody() {
  if (!$("g-place").checked) return {};
  const sp = startPose();
  if (!sp) throw new Error("Set the start pose: tap the map where the robot stands, and say which way it faces.");
  return { start_pose: sp };
}
$("g-place").addEventListener("change", () => {
  $("g-place-fields").hidden = !$("g-place").checked;
  setMode($("g-place").checked ? "place" : "point");
});
$("g-place-tap").addEventListener("click", () => setMode(S.mode === "place" ? "point" : "place"));
for (const id of ["g-px", "g-py", "g-pyaw"]) $(id).addEventListener("input", () => requestDraw());

function formGoal() {
  const kind = $("g-kind").value;
  let params;
  if (kind === "point") {
    const x = parseFloat($("g-x").value), y = parseFloat($("g-y").value);
    if (Number.isNaN(x) || Number.isNaN(y)) throw new Error("Set x and y, or tap the map.");
    params = { x, y };
  } else if (kind === "go_to_object") {
    const v = $("g-obj").value.trim();
    if (!v) throw new Error("Say which object: a kind, a label or an id.");
    params = { [$("g-objby").value]: v };
    if ($("g-objarea").value) params.area = $("g-objarea").value;
  } else if (kind === "go_to_area") {
    if (!$("g-area").value) throw new Error("Draw an area first, then pick it.");
    params = { area: $("g-area").value };
  } else if (kind === "explore") {
    params = $("g-scope").value ? { area: $("g-scope").value } : { site: true };
  } else {
    params = { areas: [...document.querySelectorAll(".g-inv-area:checked")].map((e) => e.value) };
  }
  const must = [...document.querySelectorAll(".g-must:checked")].map((e) => e.value);
  const ms = parseFloat($("g-maxspeed").value), tl = parseFloat($("g-timelimit").value);
  if (ms > 0) must.push({ name: "max_speed", mps: ms });
  if (tl > 0) must.push({ name: "time_limit", seconds: tl });
  const goal = { kind, params, must_not: must, expect: $("g-expect").value };
  goal.sim_first = $("g-simfirst").checked;
  if ($("g-name").value.trim()) goal.name = $("g-name").value.trim();
  if ($("g-folder").value.trim()) goal.folder = $("g-folder").value.trim();
  return goal;
}

$("g-run").addEventListener("click", guard(async () => {
  const r = robot();
  if (!r) throw new Error("No robot.");
  const j = await api("POST", "/goal-runs", { goal: formGoal(), robots: [r.id], ...(S.site ? { site: S.site } : {}), ...startBody() });
  S.run = j.run.id;
  await Promise.all([loadRuns(), refreshRobot(r.id)]);
  if (j.run.state === "refused") toast("Refused: " + j.run.reason, true);
}));

// A goal in words (§3.4.5): the planner proposes, the operator reads it back and presses Run. Nothing runs before.
$("say-go").addEventListener("click", guard(async () => {
  const r = robot();
  const p = (await api("POST", "/plan", { text: $("say").value, ...(r ? { robot: r.id } : {}), ...(S.site ? { site: S.site } : {}) })).plan;
  setKids($("plan-out"),
    p.goals.map((x) => h("div", { class: "row", "data-plan": "1" },
      h("span", { class: "grow" }, x.read_back), h("span", { class: "faint", style: "font-size:12px" }, p.source),
      h("button", { class: "btn sm primary", type: "button", "data-action": "run-plan", "data-needs-fresh": "1", onclick: guard(async () => {
        const j = await api("POST", "/goal-runs", { goal: x.goal, robots: [r.id], ...(S.site ? { site: S.site } : {}), ...startBody() });
        S.run = j.run.id; await Promise.all([loadRuns(), refreshRobot(r.id)]);
        if (j.run.state === "refused") toast("Refused: " + j.run.reason, true);
      }) }, "Run"))),
    p.goals.length ? null : h("div", { class: "dim", id: "plan-none" }, p.message),
    p.dropped.length ? h("div", { class: "faint", style: "font-size:12px" }, `${p.dropped.length} part(s) of the plan were not valid goals and were dropped.`) : null);
  applyFreshness();
}));

$("g-save").addEventListener("click", guard(async () => {
  const goal = formGoal();
  if (!goal.name) throw new Error("Give the goal a name to save it.");
  await api("POST", "/goals", goal);
  await loadGoals();
  toast("Saved to the library.");
}));

// --- the library -----------------------------------------------------------------------------------------
function goalSummary(g) {
  const p = g.params;
  if (g.kind === "point") return `point (${p.x}, ${p.y})`;
  if (g.kind === "go_to_object") return "go to " + (p.kind || p.label || p.id) + (p.area ? " in " + p.area : "");
  if (g.kind === "go_to_area") return "go to " + p.area;
  if (g.kind === "explore") return "explore " + (p.area || "the site");
  return "inventory " + (p.areas.length ? p.areas.join(", ") : "of the site");
}

function renderLibrary() {
  renderLibraryList();
  applyFreshness();
}
function renderLibraryList() {
  const box = $("goal-list");
  const sig = JSON.stringify(S.goals.map((g) => [g.id, g.name, g.folder, goalSummary(g)]));
  if (box.dataset.sig === sig && box.firstChild) return;      // see renderAreas
  box.dataset.sig = "";
  if (!S.goals.length) { box.replaceChildren(h("div", { class: "dim" }, "Nothing saved yet. Define a goal and press Save to library, or save a run.")); return; }
  box.dataset.sig = sig;
  const folders = new Map();
  for (const g of S.goals) { if (!folders.has(g.folder)) folders.set(g.folder, []); folders.get(g.folder).push(g); }
  box.replaceChildren(...[...folders].map(([folder, goals]) => h("div", {},
    h("div", { class: "folder" }, folder ? folder + "/" : "/"),
    h("ul", { class: "list" }, goals.map((g) => h("li", { "data-goal": g.id },
      h("div", { class: "row" },
        h("span", { class: "grow" }, h("b", {}, g.name), " ", h("span", { class: "dim" }, goalSummary(g))),
        h("button", { class: "btn sm primary", type: "button", "data-action": "run", "data-needs-fresh": "1", onclick: guard(async () => {
          const r = robot();
          const j = await api("POST", `/goals/${g.id}/runs`, { robots: [r.id], ...(S.site ? { site: S.site } : {}), ...startBody() });
          S.run = j.run.id; await Promise.all([loadRuns(), refreshRobot(r.id)]);
          if (j.run.state === "refused") toast("Refused: " + j.run.reason, true);
        }) }, "Run"),
        dangerous(h("button", { class: "btn sm danger", type: "button", "data-action": "delete" }, "Delete"),
          async () => { await api("DELETE", `/goals/${g.id}`); await loadGoals(); }))))))));
}

// --- runs ------------------------------------------------------------------------------------------------
function renderRuns() {
  $("run-list").replaceChildren(...(S.runs.length ? S.runs.map((r) => h("button", { class: "run", type: "button", "data-run": r.id, "aria-pressed": String(r.id === S.run),
    onclick: guard(async () => { S.run = r.id; renderRuns(); await loadRunDetail(r.id); }) },
    `#${r.id} ${r.goal.name} `, stateBadge(r.state))) : [h("div", { class: "dim" }, "No goal runs for this robot yet.")]));
}

const startPoseText = (p) => `Started from a pose the operator placed: (${p.x}, ${p.y}) facing ${Math.round(p.yaw * 180 / Math.PI)} deg`;

function renderRunDetail() {
  const box = $("run-detail"), r = detail;
  if (!r || r.id !== S.run) { box.replaceChildren(); return; }
  box.dataset.run = r.id;
  const live = !TERMINAL.includes(r.state), pr = r.progress || {};
  const watch = h("a", { class: "watch", id: "watch", href: r.watch || "#", target: "_blank", rel: "noopener", "aria-disabled": String(!r.watch),
    title: r.watch ? "Open this run in the Observatory" : "This run has no Observatory run key: nothing to watch" }, "Watch");
  const saveName = h("input", { id: "save-name", class: "grow", placeholder: "Name", "aria-label": "Name to save this goal as" });
  const saveFolder = h("input", { id: "save-folder", class: "grow", placeholder: "Folder", "aria-label": "Folder", value: r.goal.folder || "" });
  setKids(box,
    h("h3", {}, `Run #${r.id} `, stateBadge(r.state, "run-state"), " ", watch),
    r.reason ? h("div", { class: "dim", id: "run-reason" }, r.reason) : null,
    (r.conditions || {}).start_pose ? h("div", { class: "dim", id: "run-placed" }, startPoseText(r.conditions.start_pose)) : null,
    (r.conditions || {}).rehearsal && r.conditions.rehearsal.flagged
      ? h("div", { class: "dim", id: "run-rehearsal" }, r.conditions.rehearsal.run ? `Rehearsed in the simulator by run #${r.conditions.rehearsal.run}` : "Not rehearsed in the simulator") : null,
    r.no_verdict ? h("div", { class: "dim", id: "run-no-verdict" }, "No verdict: " + r.no_verdict) : null,
    h("div", { class: "kv", id: "run-progress" },
      h("span", {}, "elapsed ", h("b", {}, pr.elapsed_s != null ? pr.elapsed_s + " s" : "-")),
      h("span", {}, "left ", h("b", {}, pr.distance_left_m != null ? pr.distance_left_m + " m" : "-")),
      h("span", {}, "area ", h("b", {}, pr.area || "none")),
      r.as_expected != null ? h("span", {}, "as expected ", h("b", {}, r.as_expected ? "yes" : "no")) : null),
    r.guardrails.length ? h("div", { class: "faint", style: "font-size:12px" }, "must not: " + r.guardrails.map((g) => g.name + (g.mps ? " " + g.mps : "") + (g.seconds ? " " + g.seconds : "")).join(", ")) : null,
    r.broken ? h("div", { class: "dim" }, "Broken: " + r.broken.detail) : null,
    r.result ? h("pre", { class: "json" }, JSON.stringify(r.result, null, 1)) : null,
    !live ? momentLink(r.run_key, pr.elapsed_s) : null,
    (r.anomalies || []).length ? h("div", { class: "run-anomalies", id: "run-anomalies" }, h("h3", {}, "Alarms"), r.anomalies.map(anomalyLine))
      : h("div", { class: "run-anomalies", id: "run-anomalies" }),
    h("div", { class: "decisions", id: "decisions" }, r.decisions.map((d) => h("div", {}, d.text))),
    h("div", { class: "row", style: "margin-top:6px" },
      live ? h("button", { class: "btn danger", type: "button", id: "run-cancel", onclick: guard(async () => { await api("POST", `/goal-runs/${r.id}/cancel`); await loadRuns(); }) }, "Cancel run") : null),
    h("div", { class: "row", style: "margin-top:6px" }, saveName, saveFolder,
      h("button", { class: "btn", type: "button", id: "run-save", onclick: guard(async () => {
        await api("POST", `/goal-runs/${r.id}/save`, { name: saveName.value, folder: saveFolder.value });
        await loadGoals(); toast("The run's goal is in the library.");
      }) }, "Save to library")));
  const d = $("decisions"); d.scrollTop = d.scrollHeight;
}

// --- STOP ------------------------------------------------------------------------------------------------
$("stop-robot").addEventListener("click", guard(async () => {
  const r = robot();
  if (!r) return;
  const j = await api("POST", `/robots/${r.id}/stop`, { client: "page" });
  toast(j.stop.confirmed ? `${r.id} stopped.` : `${r.id}: STOP sent, but the robot did not answer, so it cannot be confirmed.`, !j.stop.confirmed);
  await Promise.all([refreshRobot(r.id), loadRuns()]).catch(() => {});
}));
$("stop-all").addEventListener("click", guard(async () => {
  const j = await api("POST", "/stop", { client: "page" });
  const bad = j.stop.robots.filter((r) => !r.confirmed).map((r) => r.robot);
  toast(bad.length ? `STOP sent to all. Not confirmed: ${bad.join(", ")}.` : "All robots stopped.", bad.length > 0);
  await Promise.all([loadRobots(), loadRuns()]).catch(() => {});   // the stop is done; a refresh a token refuses must not hide it
}));

// --- the map ---------------------------------------------------------------------------------------------
let drawPending = false;
function requestDraw() { if (!drawPending) { drawPending = true; requestAnimationFrame(() => { drawPending = false; draw(); }); } }

let V = null; // the view: scale and offsets, world to screen
function computeView(w, h2) {
  let x0 = -4, y0 = -3, x1 = 4, y1 = 3;
  const m = S.map;
  if (m) { x0 = m.origin[0]; y0 = m.origin[1]; x1 = x0 + m.width * m.resolution_m; y1 = y0 + m.height * m.resolution_m; }
  const grow = (x, y) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); };
  for (const a of S.areas) for (const p of a.outline) grow(p[0], p[1]);
  for (const o of S.objects) grow(o.x, o.y);
  for (const p of S.draft) grow(p[0], p[1]);
  const r = robot();
  if (r && r.status && r.status.pose) grow(r.status.pose.x, r.status.pose.y);
  x0 -= 0.3; y0 -= 0.3; x1 += 0.3; y1 += 0.3;
  const pad = 6, scale = Math.min((w - 2 * pad) / (x1 - x0), (h2 - 2 * pad) / (y1 - y0));
  const ox = (w - scale * (x1 - x0)) / 2 - scale * x0, oy = (h2 + scale * (y1 - y0)) / 2 + scale * y0;
  return { scale, ox, oy, w, h: h2 };
}
const toScreen = (x, y) => [V.ox + x * V.scale, V.oy - y * V.scale];
const toWorld = (px, py) => [(px - V.ox) / V.scale, (V.oy - py) / V.scale];

function draw() {
  const cv = $("map"), dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, hh = cv.clientHeight;
  if (!w || !hh) return;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(hh * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(hh * dpr); }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const css = getComputedStyle(document.documentElement), col = (n) => css.getPropertyValue(n).trim();
  ctx.fillStyle = col("--surface-1"); ctx.fillRect(0, 0, w, hh);
  V = computeView(w, hh);

  // a 1 m grid
  ctx.strokeStyle = col("--scene-grid"); ctx.lineWidth = 1; ctx.beginPath();
  const [wx0, wy1] = toWorld(0, 0), [wx1, wy0] = toWorld(w, hh);
  for (let x = Math.ceil(wx0); x <= wx1; x++) { const [sx] = toScreen(x, 0); ctx.moveTo(sx, 0); ctx.lineTo(sx, hh); }
  for (let y = Math.ceil(wy0); y <= wy1; y++) { const [, sy] = toScreen(0, y); ctx.moveTo(0, sy); ctx.lineTo(w, sy); }
  ctx.stroke();

  if ($("layer-grid").checked && S.map) {
    const m = S.map, res = m.resolution_m;
    for (let j = 0; j < m.height; j++) for (let i = 0; i < m.width; i++) {
      const v = m.data[j * m.width + i];
      if (v < 0) continue;
      ctx.fillStyle = v >= 50 ? col("--data-occupied") : col("--data-free");
      const [sx, sy] = toScreen(m.origin[0] + i * res, m.origin[1] + (j + 1) * res);
      ctx.fillRect(sx, sy, res * V.scale + 0.5, res * V.scale + 0.5);
    }
  }

  ctx.font = "11px " + col("--font-ui"); ctx.textAlign = "center"; ctx.textBaseline = "middle";
  if ($("layer-areas").checked) {
    for (const a of S.areas) {
      poly(ctx, a.outline); ctx.fillStyle = col("--accent-soft"); ctx.fill();
      ctx.strokeStyle = col("--accent"); ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
      const c = a.outline.reduce((s, p) => [s[0] + p[0] / a.outline.length, s[1] + p[1] / a.outline.length], [0, 0]);
      const [cx, cy] = toScreen(c[0], c[1]);
      ctx.fillStyle = col("--accent-text"); ctx.fillText(a.name, cx, cy - 8);
    }
  }
  if ($("layer-objects").checked) {
    for (const o of S.objects) {
      for (const p of o.parts) {
        const [px, py, hx, hy, yaw] = p, c = Math.cos(yaw), s = Math.sin(yaw);
        const pts = [[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]].map(([dx, dy]) => [px + dx * c - dy * s, py + dx * s + dy * c]);
        poly(ctx, pts);
        ctx.globalAlpha = o.confirmed ? 0.7 : 0.22; ctx.fillStyle = col("--data-box"); ctx.fill(); ctx.globalAlpha = 1;
        ctx.strokeStyle = o.landmark >= 0.7 ? col("--data-plan") : col("--line-strong"); ctx.lineWidth = o.landmark >= 0.7 ? 2 : 1; ctx.stroke();
      }
      const [sx, sy] = toScreen(o.x, o.y);
      ctx.fillStyle = col("--text-1"); ctx.fillText(o.label || o.kind, sx, sy);
    }
  }
  if (S.draft.length) {
    poly(ctx, S.draft, S.draft.length < 3); ctx.strokeStyle = col("--status-warn"); ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = col("--status-warn");
    for (const p of S.draft) { const [sx, sy] = toScreen(p[0], p[1]); ctx.beginPath(); ctx.arc(sx, sy, 4, 0, 7); ctx.fill(); }
  }
  if (S.target) {
    const [sx, sy] = toScreen(S.target[0], S.target[1]);
    ctx.strokeStyle = col("--data-plan"); ctx.lineWidth = 2; ctx.beginPath();
    ctx.moveTo(sx - 8, sy); ctx.lineTo(sx + 8, sy); ctx.moveTo(sx, sy - 8); ctx.lineTo(sx, sy + 8); ctx.stroke();
  }
  const sp = startPose();
  if (sp) {      // where the operator says the robot stands: a ring and the way it faces
    const [sx, sy] = toScreen(sp.x, sp.y), rad = Math.max(8, 0.18 * V.scale);
    ctx.strokeStyle = col("--status-warn"); ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(sx, sy, rad, 0, 7);
    ctx.moveTo(sx, sy); ctx.lineTo(sx + rad * 1.8 * Math.cos(sp.yaw), sy - rad * 1.8 * Math.sin(sp.yaw)); ctx.stroke();
  }
  const r = robot();
  if (r && r.status && r.status.pose) {
    const p = r.status.pose, [sx, sy] = toScreen(p.x, p.y), rad = Math.max(6, 0.15 * V.scale);
    ctx.fillStyle = r.online ? col("--data-truth") : col("--text-3"); ctx.beginPath(); ctx.arc(sx, sy, rad, 0, 7); ctx.fill();
    ctx.strokeStyle = col("--text-1"); ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(sx, sy);
    ctx.lineTo(sx + rad * 1.8 * Math.cos(p.yaw), sy - rad * 1.8 * Math.sin(p.yaw)); ctx.stroke();
  }
}

function poly(ctx, pts, open) {
  ctx.beginPath();
  pts.forEach((p, i) => { const [sx, sy] = toScreen(p[0], p[1]); if (i) ctx.lineTo(sx, sy); else ctx.moveTo(sx, sy); });
  if (!open) ctx.closePath();
}

$("map").addEventListener("click", (ev) => {
  if (!V) return;
  const rect = $("map").getBoundingClientRect();
  const [x, y] = toWorld(ev.clientX - rect.left, ev.clientY - rect.top).map((v) => Math.round(v * 100) / 100);
  if (S.mode === "draw") { S.draft.push([x, y]); renderHint(); }
  else if (S.mode === "place") { $("g-px").value = x; $("g-py").value = y; $("maphint").textContent = `Start pose at (${x}, ${y}), facing ${$("g-pyaw").value || 0} deg.`; }
  else {
    S.target = [x, y];
    if ($("g-kind").value !== "point") { $("g-kind").value = "point"; renderGoalFields(); }
    $("g-x").value = x; $("g-y").value = y;
    $("maphint").textContent = `Point goal at (${x}, ${y}). Press Run now.`;
  }
  requestDraw();
});
for (const id of ["layer-grid", "layer-objects", "layer-areas"]) $(id).addEventListener("change", requestDraw);
new ResizeObserver(requestDraw).observe($("map"));

// --- the event stream ------------------------------------------------------------------------------------
function logLine(e) {
  const log = $("event-log");
  log.prepend(h("div", {}, `${e.seq} ${e.kind}${e.robot ? " " + e.robot : ""}${e.text ? " " + e.text : e.state ? " " + e.state : e.event ? " " + e.event : e.anomaly ? " " + e.anomaly.anomaly : ""}`));
  while (log.childNodes.length > 60) log.lastChild.remove();
}

// --- alarms (RFC-0023 D5, RFC-0019 section 4.2): every anomaly a navigator raises, live; the badge counts the last minute's ---------
const SEV = ["info", "minor", "major", "critical"];
let ALARM_WINDOW_S = 60;
const ALARM_KEEP = 200;
S.alarms = [];      // oldest first: {robot, goal_run, watch, at (wall s), a (RFC-0019's record)}
S.alarmSel = null;

const alarmKey = (x) => [x.robot, x.goal_run, x.a.n, x.a.t, x.a.anomaly, x.a.severity].join("|");

// What the server kept of the last minute (the robot's `alarms`: the worst overall and the worst per joint) joins the feed once: the window
// is the server's, and an alarm the feed already has, or brings later, is not counted twice (the same robot, run, number and record, not the same time).
function seedAlarms(r) {
  const al = r.alarms;
  if (!al) return;
  if (al.window_s) ALARM_WINDOW_S = al.window_s;
  const have = new Set(S.alarms.map(alarmKey));
  let added = false;
  for (const e of [al.worst, ...Object.values(al.joints || {})]) {
    if (!e) continue;
    const x = { robot: r.id, goal_run: e.goal_run, watch: e.watch, at: e.at, a: e.anomaly };
    if (have.has(alarmKey(x))) continue;
    have.add(alarmKey(x));
    S.alarms.push(x);
    added = true;
  }
  if (!added) return;
  S.alarms.sort((a, b) => a.at - b.at);
  S.alarmSel = null;
  renderAlarmBadge();
  renderAlarms();
}

function worstOf(list) { return list.reduce((w, x) => (SEV.indexOf(x.a.severity) > SEV.indexOf(w) ? x.a.severity : w), "info"); }
function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }

function renderAlarmBadge() {
  const b = $("alarm");
  const now = Date.now() / 1000;
  const recent = S.alarms.filter((x) => now - x.at <= ALARM_WINDOW_S);
  b.hidden = !S.alarms.length;
  b.className = "chip alarm sev-" + (recent.length ? worstOf(recent) : "none");
  b.textContent = recent.length ? `${plural(recent.length, "alarm")}, ${worstOf(recent)}` : `${plural(S.alarms.length, "alarm")} earlier`;
  b.title = "Anomalies in the last minute, and the worst of them; click for the list";
}

function ago(at) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - at));
  return s < 60 ? `${s} s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : new Date(at * 1000).toLocaleTimeString();
}

function renderAlarms() {
  if ($("alarms").hidden) return;
  setKids($("alarm-list"), S.alarms.length ? S.alarms.map((x, i) => ({ x, i })).reverse().map(({ x, i }) =>
    h("button", { type: "button", "aria-pressed": S.alarmSel === i ? "true" : "false", onclick: () => { S.alarmSel = i; renderAlarms(); } },
      h("span", { class: "sev sev-" + x.a.severity }, x.a.severity),
      h("span", { class: "what" }, `${x.robot}: ${x.a.anomaly}, ${x.a.summary || ""}`),
      h("span", { class: "faint" }, ago(x.at)))) : h("div", { class: "dim" }, "No alarm since this page opened."));
  renderAlarmInspector();
}

function renderAlarmInspector() {
  const x = S.alarms[S.alarmSel];
  if (!x) { setKids($("alarm-insp")); return; }
  const a = x.a;
  const where = a.where || {};
  const row = (k, v) => (v == null || v === "" ? null : [h("dt", {}, k), h("dd", {}, String(v))]);
  const values = Object.entries(a.values || {}).filter(([k]) => k !== "margin_unit")
    .map(([k, v]) => `${k} ${typeof v === "object" ? JSON.stringify(v) : v}`);
  setKids($("alarm-insp"),
    h("h3", {}, `${a.anomaly} `, h("span", { class: "sev-" + a.severity }, a.severity)),
    h("div", {}, a.summary || ""),
    h("dl", {},
      row("robot", x.robot), row("goal run", x.goal_run != null ? "#" + x.goal_run : null),
      row("since", `${new Date(x.at * 1000).toLocaleTimeString()}${a.t != null ? `, ${a.t} s into the run` : ""}${a.duration_s ? `, for ${a.duration_s} s` : ""}`),
      row("from", `${a.source || "robot"}: ${a.module || "?"} (${a.detector || "?"})`),
      row("margin", a.margin != null ? `${a.margin} ${(a.values || {}).margin_unit || "m"} past its limit` : null),
      row("where (belief)", where.belief ? where.belief.join(", ") + " m, " + (where.frame || "map") : null),
      row("where (truth)", a.truth ? a.truth.slice(0, 2).map((v) => Number(v).toFixed(2)).join(", ") + " m, the simulator's" : null),
      row("values", values.join("; "))),
    h("div", { class: "row" },
      h("button", { class: "btn danger", type: "button", id: "alarm-stop", onclick: guard(async () => {
        const j = await api("POST", `/robots/${x.robot}/stop`, { client: "page" });
        toast(j.stop.confirmed ? `${x.robot} stopped.` : `${x.robot}: STOP sent, but the robot did not answer, so it cannot be confirmed.`, !j.stop.confirmed);
      }) }, `STOP ${x.robot}`),
      x.goal_run != null ? h("button", { class: "btn", type: "button", onclick: guard(() => loadRunDetail(x.goal_run)) }, "Show the run") : null,
      momentLink(runKeyOf(x.watch), a.t, x.watch ? h("a", { class: "btn", href: x.watch, target: "_blank", rel: "noopener" }, "Open in the Observatory at this moment") : null)));
}

$("alarm").addEventListener("click", () => {
  if (routeId() != null) {          // the robot page has no alarm panel: its Overview has the card
    goTab("overview");
    setOpen($("rp-alarms-head"), true);
    $("rp-alarms-head").focus();
    return;
  }
  const p = $("alarms");
  p.hidden = !p.hidden;
  $("alarm").setAttribute("aria-expanded", String(!p.hidden));
  if (!p.hidden && S.alarmSel == null && S.alarms.length) S.alarmSel = S.alarms.length - 1;
  renderAlarms();
});
setInterval(() => { if (S.alarms.length) { renderAlarmBadge(); renderAlarms(); } }, 5000);

function onAnomaly(e) {
  const x = { robot: e.robot, goal_run: e.goal_run, watch: e.watch, at: e.t, a: e.anomaly || {} };
  if (S.alarms.some((y) => alarmKey(y) === alarmKey(x))) return;
  S.alarms.push(x);
  if (S.alarms.length > ALARM_KEEP) { S.alarms.shift(); if (S.alarmSel != null) S.alarmSel = Math.max(0, S.alarmSel - 1); }
  renderAlarmBadge();
  renderAlarms();
  renderRobotPage();
  if (detail && e.goal_run === detail.id) {
    const box = $("run-anomalies");
    if (box) box.append(anomalyLine(e.anomaly || {}));
  }
}

function anomalyLine(a) {
  return h("div", {}, h("span", { class: "sev-" + a.severity }, a.severity), ` ${a.anomaly}: ${a.summary || ""}`);
}

let debounce = {};
function later(key, fn, ms) { clearTimeout(debounce[key]); debounce[key] = setTimeout(() => guard(fn)(), ms); }

function onEvent(e) {
  if (e.kind !== "state") logLine(e);
  const r = S.robots.find((x) => x.id === e.robot);
  switch (e.kind) {
    case "state":
      if (r) {
        r.state_at = Date.now();
        r.status = { pose: e.pose, velocity: e.velocity, mode: e.mode, battery_pct: e.battery_pct, link: e.link, flags: e.flags, joints: e.joints, sensors: e.sensors, program: e.program };
        later("robots-render", async () => renderRobots(), 150); requestDraw();
        if (routeId() === r.id) { paintBody(r); later("robot-facts", () => paintFacts(S.robots.find((x) => x.id === r.id) || r), 150); }
      }
      break;
    case "map":
      if (e.robot === S.robot) { S.map = e.map; requestDraw(); }
      break;
    case "robot-online": case "robot-offline": case "lock": case "stop": case "stop-all":
      later("robots", loadRobots, 150);
      break;
    case "goal-run":
      later("runs", async () => { await loadRuns(); if (TERMINAL.includes(e.state)) await loadRobots(); if (S.site && !((S.sites.find((s) => s.id === S.site) || {}).dock_pose)) await loadSites(); }, 120);
      break;
    case "decision":
      if (detail && e.goal_run === detail.id) {
        const d = $("decisions");
        if (d) { d.append(h("div", {}, e.text)); d.scrollTop = d.scrollHeight; }
      }
      break;
    case "anomaly":
      onAnomaly(e);
      break;
    case "objects": case "object-named":
      if (e.site === S.site) later("site", loadSite, 200);
      break;
    default:
  }
}

function connect() {
  const es = new EventSource(API + "/events" + (S.token ? "?token=" + encodeURIComponent(S.token) : ""));
  S.es = es;
  es.onopen = () => {
    S.conn = "live"; paintConn();
    if (S.lastConn === "lost") guard(loadAll)();
    S.lastConn = "live";
  };
  es.onerror = () => { S.conn = "reconnecting"; paintConn(); S.lastConn = "lost"; };
  for (const k of ["state", "map", "robot-online", "robot-offline", "lock", "stop", "stop-all", "goal-run", "decision", "anomaly", "objects", "object-named"]) {
    es.addEventListener(k, (ev) => onEvent(JSON.parse(ev.data)));
  }
}

// --- start -----------------------------------------------------------------------------------------------
function renderAll() { renderRobots(); renderSites(); renderAreas(); renderGoalFields(); renderLibrary(); renderRuns(); renderRunDetail(); renderHint(); requestDraw(); }

async function loadAll() {
  await Promise.all([loadRobots(), loadSites(), loadGoals()]);
  await Promise.all([loadSite(), loadRuns()]);
  renderAll();
}

window.__mc = { S, KIT, freshOf, tickFreshness, renderAreas, renderRobotPage, loadRobots, get body() { return bodyMod; }, toScreen: (x, y) => toScreen(x, y), toWorld: (x, y) => toWorld(x, y), draw, get ready() { return S.ready; } };
async function start() { renderGoalFields(); await loadAll(); connect(); S.ready = true; }
$("token-set").addEventListener("click", guard(async () => {
  S.token = $("token").value.trim();
  try { localStorage.setItem("mc-token", S.token); } catch (e) { /* storage may be off */ }
  $("tokenbox").hidden = true;
  if (S.es) S.es.close();
  await start();
}));
renderRobotPage();
guard(start)();
loadKit();
