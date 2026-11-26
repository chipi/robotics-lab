"""Scenario sets for the eval repository (robotics-evals docs/DATASET-SPEC.md): a challenge's generator drawn for a list of seeds,
one canonical JSON file per scenario, and a manifest.

    uv run lab-scenarios export --challenges 4,14,15 --seeds 1-5 --depth-impairment 1 --out DIR

Each `<layout>-s<seed>.json` is a scenario in the seed's world (challenges.draw, before the duck is moved to the origin): the start
is the seed's jitter, the goal and the obstacles are where the generator put them. An obstacle is one of the scene's bodies: `kind`
(`wall`, or the body's name without its number), centre `x`, `y`, `yaw` in radians, half-sides `hx`, `hy` and the heights `z0`, `z1`,
all in metres. Floors and drops are not exported. Sorted keys, floats to four places, one line, UTF-8. `manifest.json` lists the
items with the sha256 of each file, the commit this was made from, and the command line.

`--depth-impairment SEED|off`: item i of the seeds has sensor seed SEED + i, as run i of a `lab-challenge` batch does, so `--seeds
1-5 --depth-impairment 1` gives each scenario the sensor seed of its scene seed. Standard library and the runner's own modules; no
simulator."""

import argparse
import hashlib
import json
import math
import re
import shlex
import sys
from pathlib import Path

from labrunner.challenges import CHALLENGES, draw
from runfile import build as runbuild

FORMAT = "robotics-scenario/1"
SET_FORMAT = "robotics-scenario-set/1"
REPO = Path(__file__).resolve().parent       # the checkout whose commit the manifest names (git finds its root from here)
WALL = re.compile(r"_[snew]\d?$")            # how challenges.py names the walls: room_s, door_n, wa_e1


def numbers(text: str, what: str) -> list:
    """`1,3,5-7` as [1, 3, 5, 6, 7], each once, in the order written."""
    out = []
    for part in text.split(","):
        lo, dash, hi = part.strip().partition("-")
        try:
            a, b = int(lo), int(hi) if dash else int(lo)
        except ValueError:
            raise SystemExit(f"{what}: {part!r} is not a number or a range (1,3,5-7)")
        if b < a:
            raise SystemExit(f"{what}: {part!r} runs backwards")
        out += [n for n in range(a, b + 1) if n not in out]
    return out


def canonical(v):
    """`v` with every float rounded to four places (and -0.0 made 0.0); a value that is not finite is refused."""
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError(f"not a finite number: {v}")
        return round(v, 4) + 0.0
    if isinstance(v, dict):
        return {k: canonical(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [canonical(x) for x in v]
    return v


def text_of(doc: dict) -> str:
    return json.dumps(canonical(doc), sort_keys=True, ensure_ascii=False) + "\n"


def kind_of(name: str) -> str:
    return "wall" if WALL.search(name) else name.rstrip("0123456789")


def item(challenge: str, seed: int, impairment: int | None) -> tuple:
    """(item_id, the scenario, the scene's mode) of one challenge and seed; `impairment` the sensor's seed, or None for off."""
    scene, jitter = draw(challenge, seed)
    layout = CHALLENGES[challenge].__name__
    preset, sensor_seed = runbuild.tof({"enabled": impairment is not None, "seed": impairment or 0})
    return f"{layout}-s{seed}", {
        "format": FORMAT, "challenge": int(challenge), "scene": scene.id, "layout": layout, "seed": seed,
        "start": dict(zip(("x", "y", "yaw"), jitter)), "goal": {"x": scene.goal[0], "y": scene.goal[1]},
        "obstacles": [{"kind": kind_of(b.name), "x": b.cx, "y": b.cy, "yaw": b.yaw, "hx": b.hx, "hy": b.hy, "z0": b.z0, "z1": b.z1}
                      for b in scene.boxes],
        "limits": {"time_s": scene.time_s}, "sensor": {"impairment": preset, "seed": sensor_seed}}, scene.mode


def export(challenges: list, seeds: list, impairment: int | None, out: Path, argv: list) -> list:
    """Write the items and the manifest into `out`; nothing is written when any item is refused. Returns the manifest's items."""
    unknown = [c for c in challenges if c not in CHALLENGES]
    if unknown:
        raise SystemExit(f"unknown challenge {', '.join(unknown)}: the challenges are {', '.join(sorted(CHALLENGES, key=int))}")
    docs = {}
    for c in challenges:
        for i, seed in enumerate(seeds):
            item_id, doc, mode = item(c, seed, None if impairment is None else impairment + i)
            if mode != "go":
                raise SystemExit(f"challenge {c} ({CHALLENGES[c].__name__}) is not one goal to reach (mode {mode}): the format has one goal")
            if item_id in docs:
                raise SystemExit(f"challenges {docs[item_id]['challenge']} and {c} both make {item_id}")
            docs[item_id] = doc
    texts = {i: text_of(d).encode() for i, d in docs.items()}
    stale = sorted(p.name for p in out.glob("*.json") if p.name != "manifest.json" and p.stem not in texts) if out.is_dir() else []
    if stale:
        raise SystemExit(f"{out} holds items this export does not write: {', '.join(stale[:5])}")
    sha = runbuild.commit(REPO, 12)
    listing = [{"item_id": i, "file": f"{i}.json", "challenge": docs[i]["challenge"], "seed": docs[i]["seed"],
                "sha256": hashlib.sha256(texts[i]).hexdigest()} for i in sorted(texts)]
    manifest = {"format": SET_FORMAT, "robotics_lab": {"commit": sha or runbuild.UNKNOWN, "dirty": runbuild.dirty(REPO)},
                "command": "lab-scenarios " + shlex.join(argv), "items": listing}
    out.mkdir(parents=True, exist_ok=True)
    for i, t in texts.items():
        (out / f"{i}.json").write_bytes(t)
    (out / "manifest.json").write_bytes(text_of(manifest).encode())
    return listing


def impairment_arg(s: str) -> int | None:
    if s == "off":
        return None
    try:
        return int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"a seed (an integer) or off: {s!r}")


def main(argv: list | None = None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write a scenario set: one file per challenge and seed, and its manifest")
    ex.add_argument("--challenges", required=True, help="challenge numbers, comma separated, ranges allowed: 4,14,15")
    ex.add_argument("--seeds", required=True, help="seeds, comma separated, ranges allowed: 1-5")
    ex.add_argument("--depth-impairment", type=impairment_arg, default=None, metavar="SEED|off",
                    help="the depth sensor's impairment seed of the first seed (item i has SEED + i, as a lab-challenge batch); default off")
    ex.add_argument("--out", type=Path, required=True, help="the folder the items and manifest.json go into")
    args = ap.parse_args(argv)
    challenges = [str(n) for n in numbers(args.challenges, "--challenges")]
    items = export(challenges, numbers(args.seeds, "--seeds"), args.depth_impairment, args.out, argv)
    print(f"EXPORT: {len(items)} items into {args.out}")


if __name__ == "__main__":
    main()
