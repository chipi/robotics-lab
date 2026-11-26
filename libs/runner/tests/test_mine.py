"""Failure mining (labrunner.scenarios, `lab-scenarios mine`): a failed run becomes the scenario it failed in, with a variant set of
starts just before the failure; a passed run gives nothing; a run with no recorded scene is skipped with its reason; an item whose
(challenge, seed) is in an evaluation set is refused. No simulator. Run: cd libs/runner && uv run python tests/test_mine.py

tests/fixtures/mine holds real run folders from robots/duck/runs (gitignored there), their ticks trimmed to the records near the stop
(heavy events dropped, every kept record verbatim): ch17-s1-stuck (a failed challenge run, a cable on the floor), ch18-s5-passed,
ch21-s3-sequence (a failed run of a ten-goal challenge), explore-b11-r2-trapped (an exploration run: no challenge, no scene).
The runner has no failed run of a challenge the format fully carries (1-4, 14, 15), so those cases are built here from the generator:
`fake_run` writes a run folder whose result.json is what the runner would have written for that challenge and seed."""

import hashlib
import json
import math
import shutil
import tempfile
from pathlib import Path

from labrunner import challenges, scenarios
from labrunner.frames import compose

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:400]}]" if detail else ""))
    if not cond:
        failures.append(name)


FIX = Path(__file__).parent / "fixtures" / "mine"
tmp = Path(tempfile.mkdtemp(prefix="mine-"))


def mine(out, *args):
    try:
        scenarios.main(["mine", "--out", str(out), *args])
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2


def files(d):
    return {p.name: p.read_bytes() for p in sorted(Path(d).iterdir())}


def doc(out, item_id):
    return json.loads((Path(out) / f"{item_id}.json").read_text())


def manifest(out):
    return json.loads((Path(out) / "manifest.json").read_text())


def ids(out):
    return sorted(p.stem for p in Path(out).glob("*.json") if p.name != "manifest.json")


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def fake_run(root, name, challenge, seed, failed, status, events=(), end=10.0, step=0.1, build=None):
    """A run folder of challenge `challenge`, seed `seed`, as the runner writes one: the jitter and the moved goal from the generator,
    ticks every `step` s to `end`, the duck walking along +x from the trunk's start (0.05 m ahead of its frame) at 0.1 m/s."""
    scene, jitter = challenges.draw(challenge, seed)
    moved = challenges.build(challenge, seed)
    d = Path(root) / name
    d.mkdir(parents=True)
    res = {"challenge": challenge, "seed": seed, "scene": scene.id, "run": f"duck/{scene.id}/run-{name}", "right": "reach",
           "goal": list(moved.goal), "jitter": [round(v, 4) for v in jitter], "pass": not failed, "failed": failed, "status": status,
           "why": None}
    if build:
        res["build"] = build
    (d / "result.json").write_text(json.dumps(res))
    rows = []
    for i in range(int(end / step) + 1):
        t = round(i * step, 3)
        rows.append({"pose": [0.0, 0.0, 0.0], "vx": 0.1, "vyaw": 0.0, "t": t, "truth": [0.05 + 0.1 * t, 0.0, 0.0]})
    for kind, t in events:
        rows.append({"event": kind, "t": t, "truth": [0.05 + 0.1 * t, 0.0, 0.0]})
    rows.sort(key=lambda r: r["t"])
    (d / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def events_run(root, name, events, end=60.0):
    """An exploration-shaped folder: ticks and events only, no result file."""
    d = Path(root) / name
    d.mkdir(parents=True)
    rows = [{"pose": [0.0, 0.0, 0.0], "vx": 0.0, "vyaw": 0.0, "t": float(i), "truth": [0.05, 0.0, 0.0]} for i in range(int(end))]
    rows += [{"event": k, "t": t, "truth": [0.05, 0.0, 0.0]} for k, t in events]
    rows.sort(key=lambda r: r["t"])
    (d / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def eval_set(path, pairs):
    """A manifest in export's shape listing (challenge, seed) pairs, as avoidance-v1's."""
    items = [{"challenge": c, "file": f"x{c}-s{s}.json", "item_id": f"x{c}-s{s}", "seed": s, "sha256": "0" * 64} for c, s in pairs]
    Path(path).write_text(json.dumps({"command": "lab-scenarios export", "format": scenarios.SET_FORMAT, "items": items}))
    return path


# ---- a failed challenge run: its exact scenario and its variants -------------------------------------------------------------------
ch17 = FIX / "ch17-s1-stuck"
a = tmp / "a"
check("mining a failed run runs", mine(a, "--runs", str(ch17), "--with-floor-features") == 0)
key = "ch17-s1-run-20261118-235632"
check("items are mined-<runkey>-<k>: the scenario is 0, then the variants 1-4 (default)",
      ids(a) == [f"mined-{key}-{k}" for k in range(5)], ids(a))
want =scenarios.item("17", 1, None)[1]
base = doc(a, f"mined-{key}-0")
check("the scenario is the generator's, exactly: draw's start, goal and obstacles, the seed's world",
      {k: v for k, v in base.items() if k not in ("source", "sensor")} == json.loads(scenarios.text_of({k: v for k, v in want.items()
                                                                                                    if k != "sensor"})), base["start"])
check("the sensor the run did not record is said unknown, not off",
      base["sensor"] == {"impairment": "unknown", "seed": 0}, base["sensor"])
ticks = (ch17 / "ticks.jsonl")
src = base["source"]
check("source: run path, failure kind, time, ticks_sha256",
      src["run"] == str(ch17) and src["failure_kind"] == "stalled" and src["time"] == 30.551
      and src["ticks_sha256"] == hashlib.sha256(ticks.read_bytes()).hexdigest() and src["variant"] == 0, src)
rows = [json.loads(line) for line in ticks.read_text().splitlines()]
tick = {r["t"]: r for r in rows if "event" not in r}
jit = challenges.draw("17", 1)[1]


def start_at(t):
    """The seed-world start of a duck whose trunk (truth) is where the run's truth was at t: the trunk is 0.05 m ahead of its frame."""
    x, y, yaw = compose(jit, compose(tick[t]["truth"], (-0.05, 0.0, 0.0)))
    return {"x": round(x, 4), "y": round(y, 4), "yaw": round(yaw, 4)}


v = [doc(a, f"mined-{key}-{k}") for k in range(1, 5)]
tt = [r["t"] for r in rows if "event" not in r]
near = lambda x: min(tt, key=lambda t: abs(t - x))
check("variants: the start is the run's truth 2.0 to 1.0 s before the first stop, in the seed's world",
      [x["start"] for x in v] == [start_at(near(30.551 - 2.0 + k / 3)) for k in range(4)], [x["start"] for x in v])
check("a variant is the same scene: goal, obstacles, limits, sensor, layout and seed as the scenario",
      all({k: x[k] for k in x if k not in ("start", "source")} == {k: base[k] for k in base if k not in ("start", "source")} for x in v))
check("a variant says which: variant k, the start's time, the failure's time",
      [x["source"]["variant"] for x in v] == [1, 2, 3, 4] and all(x["source"]["time"] == 30.551 for x in v)
      and all(isinstance(x["source"]["start_t"], float) and 28.0 <= x["source"]["start_t"] <= 29.7 for x in v)
      and base["source"].get("start_t") is None, [x["source"] for x in v][:1])
check("variants differ from each other and from the scenario's start",
      len({json.dumps(x["start"]) for x in v + [base]}) == 5)
b = tmp / "b"
mine(b, "--runs", str(ch17), "--with-floor-features", "--variants", "2")
check("--variants 2 gives two", ids(b) == [f"mined-{key}-{k}" for k in range(3)], ids(b))
c = tmp / "c"
mine(c, "--runs", str(ch17), "--with-floor-features", "--variants", "0")
check("--variants 0 gives the scenario alone", ids(c) == [f"mined-{key}-0"], ids(c))

# ---- the frame: a duck whose trunk is at its start is at the scenario's start -----------------------------------------------------
d4 = fake_run(tmp / "runs", "walk", "4", 3, ["stalled: stuck: walking without moving"], "stalled", events=[("stuck", 8.0)])
f = tmp / "f"
mine(f, "--runs", str(d4), "--variants", "3")
j4 = challenges.draw("4", 3)[1]
fv = {k: doc(f, f"mined-ch4-s3-run-walk-{k}") for k in range(4)}
x0, y0, yaw0 = compose(j4, (0.0, 0.0, 0.0))
check("variants of a duck that walked 0.1 m/s along +x: 6.0, 6.5 and 7.0 s are 0.6, 0.65 and 0.7 m on (trunk 0.05 ahead of the frame)",
      all(abs(fv[k]["start"]["x"] - compose(j4, (d, 0.0, 0.0))[0]) < 6e-5 and abs(fv[k]["start"]["y"] - compose(j4, (d, 0.0, 0.0))[1]) < 6e-5
          for k, d in ((1, 0.6), (2, 0.65), (3, 0.7))), [fv[k]["start"] for k in fv])
check("a challenge the format fully carries is mined with no flag; its sensor is read from the run's build when it has one",
      fv[0]["challenge"] == 4 and fv[0]["layout"] == "box_in_open" and doc(f, "mined-ch4-s3-run-walk-0")["sensor"]["impairment"] == "unknown")
d4b = fake_run(tmp / "runs", "built", "4", 2, ["stalled: x"], "stalled", events=[("stuck", 8.0)],
               build={"tof": "d435", "seed": 7, "id": "brain@x"})
g = tmp / "g"
mine(g, "--runs", str(d4b), "--variants", "0")
check("the sensor is the run's build: preset and seed", doc(g, "mined-ch4-s2-run-built-0")["sensor"] == {"impairment": "d435", "seed": 7})

# ---- the same fields and types as export -----------------------------------------------------------------------------------------
KEYS = {"format", "challenge", "scene", "layout", "seed", "start", "goal", "obstacles", "limits", "sensor"}
bad = []
for n in ids(f) + ids(a):
    it = doc(f if n in ids(f) else a, n)
    ok = (set(it) == KEYS | {"source"} and it["format"] == "robotics-scenario/1" and type(it["challenge"]) is int
          and isinstance(it["scene"], str) and isinstance(it["layout"], str) and type(it["seed"]) is int
          and set(it["start"]) == {"x", "y", "yaw"} and all(num(x) for x in it["start"].values())
          and set(it["goal"]) == {"x", "y"} and all(num(x) for x in it["goal"].values())
          and isinstance(it["obstacles"], list) and it["obstacles"]
          and all(set(o) == {"kind", "x", "y", "yaw", "hx", "hy", "z0", "z1"} and isinstance(o["kind"], str)
                  and all(num(x) for k, x in o.items() if k != "kind") for o in it["obstacles"])
          and set(it["limits"]) == {"time_s"} and num(it["limits"]["time_s"])
          and set(it["sensor"]) == {"impairment", "seed"} and isinstance(it["sensor"]["impairment"], str) and type(it["sensor"]["seed"]) is int
          and set(it["source"]) >= {"run", "failure_kind", "time", "ticks_sha256", "variant"} and isinstance(it["source"]["run"], str)
          and isinstance(it["source"]["failure_kind"], str) and num(it["source"]["time"]) and len(it["source"]["ticks_sha256"]) == 64)
    if not ok:
        bad.append(n)
check("every item has export's fields, each of its type, and the source", not bad, bad[:3])
check("canonical: sorted keys, one line, UTF-8, floats to four places",
      all(t == (json.dumps(json.loads(t), sort_keys=True, ensure_ascii=False) + "\n").encode()
          for n, t in files(f).items()) and all(round(x, 4) == x for it in (doc(f, n) for n in ids(f)) for x in it["start"].values()))
m = manifest(a)
check("the manifest is export's: format, commit, command, items with the sha256 of each file",
      m["format"] == scenarios.SET_FORMAT and set(m["robotics_lab"]) == {"commit", "dirty"} and m["command"].startswith("lab-scenarios mine ")
      and [i["item_id"] for i in m["items"]] == ids(a)
      and all(i["file"] == i["item_id"] + ".json" and i["sha256"] == hashlib.sha256((a / i["file"]).read_bytes()).hexdigest()
              and i["challenge"] == 17 and i["seed"] == 1 and i["failure_kind"] == "stalled" for i in m["items"]), m["items"][:1])
check("the manifest counts per failure kind, and runs",
      m["counts"]["runs"] == {"seen": 1, "passed": 0, "no_failure": 0, "failed": 1, "mined": 1, "skipped": 0}
      and m["counts"]["failure_kinds"] == {"stalled": {"runs": 1, "mined": 1, "items": 5}}, m["counts"])

# ---- a floor the format cannot carry -----------------------------------------------------------------------------------------------
n = tmp / "n"
check("without the flag a run whose floor has a cable is skipped: the item would not be the scene it failed in",
      mine(n, "--runs", str(ch17)) == 0 and ids(n) == []
      and manifest(n)["skipped"][0]["reason"].startswith("challenge 17 (floor_things): the floor has cable")
      and manifest(n)["counts"]["failure_kinds"] == {"stalled": {"runs": 1, "mined": 0, "items": 0}}, manifest(n)["skipped"])
check("the flag marks the item with the floor it lacks", base["source"]["floor_features"] == ["cable"], base["source"])

# ---- a passed run gives nothing ----------------------------------------------------------------------------------------------------
p = tmp / "p"
mine(p, "--runs", str(FIX / "ch18-s5-passed"), "--with-floor-features")
check("a passed run: no items, counted passed, not listed as skipped",
      ids(p) == [] and manifest(p)["counts"]["runs"]["passed"] == 1 and manifest(p)["skipped"] == [] and manifest(p)["counts"]["failure_kinds"] == {})
pc = tmp / "pc"
mine(pc, "--runs", str(fake_run(tmp / "runs", "ok", "4", 1, [], "reached", events=[("cliff_stop", 3.0)])))
check("a verdict of pass decides: a cliff_stop in a passed challenge run is the guard working", ids(pc) == []
      and manifest(pc)["counts"]["runs"]["passed"] == 1)

# ---- a run with no recorded scene ---------------------------------------------------------------------------------------------------
e = tmp / "e"
mine(e, "--runs", str(FIX / "explore-b11-r2-trapped"))
sk = manifest(e)["skipped"]
check("an exploration run: failed (trapped), no item, skipped with the reason: no challenge and seed, no scene layout recorded",
      ids(e) == [] and len(sk) == 1 and sk[0]["failure_kind"] == "trapped" and "no challenge and seed" in sk[0]["reason"]
      and "no scene layout" in sk[0]["reason"] and sk[0]["run"] == str(FIX / "explore-b11-r2-trapped"), sk)
s21 = tmp / "s21"
mine(s21, "--runs", str(FIX / "ch21-s3-sequence"))
check("a ten-goal challenge is skipped as export refuses it: not one goal to reach",
      ids(s21) == [] and "not one goal to reach (mode sequence)" in manifest(s21)["skipped"][0]["reason"], manifest(s21)["skipped"])

# ---- the stops and the verdict, by kind ---------------------------------------------------------------------------------------------
ev = tmp / "events"
events_run(ev, "cliff", [("cliff_stop", 20.0)])
events_run(ev, "reflex-trapped", [("reflex_stop", 10.0), ("trapped", 14.0)])
events_run(ev, "reflex-stuck", [("reflex_stop", 10.0), ("stuck", 13.0)])
events_run(ev, "reflex-far", [("reflex_stop", 5.0), ("trapped", 50.0)])
events_run(ev, "reflex-alone", [("reflex_stop", 5.0), ("refused", 7.0)])
events_run(ev, "stalled", [("stalled", 30.0)])
events_run(ev, "quiet", [("reached", 30.0)])
x = tmp / "x"
mine(x, "--runs", str(ev))
kinds = {Path(s["run"]).name: s["failure_kind"] for s in manifest(x)["skipped"]}
check("kinds from the stops of a run with no verdict: cliff_stop, trapped, stalled, and a reflex_stop followed by trapped or stuck",
      kinds == {"cliff": "cliff_stop", "reflex-trapped": "reflex_stop_trapped", "reflex-stuck": "reflex_stop_stuck",
                "reflex-far": "trapped", "stalled": "stalled"}, kinds)
check("a reflex_stop alone, and a run with no stop, are no failure",
      manifest(x)["counts"]["runs"] == {"seen": 7, "passed": 0, "no_failure": 2, "failed": 5, "mined": 0, "skipped": 5}, manifest(x)["counts"])
check("counts per kind", manifest(x)["counts"]["failure_kinds"] == {k: {"runs": 1, "mined": 0, "items": 0} for k in
                                                                 ("cliff_stop", "reflex_stop_trapped", "reflex_stop_stuck", "stalled")}
      | {"trapped": {"runs": 1, "mined": 0, "items": 0}})
col = fake_run(tmp / "runs", "contact", "4", 5, ["contact at 6.0 s: 0.050 m from box, under the footprint 0.083 m"], "reached")
y = tmp / "y"
mine(y, "--runs", str(col), "--variants", "2")
yd = doc(y, "mined-ch4-s5-run-contact-0")
check("the judge's contact is a collision, at the time it names; the variants are 1-2 s before it",
      yd["source"]["failure_kind"] == "collision" and yd["source"]["time"] == 6.0
      and [doc(y, f"mined-ch4-s5-run-contact-{k}")["source"]["start_t"] for k in (1, 2)] == [4.0, 5.0],
      [doc(y, i)["source"] for i in ids(y)][1:])
miss = fake_run(tmp / "runs", "miss", "4", 4, ["said reached 0.27 m from the goal (over 0.25 m)"], "reached")
z = tmp / "z"
mine(z, "--runs", str(miss), "--variants", "0")
check("a goal said reached from too far is missed_goal, at the end of the run when nothing else says when",
      doc(z, "mined-ch4-s4-run-miss-0")["source"]["failure_kind"] == "missed_goal" and doc(z, "mined-ch4-s4-run-miss-0")["source"]["time"] == 10.0)
rr = tmp / "results"
(rr / "eval").mkdir(parents=True)
(rr / "eval" / "ticks.jsonl").write_text(json.dumps({"pose": [0, 0, 0], "t": 1.0, "truth": [0.05, 0, 0]}) + "\n")
(rr / "eval" / "results.json").write_text(json.dumps([{"goal": 1, "status": "reached", "contact": False, "fell": False},
                                                       {"goal": 2, "status": "reached", "contact": True, "fell": False}]))
rm = tmp / "rm"
mine(rm, "--runs", str(rr))
check("an evaluation's row with a contact is a collision, and with no scene recorded it is skipped",
      manifest(rm)["skipped"][0]["failure_kind"] == "collision" and "no challenge and seed" in manifest(rm)["skipped"][0]["reason"])

# ---- a generator that has changed since the run ---------------------------------------------------------------------------------------
old = fake_run(tmp / "runs", "old", "4", 6, ["stalled: x"], "stalled", events=[("stuck", 8.0)])
r = json.loads((old / "result.json").read_text())
r["jitter"][0] += 0.01
(old / "result.json").write_text(json.dumps(r))
o = tmp / "o"
mine(o, "--runs", str(old))
check("a run whose recorded jitter is not the generator's now is skipped: the scene is not the one it ran in",
      ids(o) == [] and "generator" in manifest(o)["skipped"][0]["reason"], manifest(o)["skipped"])

# ---- exclusion: an evaluation set's (challenge, seed) never becomes training data ---------------------------------------------------------
ex = eval_set(tmp / "avoidance.json", [(4, 3), (4, 5), (1, 1)])
t = tmp / "t"
runs = tmp / "excl"
for name, seed in (("a", 3), ("b", 4), ("c", 5)):
    fake_run(runs, name, "4", seed, ["stalled: x"], "stalled", events=[("stuck", 8.0)])
mine(t, "--runs", str(runs), "--exclude-dataset", str(ex))
check("--exclude-dataset: seeds 3 and 5 of challenge 4 are refused whole (scenario and variants), seed 4 is mined",
      {i.rsplit("-", 1)[0] for i in ids(t)} == {"mined-ch4-s4-run-b"} and len(ids(t)) == 5, ids(t))
check("the refusal is in the manifest, with its reason and the file",
      sorted((Path(s["run"]).name, s["failure_kind"]) for s in manifest(t)["skipped"]) == [("a", "stalled"), ("c", "stalled")]
      and all(s["reason"].startswith("excluded: challenge 4, seed") and str(ex) in s["reason"] for s in manifest(t)["skipped"])
      and manifest(t)["counts"]["runs"]["mined"] == 1 and manifest(t)["counts"]["runs"]["skipped"] == 2
      and manifest(t)["exclude_datasets"] == [{"file": str(ex), "items": 3}], manifest(t)["skipped"])
t2 = tmp / "t2"
mine(t2, "--runs", str(runs))
check("the same runs with no exclusion mine all three", len(ids(t2)) == 15)
t3 = tmp / "t3"
mine(t3, "--runs", str(ch17), "--with-floor-features", "--exclude-dataset", str(eval_set(tmp / "other.json", [(17, 1)])))
check("excluded before anything else is asked of the run (a floor flag does not let it through)", ids(t3) == []
      and manifest(t3)["skipped"][0]["reason"].startswith("excluded: challenge 17, seed 1"))
t4 = tmp / "t4"
mine(t4, "--runs", str(runs), "--exclude-dataset", str(ex), "--exclude-dataset", str(eval_set(tmp / "more.json", [(4, 4)])))
check("several --exclude-dataset add up", ids(t4) == [])
check("an evaluation manifest that is not one is refused, nothing written",
      mine(tmp / "t5", "--runs", str(runs), "--exclude-dataset", str(tmp / "missing.json")) != 0
      and mine(tmp / "t5", "--runs", str(runs), "--exclude-dataset", str(a / "mined-ch17-s1-run-20261118-235632-0.json")) != 0
      and not (tmp / "t5").exists())
avoid = Path("/work/robotics-evals/data/sources/avoidance-v1/manifest.json")
if avoid.exists():
    sets = json.loads(avoid.read_text())["items"]
    pairs = sorted({(i["challenge"], i["seed"]) for i in sets})
    ra = tmp / "avoid"
    for c_, s_ in pairs:
        fake_run(ra, f"c{c_}-s{s_}", str(c_), s_, ["stalled: x"], "stalled", events=[("stuck", 8.0)])
    t6 = tmp / "t6"
    mine(t6, "--runs", str(ra), "--exclude-dataset", str(avoid))
    check("avoidance-v1's own items: a failed run of every one is refused, nothing mined",
          len(pairs) == 30 and ids(t6) == [] and len(manifest(t6)["skipped"]) == 30, (len(pairs), ids(t6)[:2]))

# ---- determinism ---------------------------------------------------------------------------------------------------------------------
h = tmp / "h"
mine(h, "--runs", str(ch17), "--runs", str(runs), "--with-floor-features", "--exclude-dataset", str(ex))
h2 = tmp / "h2"
mine(h2, "--runs", str(ch17), "--runs", str(runs), "--with-floor-features", "--exclude-dataset", str(ex))
fh = files(h)
sans = lambda d: {n: t for n, t in files(d).items() if n != "manifest.json"}
check("the same runs and arguments give byte-identical item files", sans(h) == sans(h2) and len(sans(h)) == 10, sorted(sans(h))[:2])
mine(h, "--runs", str(ch17), "--runs", str(runs), "--with-floor-features", "--exclude-dataset", str(ex))
check("mining again into the same folder is byte-identical, manifest included", files(h) == fh)
hr = tmp / "hr"
mine(hr, "--runs", str(runs), "--runs", str(ch17), "--with-floor-features", "--exclude-dataset", str(ex))
check("the order of --runs does not change an item", sans(hr) == sans(h))

# ---- refusals ------------------------------------------------------------------------------------------------------------------------
stale = tmp / "stale"
stale.mkdir()
(stale / "mined-old-0.json").write_text("{}")
check("a folder holding an item this mining does not write is refused", mine(stale, "--runs", str(ch17), "--with-floor-features") != 0
      and files(stale) == {"mined-old-0.json": b"{}"})
dup = tmp / "dup"
check("two runs with one key are refused: the same run named twice", mine(dup, "--runs", str(ch17), "--runs", str(ch17)) != 0 and not dup.exists())
check("a --runs folder that is not there is refused", mine(tmp / "nr", "--runs", str(tmp / "nowhere")) != 0 and not (tmp / "nr").exists())
check("--variants below 0 is refused", mine(tmp / "nv", "--runs", str(ch17), "--variants", "-1") != 0)

shutil.rmtree(tmp, True)
print()
print("MINE", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
