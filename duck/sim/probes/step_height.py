"""How high a bar the duck can walk over (the robot's capability, for the challenges that ask it: RFC-0008 challenge 16,
the operator 2026-11-17: challenges follow the robot's physical limits). A straight 1 m wide corridor with a bar 4 cm
deep across it 0.6 m ahead; the duck walks straight at WALK_MPS until past it, stuck or WALK_S, the truth sampled every tick. Per bar height,
TRIALS trials: crossed (the trunk 0.25 m past the bar), stalled (did not), fell (trunk below evaluate.FALLEN_Z_M).

Needs the simulator (each trial resets it on its scene, ~40 s).

    uv run python sim/probes/step_height.py [0.005 0.01 0.015 0.02] [--trials 5]
"""

import json
import math
import sys
import time
from pathlib import Path

from duck_lab.challenge.scene import Scene, mjcf, slab, wall
from duck_lab.nav import simreset
from duck_lab.nav.evaluate import FALLEN_Z_M
from duck_lab.nav.follow import Twist
from duck_lab.nav.run import Navigator

BAR_X, WALK_MPS, WALK_S, TICK_S = 0.6, 0.3, 30.0, 0.1
YAW_RPS, YAW_HOLD_RAD = 0.0, 0.1   # --yaw: turn while walking (the navigator does, 0.1-0.2 rad/s), the sign flipped to hold the heading within YAW_HOLD_RAD   # it walks ~0.13 m/s: 30 s reaches a 0.5 m-tread flight's top
STUCK_M, STUCK_S, START_S = 0.02, 3.0, 6.0     # no STUCK_M further in STUCK_S: stuck, the trial ends (7 s did not reach a flight's top)


STEP_DEPTH_M, FLIGHT = 0.25, 3     # a flight: FLIGHT steps STEP_DEPTH_M deep (--tread to change: 0.25 caught the next riser)


def floors_for(kind: str, h: float) -> list:
    """The floors of one case, the duck starting on level 0 facing +x, the change at BAR_X: a bar across the way; a step
    up onto a raised floor or down onto a lower one; a flight of FLIGHT steps up or down."""
    start = slab("start", -0.6, BAR_X, -0.5, 0.5)
    if kind == "bar":                # three pieces meeting edge to edge: floor, the bar, floor
        return [start, slab("threshold", BAR_X, BAR_X + 0.04, -0.5, 0.5, top=h), slab("after", BAR_X + 0.04, 3.0, -0.5, 0.5)]
    if kind == "bar_overlap":        # the bar laid on a floor that runs under it (challenge 16 as built): 0 of 12 crossed
        return [slab("floor", -0.6, 3.0, -0.5, 0.5), slab("threshold", BAR_X - 0.02, BAR_X + 0.02, -0.5, 0.5, top=h)]
    if kind in ("up", "down"):
        return [start, slab("beyond", BAR_X, 3.0, -0.5, 0.5, top=h if kind == "up" else -h)]
    sign = 1 if kind == "flight_up" else -1
    steps = [slab(f"step{i}", BAR_X + i * STEP_DEPTH_M, BAR_X + (i + 1) * STEP_DEPTH_M, -0.5, 0.5, top=sign * (i + 1) * h)
             for i in range(FLIGHT)]
    return [start] + steps + [slab("beyond", BAR_X + FLIGHT * STEP_DEPTH_M, 3.0, -0.5, 0.5, top=sign * FLIGHT * h)]


def scene(kind: str, h: float, trial: int) -> Scene:
    walls = [wall("w_s", -0.6, -0.5, 3.0, -0.5, height=0.5 + FLIGHT * h), wall("w_n", -0.6, 0.5, 3.0, 0.5, height=0.5 + FLIGHT * h),
             wall("w_w", -0.6, -0.5, -0.6, 0.5), wall("w_e", 3.0, -0.5, 3.0, 0.5, height=0.5 + FLIGHT * h)]
    return Scene(f"step-{kind}-{round(h * 1000)}mm-t{trial}", "step height probe", walls, floors_for(kind, h), (2.5, 0.0),
                 "reach", 20.0)


def trial(kind: str, h: float, k: int) -> dict:
    sc = scene(kind, h, k)
    simreset.reset(str(mjcf(sc)))
    floors = [f for f in sc.floors if f.name != "threshold"]

    def floor_under(x: float) -> float:
        """The top of the floor under x (the walking floors, the bar left out: it is walked over, not stood on)."""
        return next((f.z1 for f in floors if f.cx - f.hx <= x < f.cx + f.hx), 0.0)

    nav = Navigator(truth=True)
    try:
        past = BAR_X + (FLIGHT * STEP_DEPTH_M if kind.startswith("flight") else 0.0) + 0.25
        x0 = nav.body.pose()[0]
        lowest, furthest, t0 = 1.0, x0, time.monotonic()
        turn = YAW_RPS
        gained = t0                      # when it last got STUCK_M further: it walks ~0.13 m/s, starting included
        while time.monotonic() - t0 < WALK_S and furthest <= past:
            nav.move(Twist(WALK_MPS, turn))
            x, _, yaw = nav.body.pose()
            if abs(yaw) > YAW_HOLD_RAD:
                turn = -math.copysign(YAW_RPS, yaw)
            lowest = min(lowest, nav.body.height - floor_under(x))
            if x > furthest + STUCK_M:
                furthest, gained = x, time.monotonic()
            started = furthest > x0 + STUCK_M or time.monotonic() - t0 > START_S   # 0.15 m/s: not moving after 3 s
            if lowest < FALLEN_Z_M or (started and time.monotonic() - gained > STUCK_S):
                break
            time.sleep(TICK_S)
        nav.move(Twist())
    finally:
        nav.close()
    return {"kind": kind, "height_m": h, "speed_mps": WALK_MPS, "yaw_rps": YAW_RPS, "trial": k, "crossed": furthest > past, "fell": lowest < FALLEN_Z_M,
            "furthest_m": round(furthest, 3), "lowest_trunk_above_floor_m": round(lowest, 3)}


def main() -> None:
    args = sys.argv[1:]
    trials, kinds = 5, ["bar", "up", "down", "flight_up", "flight_down"]
    if "--trials" in args:
        i = args.index("--trials")
        trials, args = int(args[i + 1]), args[:i] + args[i + 2:]
    if "--kinds" in args:
        i = args.index("--kinds")
        kinds, args = args[i + 1].split(","), args[:i] + args[i + 2:]
    if "--speed" in args:
        global WALK_MPS
        i = args.index("--speed")
        WALK_MPS, args = float(args[i + 1]), args[:i] + args[i + 2:]
    if "--yaw" in args:
        global YAW_RPS
        i = args.index("--yaw")
        YAW_RPS, args = float(args[i + 1]), args[:i] + args[i + 2:]
    if "--tread" in args:
        global STEP_DEPTH_M
        i = args.index("--tread")
        STEP_DEPTH_M, args = float(args[i + 1]), args[:i] + args[i + 2:]
    heights = [float(a) for a in args] or [0.005, 0.01, 0.015, 0.02]
    rows = []
    for kind in kinds:
        for h in heights:
            for k in range(trials):
                r = trial(kind, h, k)
                rows.append(r)
                print(json.dumps(r), flush=True)
            hs = [r for r in rows if r["height_m"] == h and r["kind"] == kind]
            print(f"== {kind} {h * 100:.1f} cm: crossed {sum(r['crossed'] for r in hs)} of {len(hs)}, "
                  f"fell {sum(r['fell'] for r in hs)}", flush=True)
    Path("runs").mkdir(exist_ok=True)
    (Path("runs") / "step_height.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
