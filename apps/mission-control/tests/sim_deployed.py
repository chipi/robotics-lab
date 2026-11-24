"""Phase 5 item 4c unit C2, on the real simulator: the DEPLOYED platform's Mission Control (the container `scripts/deploy.py` starts) drives the simulated duck.

    cd apps/mission-control && uv run python tests/sim_deployed.py --commit <sha> --root <a folder of this test's own> \\
        --project robotics-lab-test --viewer-port 18070 --control-port 18060                         # make sim-deployed

NOT in `make test-control`: it resets the simulator (~45 s), builds and starts a stack, moves the duck for about a minute, and needs nobody else using the
simulator (run it under the simulator's lock). It touches only what is under --root, the simulator, and the compose project named: never `robotics-lab`.

What it does: the simulator and the gate (a thread here) and lab-nav-server (a process), as `sim_duck.py` starts them, but in the places an installation file
names for a deployed Mission Control (a folder of the gate's own, the profile store, the navigator on 127.0.0.1); that installation file; then
`scripts/deploy.py up` (the build, the host-network containers, the mounts at the same paths) twice, the second after a token exists (tokens for actions only);
then the page: `scripts/smoke_pages.py --goal-point` opens the Observatory's address /control/, starts a point goal as the page's buttons do, and waits for
`reached`. After it: the run is in the Observatory, from the data folder Mission Control cannot see; the container runs as this user, mounts no data folder, and
the gate's folder holds only the gate."""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from common import check, finish, installation_file

from labrunner.gate import Proxy
import simhost
from simhost.truth import Body
from runfile.profilestore import Store

REPO = Path(__file__).resolve().parents[3]
REAL_DATA = Path("/work/robotics-lab/data")
NAV_PORT = 18061

ap = argparse.ArgumentParser()
ap.add_argument("--commit", required=True, help="the commit deploy.py builds (a sha or a ref of this repository)")
ap.add_argument("--root", type=Path, required=True, help="this test's own folder: data, states, the installation file, the gate's folder")
ap.add_argument("--project", required=True)
ap.add_argument("--viewer-port", type=int, required=True)
ap.add_argument("--control-port", type=int, required=True)
ap.add_argument("--meshes", type=Path, default=Path("/work/robotics-lab/main/robots/duck/meshes"),
                help="the duck's meshes (`make robots` makes them; the repository does not hold them): copied into the duck's folder this test gives the container")
ap.add_argument("--robots-dir", type=Path, help="the descriptions and meshes the Observatory mounts (default: the meshes' robots/ folder)")
args = ap.parse_args()
if args.project == "robotics-lab":
    raise SystemExit("this test deploys a project of its own, never robotics-lab")
ROOT = args.root.resolve()
VIEWER, CONTROL = f"http://127.0.0.1:{args.viewer_port}", f"http://127.0.0.1:{args.control_port}"
DEPLOY = [sys.executable, str(REPO / "scripts" / "deploy.py")]
DEPLOY_ARGS = ["--project", args.project, "--viewer-port", str(args.viewer_port), "--control-port", str(args.control_port),
               "--deploy-state", str(ROOT / "deploy-state"), "--data", str(ROOT / "data"), "--viewer-state", str(ROOT / "viewer-state"),
               "--control-state", str(ROOT / "control-state"), "--installation", str(ROOT / "installation.json"),
               "--control-robots", str(ROOT / "robot-files"), "--robots-dir", str(args.robots_dir or args.meshes.parent.parent)]


def wait_for(cond, timeout, every=0.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(every)
    return None


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


# --- this test's folders and its installation ------------------------------------------------------------------------------------
ROOT.mkdir(parents=True, exist_ok=True)
for sub in ("gate", "robot-files", "nav", "state"):
    (ROOT / sub).mkdir(exist_ok=True)
(ROOT / "data" / "scenes" / "apartment").mkdir(parents=True, exist_ok=True)
(ROOT / "data" / "runs").mkdir(exist_ok=True)
shutil.copy(REAL_DATA / "scenes" / "apartment" / "scene.json", ROOT / "data" / "scenes" / "apartment" / "scene.json")     # a read of the real folder, a copy
for name in ("robots.sim/duck-sim.json", "robots.example/fake-1.json"):
    shutil.copy(REPO / "apps" / "mission-control" / name, ROOT / "robot-files" / Path(name).name)
# the duck's folder as this checkout holds it, with the meshes it does not: the registration's commands made absolute, so the runner starts this checkout's
# navigator (a profile of this checkout needs its code), and the container, which mounts this folder, finds the description and the meshes beside it
DUCK = ROOT / "duck-folder"
DUCK.mkdir(exist_ok=True)
for name in ("profile.json", "robot.json", "robot.urdf"):
    shutil.copy(REPO / "robots" / "duck" / name, DUCK / name)
if not (DUCK / "meshes").exists():
    shutil.copytree(args.meshes, DUCK / "meshes")
reg = json.loads((REPO / "robots" / "duck" / "registration.json").read_text())
for key in ("payload", "navigator_api"):
    reg[key] = [str(REPO / "robots" / "duck" / ".venv" / "bin" / "python"), *reg[key][1:]]
reg["sim"] = str(REPO / "robots" / "duck" / "sim")
(DUCK / "registration.json").write_text(json.dumps(reg, indent=2))
STORE = ROOT / "state" / "profiles"
Store(STORE).seed("duck", DUCK / "profile.json")
GATE = ROOT / "gate" / "gate.sock"
installation_file(ROOT / "installation.json", {"duck": {"registration": str(DUCK / "registration.json"), "navigator": f"127.0.0.1:{NAV_PORT}", "gate": str(GATE),
                                                         "profile": str(STORE / "duck")}}, state=str(ROOT / "state"), observatory=VIEWER)
os.environ["ROBOTICS_LAB_INSTALLATION"] = str(ROOT / "installation.json")       # the runner finds the duck and its version store by it, as the container does

# --- the simulator, the gate, the navigator (as sim_duck.py) ----------------------------------------------------------------------------
HOST = simhost.load()
print("resetting the simulator (robots/duck/sim/reset_sim.py) ...", flush=True)
subprocess.run([str(REPO / "robots" / "duck" / ".venv" / "bin" / "python"), "sim/reset_sim.py"], cwd=REPO / "robots" / "duck", check=True, timeout=400)
body = Body(HOST.truth_port)
proxy = Proxy(GATE, HOST.sockets["robot"], log=ROOT / "gate.jsonl", lease_s=20.0, takeover_names={"operator-laptop"})
proxy.start()
navlog = open(ROOT / "nav-server.log", "w")
nav = subprocess.Popen([sys.executable, "-m", "labrunner.navapi", "--listen", f"127.0.0.1:{NAV_PORT}", "--robot-socket", str(GATE),
                        "--data", str(ROOT / "data"), "--out", str(ROOT / "nav"), "--scene", "apartment"], stdout=navlog, stderr=subprocess.STDOUT)
try:
    check("lab-nav-server is up", wait_for(lambda: "lab-nav-server" in (ROOT / "nav-server.log").read_text(), 60, 0.2) is not None)
    check("the gate's folder holds the gate's socket and nothing else (the container is handed the folder)", sorted(p.name for p in GATE.parent.iterdir()) == ["gate.sock"])

    # --- the deploy, twice: the second with a token, so tokens are for actions only -------------------------------------------------------
    print("\n--- deploy 1: no token exists yet", flush=True)
    r = subprocess.run([*DEPLOY, "up", "--commit", args.commit, "--no-browser", *DEPLOY_ARGS], text=True)
    check("deploy 1 ends PASS (both healthy, the smoke's HTTP part)", r.returncode == 0, r.returncode)
    container = f"{args.project}-mission-control-1"
    made = subprocess.run(["docker", "exec", container, "mission-control", "token", "create", "--client", "page", "--state", "/state"], text=True, capture_output=True)
    token = made.stdout.split(": ")[-1].strip()
    check("a token is made with the command the deploy prints, inside the container", made.returncode == 0 and token.startswith("mc_"), made.stderr)
    print("\n--- deploy 2: the same commit again, now with a token", flush=True)
    r = subprocess.run([*DEPLOY, "up", "--commit", args.commit, "--no-browser", *DEPLOY_ARGS], text=True, capture_output=True)
    print(r.stdout[-1500:])
    check("deploy 2 ends PASS, and says tokens for actions only", r.returncode == 0 and "tokens for actions only" in r.stdout, r.returncode)
    state = json.loads((ROOT / "deploy-state" / f"{args.project}.json").read_text())
    check("the record says the commit is current, and a redeploy of it keeps no false previous", state["current"]["sha"].startswith(args.commit[:12]) and state["previous"] is None, state)

    # --- what the container was given ------------------------------------------------------------------------------------------------
    info = json.loads(subprocess.run(["docker", "inspect", container], text=True, capture_output=True, check=True).stdout)[0]
    mounts = {m["Destination"]: m["RW"] for m in info["Mounts"]}
    check("Mission Control's container runs as this user, on the host's network, with the installation, the gate's folder, the robot's folder and the store mounted",
          info["Config"]["User"] == f"{os.getuid()}:{os.getgid()}" and info["HostConfig"]["NetworkMode"] == "host"
          and mounts.get(str(ROOT / "installation.json")) is False and mounts.get(str(GATE.parent)) is True and mounts.get(str(DUCK)) is False
          and mounts.get(str(STORE)) is True, (info["Config"]["User"], mounts))
    check("it is given no data folder and no index: it reads runs only through the Observatory", not any(str(ROOT / "data") in d or "index" in d for d in mounts), sorted(mounts))
    check("Mission Control reads and lists the duck through the Observatory's address (online, the gate's own lease free)",
          wait_for(lambda: next((x for x in get(VIEWER + "/control/api/v1/robots")["robots"] if x["id"] == "duck-sim" and x["online"]), None), 60) is not None,
          get(VIEWER + "/control/api/v1/robots")["robots"])
    refused = urllib.request.Request(VIEWER + "/control/api/v1/goal-runs", data=json.dumps({"goal": {"kind": "point", "params": {"x": 0.1, "y": 0.0}}, "robots": ["duck-sim"]}).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(refused, timeout=10)
        check("a goal with no token is refused (401)", False)
    except urllib.error.HTTPError as exc:
        check("a goal with no token is refused (401)", exc.code == 401, exc.code)

    # --- the page drives the duck ---------------------------------------------------------------------------------------------------------
    print("\n--- a goal from the deployed page (the Observatory's address, /control/)", flush=True)
    shots = ROOT / "shots"
    page = subprocess.run(["uv", "run", "--project", str(REPO / "apps" / "observatory"), "--frozen", "python", str(REPO / "scripts" / "smoke_pages.py"),
                           "--viewer", VIEWER, "--control", CONTROL, "--token", token, "--goal-point", "1.5,0.5", "--goal-robot", "duck-sim", "--shots", str(shots)],
                          text=True, capture_output=True)
    print(page.stdout[-3000:], page.stderr[-800:])
    goal = next((json.loads(line[5:]) for line in page.stdout.splitlines() if line.startswith("GOAL ")), {})
    check("the page's goal ends reached, and the page logged no error", page.returncode == 0 and goal.get("state") == "reached", goal)
    pose = body.pose()
    check("the simulator's truth agrees: the duck stands within 0.5 m of (1.5, 0.5)", math.dist(pose[:2], (1.5, 0.5)) < 0.5, pose)
    key = goal.get("key")
    run_dir = ROOT / "data" / "runs" / (key or "none")
    check("the run is in the data folder the Observatory reads", bool(key) and any(run_dir.glob("*.mcap")), key)
    seen = wait_for(lambda: get(f"{VIEWER}/api/v1/runs/{key}") if key else None, 60)
    check("the Observatory serves the run Mission Control's goal made, and it carries the goal run", seen is not None and seen.get("key") == key, seen and seen.get("status"))
    check("its Watch link points at the Observatory's own address", (goal.get("watch") or "").startswith(VIEWER + "/watch/"), goal.get("watch"))
    print("\n--- smoke of the whole stack after the run", flush=True)
    r = subprocess.run([*DEPLOY, "smoke", *DEPLOY_ARGS], text=True)
    check("deploy.py smoke passes with the run in place (the watch page of the newest run included)", r.returncode == 0, r.returncode)
finally:
    nav.terminate()
    try:
        nav.wait(10)
    except subprocess.TimeoutExpired:
        nav.kill()
    proxy.stop()
finish("sim_deployed")
