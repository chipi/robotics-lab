"""Planning in Mission Control (RFC-0014 §3.4.5, RFC-0030): the site's own words reach the planner, `POST /plan` answers as it always has, a
planner.json beside the robot files is not a robot, and nothing runs. The matcher, the LLM client and the validation of what a model says
are the library missions' and are tested in libs/missions.
Run: cd apps/mission-control && uv run python tests/test_planner.py"""

import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from common import Clock, check, finish, make_mc, robot_file, run_for

from mission_control.api import serve
from mission_control.robots import load_robot_files

with tempfile.TemporaryDirectory() as tmp:
    Path(tmp, "planner.json").write_text(json.dumps({"base_url": "http://x/v1", "model": "m"}))
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
