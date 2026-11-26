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
simulator.

    uv run lab-scenarios mine --runs robots/duck/runs [--runs DIR ...] --out DIR [--variants 4] [--exclude-dataset MANIFEST ...]

`mine` (failure mining, the data flywheel): each failed run under the folders given becomes the scenario it failed in, an item of
export's format with a `source` (run, failure_kind, time, ticks_sha256, variant) and the id `mined-<runkey>-<k>`. k 0 is the seed's
scenario, drawn again exactly (a run's result.json names its challenge and seed); k 1.. are `--variants` starts, the same scene, taken
from the run's truth pose 2.0 to 1.0 s before the first stop. A run fails by its judge's verdict (`collision` is the judge's contact;
`fall`, `drop_margin`, `bounds`; else its status: `stalled`, `refused`, `trapped`, `time`, `missed_goal`), or, with no verdict, by a
stop: `cliff_stop`, `trapped`, `stalled`, `reflex_stop_trapped` and `reflex_stop_stuck` (a trapped or a stuck within REFLEX_WINDOW_S
of a reflex_stop); an evaluation's row with a contact is a `collision`. A passed run gives nothing. A failed run that cannot be a
scenario is in the manifest's `skipped` with its reason: no challenge and seed recorded (an exploration's run records neither, nor a
scene layout; no geometry is made up), a challenge that is not one goal, a floor feature the format does not carry (a cable, a step, a
drop; `--with-floor-features` mines it anyway and marks `source.floor_features`), a generator that has changed since the run, or
`--exclude-dataset MANIFEST` (an evaluation set: its (challenge, seed) never becomes training data; asked before anything else).
Runner folders only (ticks.jsonl), not data-folder runs.

    uv run lab-scenarios pool --challenges 1,2,3,4,14,15 --seeds 1000-5999 [--exclude-dataset MANIFEST ...] --out FILE.jsonl

`pool` (the training distribution, R7a): the same items as `export`, one canonical line each (so a line is, byte for byte, the file
`export` writes for that challenge and seed), in one file: the challenges in the order given, the seeds ascending. FILE.manifest.json
beside it holds the file's sha256, the commit, the command, the counts by challenge and `max_obstacles` (the most any item holds: the
slot count a trainer needs). `--exclude-dataset MANIFEST` (as `mine`): an evaluation set's (challenge, seed) never enter the pool; the
manifest counts what each removed. A challenge that is not one goal, or whose floor has a drop or a step (the format does not carry
it), is refused, as is a pool the exclusions leave empty. The sensor is off in every item: the trainer draws its own."""

import argparse
import bisect
import hashlib
import json
import math
import re
import shlex
import sys
from pathlib import Path

from labrunner.challenges import CHALLENGES, build as built, draw
from labrunner.frames import compose
from labrunner.scene import TRUNK_START
from runfile import build as runbuild

FORMAT = "robotics-scenario/1"
SET_FORMAT = "robotics-scenario-set/1"
POOL_FORMAT = "robotics-scenario-pool/1"
STOPS = ("reflex_stop", "cliff_stop", "stuck", "stalled", "trapped")   # events that mark where a run stopped
REFLEX_WINDOW_S = 10.0       # a trapped or stuck this soon after a reflex_stop is the reflex's consequence (a guess, not read from runs)
LEAD_S = (2.0, 1.0)          # the variants' starts: the truth pose this long before the first stop, from the earlier to the later
RULE_KINDS = {"contact": "collision", "fall": "fall", "drop_margin": "drop_margin", "bounds": "bounds"}
BROKEN = re.compile(r"^(contact|fall|drop_margin|bounds) at ([0-9.]+) s")   # judge.broken_failures
NO_SCENE = "no challenge and seed recorded, and no scene layout in the run folder (an exploration run stores neither)"
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


def jload(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def read_rows(path: Path) -> list:
    rows = []
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            rows.append(r)
    return rows


def failure(folder: Path, rows: list, res) -> tuple:
    """(state, kind, t) of one run: `passed` (its judge says so: nothing else is asked), `no_failure` (no verdict and no listed stop)
    or `failed` with the kind and the time of the first stop, or of the judge's broken rule if that came first."""
    events = sorted((r for r in rows if "event" in r and isinstance(r.get("t"), (int, float))), key=lambda r: r["t"])
    if isinstance(res, dict) and isinstance(res.get("pass"), bool):
        if res["pass"]:
            return "passed", None, None
        failed = res.get("failed") or []
        m = BROKEN.match(failed[0]) if failed and isinstance(failed[0], str) else None
        status = res.get("status")
        kind = RULE_KINDS[m[1]] if m else "missed_goal" if status == "reached" else status if isinstance(status, str) and status else "failed"
        stops = [e["t"] for e in events if e["event"] in STOPS or (kind == "refused" and e["event"] == "refused")][:1]
        times = ([float(m[2])] if m else []) + stops
        return "failed", kind, min(times) if times else max((r["t"] for r in rows if "event" not in r and "t" in r), default=0.0)
    found = []
    for e in events:
        if e["event"] in ("cliff_stop", "trapped", "stalled"):
            found.append((e["t"], e["event"]))
        elif e["event"] == "reflex_stop":
            after = next((f["event"] for f in events if f["event"] in ("trapped", "stuck") and e["t"] < f["t"] <= e["t"] + REFLEX_WINDOW_S), None)
            if after:
                found.append((e["t"], f"reflex_stop_{after}"))
    if found:
        t, kind = min(found)
        return "failed", kind, t
    results = jload(folder / "results.json")
    if isinstance(results, list):
        for flag, kind in (("contact", "collision"), ("fell", "fall")):
            if any(isinstance(r, dict) and r.get(flag) for r in results):
                return "failed", kind, None
    return "no_failure", None, None


def exclusions(paths: list) -> tuple:
    """({(challenge, seed): manifest path}, [{file, items}]) of the evaluation sets that must not become training data."""
    pairs, listing = {}, []
    for p in paths:
        try:
            m = json.loads(Path(p).read_text())
            items = m["items"]
            if m["format"] != SET_FORMAT or not isinstance(items, list):
                raise ValueError(f"format {m['format']!r}")
            for i in items:
                pairs.setdefault((int(i["challenge"]), int(i["seed"])), str(p))
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise SystemExit(f"--exclude-dataset {p}: not a {SET_FORMAT} manifest ({e!r})")
        listing.append({"file": str(p), "items": len(items)})
    return pairs, listing


def runkey(res: dict) -> str:
    """`duck/ch17-s1/run-20261118-235632` as `ch17-s1-run-20261118-235632`: the run's own name, without the robot."""
    parts = str(res.get("run") or "").split("/")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", "-".join(parts[1:] if len(parts) > 1 else parts)).strip("-") or "run"


def variant_starts(rows: list, t, n: int, jitter: tuple, base: dict) -> list:
    """[(t, start)] of up to `n` distinct starts for the seed's world: the run's truth (the trunk's pose in the duck's start frame)
    LEAD_S before the first stop at `t`, the duck's frame placed so its trunk is where the truth was, then moved by the jitter."""
    pts = sorted((r["t"], r["truth"]) for r in rows if "event" not in r and isinstance(r.get("t"), (int, float))
                 and isinstance(r.get("truth"), list) and len(r["truth"]) >= 3)
    if not pts or n == 0 or t is None:
        return []
    times = [t - LEAD_S[0] + (LEAD_S[0] - LEAD_S[1]) * k / (n - 1) for k in range(n)] if n > 1 else [t - sum(LEAD_S) / 2]
    ts = [p[0] for p in pts]
    seen, out = {tuple(round(v, 4) for v in base.values())}, []
    for want in times:
        i = bisect.bisect_left(ts, want)
        j = min((k for k in (i - 1, i) if 0 <= k < len(ts)), key=lambda k: abs(ts[k] - want))
        x, y, yaw = compose(jitter, compose(tuple(pts[j][1][:3]), (-TRUNK_START[0], -TRUNK_START[1], 0.0)))
        start = {"x": round(x, 4), "y": round(y, 4), "yaw": round(yaw, 4)}
        if tuple(start.values()) not in seen:
            seen.add(tuple(start.values()))
            out.append((pts[j][0], start))
    return out


def scenario_items(folder: Path, rows: list, res, kind: str, t, variants: int, floor_features: bool, excluded: dict):
    """[(item_id, item)] of one failed run: its scenario (k 0) and its variants; or the reason it cannot be one, as a string."""
    try:
        challenge, seed = str(res["challenge"]), res["seed"]
    except (TypeError, KeyError):
        return NO_SCENE
    if challenge not in CHALLENGES or type(seed) is not int:
        return f"challenge {challenge}, seed {seed!r}: not one this generator draws"
    if (int(challenge), seed) in excluded:
        return f"excluded: challenge {challenge}, seed {seed} is in {excluded[(int(challenge), seed)]}"
    scene, jitter = draw(challenge, seed)
    layout = CHALLENGES[challenge].__name__
    if scene.mode != "go":
        return f"challenge {challenge} ({layout}) is not one goal to reach (mode {scene.mode}): the format has one goal"
    features = [f.name for f in scene.floors if abs(f.z1) > 1e-6]
    if features and not floor_features:
        return f"challenge {challenge} ({layout}): the floor has {', '.join(features)}, which {FORMAT} does not carry"
    close = lambda a, b: isinstance(a, list) and len(a) == len(b) and all(isinstance(x, (int, float)) and abs(x - y) <= 1e-3 for x, y in zip(a, b))
    if not (close(res.get("jitter"), jitter) and close(res.get("goal"), built(challenge, seed).goal)):
        return f"the generator has changed since the run: challenge {challenge}, seed {seed} no longer draws the jitter and goal it recorded"
    _, base, _ = item(challenge, seed, None)
    b = res.get("build")
    base["sensor"] = ({"impairment": b["tof"], "seed": int(b["seed"])} if isinstance(b, dict) and isinstance(b.get("tof"), str) and "seed" in b
                      else {"impairment": runbuild.UNKNOWN, "seed": 0})      # a run before ebe0b8a records no sensor: not "off"
    source = {"run": str(folder), "failure_kind": kind, "time": t, "ticks_sha256": hashlib.sha256((folder / "ticks.jsonl").read_bytes()).hexdigest()}
    if features:
        source["floor_features"] = features
    key = runkey(res)
    out = [(f"mined-{key}-0", {**base, "source": {**source, "variant": 0, "start_t": None}})]
    for k, (at, start) in enumerate(variant_starts(rows, t, variants, jitter, base["start"]), 1):
        out.append((f"mined-{key}-{k}", {**base, "start": start, "source": {**source, "variant": k, "start_t": at}}))
    return out


def mine(runs: list, out: Path, argv: list, variants: int = 4, exclude: list = (), floor_features: bool = False) -> dict:
    """Write the mined items and the manifest into `out`; nothing is written when the call is refused. Returns the manifest."""
    if variants < 0:
        raise SystemExit("--variants: 0 or more")
    for r in runs:
        if not r.is_dir():
            raise SystemExit(f"--runs {r}: not a folder")
    excluded, excluded_listing = exclusions(list(exclude))
    folders = [p.parent for r in runs for p in r.rglob("ticks.jsonl")]
    twice = sorted({str(f) for f in folders if sum(g.resolve() == f.resolve() for g in folders) > 1})
    if twice:
        raise SystemExit(f"a run is named twice: {', '.join(twice[:3])}")
    counts = dict.fromkeys(("seen", "passed", "no_failure", "failed", "mined", "skipped"), 0)
    kinds, skipped, docs, made = {}, [], {}, {}
    for folder in sorted(folders, key=str):
        counts["seen"] += 1
        rows, res = read_rows(folder / "ticks.jsonl"), jload(folder / "result.json")
        state, kind, t = failure(folder, rows, res)
        if state != "failed":
            counts[state] += 1
            continue
        counts["failed"] += 1
        k = kinds.setdefault(kind, {"runs": 0, "mined": 0, "items": 0})
        k["runs"] += 1
        got = scenario_items(folder, rows, res, kind, t, variants, floor_features, excluded)
        if isinstance(got, str):
            counts["skipped"] += 1
            skipped.append({"run": str(folder), "failure_kind": kind, "time": t, "reason": got})
            continue
        counts["mined"] += 1
        k["mined"] += 1
        k["items"] += len(got)
        for item_id, d in got:
            if item_id in docs:
                raise SystemExit(f"runs {docs[item_id]['source']['run']} and {folder} both make {item_id}")
            docs[item_id] = d
            made[item_id] = kind
    texts = {i: text_of(d).encode() for i, d in docs.items()}
    stale = sorted(p.name for p in out.glob("*.json") if p.name != "manifest.json" and p.stem not in texts) if out.is_dir() else []
    if stale:
        raise SystemExit(f"{out} holds items this mining does not write: {', '.join(stale[:5])}")
    sha = runbuild.commit(REPO, 12)
    listing = [{"item_id": i, "file": f"{i}.json", "challenge": docs[i]["challenge"], "seed": docs[i]["seed"], "failure_kind": made[i],
                "run": docs[i]["source"]["run"], "sha256": hashlib.sha256(texts[i]).hexdigest()} for i in sorted(texts)]
    manifest = {"format": SET_FORMAT, "robotics_lab": {"commit": sha or runbuild.UNKNOWN, "dirty": runbuild.dirty(REPO)},
                "command": "lab-scenarios " + shlex.join(argv), "counts": {"runs": counts, "failure_kinds": kinds},
                "exclude_datasets": excluded_listing, "skipped": sorted(skipped, key=lambda s: s["run"]), "items": listing}
    out.mkdir(parents=True, exist_ok=True)
    for i, t in texts.items():
        (out / f"{i}.json").write_bytes(t)
    (out / "manifest.json").write_bytes(text_of(manifest).encode())
    return manifest


def pool(challenges: list, seeds: list, exclude: list, out: Path, argv: list) -> dict:
    """Write the pool (one canonical item per line) and its manifest beside it; nothing is written when the call is refused.
    Returns the manifest."""
    if out.suffix != ".jsonl":
        raise SystemExit(f"--out {out}: a .jsonl file (the manifest takes its name from it)")
    unknown = [c for c in challenges if c not in CHALLENGES]
    if unknown:
        raise SystemExit(f"unknown challenge {', '.join(unknown)}: the challenges are {', '.join(sorted(CHALLENGES, key=int))}")
    excluded, excluded_listing = exclusions(list(exclude))
    lines, counts, most = [], {}, 0
    for c in challenges:
        counts[c] = {"layout": CHALLENGES[c].__name__, "items": 0, "excluded": 0}
        for seed in seeds:
            if (int(c), seed) in excluded:
                counts[c]["excluded"] += 1
                continue
            item_id, doc, mode = item(c, seed, None)
            if mode != "go":
                raise SystemExit(f"challenge {c} ({CHALLENGES[c].__name__}) is not one goal to reach (mode {mode}): the format has one goal")
            features = [f.name for f in draw(c, seed)[0].floors if abs(f.z1) > 1e-6]
            if features:
                raise SystemExit(f"challenge {c} ({CHALLENGES[c].__name__}): the floor has {', '.join(features)}, which {FORMAT} does not carry")
            lines.append(text_of(doc).encode())
            counts[c]["items"] += 1
            most = max(most, len(doc["obstacles"]))
    if not lines:
        raise SystemExit("the pool is empty: the exclusions leave no item")
    sha = runbuild.commit(REPO, 12)
    manifest = {"format": POOL_FORMAT, "file": out.name, "sha256": hashlib.sha256(b"".join(lines)).hexdigest(), "items": len(lines),
                "max_obstacles": most, "robotics_lab": {"commit": sha or runbuild.UNKNOWN, "dirty": runbuild.dirty(REPO)},
                "command": "lab-scenarios " + shlex.join(argv), "challenges": counts,
                "exclude_datasets": excluded_listing, "excluded": sum(v["excluded"] for v in counts.values())}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"".join(lines))
    out.with_suffix(".manifest.json").write_bytes(text_of(manifest).encode())
    return manifest


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
    mn = sub.add_parser("mine", help="turn each failed run into the scenario it failed in, with variant starts just before the failure")
    mn.add_argument("--runs", type=Path, action="append", required=True, metavar="DIR",
                    help="a folder of runner run folders (ticks.jsonl), searched all the way down; repeat for more")
    mn.add_argument("--out", type=Path, required=True, help="the folder the items and manifest.json go into")
    mn.add_argument("--variants", type=int, default=4, metavar="N", help="starts moved to the run's truth pose 2.0-1.0 s before the first stop (default 4)")
    mn.add_argument("--exclude-dataset", type=Path, action="append", default=[], metavar="MANIFEST",
                    help="an evaluation set's manifest.json: its (challenge, seed) are never mined; repeat for more")
    mn.add_argument("--with-floor-features", action="store_true",
                    help="mine a run whose floor has a cable, a step or a drop too (the format does not carry it); the item says so in source.floor_features")
    pl = sub.add_parser("pool", help="write a training pool: the items of challenges and seeds, one line each, and a manifest")
    pl.add_argument("--challenges", required=True, help="challenge numbers, comma separated, ranges allowed: 1,2,3,4,14,15")
    pl.add_argument("--seeds", required=True, help="seeds, comma separated, ranges allowed: 1000-5999")
    pl.add_argument("--exclude-dataset", type=Path, action="append", default=[], metavar="MANIFEST",
                    help="an evaluation set's manifest.json: its (challenge, seed) never enter the pool; repeat for more")
    pl.add_argument("--out", type=Path, required=True, help="the .jsonl file; FILE.manifest.json is written beside it")
    args = ap.parse_args(argv)
    if args.cmd == "pool":
        m = pool([str(n) for n in numbers(args.challenges, "--challenges")], numbers(args.seeds, "--seeds"), args.exclude_dataset, args.out, argv)
        print(f"POOL: {m['items']} items ({m['excluded']} excluded, at most {m['max_obstacles']} obstacles) into {args.out}")
        return
    if args.cmd == "mine":
        m = mine(args.runs, args.out, argv, args.variants, args.exclude_dataset, args.with_floor_features)
        c = m["counts"]["runs"]
        print(f"MINE: {len(m['items'])} items from {c['mined']} of {c['failed']} failed runs ({c['seen']} seen, {c['passed']} passed, "
              f"{c['skipped']} skipped) into {args.out}")
        return
    challenges = [str(n) for n in numbers(args.challenges, "--challenges")]
    items = export(challenges, numbers(args.seeds, "--seeds"), args.depth_impairment, args.out, argv)
    print(f"EXPORT: {len(items)} items into {args.out}")


if __name__ == "__main__":
    main()
