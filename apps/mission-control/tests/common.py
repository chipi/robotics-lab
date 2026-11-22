"""Shared by the tests: the check helper, a fake clock, the fake robot's file, and a Mission Control built
on them. Nothing here touches a real robot or the simulator."""

import copy
import json
import sys
from pathlib import Path

from mission_control.core import MissionControl, TICK_S
from mission_control.robots import RobotConfig

failures: list = []
# the duck's registration (phase 5 step 1): Mission Control has no robot's package installed, so a test names the duck by its file
DUCK_REGISTRATION = Path(__file__).resolve().parents[3] / "robots" / "duck" / "registration.json"


def installation_file(path: Path, robots: dict | None = None, **top) -> Path:
    """A test's own installation file at `path`: the duck registered by its file, each robot's other settings merged in, and the
    top-level keys given (state, observatory, ...). This machine's installation is never read by a test."""
    rs = {"duck": {"registration": str(DUCK_REGISTRATION)}}
    for name, extra in (robots or {}).items():
        rs.setdefault(name, {}).update(extra)
    path.write_text(json.dumps({"installation": 1, **top, "robots": rs}))
    return path


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:200]}]" if detail else ""))
    if not cond:
        failures.append(name)


def finish(label: str) -> None:
    if failures:
        print(f"FAIL {label}: {len(failures)} failed: {failures}")
        sys.exit(1)
    print(f"PASS {label}")


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


FAKE_FILE = {
    "id": "fake-1",
    "label": "Fake robot",
    "kind": "fake",
    "adapter": {"type": "fake"},
    "factsheet": {"typeSpecification": {"seriesName": "Fake robot", "mobileRobotKinematics": "DIFFERENTIAL"},
                  "physicalParameters": {"maximumSpeed": 0.5, "maximumAngularSpeed": 1.5}},
    "control": {"deadman_s": 0.5, "lease_s": 20.0, "takeover": ["operator-laptop"]},
    "capabilities": {
        "sensors": [],
        "recognisers": [{"name": "fake-camera", "kinds": ["fridge", "sofa", "desk", "plant"], "frame": "site"}],
        "localisation": {"frame": "site", "how": "dock"},
        "map": {"kind": "occupancy_grid", "resolution_m": 0.5},
        "navigator": {"goal_kinds": ["point", "go_to_object", "go_to_area", "explore", "inventory"],
                      "conditions": ["within_m", "within_s", "facing_deg"]},
        "guardrails": ["contact", "fall", "drop_clearance", "stuck", "time_limit", "no_go_area", "max_speed"],
        "skills": [],
        "description": "fake",
    },
    "rates": {"state_hz": 2.0, "map_hz": 1.0, "max_state_hz": 10.0},
}


def robot_file(rid: str = "fake-1", **over) -> dict:
    raw = copy.deepcopy(FAKE_FILE)
    raw["id"] = rid
    raw.update(over)
    return raw


def make_mc(clock: Clock, *files, state_dir=None) -> MissionControl:
    configs = [RobotConfig(f) for f in (files or (robot_file(),))]
    return MissionControl(configs, state_dir=state_dir, clock=clock, wall=clock)


def run_for(mc: MissionControl, clock: Clock, seconds: float, until=None, dt: float = TICK_S) -> float:
    """Tick Mission Control `dt` at a time for up to `seconds` of fake time, or until `until()` is true.
    Returns the time spent."""
    spent = 0.0
    while spent < seconds - 1e-9:
        clock.advance(dt)
        spent += dt
        mc.tick()
        if until is not None and until():
            break
    return spent


def run_state(mc: MissionControl, run_id: int) -> str:
    return mc.get_run(run_id)["state"]


def finish_run(mc, clock, run_id, seconds: float = 120.0) -> dict:
    from mission_control.goals import TERMINAL
    run_for(mc, clock, seconds, until=lambda: run_state(mc, run_id) in TERMINAL)
    return mc.get_run(run_id)
