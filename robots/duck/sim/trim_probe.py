"""K1, the crossing's first probe (EXECUTION-PLAN phase 4): a constant yaw trim against the walk's drift.

The duck walks straight at WALK_MPS along a 1 m wide corridor, vyaw a constant TRIM, no steering, truth sampled every tick.
  --drift   a flat floor, WALK_S seconds, TRIALS trials: the heading's slope (rad/s, least squares over the truth yaw) and the
            sideways distance at the end, per TRIM. The trim that cancels the drift is minus the slope at trim 0.
  --bar H   the same walk across a bar H m high (4 cm deep, 0.6 m ahead, three pieces edge to edge as STEPS.md): crossed (the
            trunk 0.25 m past the bar), stalled, or fell, per TRIM, with the heading's slope.

  --nav     with --bar: the navigator's own go_to across the bar (its loop and rules), per DEADBAND (--deadbands, the walk's
            steering deadband in rad, 0 off) instead of per trim: crossed, with how many turn commands over 0.1 rad/s the
            walk made while within 0.5 m of the bar.

Needs the simulator (each trial resets it on its scene, ~40 s). One sim job at a time:

    robots/duck/.venv/bin/python robots/duck/sim/trim_probe.py --drift --trims 0 [--trials 5]
    robots/duck/.venv/bin/python robots/duck/sim/trim_probe.py --bar 0.005 --trims 0,0.05 [--trials 5]
    robots/duck/.venv/bin/python robots/duck/sim/trim_probe.py --bar 0.005 --nav --deadbands 0,0.2 [--trials 5]
"""

import argparse
import json
import math
import time
import types

from duck_lab.challenge.scene import Scene, mjcf, slab, wall
from duck_lab.nav import simreset
from duck_lab.nav.evaluate import FALLEN_Z_M
from duck_lab.nav.follow import Twist
from duck_lab.nav.run import Navigator

BAR_X, BAR_DEEP_M, TICK_S, STUCK_M, STUCK_S, START_S = 0.6, 0.04, 0.1, 0.02, 3.0, 6.0
LENGTH_M = 4.0


def scene(h: float | None, k: int) -> Scene:
    walls = [wall("w_s", -0.6, -0.5, LENGTH_M, -0.5, height=0.5), wall("w_n", -0.6, 0.5, LENGTH_M, 0.5, height=0.5),
             wall("w_w", -0.6, -0.5, -0.6, 0.5), wall("w_e", LENGTH_M, -0.5, LENGTH_M, 0.5, height=0.5)]
    if h is None:
        floors = [slab("floor", -0.6, LENGTH_M, -0.5, 0.5)]
    else:
        floors = [slab("start", -0.6, BAR_X, -0.5, 0.5), slab("threshold", BAR_X, BAR_X + BAR_DEEP_M, -0.5, 0.5, top=h),
                  slab("after", BAR_X + BAR_DEEP_M, LENGTH_M, -0.5, 0.5)]
    return Scene(f"trim-{'flat' if h is None else round(h * 1000)}mm-t{k}", "trim probe", walls, floors, (LENGTH_M - 0.5, 0.0), "reach", 20.0)


def slope(ts: list, ys: list) -> float:
    n, mt, my = len(ts), sum(ts) / len(ts), sum(ys) / len(ys)
    den = sum((t - mt) ** 2 for t in ts)
    return sum((t - mt) * (y - my) for t, y in zip(ts, ys)) / den if den else 0.0


def unwrap(yaws: list) -> list:
    out, turns = [], 0.0
    for i, y in enumerate(yaws):
        if i and y - yaws[i - 1] > math.pi:
            turns -= 2 * math.pi
        elif i and y - yaws[i - 1] < -math.pi:
            turns += 2 * math.pi
        out.append(y + turns)
    return out


def trial(h: float | None, trim: float, k: int, speed: float, seconds: float) -> dict:
    sc = scene(h, k)
    simreset.reset(str(mjcf(sc)))
    nav = Navigator(truth=True)
    try:
        past = BAR_X + BAR_DEEP_M + 0.25
        ts, yaws, ys, xs, lowest = [], [], [], [], 1.0
        x0 = nav.body.pose()[0]
        furthest, gained, t0 = x0, time.monotonic(), time.monotonic()
        while time.monotonic() - t0 < seconds:
            nav.move(Twist(speed, trim))
            x, y, yaw = nav.body.pose()
            ts.append(time.monotonic() - t0)
            xs.append(x)
            ys.append(y)
            yaws.append(yaw)
            lowest = min(lowest, nav.body.height)
            if x > furthest + STUCK_M:
                furthest, gained = x, time.monotonic()
            started = furthest > x0 + STUCK_M or time.monotonic() - t0 > START_S
            if h is not None and (furthest > past or lowest < FALLEN_Z_M or (started and time.monotonic() - gained > STUCK_S)):
                break
            if h is None and (x > LENGTH_M - 0.6 or abs(y) > 0.4):
                break
            time.sleep(TICK_S)
        nav.move(Twist())
    finally:
        nav.close()
    yaws = unwrap(yaws)
    moving = [i for i, x in enumerate(xs) if x > x0 + 0.1]
    sl = slope([ts[i] for i in moving], [yaws[i] for i in moving]) if len(moving) > 10 else None
    return {"bar_m": h, "trim_rad_s": trim, "speed_mps": speed, "trial": k, "heading_slope_rad_s": None if sl is None else round(sl, 4),
            "heading_end_rad": round(yaws[-1] - yaws[0], 3), "y_end_m": round(ys[-1], 3), "x_end_m": round(xs[-1], 3),
            "walked_s": round(ts[-1], 1), **({"crossed": furthest > past, "fell": lowest < FALLEN_Z_M} if h is not None else {})}


def nav_trial(h: float, deadband: float, k: int, seconds: float, pace: bool = True) -> dict:
    sc = scene(h, k)
    simreset.reset(str(mjcf(sc)))
    nav = Navigator(truth=True)
    try:
        nav.locomotion.deadband = deadband
        if not pace:
            nav.pace_cfg = types.SimpleNamespace(caution_mps=nav.loco.cruise_mps, look_m=0.7, unknown_reach_m=0.4)
        past = BAR_X + BAR_DEEP_M + 0.25
        x0 = nav.body.pose()[0]
        turns, move = [], nav.move

        def logged(tw, **kw):
            x = nav.body.pose()[0]
            if abs(tw.vyaw) > 0.1 and tw.vx > 0 and abs(x - BAR_X) < 0.5:
                turns.append(round(tw.vyaw, 2))
            return move(tw, **kw)
        nav.move = logged
        t0 = time.monotonic()
        out = nav.go_to((past + 0.4 - x0, 0.0), seconds)
        x = nav.body.pose()[0]
    finally:
        nav.close()
    return {"bar_m": h, "deadband_rad": deadband, "trial": k, "crossed": x > past, "status": out.get("status"), "why": out.get("why"),
            "furthest_m": round(x, 3), "seconds": round(time.monotonic() - t0, 1), "turn_commands_near_bar": len(turns), "pace": pace}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nav", action="store_true")
    ap.add_argument("--no-pace", action="store_true", help="with --nav: the caution pace off (caution = cruise)")
    ap.add_argument("--deadbands", default="0")
    ap.add_argument("--drift", action="store_true")
    ap.add_argument("--bar", type=float, default=None)
    ap.add_argument("--trims", default="0")
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--speed", type=float, default=0.3)
    ap.add_argument("--seconds", type=float, default=15.0)
    a = ap.parse_args()
    if a.drift == (a.bar is not None):
        raise SystemExit("one of --drift or --bar H")
    h = None if a.drift else a.bar
    if a.nav:
        if h is None:
            raise SystemExit("--nav needs --bar H")
        for db in [float(v) for v in a.deadbands.split(",")]:
            rows = []
            for k in range(a.trials):
                rows.append(nav_trial(h, db, k, 60.0, not a.no_pace))
                print(json.dumps(rows[-1]), flush=True)
            print(f"== navigator, deadband {db:g} rad: crossed {sum(r['crossed'] for r in rows)} of {len(rows)}, "
                  f"turn commands near the bar {[r['turn_commands_near_bar'] for r in rows]}", flush=True)
        return
    for trim in [float(v) for v in a.trims.split(",")]:
        rows = []
        for k in range(a.trials):
            r = trial(h, trim, k, a.speed, a.seconds)
            rows.append(r)
            print(json.dumps(r), flush=True)
        sl = [r["heading_slope_rad_s"] for r in rows if r["heading_slope_rad_s"] is not None]
        print(f"== trim {trim:+.3f} rad/s: heading slope mean {sum(sl) / len(sl):+.4f} rad/s over {len(sl)} trials"
              + ("" if h is None else f", crossed {sum(r['crossed'] for r in rows)} of {len(rows)}, fell {sum(r['fell'] for r in rows)}"), flush=True)


if __name__ == "__main__":
    main()
