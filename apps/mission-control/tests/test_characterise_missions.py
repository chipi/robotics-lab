"""Characterisation of what RFC-0030 row 1 moves out (planner, goal schemas, guardrail vocabulary and merge): the answers and error codes
Mission Control gives for goals, plans and guardrails, recorded from the code before the move (`--record`) and compared after it. It
reaches the code only through Mission Control's own routes and methods, and the library's functions through whichever module holds
them, so the same file ran unchanged before and after.
Run: cd apps/mission-control && uv run python tests/test_characterise_missions.py"""

import importlib
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from common import Clock, check, finish, make_mc, robot_file, run_for

from mission_control.api import serve
from mission_control.robots import ConfigError, RobotConfig

GOLDEN = Path(__file__).with_name("characterise_missions.json")


def module(name):
    for pkg in ("missions", "mission_control"):
        try:
            return importlib.import_module(f"{pkg}.{name}")
        except ImportError:
            continue
    raise ImportError(name)


def outcome(fn, *args, **kw):
    try:
        return {"ok": fn(*args, **kw)}
    except Exception as exc:
        if not hasattr(exc, "code"):
            raise
        return {"error": {"code": exc.code, "message": str(exc)}}


def strip(v):
    if isinstance(v, dict):
        return {k: strip(x) for k, x in v.items() if k not in ("created_at", "updated_at", "started_at", "ended_at", "at")}
    if isinstance(v, list):
        return [strip(x) for x in v]
    return v


GOALS = [
    {"name": "to the door", "kind": "point", "params": {"x": 1, "y": 2}},
    {"name": "p", "kind": "point", "params": {"x": 1, "y": 2, "frame": "map"}, "done_when": {"within_m": 0.5}},
    {"name": "fridge", "kind": "go_to_object", "params": {"kind": "fridge", "area": "kitchen"}, "must_not": ["contact", "drop", {"name": "max_speed", "mps": 0.2}]},
    {"name": "fridge by label", "kind": "go_to_object", "params": {"label": " the cold box "}, "folder": "/a//b/", "sim_first": False, "scene": "flat"},
    {"name": "area", "kind": "go_to_area", "params": {"area": "kitchen"}, "expect": "refuse"},
    {"name": "e1", "kind": "explore", "params": {"site": True}, "budget": {"minutes": 2}},
    {"name": "e2", "kind": "explore", "params": {"area": "kitchen"}},
    {"name": "inv", "kind": "inventory"},
    {"name": "inv2", "kind": "inventory", "params": {"areas": ["kitchen", " study "]}, "must_not": [{"name": "no_go_area", "area": "stairwell"}, "contact", "contact"]},
    {"kind": "point", "params": {"x": 0, "y": 0}},
    {"name": "x", "kind": "fetch", "params": {}},
    {"name": "x", "kind": None},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "colour": 1},
    {"name": "x", "kind": "point", "params": {"x": 0}},
    {"name": "x", "kind": "point", "params": {"x": True, "y": 0}},
    {"name": "x", "kind": "point", "params": {"x": "a", "y": 0}},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0, "frame": "world"}},
    {"name": "x", "kind": "point", "params": []},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "budget": {"minutes": 1}},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "expect": "maybe"},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "sim_first": "yes"},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "folder": "../x"},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "folder": 3},
    {"name": "  ", "kind": "point", "params": {"x": 0, "y": 0}},
    {"name": "x", "kind": "go_to_object", "params": {}},
    {"name": "x", "kind": "go_to_object", "params": {"kind": "fridge", "label": "mine"}},
    {"name": "x", "kind": "go_to_object", "params": {"kind": "fridge", "bogus": 1}},
    {"name": "x", "kind": "go_to_area", "params": {"area": "k"}, "done_when": {"within_m": 1}},
    {"name": "x", "kind": "go_to_area", "params": {"area": "k"}, "done_when": {"within_s": -4}},
    {"name": "x", "kind": "go_to_area", "params": {"area": "k"}, "done_when": 3},
    {"name": "x", "kind": "go_to_area", "params": {"area": "k"}, "done_when": {"nope": 1}},
    {"name": "x", "kind": "go_to_area", "params": {}},
    {"name": "x", "kind": "explore", "params": {"area": "k", "site": True}},
    {"name": "x", "kind": "explore", "params": {"site": False}},
    {"name": "x", "kind": "explore", "params": {"area": "k"}, "budget": {"minutes": 0}},
    {"name": "x", "kind": "explore", "params": {"area": "k"}, "budget": {"hours": 1}},
    {"name": "x", "kind": "inventory", "params": {"areas": "kitchen"}},
    {"name": "x", "kind": "inventory", "params": {"zones": []}},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "must_not": "contact"},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "must_not": ["teleport"]},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "must_not": [{"name": "max_speed"}]},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "must_not": [{"name": "max_speed", "mps": -1}]},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "must_not": [{"name": "time_limit", "seconds": True}]},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "must_not": [{"name": "contact", "mps": 1}]},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "must_not": ["no_go_area"]},
    {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "must_not": [3]},
    "not a goal",
]

TEXTS = ["go to the kitchen", "Please go to my cold box", "go to the fridge", "go to the bed", "go to 1.5, 0.5", "drive to (2 -1)", "explore", "explore the kitchen",
         "explore the moon", "inventory", "take an inventory of the kitchen", "what is in the flat", "go to the kitchen without touching anything",
         "make me a sandwich", "  ", "", None, 7]

PLANNER_ANSWER = ("Here is the plan:\n```json\n" + json.dumps({"goals": [
    {"name": "tidy up", "kind": "go_to_area", "params": {"area": "kitchen"}, "must_not": ["contact", {"name": "max_speed", "mps": 0.2}]},
    {"name": "fly", "kind": "fly", "params": {}},
    {"name": "bad guardrail", "kind": "point", "params": {"x": 1, "y": 1}, "must_not": ["teleport"]},
    {"name": "extra field", "kind": "point", "params": {"x": 1, "y": 1}, "obey": True}]}) + "\n```")

answers = {"status": 200, "content": PLANNER_ANSWER}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        if answers["status"] != 200:
            self.send_response(answers["status"])
            self.end_headers()
            return
        data = json.dumps({"choices": [{"message": {"content": answers["content"]}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def build() -> dict:
    rec: dict = {}
    stub = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{stub.server_address[1]}/v1"
    pl = module("planner")
    clock = Clock()
    mc = make_mc(clock, robot_file(guardrails=[{"name": "max_speed", "mps": 0.4}, "contact", "drop"]))
    mc.planner = pl.LlmPlanner(url, "some-model", "secret-key")
    run_for(mc, clock, 0.3)
    mc.sites.create("Home", "apartment")
    mc.assign_site("fake-1", "home")
    mc.sites.create_area("home", "Kitchen", "kitchen", [[2.0, 0.5], [3.9, 0.5], [3.9, 2.9], [2.0, 2.9]])
    mc.sites.create_area("home", "Stairwell", None, [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    mc.sites.merge_run_objects("home", [{"id": "n", "kind": "fridge", "x": 3.0, "y": 1.5, "n": 3, "confirmed": True, "unique": True,
                                         "parts": [[3.0, 1.5, 0.4, 0.35, 0.0, 0.0, 1.8]]}], "x", {})
    mc.sites.label("home", "obj-1", "my fridge")
    srv = serve(mc, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return {"status": r.status, "body": strip(json.loads(r.read()))}
        except urllib.error.HTTPError as exc:
            return {"status": exc.code, "body": strip(json.loads(exc.read()))}

    rec["goals_http"] = [{"in": i, "out": call("POST", "/goals", g)} for i, g in enumerate(GOALS)]
    rec["goal_put"] = [call("PUT", "/goals/1", g) for g in (GOALS[0], GOALS[10], GOALS[41])]
    rec["folders"] = [call("GET", "/goals?folder=" + f) for f in ("a", "a/b", "..", "%2E", "")]
    rec["run_bad_pose"] = [call("POST", "/goal-runs", {"goal": GOALS[0], "robots": ["fake-1"], "start_pose": p})
                           for p in ({"x": 1}, {"x": 1, "y": 2, "yaw": "a"}, {"x": 1, "y": 2, "yaw": 7.0, "frame": "map"}, 3)]
    rec["run_bad_goal"] = call("POST", "/goal-runs", {"goal": GOALS[10], "robots": ["fake-1"]})
    rec["run_bad_guardrail"] = call("POST", "/goal-runs", {"goal": GOALS[40], "robots": ["fake-1"]})

    mc.sites.set_guardrails("home", [{"name": "max_speed", "mps": 0.3}, {"name": "no_go_area", "area": "Stairwell"}])
    for tag, goal in (("loosen", {"name": "g", "kind": "point", "params": {"x": 1, "y": 0}, "must_not": [{"name": "max_speed", "mps": 0.9}, {"name": "time_limit", "seconds": 30}, "contact"]}),
                      ("tighten", {"name": "g", "kind": "point", "params": {"x": 1, "y": 0}, "must_not": [{"name": "max_speed", "mps": 0.1}, {"name": "drop_clearance", "m": 0.2}]}),
                      ("refused_guardrail_not_enforced", {"name": "g", "kind": "point", "params": {"x": 1, "y": 0}})):
        rec["run_" + tag] = call("POST", "/goal-runs", {"goal": goal, "robots": ["fake-1"]})
        run_for(mc, clock, 120.0, until=lambda: not mc.robots["fake-1"].active)
    rec["site_guardrails"] = {"good": outcome(mc.sites.set_guardrails, "home", ["contact", {"name": "no_go_area", "area": "kitchen"}, {"name": "drop_clearance", "m": 0.3}]),
                              "unknown": outcome(mc.sites.set_guardrails, "home", ["teleport"]),
                              "not_a_list": outcome(mc.sites.set_guardrails, "home", "contact"),
                              "no_area": outcome(mc.sites.set_guardrails, "home", [{"name": "no_go_area", "area": "nowhere"}]),
                              "bad_limit": outcome(mc.sites.set_guardrails, "home", [{"name": "time_limit", "seconds": 0}])}
    bundle = mc.sites.export_site("home")
    rec["import"] = {"good": outcome(mc.sites.import_site, "copy", bundle),
                     "bad": outcome(mc.sites.import_site, "copy2", {**bundle, "guardrails": [{"name": "teleport"}]})}

    rec["robot_files"] = {}
    for tag, gr in (("none", None), ("good", [{"name": "max_speed", "mps": 0.2}, "stall"]), ("unknown", ["teleport"]), ("not_list", "contact"),
                    ("bad_limit", [{"name": "time_limit", "seconds": -1}])):
        raw = robot_file("g-" + tag)
        if gr is not None:
            raw["guardrails"] = gr
        try:
            rec["robot_files"][tag] = {"ok": RobotConfig(raw).guardrails}
        except ConfigError as exc:
            rec["robot_files"][tag] = {"config_error": str(exc)}

    rec["plan_http"] = [{"in": t, "out": call("POST", "/plan", {"text": t, "robot": "fake-1"})} for t in TEXTS]
    rec["plan_no_robot"] = call("POST", "/plan", {"text": "go to the kitchen"})
    rec["plan_ghost"] = call("POST", "/plan", {"text": "x", "robot": "ghost"})
    answers["content"] = "no json at all"
    rec["llm_no_json"] = call("POST", "/plan", {"text": "do a dance", "robot": "fake-1"})
    answers["content"] = '{"goals": 3}'
    rec["llm_goals_not_list"] = call("POST", "/plan", {"text": "do a dance", "robot": "fake-1"})
    answers["content"] = "{not json}"
    rec["llm_bad_json"] = call("POST", "/plan", {"text": "do a dance", "robot": "fake-1"})
    answers["status"] = 500
    rec["llm_500"] = call("POST", "/plan", {"text": "do a dance", "robot": "fake-1"})
    stub.shutdown()
    stub.server_close()
    rec["llm_unreachable"] = call("POST", "/plan", {"text": "do a dance", "robot": "fake-1"})
    mc.planner = None
    rec["llm_off"] = call("POST", "/plan", {"text": "do a dance", "robot": "fake-1"})

    gl, gr = module("goals"), module("guardrails")
    rec["direct_validate"] = [outcome(gl.validate, g) for g in GOALS]
    rec["direct_validate_adhoc"] = [outcome(gl.validate, g, require_name=False) for g in GOALS[:3] + [{"kind": "point", "params": {"x": 0, "y": 0}}]]
    rec["direct_version"] = [gl.version(g["ok"]) for g in rec["direct_validate"] if "ok" in g]
    rec["direct_normalise"] = [outcome(gr.normalise, e) for e in ("contact", "drop", "stall", {"name": "max_speed", "mps": 0.2}, "teleport", "max_speed",
                                                                  {"name": "no_go_area", "area": "x"}, "no_go_area", {"name": "contact", "mps": 1}, 3, {"name": 3})]
    rec["direct_normalise_list"] = [outcome(gr.normalise_list, e) for e in (None, ["contact", "contact", "drop"], "contact", [["x"]])]
    levels = {"robot": [{"name": "max_speed", "mps": 0.4}, {"name": "contact"}, {"name": "drop_clearance", "m": 0.3}],
              "site": [{"name": "no_go_area", "area": "a"}, {"name": "max_speed", "mps": 0.3}, {"name": "time_limit", "seconds": 60.0}],
              "goal": [{"name": "max_speed", "mps": 0.9}, {"name": "time_limit", "seconds": 30.0}, {"name": "contact"}, {"name": "no_go_area", "area": "b"},
                       {"name": "drop_clearance", "m": 0.1}]}
    rec["direct_merge"] = [gr.merge(levels), gr.merge({"goal": levels["goal"]}), gr.merge({}), gr.merge({"site": [], "other": [{"name": "contact"}]})]
    rec["direct_levels"] = list(gr.LEVELS)
    rec["direct_names"] = list(gr.NAMES)
    ctx = pl.Context([{"id": "kitchen", "name": "Kitchen", "type": "kitchen"}], [{"id": "obj-1", "kind": "fridge", "label": "the cold box", "area": "kitchen"}],
                     ["fridge", "bed"], "home")
    rec["direct_plan"] = [outcome(pl.plan, t, ctx) for t in TEXTS]
    rec["direct_match"] = [pl.match(t, ctx) for t in TEXTS if isinstance(t, str)]
    srv.shutdown()
    srv.server_close()
    return json.loads(json.dumps(rec))


got = build()
if "--record" in sys.argv:
    GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
    print(f"recorded {GOLDEN.name}: {len(got)} sections")
    sys.exit(0)

want = json.loads(GOLDEN.read_text())
for key in sorted(want):
    check(f"unchanged: {key}", got.get(key) == want[key],
          next((f"{a!r} != {b!r}" for a, b in zip(got.get(key) if isinstance(got.get(key), list) else [got.get(key)],
                                                   want[key] if isinstance(want[key], list) else [want[key]]) if a != b), ""))
check("no section appeared or vanished", sorted(got) == sorted(want), sorted(set(got) ^ set(want)))
finish("test_characterise_missions")
