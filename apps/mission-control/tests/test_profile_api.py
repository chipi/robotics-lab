"""A robot's profile versions through Mission Control's API (phase 5 step 1, RFC-0023 D10): the view (which version runs, the
store's versions), a save as the next version (the store seeded from the robot's own file first), going back, the diff, export and
import into another machine's store, and the refusals: a robot file that holds the robot itself has no versions; a save the
installation would not run is refused saying what to change, nothing written; an invalid profile and a tampered export are refused.
A pointer to the duck's profile behind the fake adapter: no gate, no simulator.
Run: cd apps/mission-control && uv run python tests/test_profile_api.py"""

import atexit
import copy
import json
import os
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from common import FAKE_FILE, check, finish, installation_file

from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig
from runfile import installation

tmp = Path(tempfile.mkdtemp(prefix="mc-profile-"))
atexit.register(shutil.rmtree, tmp, True)
REPO_PROFILE = Path(__file__).resolve().parents[3] / "robots" / "duck" / "profile.json"
REPO = json.loads(REPO_PROFILE.read_text())
STATE = tmp / "inst-state"
FOLDER = STATE / "profiles" / "duck"
inst = tmp / "installation.json"


def write_installation(profile):
    installation_file(inst, {"duck": {"profile": str(profile)}} if profile else {}, state=str(STATE))


write_installation(None)
os.environ[installation.ENV] = str(inst)
mc = MissionControl([RobotConfig({"id": "duck-1", "robot": "duck", "variant": "sim", "adapter": {"type": "fake"}}),
                     RobotConfig(FAKE_FILE)], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
threading.Thread(target=srv.serve_forever, daemon=True).start()


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


v = call("GET", "/robots/duck-1/profile")["profile"]
check("the view: the robot's own file runs (no profile named), no versions yet, and why it cannot be written",
      v["running"]["path"] == str(REPO_PROFILE) and v["versions"] == [] and v["writable"] is False
      and "robots.duck.profile" in v["why_not"] and v["profile"] == REPO, {k: v[k] for k in ("running", "writable", "why_not")})
v2 = copy.deepcopy(REPO)
v2["locomotion"]["cruise_mps"] = 0.25
r = call("POST", "/robots/duck-1/profile", {"profile": v2})
check("must fail: a save the installation would not run is refused, saying what to set, and nothing is written",
      r["error"]["code"] == "profile_not_writable" and str(FOLDER) in r["error"]["message"] and not FOLDER.exists(), r)
r = call("GET", "/robots/fake-1/profile")
check("a robot file that holds the robot itself has no profile versions", r["error"]["code"] == "no_profile", r)

write_installation(FOLDER)
r = call("POST", "/robots/duck-1/profile", {"profile": v2})
check("a save: the store seeded with the robot's own file (1), the change saved as 2 and made current, from the next goal",
      r.get("saved", {}).get("version") == 2 and r["saved"]["applies"] == "from the next goal"
      and json.loads((FOLDER / "1.json").read_text()) == REPO and (FOLDER / "current").read_text().strip() == "2", r)
v = call("GET", "/robots/duck-1/profile")["profile"]
check("the view now: version 2 runs (the store's), two versions listed, writable",
      v["current"] == 2 and v["running"]["path"] == str(FOLDER / "2.json") and [x["version"] for x in v["versions"]] == [1, 2]
      and v["writable"] is True and v["profile"]["locomotion"]["cruise_mps"] == 0.25, {k: v[k] for k in ("current", "running")})
r = call("POST", "/robots/duck-1/profile", {"profile": v2})
check("saving the same again is refused: no version that changes nothing", r["error"]["code"] == "profile" and "nothing to save" in r["error"]["message"], r)
bad = copy.deepcopy(REPO)
bad["locomotion"]["cruise_mps"] = 0.9
r = call("POST", "/robots/duck-1/profile", {"profile": bad})
check("an invalid profile is refused with the validator's reason, nothing written",
      r["error"]["code"] == "profile" and "not a valid profile" in r["error"]["message"] and sorted(p.name for p in FOLDER.glob("*.json")) == ["1.json", "2.json"], r)
d = call("GET", "/robots/duck-1/profile/diff?a=1&b=2")["diff"]
check("the diff of 1 and 2: the one number changed", d["changes"] == [{"path": "locomotion.cruise_mps", "a": REPO["locomotion"]["cruise_mps"], "b": 0.25}], d)
r = call("PUT", "/robots/duck-1/profile/current", {"version": 1})
check("going back: version 1 current again", r["profile"]["current"] == 1 and call("GET", "/robots/duck-1/profile")["profile"]["current"] == 1, r)
r = call("PUT", "/robots/duck-1/profile/current", {"version": 7})
check("going to a version that does not exist is refused", r["error"]["code"] == "profile" and "no such version" in r["error"]["message"], r)

v3 = copy.deepcopy(REPO)
v3["capabilities"]["description"] = "the duck, version 3"
call("POST", "/robots/duck-1/profile", {"profile": v3})
check("Mission Control's view of the robot follows a version it saves, with no restart",
      call("GET", "/robots/duck-1")["robot"]["capabilities"]["description"] == "the duck, version 3")
call("PUT", "/robots/duck-1/profile/current", {"version": 1})
check("... and one it goes back to", call("GET", "/robots/duck-1")["robot"]["capabilities"]["description"] == REPO["capabilities"]["description"])
fast = copy.deepcopy(REPO)
fast["rates"]["state_hz"] = 20.0
r = call("POST", "/robots/duck-1/profile", {"profile": fast})
check("must fail: a profile whose state rate is above the robot's limit is refused, nothing written, the view unchanged",
      r["error"]["code"] == "profile" and "above the robot's limit" in r["error"]["message"]
      and sorted(p.name for p in FOLDER.glob("*.json")) == ["1.json", "2.json", "3.json"]
      and call("GET", "/robots/duck-1")["robot"]["capabilities"]["description"] == REPO["capabilities"]["description"], r)

exp = call("GET", "/robots/duck-1/profile/export?version=2")["export"]
check("an export: version 2, its checksum, the profile", exp["version"] == 2 and exp["profile"] == v2 and exp["checksum"].startswith("sha256:"), exp["checksum"])
shutil.rmtree(STATE / "profiles")                 # another machine: an empty store
r = call("POST", "/robots/duck-1/profile/import", {"export": exp})
check("import into an empty store: seeded (1), the export saved as 2 and current", r["imported"] == {"robot": "duck", "version": 2, "current": 2}, r)
tampered = copy.deepcopy(exp)
tampered["profile"]["locomotion"]["cruise_mps"] = 0.2
r = call("POST", "/robots/duck-1/profile/import", {"export": tampered})
check("must fail: an export changed on the way is refused, nothing written",
      r["error"]["code"] == "profile" and "does not match" in r["error"]["message"] and sorted(p.name for p in FOLDER.glob("*.json")) == ["1.json", "2.json"], r)

noted = copy.deepcopy(v2)
noted["locomotion"]["why"] = "walked slower on the rug"
r = call("POST", "/robots/duck-1/profile", {"profile": noted})
check("a change of a note alone is a new version (the checksum covers the notes, the operator's decision b)",
      r.get("saved", {}).get("version") == 3, r)
d = call("GET", "/robots/duck-1/profile/diff?a=2&b=3")["diff"]
check("must fail: the diff of two versions that differ only in a note says so, not an empty list that reads as the same",
      d["changes"] == [] and d["only_notes"] is True and d["notes_changed"] == 1, d)
d = call("GET", "/robots/duck-1/profile/diff?a=2&b=3&notes=1")["diff"]
check("... and with notes it shows the note", d["changes"] == [{"path": "locomotion.why", "a": None, "b": "walked slower on the rug"}], d)
d = call("GET", "/robots/duck-1/profile/diff?a=1&b=2")["diff"]
check("a diff of values is not only notes", d["only_notes"] is False and d["notes_changed"] == 0, d)

srv.shutdown()
srv.server_close()
mc.close()
finish("test_profile_api")
