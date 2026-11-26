"use strict";
/* The robot page's Modules, Settings and Calibration (RFC-0023 D3 and D10). Everything is a call of the profile API in CONTRACT.md: the versions,
   one version's profile (an export), a save, going back, the diff, export and import. Loaded before app.js; it uses app.js's h, icon, fold,
   keepFocus, api, setKids, toast, refreshRobot and S, only when called. The Settings tab is built once per robot visit and is not rebuilt by the
   page's own refresh; the edit form and the history are two drawers, built with it. */

const ST_META = ["measured", "why"];
const ST_SKIP = new Set(["variants", "plugins", "factsheet", "capabilities", "control", "subsystems"]);   // the robot's identity, not its settings
const ST_LOCKED = ["factsheet", "control", "capabilities", "plugins", "subsystems"];                       // listed read only, edited in the file
const ST_BLOCK_OF = { locomotion: "locomotion", range_sensing: "sensors", localisation: "localisation", looking: "looking" };   // RFC-0020 section 4: the block each plugin answers for
const ST_DESC = {
  locomotion: "How the robot walks: speeds, turning, the pivot, the pace, the arc, getting unstuck.",
  joints: "The joints and the limits behind the body alarms (joint_overload, joint_tracking, motor_hot, loop_slow).",
  sensors: "The depth sensor, its mount, and the simulator's camera.",
  localisation: "The map, the odometry, closure and fixes.",
  looking: "Where the head looks while walking.",
};
const ST_UNITS = [[/_mps$/, "m/s"], [/_rad_s$/, "rad/s"], [/_mm$/, "mm"], [/_m$/, "m"], [/_s$/, "s"], [/_deg$/, "deg"], [/_rad$/, "rad"], [/_hz$/, "Hz"],
  [/_ma$/, "mA"], [/_c$/, "deg C"], [/_pct$/, "%"], [/_per_m$/, "per m"]];

const ST = { robot: null, view: null, shown: null, shownProfile: null, pending: null, dirty: false, loading: null, layer: null, block: null,
  form: null, cache: {}, opener: null };

const stObj = (v) => v != null && typeof v === "object" && !Array.isArray(v);
const stNum = (v) => v === null || typeof v === "number";
const stShow = (v) => (v === undefined ? "none" : typeof v === "string" ? v : JSON.stringify(v));
const stUnit = (name) => { const u = ST_UNITS.find(([re]) => re.test(name)); return u ? u[1] : "unitless"; };
const stCell = (v) => {      // a long value is a list or a text: its length, or its start; the cell's title has all of it
  const s = v === undefined ? "not set" : stShow(v);
  return s.length <= 40 ? s : Array.isArray(v) ? `list of ${v.length}` : s.slice(0, 39) + "…";
};

function* stLeaves(o, prefix = "") {          // [path, value] of every non-note leaf; a list is one leaf
  for (const [k, v] of Object.entries(o || {})) {
    if (ST_META.includes(k)) continue;
    if (stObj(v)) yield* stLeaves(v, prefix + k + ".");
    else yield [prefix + k, v];
  }
}

function* stNotes(o, prefix = "") {            // [dict path, {measured, why}] of every dict that carries a note
  if (!stObj(o)) return;
  if (ST_META.some((m) => typeof o[m] === "string")) yield [prefix.replace(/\.$/, ""), { measured: o.measured, why: o.why }];
  for (const [k, v] of Object.entries(o)) if (stObj(v) && !ST_META.includes(k)) yield* stNotes(v, prefix + k + ".");
}

const stGet = (o, path) => path.split(".").reduce((a, k) => (stObj(a) ? a[k] : undefined), o);
function stSet(o, path, v) {
  const ks = path.split(".");
  let at = o;
  for (const k of ks.slice(0, -1)) at = stObj(at[k]) ? at[k] : (at[k] = {});
  if (v === undefined) delete at[ks[ks.length - 1]]; else at[ks[ks.length - 1]] = v;
}
const stMerge = (base, over) => {
  const out = { ...base };
  for (const [k, v] of Object.entries(over || {})) out[k] = stObj(v) && stObj(out[k]) ? stMerge(out[k], v) : v;
  return out;
};

const stVariants = (p) => [...new Set(["sim", "real", ...Object.keys(p.variants || {})])];
function stBlocks(p) {
  const vs = Object.values(p.variants || {}), names = new Set([...Object.keys(p), ...vs.flatMap((v) => Object.keys(v))]);
  return [...names].filter((k) => !ST_SKIP.has(k) && [p[k], ...vs.map((v) => v[k])].some((o) => stObj(o) && [...stLeaves(o)].some(([, x]) => stNum(x))));
}
const stOverrides = (p, variant, block) => [...stLeaves((p.variants?.[variant] || {})[block])].filter(([path, v]) => JSON.stringify(stGet(p[block], path)) !== JSON.stringify(v));
const stRunning = (p, variant) => {
  const run = { ...p };
  for (const [k, v] of Object.entries((p.variants || {})[variant] || {})) run[k] = stObj(v) && stObj(run[k]) ? stMerge(run[k], v) : v;
  return run;
};
const stNext = () => { const n = ST.view.versions.map((x) => x.version); return (n.length ? Math.max(...n) : 1) + 1; };
const stDirOf = (path) => (path.includes(".") ? path.slice(0, path.lastIndexOf(".")) : "");

// --- Modules: the profile's plugins; no source reports a plugin's own state to Mission Control, so each says so -----------------------------------------
function paintModules(r) {
  const box = $("rp-modules-body");
  if (!r.profile) { delete box.dataset.sig; return setKids(box, h("div", { class: "empty" }, "No profile: this robot's file holds the robot itself, so it names no plugins.")); }
  if (!ST.view || ST.robot !== r.id) { delete box.dataset.sig; return setKids(box, h("div", { class: "empty" }, "Loading")); }
  const p = ST.view.profile, variant = ST.view.variant, run = stRunning(p, variant);
  const mods = Object.entries(p.plugins || {}).map(([iface, name]) => {
    const block = ST_BLOCK_OF[iface], ovr = new Set(stOverrides(p, variant, block).map(([path]) => path));
    const all = [...stLeaves(run[block])].filter(([, v]) => !Array.isArray(v));
    return { iface, name, block, ov: ovr.size, vals: all.slice(0, 12).map(([path, v]) => [path, stShow(v), ovr.has(path)]), more: all.length - 12 };
  });
  const sig = JSON.stringify([mods, variant, r.id]);
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  keepFocus(box, () => setKids(box,
    h("div", { class: "modlist" }, mods.map((m, i) => h("section", { class: "card", "data-plugin": m.iface },
      fold("mod:" + m.iface, i === 0,
        [h("b", { class: "mono" }, m.name), h("span", { class: "dim" }, m.block ? `answers for ${m.block}` : "no settings block of its own"), h("span", { class: "sp" }),
          m.ov ? h("span", { class: "badge" }, `${variant} changes ${m.ov}`) : null, h("span", { class: "tag" }, "live state not reported")],
        h("div", {},
          h("div", { class: "kvgrid" }, m.vals.map(([k, v, o]) => h("div", {}, h("span", { class: "mono dim" }, k), h("span", { class: "mono" + (o ? " ovr" : "") }, v)))),
          m.block ? h("div", { class: "prov" }, h("a", { href: hashOf(r.id, "settings"), onclick: () => { ST.block = m.block; if (ST.shownProfile) { stViewer(); stMark(); } } }, `All of ${m.block} in Settings`),
            m.more > 0 ? ` (${m.more} more values there)` : "")
            : h("div", { class: "prov dim" }, "Chosen in the profile's plugins; a run may pick another (lab-challenge --local-controller).")),
        "mhead")))),
    h("div", { class: "hint" }, `Configured, as the ${variant} variant runs them. Mission Control is not told what a plugin does while a goal runs.`)));
}

// --- Calibration (RFC-0023 D11, unit A3): guided procedures through the calibration API, then what the profile says was measured ------------------------------
// A card per procedure; its side drawer holds the step guide, the parameters, the run and what keeping it changes. The page polls while a run runs.
const CAL = { robot: null, data: null, error: null, loading: false, timer: null, proc: null, params: {}, tape: "", sig: null, paintSig: null };
const CAL_PHASE = { running: "running", needs_tape: "waiting for the tape", measured: "measured", refused: "refused", cancelled: "cancelled", interrupted: "interrupted", failed: "failed" };
const CAL_STEP = { settle: "standing still", walk: "walking", stop: "stopping" };
const CAL_WHO = { operator: "you", robot: "robot", runner: "runner" };

async function calLoad() {
  const id = CAL.robot;
  if (!id) return;
  CAL.loading = true;
  try { CAL.data = (await api("GET", `/robots/${id}/calibration`)).calibration; CAL.error = null; }
  catch (e) { if (CAL.robot !== id) return; CAL.data = null; CAL.error = e.message; }
  finally { CAL.loading = false; }
  if (CAL.robot !== id) return;
  paintCalibration(S.robots.find((x) => x.id === id));
  if ($("cal-drawer") && !$("cal-drawer").hidden) calPaint();
  calSchedule();
}

function calSchedule() {          // one poll pending at most: the page repaints on every event, and each repaint must not push the poll back
  if (CAL.data?.run?.phase === "running" && routeTab() === "calibration" && routeId() === CAL.robot) {
    if (!CAL.timer) CAL.timer = setTimeout(() => { CAL.timer = null; calLoad(); }, 1000);
  } else { clearTimeout(CAL.timer); CAL.timer = null; }
}

function calForget() { clearTimeout(CAL.timer); Object.assign(CAL, { robot: null, data: null, error: null, loading: false, timer: null, proc: null, params: {}, tape: "", sig: null, paintSig: null }); }

function calSay(msg, err) {
  const el = $("cal-status");
  if (el) { el.textContent = msg; el.className = "sterr" + (err ? "" : " ok"); }
  toast(msg, err);
}

async function calDo(method, path, body, said) {
  try {
    await api(method, `/robots/${CAL.robot}/calibration${path}`, body);
    if (said) calSay(said);
    await calLoad();
  } catch (e) { calSay(e.message, true); await calLoad(); }
}

async function calStart() {
  const p = CAL.data.procedures.find((x) => x.id === CAL.proc);
  await calDo("POST", "", { procedure: p.id, params: { speed_mps: Number(CAL.params.speed_mps), seconds: Number(CAL.params.seconds) } }, "The robot is starting. Stand clear.");
}

async function calKeep() {
  await calDo("POST", "/keep", {}, null);
  const run = CAL.data?.run;
  if (run?.kept) {
    calSay(`Kept as version ${run.kept.version}: it applies ${run.kept.applies}.`);
    await refreshRobot(CAL.robot);
    await stLoad(CAL.robot);
  }
}

const calFmt = (v) => (v == null ? "none" : typeof v === "number" ? String(v) : stShow(v));

function calStatus(run) {
  if (!run) return "no run yet";
  if (run.phase === "kept") return `kept as version ${run.kept.version}`;
  const text = CAL_PHASE[run.phase] || run.phase;
  return run.value != null ? `${text}: ${run.value}` : run.reason ? `${text}: ${run.reason}` : text;
}

function calCard(p, run) {
  const mine = run && run.procedure === p.id ? run : null;
  return h("section", { class: "card", "data-procedure": p.id },
    h("div", { class: "shead static" }, p.title, h("span", { class: "sp" }), h("span", { class: "chip", "data-cal-current": "" }, `now ${calFmt(p.current)}`),
      h("button", { id: "cal-open-" + p.id, class: "btn primary", type: "button", disabled: !p.available, title: p.available ? null : p.why_not,
        onclick: () => { CAL.proc = p.id; CAL.params = mine && mine.params ? { ...mine.params } : { speed_mps: p.params.speed_mps, seconds: p.params.seconds }; stOpen("cal-drawer"); } },
      mine && mine.phase === "running" ? "Open the run" : "Calibrate")),
    h("div", { class: "cbody" },
      h("p", { class: "dim", style: "margin:0 0 8px" }, p.what),
      h("div", { class: "kvline" }, h("span", { class: "mono dim" }, p.sets), h("span", { class: "sp" }), h("span", { class: "tag", "data-cal-status": "" }, calStatus(mine))),
      p.available ? null : h("div", { class: "hint" }, p.why_not)));
}

function calMeasured(p, r) {
  const rows = [];
  for (const [layer, src] of [["base", p], ...Object.entries(p.variants || {})]) {
    for (const b of Object.keys(src)) {
      if (layer === "base" && b === "variants") continue;
      for (const [path, n] of stNotes(src[b], b + ".")) if (typeof n.measured === "string" && n.measured) rows.push({ path, layer, text: n.measured });
    }
  }
  const when = (t) => (/^(\d{4}-\d{2}-\d{2})/.exec(t) || [])[1] || (/^not measured/i.test(t) ? "not measured" : "no date");
  const by = (t) => (/^[^,]*, Mission Control's calibration procedure (\w+)/.exec(t) || [])[1] || (/[\w./-]+\.py/.exec(t) || [])[0] || "-";
  return h("section", { class: "card" },
    h("div", { class: "shead static" }, "What is measured, and where it came from"),
    rows.length ? h("div", { class: "twrap" }, h("table", { class: "t", id: "cal-table" },
      h("thead", {}, h("tr", {}, ["Values", "Layer", "Measured", "By", "What it says"].map((x) => h("th", {}, x)))),
      h("tbody", {}, rows.map((x) => h("tr", { "data-path": x.path, "data-layer": x.layer },
        h("td", { class: "k" }, x.path), h("td", { class: "v" }, x.layer),
        h("td", { class: when(x.text) === "not measured" || when(x.text) === "no date" ? "na" : "v" }, when(x.text)),
        h("td", { class: "v inh" }, by(x.text)), h("td", { class: "says" }, x.text))))))
      : h("div", { class: "empty" }, "No measured line in this profile."));
}

function paintCalibration(r) {
  const box = $("rp-calibration-body");
  if (!r.profile) return setKids(box, h("div", { class: "empty" }, "No profile: this robot's file holds the robot itself, so nothing is measured here."));
  if (!ST.view || ST.robot !== r.id) return setKids(box, h("div", { class: "empty" }, "Loading"));
  if (CAL.robot !== r.id) { calForget(); CAL.robot = r.id; }
  if (routeTab() === "calibration" && !CAL.data && !CAL.error && !CAL.loading) calLoad();     // asked for only when the tab is looked at
  const sig = JSON.stringify([CAL.data, CAL.error, ST.view.running.checksum, r.id]);
  if (CAL.sig === sig && box.firstChild) return calSchedule();
  CAL.sig = sig;
  const d = CAL.data;
  keepFocus(box, () => setKids(box,
    h("div", { class: "modlist" },
      d ? d.procedures.map((p) => calCard(p, d.run))
        : h("section", { class: "card" }, h("div", { class: "shead static" }, "Procedures"), h("div", { class: "empty", id: "cal-none" }, CAL.error ? `No procedures: ${CAL.error}` : "Loading")),
      calMeasured(ST.view.profile, r))));
  calSchedule();
}

// The drawer: the guide, the parameters, what the run measured, and the buttons the run's phase allows.
const calDrawer = () => stDrawer("cal-drawer", "cal-title", "Calibrate",
  [h("div", { id: "cal-body", class: "calbody" }), h("div", { id: "cal-status", class: "sterr", role: "alert" })],
  h("div", { id: "cal-foot", class: "dfoot" }), "calibration");

// A repaint with nothing new is skipped: rebuilding the foot would drop an armed Keep or Discard between its two presses. Opening forces it.
function calPaint(force) {
  const d = CAL.data, p = d && d.procedures.find((x) => x.id === CAL.proc);
  if (!p) return;
  const sig = JSON.stringify([CAL.proc, d, d.writable ? stNext() : null]);
  if (!force && CAL.paintSig === sig) return;
  CAL.paintSig = sig;
  const run = d.run && d.run.procedure === p.id ? d.run : null, phase = run ? run.phase : null, live = phase === "running";
  setKids($("cal-title"), p.title);
  const steps = (run ? run.steps : p.steps.map((s) => ({ ...s, status: "todo" })));
  const field = (key, label, unit, attrs) => h("div", { class: "frow" }, h("label", { for: "cal-" + key }, label),
    h("input", { id: "cal-" + key, type: "number", step: "any", inputmode: "decimal", "data-fk": "cal:" + key, value: CAL.params[key] ?? "", disabled: live, ...attrs,
      oninput: (ev) => { CAL.params[key] = ev.target.value; } }), h("span", { class: "unit" }, unit));
  const res = run && run.measured ? h("table", { class: "t", id: "cal-result" }, h("tbody", {},
    h("tr", {}, h("td", { class: "k" }, "Odometry read"), h("td", { class: "v" }, `${run.measured.odom_m} m`), h("td", { class: "says" }, "the robot's own, between its two marks")),
    h("tr", {}, h("td", { class: "k" }, "Reference"), h("td", { class: "v", id: "cal-ref" }, run.reference ? `${run.reference.distance_m} m` : "not known yet"),
      h("td", { class: "says" }, run.reference ? (run.reference.by === "truth" ? "the simulator's truth, read by the runner" : "the operator's tape") : "needs your tape reading")),
    h("tr", {}, h("td", { class: "k" }, "Measured"), h("td", { class: "v", id: "cal-value" }, run.value == null ? "none" : String(run.value)), h("td", { class: "says" }, "reference over odometry")),
    h("tr", {}, h("td", { class: "k" }, "Now"), h("td", { class: "v", id: "cal-now" }, calFmt(run.current)), h("td", { class: "says" }, p.sets)))) : null;
  const tape = run && (phase === "needs_tape" || (phase === "measured" && run.reference && run.reference.by === "operator")) ? h("div", { class: "frow", id: "cal-tape-row" },
    h("label", { for: "cal-tape" }, "tape, m"), h("input", { id: "cal-tape", type: "number", step: "any", min: "0", inputmode: "decimal", "data-fk": "cal:tape", value: CAL.tape,
      oninput: (ev) => { CAL.tape = ev.target.value; } }),
    h("button", { id: "cal-tape-use", class: "btn", type: "button", "data-fk": "cal:tape-use", onclick: () => calDo("POST", "/reference", { distance_m: Number(CAL.tape) }, "Tape distance taken.") }, "Use")) : null;
  const writes = run && run.writes.length ? h("div", { class: "diff", id: "cal-writes" }, run.writes.map((w) => h("div", { class: "strow2", "data-path": w.path },
    h("span", { class: "p mono" }, w.path), h("span", { class: "inh" }, stShow(w.from)), h("span", { class: "inh" }, "to"), h("span", { class: "ovr" }, stShow(w.to))))) : null;
  keepFocus($("cal-body"), () => setKids($("cal-body"),
    h("p", { class: "hint", style: "margin:0" }, p.what),
    h("ol", { id: "cal-steps", class: "checks" }, steps.map((s) => h("li", { "data-step": s.id, "data-status": s.status },
      icon(s.status === "done" ? "check" : "dot", s.status === "done" ? "ok" : s.status === "now" ? "now" : "na"),
      h("span", { class: "sr" }, s.status === "done" ? "done: " : s.status === "now" ? "now: " : "to do: "),
      h("span", { class: "what" }, s.text), h("span", { class: "val" }, CAL_WHO[s.who] || s.who)))),
    live ? h("div", { class: "hint", id: "cal-live", "aria-live": "polite" }, `The robot is ${CAL_STEP[run.step] || "starting"}.`) : null,
    run && !live && run.reason ? h("div", { class: "sterr", id: "cal-reason" }, `${CAL_PHASE[phase] || phase}: ${run.reason}`) : null,
    h("div", { class: "stform" }, field("seconds", "seconds", "s", { min: 2, max: 30 }), field("speed_mps", "speed", "m/s", { min: 0.05, max: p.params ? p.params.max_speed_mps : null })),
    res, tape,
    run && run.plausible === false ? h("div", { class: "sterr", id: "cal-implausible" }, `${run.value} is outside ${run.bounds[0]} to ${run.bounds[1]}: the robot was probably blocked or the tape misread. Run it again.`) : null,
    writes ? [h("div", { class: "dim" }, phase === "kept" ? `Kept as version ${run.kept.version}. It changed:` : "Keeping it changes:"), writes] : null));
  const n = d.writable ? stNext() : null;
  setKids($("cal-foot"),
    h("span", { id: "cal-note", class: "note" }, phase === "measured" ? (d.writable ? `Kept as version ${n}. It applies from the next goal, never during one.` : `Cannot be kept here: ${d.why_not}`) : ""),
    live ? h("button", { id: "cal-cancel", class: "btn", type: "button", "data-fk": "cal:cancel", onclick: () => calDo("POST", "/cancel", {}, "Cancel asked: the robot stops.") }, "Cancel the run") : null,
    run && !live && phase !== "kept" ? dangerous(h("button", { id: "cal-discard", class: "btn", type: "button", "data-fk": "cal:discard" }, "Discard"), () => calDo("DELETE", "", undefined, "The run is discarded."), "Press again to discard") : null,
    live ? null : h("button", { id: "cal-start", class: "btn" + (phase === "measured" ? "" : " primary"), type: "button", "data-fk": "cal:start", disabled: !p.available, onclick: calStart }, run ? "Run again" : "Start"),
    phase === "measured" ? dangerous(h("button", { id: "cal-keep", class: "btn primary", type: "button", "data-fk": "cal:keep", disabled: !(run.plausible && d.writable) }, `Keep as version ${n ?? "?"}`), calKeep, "Press again to keep") : null);
}

// --- Settings -----------------------------------------------------------------------------------------------------------------------------------------
function paintProfile(r) {
  if (!r.profile) {
    stForget();
    setKids($("rp-settings-body"), h("div", { class: "empty" }, "No profile: this robot's file holds the robot itself, so it has no versions to edit."));
    paintModules(r);
    return paintCalibration(r);
  }
  if (ST.robot !== r.id) {
    Object.assign(ST, { robot: r.id, view: null, shown: null, shownProfile: null, pending: null, dirty: false, layer: null, block: null, cache: {} });
    stBuild();
    stLoad(r.id);
  } else if (ST.view && !ST.loading && r.profile.checksum !== ST.view.running.checksum) stLoad(r.id);
  paintModules(r);
  paintCalibration(r);
}

function stForget() {
  ST.robot = null; ST.view = null; ST.dirty = false;
  calForget();
  setKids($("drawer-root"));
  document.body.classList.remove("modal");
}

function stBuild() {
  setKids($("rp-settings-body"),
    h("div", { class: "toolbar" },
      h("label", { class: "toggle" }, "Version ", h("select", { id: "st-version", class: "sel", "aria-label": "Version shown", onchange: (ev) => stAct(() => stShow_(Number(ev.target.value))) })),
      h("span", { id: "st-runs", class: "chip" }, h("span", {})),
      h("label", { class: "toggle" }, h("input", { id: "st-only-overridden", type: "checkbox", onchange: stViewer }), "only what a variant changes"),
      h("span", { class: "sp" }),
      h("button", { id: "st-history-open", class: "btn", type: "button", onclick: () => stOpen("st-history") }, icon("history"), "History and compare"),
      h("input", { id: "st-import-file", type: "file", accept: "application/json,.json", "aria-label": "Import a profile version from a file", onchange: stImport }),
      h("label", { class: "btn ghost stfile", for: "st-import-file" }, "Import"),
      h("button", { id: "st-export", class: "btn ghost", type: "button", onclick: () => stAct(() => stExport(ST.shown)) }, "Export")),
    h("div", { id: "st-writable", class: "hint" }),
    h("div", { class: "hint" }, h("span", { id: "st-shown" }), " ", h("span", { id: "st-summary" })),
    h("div", { id: "st-status", class: "hint", "aria-live": "polite" }),
    h("div", { class: "settings" }, h("nav", { id: "st-blocks", class: "blist", "aria-label": "Blocks" }), h("div", { id: "st-pane", class: "stpane" })));
  setKids($("drawer-root"), stEditDrawer(), stHistoryDrawer(), calDrawer());
}

function stDrawer(id, titleId, title, body, foot, tab = "settings") {
  return h("div", { id, class: "scrim", "data-tab": tab, hidden: true, onclick: (ev) => { if (ev.target === ev.currentTarget) stClose(); } },
    h("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
      h("div", { class: "dhead" }, h("h3", { id: titleId }, title), h("button", { class: "btn icon ghost", type: "button", "aria-label": "Close", onclick: stClose }, icon("close"))),
      h("div", { class: "dbody" }, body), foot));
}

const stEditDrawer = () => stDrawer("st-edit", "st-edit-title", "Edit",
  [h("div", { class: "layerrow" }, h("span", { id: "st-layer-label", class: "dim" }, "Layer"), h("div", { id: "st-edit-layer", class: "seg", role: "group", "aria-labelledby": "st-layer-label" })),
    h("div", { id: "st-edit-from", class: "hint" }),
    h("div", { id: "st-form", class: "stform" }),
    h("div", { id: "st-drawer-status", class: "sterr", role: "alert" })],
  h("div", { class: "dfoot" }, h("span", { id: "st-save-note", class: "note" }),
    h("button", { id: "st-cancel", class: "btn", type: "button", onclick: stClose }, "Cancel"),
    h("button", { id: "st-save", class: "btn primary", type: "button", onclick: stSave }, "Save")));

const stHistoryDrawer = () => stDrawer("st-history", "st-history-title", "History and compare",
  [h("ul", { id: "st-versions", class: "list vlist" }),
    h("div", { class: "cmp" }, h("b", {}, "Compare"), h("select", { id: "st-diff-a", class: "sel", "aria-label": "From version", onchange: stDiff }), h("span", { class: "inh" }, "to"),
      h("select", { id: "st-diff-b", class: "sel", "aria-label": "To version", onchange: stDiff }),
      h("label", { class: "toggle" }, h("input", { id: "st-diff-notes", type: "checkbox", onchange: stDiff }), "with measured and why")),
    h("div", { id: "st-diff-out", class: "stdiff", "aria-live": "polite" })],
  null);

// A drawer opens over a scrim, takes the focus, keeps Tab inside, and closes on Esc, the close button, the scrim or Cancel; the focus goes back to
// the button that opened it (found by its id at that time: the pane behind may have been rebuilt).
const stOpenDrawer = () => document.querySelector("#drawer-root .scrim:not([hidden])");

function stOpen(id) {
  const el = $(id);
  if (!el) return;
  ST.opener = (document.activeElement && document.activeElement.id) || ST.opener;
  if (id === "st-edit") stForm();
  else if (id === "cal-drawer") { setKids($("cal-status")); calPaint(true); }
  else {
    const n = ST.view.versions.map((x) => x.version);
    stVersions(true);
    if (n.length > 1) { $("st-diff-a").value = n[n.length - 2]; $("st-diff-b").value = n[n.length - 1]; stDiff(); }
  }
  el.hidden = false;
  document.body.classList.add("modal");
  (el.querySelector("[data-autofocus]") || el.querySelector("button")).focus();
}

function stCloseDrawers() {
  for (const d of document.querySelectorAll("#drawer-root .scrim")) d.hidden = true;
  document.body.classList.remove("modal");
}

function stClose() {
  const was = !!stOpenDrawer();
  ST.dirty = false;
  stCloseDrawers();
  const back = was && ST.opener && $(ST.opener);
  if (back) back.focus();
}

document.addEventListener("keydown", (ev) => {
  const d = stOpenDrawer();
  if (!d) return;
  if (ev.key === "Escape") { ev.preventDefault(); stClose(); return; }
  if (ev.key !== "Tab") return;
  const f = [...d.querySelectorAll("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]")].filter((e) => e.offsetParent !== null);
  if (!f.length) return;
  const at = document.activeElement;
  if (!d.contains(at) || (ev.shiftKey && at === f[0])) { ev.preventDefault(); f[f.length - 1].focus(); }
  else if (!ev.shiftKey && at === f[f.length - 1]) { ev.preventDefault(); f[0].focus(); }
});

async function stLoad(id) {
  const run = (async () => {
    const view = (await api("GET", `/robots/${id}/profile`)).profile;
    if (ST.robot !== id) return;
    ST.view = view;
    const have = view.versions.map((v) => v.version);
    if (!have.includes(ST.shown)) ST.shown = view.current;
    await stShownProfile();
    stRender();
    if (CAL.robot === id && CAL.data) calLoad();       // a saved version changes the value a procedure shows as now
  })();
  ST.loading = run;
  try { await run; } catch (e) { stSay(`The profile could not be loaded: ${e.message}`, true); } finally { if (ST.loading === run) ST.loading = null; }
}

async function stShownProfile() {
  const v = ST.view, n = ST.shown;
  if (n == null || n === v.current) { ST.shownProfile = v.profile; return; }
  const sum = v.versions.find((x) => x.version === n).checksum;
  if (ST.cache[n]?.checksum !== sum) ST.cache[n] = (await api("GET", `/robots/${ST.robot}/profile/export?version=${n}`)).export;
  ST.shownProfile = ST.cache[n].profile;
}

function stSay(msg, err) {
  for (const id of ["st-status", "st-drawer-status"]) {
    const el = $(id);
    if (el) { el.textContent = msg; el.className = (id === "st-status" ? "hint" : "sterr") + (err ? " err" : ""); }
  }
  toast(msg, err);
}

function stRender() {
  const v = ST.view, p = ST.shownProfile;
  setKids($("st-writable"), v.writable ? "This machine keeps the versions: a save is written to its store." : `Versions cannot be written here: ${v.why_not}`);
  $("st-save").disabled = !v.writable;
  $("st-import-file").disabled = !v.writable;
  $("st-export").disabled = ST.shown == null;
  const nums = v.versions.map((x) => x.version);
  setKids($("st-version"), nums.length ? [...nums].reverse().map((n) => h("option", { value: n, selected: n === ST.shown }, `version ${n}${n === v.current ? " (current)" : ""}`))
    : h("option", { value: "" }, "the robot's own file"));
  $("st-version").disabled = !nums.length;
  setKids($("st-runs").firstChild, "runs the ", h("b", {}, v.variant), " variant");
  ST.layer ||= v.variant;
  const blocks = stBlocks(p), all = [...blocks, ...ST_LOCKED.filter((k) => p[k] !== undefined)];
  ST.block = all.includes(ST.block) ? ST.block : blocks[0];
  stNav(p, blocks);
  stViewer();
  if (!$("st-edit").hidden && (!ST.dirty || ST.form?.version !== ST.shown)) stForm();
  stVersions();
  const keep = (id, d) => { const c = Number($(id).value); return nums.includes(c) ? c : d; };
  const a = keep("st-diff-a", nums[Math.max(0, nums.length - 2)]), b = keep("st-diff-b", nums[nums.length - 1]);
  for (const [id, cur] of [["st-diff-a", a], ["st-diff-b", b]]) setKids($(id), nums.map((n) => h("option", { value: n, selected: n === cur }, `version ${n}`)));
  $("st-diff-a").disabled = $("st-diff-b").disabled = nums.length < 2;
  paintModules(S.robots.find((x) => x.id === ST.robot));
  paintCalibration(S.robots.find((x) => x.id === ST.robot));
}

function stVersions(force) {          // skipped when nothing changed, so a reload between its two presses keeps Make current armed
  const v = ST.view, box = $("st-versions");
  const sig = JSON.stringify([v.versions, v.writable, ST.pending, ST.shown]);
  if (!force && box.dataset.sig === sig && box.firstChild) return;
  box.dataset.sig = sig;
  if (!v.versions.length) return setKids(box, h("li", { class: "dim" }, `No versions yet: the robot's own file runs (${v.running.path}). The first save keeps it as version 1 and saves the change as version 2.`));
  keepFocus(box, () => setKids(box, [...v.versions].reverse().map((x) => h("li", { class: "vrow", "data-version": x.version, "data-current": String(x.current) },
    h("span", { class: "nm" }, `Version ${x.version}`), h("span", { class: "faint mono" }, x.checksum.slice(7, 19)),
    x.current ? h("span", { class: "cur" }, "current") : null,
    ST.pending === x.version ? h("span", { class: "tag", "data-applies": "" }, "from the next goal") : null,
    ST.shown === x.version ? h("span", { class: "dim" }, "shown") : null,
    h("span", { class: "sp" }),
    h("button", { class: "btn ghost", type: "button", "data-act": "view", "data-fk": `view:${x.version}`, onclick: () => stAct(async () => { await stShow_(x.version); stClose(); }) }, "View"),
    x.current ? null : dangerous(h("button", { class: "btn", type: "button", "data-act": "use", "data-fk": `use:${x.version}`, disabled: !v.writable }, "Make current"), () => stAct(() => stUse(x.version)), "Press again to make current")))));
}

const stAct = async (fn) => { try { await fn(); } catch (e) { stSay(e.message, true); } };

async function stShow_(n) {
  ST.shown = n; ST.dirty = false;
  await stShownProfile();
  stRender();
}

async function stUse(n) {
  await api("PUT", `/robots/${ST.robot}/profile/current`, { version: n });
  ST.pending = n; ST.shown = n; ST.dirty = false;
  stSay(`Version ${n} is current: it applies from the next goal.`);
  await refreshRobot(ST.robot);
  await stLoad(ST.robot);
}

async function stExport(n) {
  const ex = (await api("GET", `/robots/${ST.robot}/profile/export?version=${n}`)).export;
  const a = h("a", { href: URL.createObjectURL(new Blob([JSON.stringify(ex, null, 2) + "\n"], { type: "application/json" })), download: `${ST.view.robot}-profile-v${n}.json` });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

async function stImport(ev) {
  const file = ev.target.files[0];
  ev.target.value = "";
  if (!file) return;
  await stAct(async () => {
    let ex;
    try { ex = JSON.parse(await file.text()); } catch (e) { throw new Error(`${file.name} is not JSON: ${e.message}`); }
    const got = (await api("POST", `/robots/${ST.robot}/profile/import`, { export: ex })).imported;
    ST.pending = got.current; ST.shown = got.current; ST.dirty = false;
    stSay(`Imported ${file.name} as version ${got.version}: it applies from the next goal.`);
    await refreshRobot(ST.robot);
    await stLoad(ST.robot);
  });
}

// --- the blocks, and a version block by block: the base, the running variant, the others ------------------------------------------------------------------
function stNav(p, blocks) {
  const box = $("st-blocks"), run = ST.view.variant;
  const btn = (b, lock) => {
    const n = lock ? 0 : stOverrides(p, run, b).length;
    return h("button", { class: "blk", type: "button", "data-block": b, "data-fk": "blk:" + b, onclick: () => { ST.block = b; stViewer(); stMark(); } },
      h("span", { class: "sp" }, b),
      n ? h("span", { class: "badge", title: `values the ${run} variant overrides` }, n, h("span", { class: "sr" }, ` overridden by the ${run} variant`)) : null,
      lock ? [icon("lock"), h("span", { class: "sr" }, "read only")] : null);
  };
  keepFocus(box, () => setKids(box, h("div", { class: "bhead" }, "Tunable"), blocks.map((b) => btn(b, false)),
    h("div", { class: "bhead" }, "Identity, edited in the file"), ST_LOCKED.filter((k) => p[k] !== undefined).map((b) => btn(b, true))));
  stMark();
}

function stMark() {
  for (const b of document.querySelectorAll("#st-blocks [data-block]")) {
    const on = b.dataset.block === ST.block;
    b.classList.toggle("on", on);
    if (on) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
  }
}

function stViewer() {
  const p = ST.shownProfile, block = ST.block, run = ST.view.variant, pane = $("st-pane");
  setKids($("st-shown"), `${ST.shown == null ? "The robot's own file" : `Version ${ST.shown}${ST.shown === ST.view.current ? ", the current one" : ""}`}, the ${run} variant runs.`);
  const counts = stBlocks(p).map((b) => stOverrides(p, run, b).length).filter((n) => n);
  setKids($("st-summary"), `The ${run} variant (running) overrides ${plural(counts.reduce((a, n) => a + n, 0), "value")} in ${plural(counts.length, "block")}.`);
  const head = (editable, text) => h("div", { class: "bh" }, h("div", {}, h("h2", {}, block), text ? h("p", {}, text) : null), h("span", { class: "sp" }),
    editable ? h("button", { id: "st-edit-open", class: "btn primary", type: "button", disabled: !ST.view.writable, onclick: () => stOpen("st-edit") }, icon("pencil"), `Edit ${block}`) : null);

  if (ST_LOCKED.includes(block)) {
    const v = p[block];
    const rows = Array.isArray(v) ? v.map((x, i) => [stObj(x) && x.name ? x.name : String(i), x]) : [...stLeaves(v)];
    return setKids(pane, head(false, "The robot's identity. It is read here and edited in the profile file, never on this page."),
      h("section", { class: "card", "data-locked": block }, h("div", { class: "twrap" }, h("table", { class: "t wrapv" },
        h("thead", {}, h("tr", {}, h("th", {}, "Value"), h("th", {}, "Set to"))),
        h("tbody", {}, rows.map(([k, x]) => h("tr", {}, h("td", { class: "k" }, k), h("td", { class: "v" }, stShow(x)))))))));
  }

  const vs = stVariants(p), cols = [run, ...vs.filter((x) => x !== run)], only = $("st-only-overridden").checked;
  const paths = new Set([...stLeaves(p[block]), ...vs.flatMap((x) => [...stLeaves((p.variants?.[x] || {})[block])])].map(([k]) => k));
  const rows = [...paths].map((path) => {
    const base = stGet(p[block], path), own = Object.fromEntries(vs.map((x) => [x, stGet((p.variants?.[x] || {})[block], path)]));
    const over = vs.filter((x) => own[x] !== undefined && JSON.stringify(own[x]) !== JSON.stringify(base));
    return { path, base, own, over };
  }).filter((r) => !only || r.over.length);
  const groups = new Map();
  for (const r of rows) { const g = stDirOf(r.path); (groups.get(g) || groups.set(g, []).get(g)).push(r); }
  const notes = new Map();
  for (const [layer, src] of [["base", p[block]], ...vs.map((x) => [x, (p.variants?.[x] || {})[block]])]) {
    for (const [path, n] of stNotes(src, block + ".")) (notes.get(path) || notes.set(path, []).get(path)).push({ layer, ...n });
  }
  const th = (c) => h("th", { class: c === run ? "run" : null, "data-col-head": c }, c === run ? `${c}, running` : c);
  const cards = [...groups].map(([g, list]) => {
    const full = g ? `${block}.${g}` : block, ov = list.filter((r) => r.over.includes(run)).length, lines = notes.get(full) || [];
    return h("section", { class: "card", "data-group": full },
      fold("grp:" + full, true, [h("span", { class: "mono" }, full), h("span", { class: "sp" }), h("span", { class: "sum" }, `${plural(list.length, "value")}${ov ? `, ${run} changes ${ov}` : ""}`)],
        h("div", {},
          h("div", { class: "twrap" }, h("table", { class: "t" },
            h("thead", {}, h("tr", {}, h("th", { class: "kcol" }, "Value"), th("base"), cols.map(th), h("th", {}, "unit"))),
            h("tbody", {}, list.map((r) => h("tr", { "data-path": r.path, "data-overridden": r.over.includes(run) ? run : r.over[0] || false },
              h("td", { class: "k", title: r.path }, r.path.slice(r.path.lastIndexOf(".") + 1)),
              h("td", { class: "v", "data-col": "base", title: stShow(r.base) }, stCell(r.base)),
              cols.map((x) => h("td", { class: "v" + (x === run ? " run" : "") + (r.over.includes(x) ? " ovr" : " inh"), "data-col": x, title: r.over.includes(x) ? stShow(r.own[x]) : null }, r.over.includes(x) ? stCell(r.own[x]) : "=")),
              h("td", { class: "unit" }, stUnit(r.path.slice(r.path.lastIndexOf(".") + 1)).replace("unitless", ""))))))),
          lines.map((n) => h("p", { class: "prov", "data-measured-for": full }, n.measured ? [h("b", {}, `Measured (${n.layer}). `), n.measured] : null,
            n.why ? [n.measured ? " " : null, h("b", {}, `Why (${n.layer}). `), n.why] : null))), "ghead"));
  });
  setKids(pane, head(true, ST_DESC[block]), cards.length ? h("div", { class: "groups" }, cards) : h("div", { class: "card empty" }, only ? "No value here is changed by a variant." : "Nothing to show in this block."));
}

// --- edit a copy: the numbers of one block in one layer, each with its unit; the notes of the dict they sit in ----------------------------------------------
function stForm() {
  const p = ST.shownProfile, block = ST.block, run = ST.view.variant;
  const layers = ["base", ...new Set([...stVariants(p), run])];
  if (!layers.includes(ST.layer)) ST.layer = "base";
  const layer = ST.layer;
  const own = layer === "base" ? p[block] : (p.variants?.[layer] || {})[block];
  const shownIn = layer === "base" ? p[block] : stMerge(p[block] || {}, p.variants?.[layer]?.[block] || {});
  const fields = [...stLeaves(shownIn)].filter(([, v]) => stNum(v));
  const groups = new Map();
  for (const [path, v] of fields) {
    const g = stDirOf(path);
    (groups.get(g) || groups.set(g, []).get(g)).push([path, v]);
  }
  ST.form = { version: ST.shown, layer, block, fields, groups: [...groups.keys()] };
  ST.dirty = false;
  setKids($("st-edit-title"), "Edit ", h("span", { class: "mono" }, block));
  keepFocus($("st-edit-layer"), () => setKids($("st-edit-layer"), layers.map((l) => h("button", { type: "button", "data-layer": l, "data-fk": "layer:" + l, "data-autofocus": l === layer, "aria-pressed": String(l === layer),
    onclick: () => { ST.layer = l; stForm(); } }, l.charAt(0).toUpperCase() + l.slice(1)))));
  setKids($("st-edit-from"), `A copy of ${ST.shown == null ? "the robot's own file" : `version ${ST.shown}`}, in the ${layer === "base" ? "base layer: what every variant starts from" : `${layer} variant${layer === run ? " (running)" : ""}: a field with a value overrides the base, an empty one inherits it`}. Lists and tables are edited in the file.`);
  const n = stNext();
  setKids($("st-save-note"), `Saved as version ${n}. It applies from the next goal, never during one.`);
  setKids($("st-save"), `Save as version ${n}`);
  setKids($("st-drawer-status"));
  const mark = () => { ST.dirty = true; };
  setKids($("st-form"), !fields.length ? h("div", { class: "dim" }, "No numbers in this block.") : [...groups].map(([g, list]) => {
    const dict = stGet(own, g) ?? (g ? undefined : own), full = g ? `${block}.${g}` : block;
    return h("fieldset", { class: "stgroup", "data-group": full },
      h("legend", { class: "mono" }, full),
      list.map(([path, v]) => {
        const key = `${block}.${path}`, name = path.slice(path.lastIndexOf(".") + 1), mine = stGet(own, path);
        return h("div", { class: "stfield", "data-field": key },
          h("div", { class: "frow" },
            h("label", { for: "stf-" + key }, name),
            h("input", { id: "stf-" + key, type: "number", step: "any", inputmode: "decimal", class: layer !== "base" && mine != null ? "set" : null, "data-path": key, "data-orig": mine == null ? "" : String(mine), "aria-describedby": "ste-" + key,
              placeholder: layer === "base" ? null : `= base ${stShow(stGet(p[block], path))}`, value: mine ?? "",
              oninput: (ev) => { mark(); if (layer !== "base") ev.target.classList.toggle("set", ev.target.value.trim() !== ""); } }),
            h("span", { class: "unit", "data-unit-for": key }, stUnit(name))),
          h("div", { id: "ste-" + key, class: "sterr", "data-error-for": key, role: "alert" }));
      }),
      h("div", { "data-notes": full, class: "tx" },
        ST_META.map((m) => h("div", {}, h("label", { for: `stn-${full}-${m}` }, m),
          h("textarea", { id: `stn-${full}-${m}`, rows: m === "why" ? 3 : 2, "data-note": m, "data-orig": dict?.[m] || "", oninput: mark }, dict?.[m] || ""))),
        h("div", { class: "sterr", "data-error-for": full, role: "alert" })));
  }));
}

// the field a server message is about: the longest field or group path the message names, after the validator's own prefix
// ("profile.", "variants.sim merged." or "variants.sim.": which text it checked)
function stWhere(msg) {
  const keys = [...ST.form.fields.map(([path]) => `${ST.form.block}.${path}`), ...ST.form.groups.map((g) => (g ? `${ST.form.block}.${g}` : ST.form.block))];
  const named = keys.filter((k) => new RegExp(`(?:^|[\\s:])(?:profile|variants\\.\\w+(?: merged)?)\\.${k.replace(/\./g, "\\.")}(?![\\w.])`).test(msg)).sort((a, b) => b.length - a.length);
  return named[0] || null;
}

async function stSave() {
  await stAct(async () => {
    const f = ST.form, copy = JSON.parse(JSON.stringify(ST.shownProfile)), at = (path) => (f.layer === "base" ? "" : `variants.${f.layer}.`) + path;
    for (const el of $("st-form").querySelectorAll("input[data-path]")) {
      const raw = el.value.trim();
      if (raw === el.dataset.orig) continue;
      if (raw === "" && f.layer !== "base") stSet(copy, at(el.dataset.path), undefined);
      else stSet(copy, at(el.dataset.path), raw === "" ? null : Number(raw));
    }
    for (const el of $("st-form").querySelectorAll("textarea[data-note]")) {
      if (el.value === el.dataset.orig) continue;
      stSet(copy, at(el.closest("[data-notes]").dataset.notes + "." + el.dataset.note), el.value.trim() || undefined);
    }
    $("st-status").textContent = "";
    $("st-drawer-status").textContent = "";
    for (const el of document.querySelectorAll("#st-form [data-error-for]")) el.textContent = "";
    for (const el of document.querySelectorAll("#st-form input[aria-invalid]")) el.removeAttribute("aria-invalid");
    let saved;
    try { saved = (await api("POST", `/robots/${ST.robot}/profile`, { profile: copy })).saved; }
    catch (e) {
      const k = e.code === "profile" ? stWhere(e.message) : null;
      if (!k) throw e;
      const slot = document.querySelector(`#st-form [data-error-for="${k}"]`);
      slot.textContent = e.message;
      document.querySelector(`#st-form input[data-path="${k}"]`)?.setAttribute("aria-invalid", "true");
      slot.scrollIntoView({ block: "nearest" });
      return stSay("Not saved: the server refused the change, see the field.", true);
    }
    ST.pending = saved.version; ST.shown = saved.version; ST.dirty = false;
    stSay(`Saved as version ${saved.version}: it applies ${saved.applies}.`);
    await refreshRobot(ST.robot);
    await stLoad(ST.robot);
    stClose();
  });
}

let stDiffSeq = 0;      // two quick changes of the selects: only the last answer is shown
async function stDiff() {
  const seq = ++stDiffSeq;
  const a = $("st-diff-a").value, b = $("st-diff-b").value, notes = $("st-diff-notes").checked;
  if (!a || !b) return;
  await stAct(async () => {
    const d = (await api("GET", `/robots/${ST.robot}/profile/diff?a=${a}&b=${b}${notes ? "&notes=1" : ""}`)).diff;
    if (seq !== stDiffSeq) return;
    setKids($("st-diff-out"),
      h("div", { class: "dim" }, `Version ${d.a} to version ${d.b}`),
      d.only_notes ? h("div", {}, `Only notes changed (${plural(d.notes_changed, "note")}): no value differs. Tick "with measured and why" to see them.`) : null,
      !d.changes.length && !d.only_notes ? h("div", {}, "No difference.") : null,
      d.changes.length ? h("div", { class: "diff" }, d.changes.map((c) => h("div", { class: "strow2", "data-path": c.path }, h("span", { class: "p mono" }, c.path), h("span", { class: "inh" }, stShow(c.a)), h("span", { class: "inh" }, "to"), h("span", { class: "ovr" }, stShow(c.b))))) : null,
      !notes && !d.only_notes && d.notes_changed ? h("div", { class: "dim" }, `${plural(d.notes_changed, "note")} also changed.`) : null);
  });
}
