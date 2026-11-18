"use strict";
/* Mission Control's page (RFC-0014 step 1). Plain JS, no build, no library. Everything it does is a call of the API
   in CONTRACT.md and the event stream; nothing works only here. Data goes into the page by textContent, never as HTML. */

const API = "/api/v1";
const $ = (id) => document.getElementById(id);
const ARM_MS = 6000; // a delete needs a second press within this long
const TERMINAL = ["reached", "done", "refused", "failed", "stopped_by_guardrail", "not_found", "cancelled", "interrupted"];

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
  mode: "point", draft: [], target: null, ready: false, es: null, lastConn: null, armed: null, token: null,
};

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

let toastTimer = null;
function toast(msg, err) {
  const t = $("toast");
  t.textContent = msg; t.className = err ? "err" : ""; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, err ? 7000 : 3500);
}
const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };

// --- theme -----------------------------------------------------------------------------------------------
function effectiveTheme() {
  return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
}
try { const t = localStorage.getItem("mc-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* storage may be off */ }
try { S.token = localStorage.getItem("mc-token") || null; } catch (e) { /* storage may be off */ }
$("theme").addEventListener("click", () => {
  const next = effectiveTheme() === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("mc-theme", next); } catch (e) { /* ignore */ }
  requestDraw();
});

// --- loading ---------------------------------------------------------------------------------------------
const robot = () => S.robots.find((r) => r.id === S.robot) || null;

async function loadRobots() {
  const list = (await api("GET", "/robots")).robots;
  S.robots = await Promise.all(list.map(async (r) => (await api("GET", "/robots/" + r.id)).robot));
  if (!robot() && S.robots.length) await selectRobot(S.robots[0].id, true);
  renderRobots();
}

async function refreshRobot(id) {
  const i = S.robots.findIndex((r) => r.id === id);
  if (i < 0) return loadRobots();
  S.robots[i] = (await api("GET", "/robots/" + id)).robot;
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

function renderRobots() {
  const box = $("robot-list");
  box.replaceChildren(...S.robots.map((r) => {
    const st = r.status || {}, p = st.pose;
    return h("button", { class: "robot", type: "button", id: "robot-" + r.id, "data-online": String(r.online), "aria-pressed": String(r.id === S.robot),
      onclick: guard(() => selectRobot(r.id)) },
      h("div", { class: "name" }, h("span", { class: "dot" + (r.online ? " on" : "") }), r.label, " ", h("span", { class: "faint mono" }, r.id)),
      h("div", { class: "kv" },
        h("span", {}, "", h("b", { class: "online" }, r.online ? "online" : "offline")),
        h("span", {}, "lock ", h("b", { class: "lock" }, lockText(r))),
        h("span", {}, "mode ", h("b", {}, st.mode || "-")),
        h("span", {}, "battery ", h("b", {}, st.battery_pct != null ? st.battery_pct + "%" : "-")),
        h("span", {}, "pose ", h("b", { class: "mono" }, p ? `${p.x.toFixed(2)}, ${p.y.toFixed(2)}` : "-")),
        h("span", {}, "site ", h("b", {}, r.site || "none")),
        r.goal_run ? h("span", {}, "run ", h("b", {}, "#" + r.goal_run)) : null));
  }));
  const r = robot();
  $("stop-robot").textContent = r ? "STOP " + r.id : "STOP";
  $("stop-robot").disabled = !r;
}

// --- sites and areas -------------------------------------------------------------------------------------
function renderSites() {
  const sel = $("site-sel");
  sel.replaceChildren(h("option", { value: "" }, "(no site)"), ...S.sites.map((s) => h("option", { value: s.id }, `${s.name} (${s.kind})`)));
  sel.value = S.site || "";
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
  if (!S.site) { box.replaceChildren(h("div", { class: "dim" }, "Pick a site for this robot to see and draw its areas.")); return; }
  if (!S.areas.length) { box.replaceChildren(h("div", { class: "dim" }, "No areas yet: " + "none defined.")); return; }
  box.replaceChildren(h("ul", { class: "list" }, S.areas.map((a) => {
    // Armed in S, not in the button: a redraw of the list (an event, a refresh) must not disarm it.
    const armed = S.armed && S.armed.id === a.id && Date.now() < S.armed.until;
    const del = h("button", { class: "btn sm danger", type: "button", "data-area": a.id, "data-action": "delete", onclick: guard(async () => {
      if (!(S.armed && S.armed.id === a.id && Date.now() < S.armed.until)) {
        const mine = { id: a.id, until: Date.now() + ARM_MS };
        S.armed = mine;
        setTimeout(() => { if (S.armed === mine) { S.armed = null; renderAreas(); } }, ARM_MS);
        renderAreas();
        return;
      }
      S.armed = null;
      await api("DELETE", `/sites/${S.site}/areas/${a.id}`); await loadSite();
    }) }, armed ? "Sure?" : "Delete");
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
  renderHint(); requestDraw();
}

function renderHint() {
  const r = robot();
  $("maphint").textContent = S.mode === "draw"
    ? `Drawing an area: tap the map to place corners (${S.draft.length} so far; at least 3), then name it and save.`
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
  if ($("g-name").value.trim()) goal.name = $("g-name").value.trim();
  if ($("g-folder").value.trim()) goal.folder = $("g-folder").value.trim();
  return goal;
}

$("g-run").addEventListener("click", guard(async () => {
  const r = robot();
  if (!r) throw new Error("No robot.");
  const j = await api("POST", "/goal-runs", { goal: formGoal(), robots: [r.id], ...(S.site ? { site: S.site } : {}) });
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
      h("button", { class: "btn sm primary", type: "button", "data-action": "run-plan", onclick: guard(async () => {
        const j = await api("POST", "/goal-runs", { goal: x.goal, robots: [r.id], ...(S.site ? { site: S.site } : {}) });
        S.run = j.run.id; await Promise.all([loadRuns(), refreshRobot(r.id)]);
        if (j.run.state === "refused") toast("Refused: " + j.run.reason, true);
      }) }, "Run"))),
    p.goals.length ? null : h("div", { class: "dim", id: "plan-none" }, p.message),
    p.dropped.length ? h("div", { class: "faint", style: "font-size:12px" }, `${p.dropped.length} part(s) of the plan were not valid goals and were dropped.`) : null);
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
  const box = $("goal-list");
  if (!S.goals.length) { box.replaceChildren(h("div", { class: "dim" }, "Nothing saved yet. Define a goal and press Save to library, or save a run.")); return; }
  const folders = new Map();
  for (const g of S.goals) { if (!folders.has(g.folder)) folders.set(g.folder, []); folders.get(g.folder).push(g); }
  box.replaceChildren(...[...folders].map(([folder, goals]) => h("div", {},
    h("div", { class: "folder" }, folder ? folder + "/" : "/"),
    h("ul", { class: "list" }, goals.map((g) => h("li", { "data-goal": g.id },
      h("div", { class: "row" },
        h("span", { class: "grow" }, h("b", {}, g.name), " ", h("span", { class: "dim" }, goalSummary(g))),
        h("button", { class: "btn sm primary", type: "button", "data-action": "run", onclick: guard(async () => {
          const r = robot();
          const j = await api("POST", `/goals/${g.id}/runs`, { robots: [r.id], ...(S.site ? { site: S.site } : {}) });
          S.run = j.run.id; await Promise.all([loadRuns(), refreshRobot(r.id)]);
          if (j.run.state === "refused") toast("Refused: " + j.run.reason, true);
        }) }, "Run"),
        h("button", { class: "btn sm danger", type: "button", "data-action": "delete", onclick: guard(async () => {
          await api("DELETE", `/goals/${g.id}`); await loadGoals();
        }) }, "Delete"))))))));
}

// --- runs ------------------------------------------------------------------------------------------------
function renderRuns() {
  $("run-list").replaceChildren(...(S.runs.length ? S.runs.map((r) => h("button", { class: "run", type: "button", "data-run": r.id, "aria-pressed": String(r.id === S.run),
    onclick: guard(async () => { S.run = r.id; renderRuns(); await loadRunDetail(r.id); }) },
    `#${r.id} ${r.goal.name} `, h("span", { class: "state " + r.state }, r.state))) : [h("div", { class: "dim" }, "No goal runs for this robot yet.")]));
}

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
    h("h3", {}, `Run #${r.id} `, h("span", { class: "state " + r.state, id: "run-state" }, r.state), " ", watch),
    r.reason ? h("div", { class: "dim", id: "run-reason" }, r.reason) : null,
    h("div", { class: "kv", id: "run-progress" },
      h("span", {}, "elapsed ", h("b", {}, pr.elapsed_s != null ? pr.elapsed_s + " s" : "-")),
      h("span", {}, "left ", h("b", {}, pr.distance_left_m != null ? pr.distance_left_m + " m" : "-")),
      h("span", {}, "area ", h("b", {}, pr.area || "none")),
      r.as_expected != null ? h("span", {}, "as expected ", h("b", {}, r.as_expected ? "yes" : "no")) : null),
    r.guardrails.length ? h("div", { class: "faint", style: "font-size:12px" }, "must not: " + r.guardrails.map((g) => g.name + (g.mps ? " " + g.mps : "") + (g.seconds ? " " + g.seconds : "")).join(", ")) : null,
    r.broken ? h("div", { class: "dim" }, "Broken: " + r.broken.detail) : null,
    r.result ? h("pre", { class: "json" }, JSON.stringify(r.result, null, 1)) : null,
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
  ctx.fillStyle = col("--bg-viewport"); ctx.fillRect(0, 0, w, hh);
  V = computeView(w, hh);

  // a 1 m grid
  ctx.strokeStyle = col("--draw-grid"); ctx.lineWidth = 1; ctx.beginPath();
  const [wx0, wy1] = toWorld(0, 0), [wx1, wy0] = toWorld(w, hh);
  for (let x = Math.ceil(wx0); x <= wx1; x++) { const [sx] = toScreen(x, 0); ctx.moveTo(sx, 0); ctx.lineTo(sx, hh); }
  for (let y = Math.ceil(wy0); y <= wy1; y++) { const [, sy] = toScreen(0, y); ctx.moveTo(0, sy); ctx.lineTo(w, sy); }
  ctx.stroke();

  if ($("layer-grid").checked && S.map) {
    const m = S.map, res = m.resolution_m;
    for (let j = 0; j < m.height; j++) for (let i = 0; i < m.width; i++) {
      const v = m.data[j * m.width + i];
      if (v < 0) continue;
      ctx.fillStyle = v >= 50 ? col("--c-occ") : col("--c-free");
      const [sx, sy] = toScreen(m.origin[0] + i * res, m.origin[1] + (j + 1) * res);
      ctx.fillRect(sx, sy, res * V.scale + 0.5, res * V.scale + 0.5);
    }
  }

  ctx.font = "11px " + col("--ui"); ctx.textAlign = "center"; ctx.textBaseline = "middle";
  if ($("layer-areas").checked) {
    for (const a of S.areas) {
      poly(ctx, a.outline); ctx.fillStyle = col("--accent-soft"); ctx.fill();
      ctx.strokeStyle = col("--accent"); ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
      const c = a.outline.reduce((s, p) => [s[0] + p[0] / a.outline.length, s[1] + p[1] / a.outline.length], [0, 0]);
      const [cx, cy] = toScreen(c[0], c[1]);
      ctx.fillStyle = col("--on-accent"); ctx.fillText(a.name, cx, cy - 8);
    }
  }
  if ($("layer-objects").checked) {
    for (const o of S.objects) {
      for (const p of o.parts) {
        const [px, py, hx, hy, yaw] = p, c = Math.cos(yaw), s = Math.sin(yaw);
        const pts = [[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]].map(([dx, dy]) => [px + dx * c - dy * s, py + dx * s + dy * c]);
        poly(ctx, pts);
        ctx.globalAlpha = o.confirmed ? 0.7 : 0.22; ctx.fillStyle = col("--c-box"); ctx.fill(); ctx.globalAlpha = 1;
        ctx.strokeStyle = o.landmark >= 0.7 ? col("--c-plan") : col("--border-strong"); ctx.lineWidth = o.landmark >= 0.7 ? 2 : 1; ctx.stroke();
      }
      const [sx, sy] = toScreen(o.x, o.y);
      ctx.fillStyle = col("--text"); ctx.fillText(o.label || o.kind, sx, sy);
    }
  }
  if (S.draft.length) {
    poly(ctx, S.draft, S.draft.length < 3); ctx.strokeStyle = col("--warn"); ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = col("--warn");
    for (const p of S.draft) { const [sx, sy] = toScreen(p[0], p[1]); ctx.beginPath(); ctx.arc(sx, sy, 4, 0, 7); ctx.fill(); }
  }
  if (S.target) {
    const [sx, sy] = toScreen(S.target[0], S.target[1]);
    ctx.strokeStyle = col("--c-plan"); ctx.lineWidth = 2; ctx.beginPath();
    ctx.moveTo(sx - 8, sy); ctx.lineTo(sx + 8, sy); ctx.moveTo(sx, sy - 8); ctx.lineTo(sx, sy + 8); ctx.stroke();
  }
  const r = robot();
  if (r && r.status && r.status.pose) {
    const p = r.status.pose, [sx, sy] = toScreen(p.x, p.y), rad = Math.max(6, 0.15 * V.scale);
    ctx.fillStyle = r.online ? col("--c-truth") : col("--text-faint"); ctx.beginPath(); ctx.arc(sx, sy, rad, 0, 7); ctx.fill();
    ctx.strokeStyle = col("--text"); ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(sx, sy);
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
  log.prepend(h("div", {}, `${e.seq} ${e.kind}${e.robot ? " " + e.robot : ""}${e.text ? " " + e.text : e.state ? " " + e.state : e.event ? " " + e.event : ""}`));
  while (log.childNodes.length > 60) log.lastChild.remove();
}

let debounce = {};
function later(key, fn, ms) { clearTimeout(debounce[key]); debounce[key] = setTimeout(() => guard(fn)(), ms); }

function onEvent(e) {
  if (e.kind !== "state") logLine(e);
  const r = S.robots.find((x) => x.id === e.robot);
  switch (e.kind) {
    case "state":
      if (r) { r.status = { pose: e.pose, velocity: e.velocity, mode: e.mode, battery_pct: e.battery_pct, link: e.link, flags: e.flags }; later("robots-render", async () => renderRobots(), 150); requestDraw(); }
      break;
    case "map":
      if (e.robot === S.robot) { S.map = e.map; requestDraw(); }
      break;
    case "robot-online": case "robot-offline": case "lock": case "stop": case "stop-all":
      later("robots", loadRobots, 150);
      break;
    case "goal-run":
      later("runs", async () => { await loadRuns(); if (TERMINAL.includes(e.state)) await loadRobots(); }, 120);
      break;
    case "decision":
      if (detail && e.goal_run === detail.id) {
        const d = $("decisions");
        if (d) { d.append(h("div", {}, e.text)); d.scrollTop = d.scrollHeight; }
      }
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
  const conn = $("conn");
  es.onopen = () => {
    conn.textContent = "live"; conn.className = "chip ok";
    if (S.lastConn === "lost") guard(loadAll)();
    S.lastConn = "live";
  };
  es.onerror = () => { conn.textContent = "reconnecting"; conn.className = "chip bad"; S.lastConn = "lost"; };
  for (const k of ["state", "map", "robot-online", "robot-offline", "lock", "stop", "stop-all", "goal-run", "decision", "objects", "object-named"]) {
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

window.__mc = { S, renderAreas, toScreen: (x, y) => toScreen(x, y), toWorld: (x, y) => toWorld(x, y), draw, get ready() { return S.ready; } };
async function start() { renderGoalFields(); await loadAll(); connect(); S.ready = true; }
$("token-set").addEventListener("click", guard(async () => {
  S.token = $("token").value.trim();
  try { localStorage.setItem("mc-token", S.token); } catch (e) { /* storage may be off */ }
  $("tokenbox").hidden = true;
  if (S.es) S.es.close();
  await start();
}));
guard(start)();
