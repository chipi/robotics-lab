#!/usr/bin/env python3
"""Turn one arm's batch of challenge runs into the scores JSONL `evh import-run` reads (one row per scenario), and say whether the batch can
be imported. Read only on the runs; writes only the --out file you name. Starts no simulator, runs no `evh`.

    batch_scores.py robots/duck/runs/c22-ten --out /tmp/rules.scores.jsonl
    batch_scores.py DIR [DIR ...] --dataset /work/robotics-evals/data/datasets/avoidance_v1.json --arm rules --out rules.scores.jsonl
    batch_scores.py DIR --min-items 10 --json

A run is a folder with a result.json (lab-challenge writes it) and its ticks.jsonl. Per run, one row:
  item_id          the frozen dataset's item for the run's scene (with --dataset), else the scene id (then the set is not frozen: said so)
  success          1 when result.json `pass` is true, 0 when false; a run with `pass: null` (no verdict, rtf_low) has no row and fails the batch
  collisions       1 when a failed entry starts with "contact" (the judge records only the FIRST broken invariant), else 0
  falls            1 when a failed entry starts with "fall"
  min_clearance    result.json min_clearance_m
  time_s           the simulator's seconds (clock.sim_s), else the last tick's t
  stops            reflex_stop + cliff_stop events in ticks.jsonl
  stand_still      1 when the pose never got 0.10 m from where it started (the R5 stand-still), else 0
  pivot_fail       1 when the requested command was a pure turn (vx under 0.05, vyaw not 0) for 30 ticks in a row and the pose
                   turned under 0.2 rad over them (R5's pivot stall: yaw clipped under the walker's turn floor), else 0
                   Both need pose ticks; a run without them has neither. Import both with --metric-kind <name>=descriptive.
  _run, _ticks_sha256, _build   metadata (a key starting with `_`): the run's path, the log's hash, the build identity

Checks, each printed: the number of items (--min-items, default 10), a scene run twice, runs not in the dataset, dataset items with no run,
a run with no verdict, and the build identity (every run has one; they agree apart from the trailing -s<sensor seed>; none is dirty).
Ends `BATCH-SCORES PASS` or `FAIL`; exit 0 / 1 (a problem) / 2 (usage). On PASS it prints the `--build-ref` to give `evh import-run`.
Standard library only."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SEED_TAIL = re.compile(r"-s\d+$")
STAND_M = 0.10
PIVOT_VX, PIVOT_TICKS, PIVOT_TURNED_RAD = 0.05, 30, 0.2


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def scene_to_item(dataset: Path) -> dict:
    d = json.loads(dataset.read_text())
    return {it["fields"]["scene"]: it["item_id"] for it in d["items"] if "scene" in (it.get("fields") or {})}


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def ticks_facts(path: Path) -> tuple:
    stops, last_t, start, reach = 0, None, None, 0.0
    pivot_ticks, pivot_yaw, prev_yaw, pivot_fail = 0, 0.0, None, 0
    try:
        with path.open() as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("event") in ("reflex_stop", "cliff_stop"):
                    stops += 1
                if "pose" not in r or r.get("t") is None:
                    continue
                last_t = r["t"]
                x, y, yaw = r["pose"][:3]
                start = start or (x, y)
                reach = max(reach, math.hypot(x - start[0], y - start[1]))
                req = r.get("requested") or {}
                if abs(req.get("vx") or 0) < PIVOT_VX and abs(req.get("vyaw") or 0) > 0:
                    pivot_yaw += abs(wrap(yaw - prev_yaw)) if pivot_ticks else 0.0
                    pivot_ticks += 1
                    if pivot_ticks >= PIVOT_TICKS and pivot_yaw < PIVOT_TURNED_RAD:
                        pivot_fail = 1
                else:
                    pivot_ticks, pivot_yaw = 0, 0.0
                prev_yaw = yaw
    except OSError:
        return None, None, None, None
    if start is None:
        return stops, last_t, None, None
    return stops, last_t, int(reach < STAND_M), pivot_fail


def first_failure(failed: list, word: str) -> bool:
    return any(str(x).startswith(word) for x in failed or [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dirs", nargs="+", type=Path, help="folders searched for result.json (3+ levels allowed)")
    ap.add_argument("--dataset", type=Path, help="the frozen dataset's JSON (robotics-evals data/datasets/<id>.json): scene -> item_id")
    ap.add_argument("--arm", default="arm", help="the arm's name, for the printed command")
    ap.add_argument("--out", type=Path, help="write the scores JSONL here")
    ap.add_argument("--min-items", type=int, default=10)
    ap.add_argument("--json", action="store_true", help="print the checks as JSON")
    a = ap.parse_args()

    results = sorted({p for d in a.dirs for p in d.glob("**/result.json")})
    problems, notes = [], []
    if not results:
        print(f"no result.json under {', '.join(map(str, a.dirs))}", file=sys.stderr)
        return 2
    mapping = scene_to_item(a.dataset) if a.dataset else None
    if mapping is None:
        notes.append("no --dataset: item ids are the scene ids, so the scenario set is NOT frozen; import needs a frozen dataset (evh dataset-create)")

    same_sensor_seed = bool(a.dataset) and "sensor seed = scene seed" in json.loads(a.dataset.read_text()).get("description", "")
    sensor_wrong = []
    by_item = defaultdict(list)
    dirty_of = {}
    novel, no_verdict = [], []
    for p in results:
        r = json.loads(p.read_text())
        scene = r.get("scene")
        item = scene if mapping is None else mapping.get(scene)
        if item is None:
            novel.append(scene)
            continue
        if r.get("pass") is None:
            no_verdict.append((scene, r.get("no_verdict")))
            continue
        ticks = p.parent / "ticks.jsonl"
        stops, last_t, stand_still, pivot_fail = ticks_facts(ticks)
        clock = r.get("clock") or {}
        failed = r.get("failed") or []
        row = {"item_id": item, "success": 1 if r["pass"] else 0, "collisions": 1 if first_failure(failed, "contact") else 0,
               "falls": 1 if first_failure(failed, "fall") else 0}
        if r.get("min_clearance_m") is not None and math.isfinite(r["min_clearance_m"]):
            row["min_clearance"] = r["min_clearance_m"]
        t = clock.get("sim_s", last_t)
        if t is not None:
            row["time_s"] = round(t, 3)
        if stops is not None:
            row["stops"] = stops
        if stand_still is not None:
            row["stand_still"], row["pivot_fail"] = stand_still, pivot_fail
        row["_run"] = str(p.parent)
        if ticks.exists():
            row["_ticks_sha256"] = sha256(ticks)
        if (r.get("build") or {}).get("id"):
            row["_build"] = r["build"]["id"]
        dirty_of[item] = bool((r.get("build") or {}).get("dirty"))
        if same_sensor_seed and r.get("build") and (r["build"].get("tof") == "off" or r["build"].get("seed") != r.get("seed")):
            sensor_wrong.append((r.get("scene"), r["build"].get("tof"), r["build"].get("seed")))
        by_item[item].append((p, row))

    twice = {k: [str(p.parent) for p, _ in v] for k, v in by_item.items() if len(v) > 1}
    rows = [v[-1][1] for k, v in sorted(by_item.items())]      # a scene run twice: the later run's row is shown, and the batch fails

    n = len(rows)
    if n < a.min_items:
        problems.append(f"{n} scenarios, under the {a.min_items} an arm needs for a comparison")
    if sensor_wrong:
        problems.append(f"the dataset says sensor seed = scene seed (depth impairment on), but {len(sensor_wrong)} runs were not run so (scene, tof, seed): {sensor_wrong[:3]}; run with --depth-impairment <first seed>")
    if twice:
        problems.append(f"{len(twice)} scenes ran more than once (a seed is one item, not a repeat): {sorted(twice)[:5]}")
    if novel:
        problems.append(f"{len(novel)} runs are not in the dataset: scenes {sorted(set(novel))[:6]}")
    if no_verdict:
        problems.append(f"{len(no_verdict)} runs have no verdict (pass null: {no_verdict[:3]}); they cannot be scored")
    missing = sorted(set(mapping.values()) - set(by_item)) if mapping is not None else []
    if missing:
        problems.append(f"{len(missing)} dataset items have no run: {missing[:6]}{' ...' if len(missing) > 6 else ''} "
                        f"(evh refuses a missing item unless --allow-subset, which records the coverage)")

    builds = [r.get("_build") for r in rows]
    have = [b for b in builds if b]
    build_ref = None
    if not have:
        problems.append(f"none of the {n} runs records a build identity (they predate ebe0b8a, 2026-11-26): `evh import-run` requires "
                        "--build-ref and a run without one is not imported; re-run the arm to get one")
    else:
        if len(have) < n:
            problems.append(f"{n - len(have)} of {n} runs have no build identity")
        heads = Counter(SEED_TAIL.sub("", b) for b in have)
        if len(heads) > 1:
            problems.append("the runs were not built alike (ids differ beyond the sensor seed): " + "; ".join(f"{k} x{v}" for k, v in heads.items()))
        elif len(have) == n:
            build_ref = next(iter(heads))
        dirty = sum(dirty_of[r["item_id"]] for r in rows)
        if dirty:
            problems.append(f"{dirty} runs were built from a dirty tree: the commit in the id does not describe the code that ran; "
                            "commit and re-run (eval-harness refuses a dirty run later)")

    if a.out and rows:
        a.out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))

    ok = not problems
    summary = {"scenarios": n, "wins": sum(r["success"] for r in rows), "collisions": sum(r["collisions"] for r in rows),
               "falls": sum(r["falls"] for r in rows), "stand_still": sum(r.get("stand_still", 0) for r in rows),
               "pivot_fail": sum(r.get("pivot_fail", 0) for r in rows), "frozen_dataset": bool(mapping is not None), "build_ref": build_ref,
               "problems": problems, "notes": notes, "out": str(a.out) if a.out and rows else None}
    if a.json:
        print(json.dumps({**summary, "verdict": "PASS" if ok else "FAIL"}, indent=1))
    else:
        print(f"{n} scenarios from {len(results)} result.json; success {summary['wins']}/{n}, collisions {summary['collisions']}, falls {summary['falls']}, "
              f"stand-stills {summary['stand_still']}, pivot stalls {summary['pivot_fail']}")
        for x in notes:
            print("NOTE  " + x)
        for x in problems:
            print("FAIL  " + x)
        if a.out and rows:
            print(f"wrote {n} rows to {a.out}")
        if build_ref:
            print(f"--build-ref {build_ref}")
            print(f"evh import-run --dataset-id <id> --system-id {a.arm} --scores {a.out or '<scores.jsonl>'} --primary-metric success "
                  f"--metric-kind stand_still=descriptive --metric-kind pivot_fail=descriptive --build-ref '{build_ref}' --source '<the lab-challenge command line>' --scorer-id batch_scores@<lab commit> --by agent:<name>")
        print("BATCH-SCORES " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
