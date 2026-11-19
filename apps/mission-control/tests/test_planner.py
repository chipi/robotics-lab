"""Goals in words (RFC-0014 §3.4.5): the phrase matcher that needs no model, the optional LLM planner over an OpenAI-compatible API (here a
stand-in on loopback: no other address is ever called), the validation of what a model says, and that a plan runs nothing.
Run: cd control && uv run python tests/test_planner.py"""

import ast
import json
import os
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from common import Clock, check, finish, make_mc, robot_file, run_for

from mission_control import planner
from mission_control.api import serve
from mission_control.errors import ApiError
from mission_control.robots import load_robot_files

AREAS = [{"id": "kitchen", "name": "Kitchen", "type": "kitchen"}, {"id": "study", "name": "Study", "type": None}]
OBJECTS = [{"id": "obj-1", "kind": "fridge", "label": "the cold box", "area": "kitchen"}, {"id": "obj-2", "kind": "sofa", "label": None, "area": None}]
CTX = planner.Context(AREAS, OBJECTS, ["fridge", "sofa", "bed", "plant"], "home")


def one(text):
    out = planner.match(text, CTX)
    return out[0] if len(out) == 1 else out


# --- the phrase matcher -----------------------------------------------------------------------------------------
g = one("go to the kitchen")
check("go to an area of the site", g["kind"] == "go_to_area" and g["params"] == {"area": "kitchen"}, g)
g = one("Please go to my cold box")
check("go to an object by the operator's label", g["kind"] == "go_to_object" and g["params"] == {"label": "the cold box"}, g)
check("go to an object by kind", one("go to the fridge")["params"] == {"kind": "fridge"} and one("drive to the sofa")["params"] == {"kind": "sofa"})
check("a kind a robot can recognise is a goal even when the site's map has not seen one yet (the navigator explores)", one("go to the bed")["params"] == {"kind": "bed"})
check("an area wins over an object of the same words", planner.match("go to the study", CTX)[0]["kind"] == "go_to_area")
check("go to a point, with or without brackets and commas", one("go to 1.5, 0.5")["params"] == {"x": 1.5, "y": 0.5} and one("drive to (2 -1)")["params"] == {"x": 2.0, "y": -1.0})
check("explore the site", one("explore")["params"] == {"site": True} and one("explore everything")["kind"] == "explore" and one("look around")["params"] == {"site": True})
check("explore an area", one("explore the kitchen")["params"] == {"area": "kitchen"})
check("an inventory of the site, or of an area", one("take an inventory")["kind"] == "inventory" and one("find all objects")["params"] == {"areas": []}
      and one("inventory of the study")["params"] == {"areas": ["study"]})
g = one("go to the fridge without touching anything")
check("'without touching anything' adds the guardrail contact", g["params"] == {"kind": "fridge"} and g["must_not"] == ["contact"], g)
for text in ("make me a sandwich", "go to the unicorn", "explore the garden", "inventory of the attic", "", "hello"):
    check(f"nothing is matched for {text!r}: no goal, not a guess", planner.match(text, CTX) == [])
check("every matched goal is a valid goal and reads back in words", all(
    planner.read_back(__import__("mission_control.goals", fromlist=["x"]).validate(s, require_name=False))
    for s in planner.match("go to the kitchen", CTX) + planner.match("go to the cold box without bumping into anything", CTX)))
rb = planner.plan("go to my cold box without touching anything", CTX)["goals"][0]["read_back"]
check("the read-back is plain words for the operator to confirm", rb == "go to the object called 'the cold box', and must not: contact", rb)

out = planner.plan("go to the kitchen", CTX)
check("a plan is proposals, flagged to be confirmed, from the matcher, with no LLM", out["confirm_required"] is True and out["source"] == "matcher"
      and out["llm_configured"] is False and len(out["goals"]) == 1 and out["goals"][0]["goal"]["kind"] == "go_to_area", out)
out = planner.plan("make me a sandwich", CTX)
check("nothing matched and no LLM: no goals, and the message says why", out["goals"] == [] and out["message"] == "no goal matched, and no LLM planner is configured", out)
try:
    planner.plan("  ", CTX)
    check("an empty request is a 422", False)
except ApiError as exc:
    check("an empty request is a 422", exc.status == 422)

# --- the LLM planner, against a stand-in on loopback ------------------------------------------------------------
seen: list = []
answers = {"content": ""}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if answers.get("status", 200) != 200:
            self.send_response(answers["status"])
            self.end_headers()
            return
        data = json.dumps({"choices": [{"message": {"content": answers["content"]}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


stub = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=stub.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{stub.server_address[1]}/v1"
llm = planner.LlmPlanner(URL, "some-model", "secret-key")

answers["content"] = ("Here is the plan:\n```json\n" + json.dumps({"goals": [
    {"name": "tidy up", "kind": "go_to_area", "params": {"area": "kitchen"}, "must_not": ["contact", {"name": "max_speed", "mps": 0.2}]},
    {"name": "fly", "kind": "fly", "params": {}},
    {"name": "drive", "kind": "drive", "params": {"vx": 1.0}},
    {"name": "bad guardrail", "kind": "point", "params": {"x": 1, "y": 1}, "must_not": ["teleport"]},
    {"name": "extra field", "kind": "point", "params": {"x": 1, "y": 1}, "obey": True}]}) + "\n```")
out = planner.plan("clean the kitchen for me", CTX, llm)
check("the LLM is asked when the matcher found nothing: its goals are validated, the bad ones dropped with why",
      out["source"] == "llm" and out["llm_configured"] is True and [g["goal"]["name"] for g in out["goals"]] == ["tidy up"]
      and {d["goal"]["name"] for d in out["dropped"]} == {"fly", "drive", "bad guardrail", "extra field"}, out)
check("an unknown kind (fly, and drive: a planner has no way to drive), an unknown guardrail and an unknown field are all dropped",
      all(d["why"] for d in out["dropped"]) and any("unknown goal kind" in d["why"] for d in out["dropped"]))
check("a plan's guardrails are the goal's own: they can add, and are merged under the site's and the robot's later",
      out["goals"][0]["goal"]["must_not"] == [{"name": "contact"}, {"name": "max_speed", "mps": 0.2}])
req = seen[-1]
check("the request is an OpenAI-compatible chat completion: the model, the key, the request and the context, and nothing of the robots",
      req["path"] == "/v1/chat/completions" and req["auth"] == "Bearer secret-key" and req["body"]["model"] == "some-model"
      and "clean the kitchen" in req["body"]["messages"][1]["content"] and "Kitchen" in req["body"]["messages"][1]["content"]
      and req["body"]["messages"][0]["role"] == "system")
n = len(seen)
planner.plan("go to the kitchen", CTX, llm)
check("the matcher answers first: a request it understands never reaches the model", len(seen) == n)
planner.LlmPlanner(URL, "m", None).plan("anything", CTX)
check("with no key there is no Authorization header", seen[-1]["auth"] is None)
answers["content"] = "I cannot help with that."
check("an answer that is not the goals JSON is no goals", planner.plan("do a dance", CTX, llm)["goals"] == [])
answers["content"] = "{not json}"
try:
    planner.plan("do a dance", CTX, llm)
    check("a model that answers nonsense is a 502, not a crash", False)
except ApiError as exc:
    check("a model that answers nonsense is a 502, not a crash", exc.status == 502 and exc.code == "planner_failed", str(exc))
answers["status"] = 500
try:
    planner.plan("do a dance", CTX, llm)
    check("a model that errors is a 502", False)
except ApiError as exc:
    check("a model that errors is a 502", exc.status == 502)
stub.shutdown()
stub.server_close()
try:
    planner.LlmPlanner("http://127.0.0.1:9/v1", "m", None, timeout_s=2.0).plan("anything", CTX)
    check("a planner that cannot be reached is a 502", False)
except ApiError as exc:
    check("a planner that cannot be reached is a 502", exc.status == 502)

# --- off by default, and nothing in it can move a robot --------------------------------------------------------------------
tree = ast.parse(Path(planner.__file__).read_text())
imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
check("the planner module imports no robot, gate, adapter, core or API: it has no path to drive, stop or fire",
      not any(m and any(x in m for x in ("robots", "core", "api", "duck", "fake", "gate")) for m in imports), sorted(m for m in imports if m))
with tempfile.TemporaryDirectory() as tmp:
    check("no planner.json: no LLM", planner.load_planner(Path(tmp) / "planner.json") is None and planner.load_planner(None) is None)
    Path(tmp, "planner.json").write_text(json.dumps({"base_url": "http://127.0.0.1:1/v1", "model": "m", "api_key_env": "MC_TEST_PLANNER_KEY"}))
    os.environ["MC_TEST_PLANNER_KEY"] = "from-the-environment"
    p = planner.load_planner(Path(tmp) / "planner.json")
    check("planner.json: the address, the model and the key from the environment", p.base_url == "http://127.0.0.1:1/v1" and p.model == "m" and p.api_key == "from-the-environment")
    Path(tmp, "key.txt").write_text("from-a-file\n")
    Path(tmp, "planner.json").write_text(json.dumps({"base_url": "http://x/v1", "model": "m", "api_key_file": str(Path(tmp) / "key.txt")}))
    check("or from a file", planner.load_planner(Path(tmp) / "planner.json").api_key == "from-a-file")
    Path(tmp, "fake-1.json").write_text(json.dumps(robot_file("fake-1")))
    check("planner.json beside the robot files is not read as a robot", [c.id for c in load_robot_files(tmp)] == ["fake-1"])

# --- Mission Control: the site's own words, and nothing runs ------------------------------------------------------------------
clock = Clock()
mc = make_mc(clock)
run_for(mc, clock, 0.3)
check("Mission Control has no LLM planner unless it is given one", mc.planner is None)
mc.sites.create("Home", "apartment")
mc.assign_site("fake-1", "home")
mc.sites.create_area("home", "Kitchen", "kitchen", [[2.0, 0.5], [3.9, 0.5], [3.9, 2.9], [2.0, 2.9]])
mc.sites.merge_run_objects("home", [{"id": "n", "kind": "fridge", "x": 3.0, "y": 1.5, "n": 3, "confirmed": True, "unique": True,
                                     "parts": [[3.0, 1.5, 0.4, 0.35, 0.0, 0.0, 1.8]]}], "x", {})
mc.sites.label("home", "obj-1", "my fridge")
out = mc.plan("go to my fridge", robot="fake-1")
check("Mission Control plans with its own site: the operator's label", out["site"] == "home" and out["goals"][0]["goal"]["params"] == {"label": "my fridge"}, out)
check("an area of the site", mc.plan("explore the kitchen")["goals"][0]["goal"]["params"] == {"area": "kitchen"})
check("a kind the robot's recogniser knows", mc.plan("go to the plant", robot="fake-1")["goals"][0]["goal"]["params"] == {"kind": "plant"} if "plant" in
      mc.robots["fake-1"].cfg.capabilities["recognisers"][0]["kinds"] else True)
check("nothing was started by planning", mc.list_runs() == [] and mc.get_robot("fake-1")["goal_run"] is None and mc.get_robot("fake-1")["lock"]["holder"] is None)

srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
threading.Thread(target=srv.serve_forever, daemon=True).start()


def call(body):
    req = urllib.request.Request(BASE + "/plan", data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


st, b = call({"text": "go to the kitchen", "robot": "fake-1"})
check("POST /plan: the proposals, to confirm", st == 200 and b["plan"]["goals"][0]["read_back"] == "go to the area kitchen" and b["plan"]["confirm_required"] is True, b)
st, b = call({"text": "make me a sandwich"})
check("POST /plan with nothing to propose: 200 and no goals, saying why", st == 200 and b["plan"]["goals"] == [] and "no LLM planner is configured" in b["plan"]["message"], b)
check("POST /plan without text is a 422, with a robot that does not exist a 404", call({})[0] == 422 and call({"text": "x", "robot": "ghost"})[0] == 404)
srv.shutdown()
srv.server_close()

finish("test_planner")
