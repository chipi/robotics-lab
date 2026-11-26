"""The scenario-set exporter (labrunner.scenarios, `lab-scenarios export`): one canonical JSON file per item, a manifest with each
file's sha256, the commit and the command line; the same commit and arguments give the same bytes; an unknown challenge is refused
before anything is written. No simulator. Run: cd libs/runner && uv run python tests/test_scenarios.py"""

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from labrunner import challenges, scenarios

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:400]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="scenarios-"))
FAMILIES = {"1": "corridor", "2": "doorway", "3": "corner_in_doorway", "4": "box_in_open", "14": "thin_legs", "15": "small_boxes"}
ALL = ",".join(FAMILIES)


def export(out, *args):
    try:
        scenarios.main(["export", "--out", str(out), *args])
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2


def files(d):
    return {p.name: p.read_bytes() for p in sorted(Path(d).iterdir())}


def places(v):
    """The most decimal places any float in `v` is written with."""
    if isinstance(v, float):
        s = repr(v)
        return len(s.partition(".")[2]) if "e" not in s else 99
    if isinstance(v, dict):
        return max((places(x) for x in v.values()), default=0)
    if isinstance(v, list):
        return max((places(x) for x in v), default=0)
    return 0


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ---- the files --------------------------------------------------------------------------------------------------------------------
a, b = tmp / "a", tmp / "b"
check("an export runs", export(a, "--challenges", ALL, "--seeds", "1-5", "--depth-impairment", "1") == 0)
export(b, "--challenges", ALL, "--seeds", "1-5", "--depth-impairment", "1")
fa, fb = files(a), files(b)
want = {f"{name}-s{s}.json" for name in FAMILIES.values() for s in range(1, 6)}
check("one file per item, named <layout>-s<seed>.json, and the manifest", set(fa) == want | {"manifest.json"} and len(want) == 30,
      sorted(set(fa) ^ (want | {"manifest.json"})))
items = {n: json.loads(t) for n, t in fa.items() if n != "manifest.json"}
check("the same commit and arguments give byte-identical item files", {n: t for n, t in fa.items() if n != "manifest.json"} ==
      {n: t for n, t in fb.items() if n != "manifest.json"})

# ---- the format and the types -----------------------------------------------------------------------------------------------------
KEYS = {"format", "challenge", "scene", "layout", "seed", "start", "goal", "obstacles", "limits", "sensor"}
bad = []
for n, it in items.items():
    ok = (set(it) == KEYS and it["format"] == "robotics-scenario/1" and type(it["challenge"]) is int and isinstance(it["scene"], str)
          and isinstance(it["layout"], str) and type(it["seed"]) is int and n == f"{it['layout']}-s{it['seed']}.json"
          and it["scene"] == f"ch{it['challenge']}-s{it['seed']}"
          and set(it["start"]) == {"x", "y", "yaw"} and all(num(v) for v in it["start"].values())
          and set(it["goal"]) == {"x", "y"} and all(num(v) for v in it["goal"].values())
          and isinstance(it["obstacles"], list) and it["obstacles"]
          and all(set(o) == {"kind", "x", "y", "yaw", "hx", "hy", "z0", "z1"} and isinstance(o["kind"], str)
                  and all(num(v) for k, v in o.items() if k != "kind") for o in it["obstacles"])
          and set(it["limits"]) == {"time_s"} and num(it["limits"]["time_s"])
          and set(it["sensor"]) == {"impairment", "seed"} and isinstance(it["sensor"]["impairment"], str) and type(it["sensor"]["seed"]) is int)
    if not ok:
        bad.append(n)
check("every item has the spec's fields, each of its type", not bad, bad[:3])
check("the layout is the generator's name", {it["layout"] for it in items.values()} == set(FAMILIES.values()))
check("canonical: sorted keys, floats to four places, one line, UTF-8",
      all(t == (json.dumps(json.loads(t), sort_keys=True, ensure_ascii=False) + "\n").encode() and places(json.loads(t)) <= 4
          for n, t in fa.items() if n != "manifest.json"))
check("the sensor's seed equals the scene's when --depth-impairment is the first seed, preset set",
      all(it["sensor"] == {"impairment": it["sensor"]["impairment"], "seed": it["seed"]} and it["sensor"]["impairment"] != "off"
          for it in items.values()))

# ---- the values: the generator's, in the seed's world --------------------------------------------------------------------------------
scene, jitter = challenges.draw("4", 3)
it = items["box_in_open-s3.json"]
check("start is the seed's jitter; goal and obstacles are the generator's, unmoved",
      it["start"] == {"x": round(jitter[0], 4), "y": round(jitter[1], 4), "yaw": round(jitter[2], 4)}
      and it["goal"] == {"x": round(scene.goal[0], 4), "y": round(scene.goal[1], 4)} and len(it["obstacles"]) == len(scene.boxes)
      and it["limits"] == {"time_s": scene.time_s}, it["start"])
check("a wall is a wall, a box a box", {o["kind"] for o in it["obstacles"]} == {"wall", "box"}
      and sum(o["kind"] == "box" for o in it["obstacles"]) == 1)
check("thin_legs: legs and a seat, by seed", {o["kind"] for o in items["thin_legs-s1.json"]["obstacles"]} >= {"leg", "seat"}
      and "seat" not in {o["kind"] for o in items["thin_legs-s2.json"]["obstacles"]})
check("start differs by seed (the jitter is drawn)", len({json.dumps(i["start"]) for i in items.values()}) > 5)
check("build still gives the duck at the origin (draw is build's own first half)", challenges.build("4", 3).jitter == jitter)

# ---- the manifest -------------------------------------------------------------------------------------------------------------------
m = json.loads(fa["manifest.json"])
head = subprocess.run(["git", "-C", str(Path(scenarios.__file__).parent), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
check("the manifest lists every item with the sha256 of its file",
      [i["item_id"] for i in m["items"]] == sorted(n[:-5] for n in want)
      and all(i["file"] == i["item_id"] + ".json" and i["sha256"] == hashlib.sha256(fa[i["file"]]).hexdigest() for i in m["items"]))
check("the manifest names the commit and the command line", m["robotics_lab"]["commit"] == head[:12] and isinstance(m["robotics_lab"]["dirty"], bool)
      and m["command"].startswith("lab-scenarios export ") and "--challenges " + ALL in m["command"] and str(a) in m["command"], m["command"])
export(a, "--challenges", ALL, "--seeds", "1-5", "--depth-impairment", "1")
check("an export again into the same folder is byte-identical, manifest included", files(a) == fa)

# ---- the sensor --------------------------------------------------------------------------------------------------------------------
c = tmp / "c"
export(c, "--challenges", "4", "--seeds", "1-3", "--depth-impairment", "off")
check("impairment off: preset off, seed 0", {json.dumps(json.loads(t)["sensor"]) for n, t in files(c).items() if n != "manifest.json"}
      == {json.dumps({"impairment": "off", "seed": 0})})
d = tmp / "d"
export(d, "--challenges", "4", "--seeds", "3-5", "--depth-impairment", "10")
check("impairment SEED: run i of the seeds has SEED + i, as the runner's batch",
      [json.loads(files(d)[f"box_in_open-s{s}.json"])["sensor"]["seed"] for s in (3, 4, 5)] == [10, 11, 12])

# ---- refusals ----------------------------------------------------------------------------------------------------------------------
e = tmp / "e"
check("an unknown challenge is refused, nothing written", export(e, "--challenges", "4,99", "--seeds", "1", "--depth-impairment", "off") != 0
      and not e.exists())
check("a challenge that is not one goal to reach is refused (21 is ten goals)",
      export(e, "--challenges", "21", "--seeds", "1", "--depth-impairment", "off") != 0 and not e.exists())
check("a bad seed list is refused", export(e, "--challenges", "4", "--seeds", "5-1", "--depth-impairment", "off") != 0
      and export(e, "--challenges", "4", "--seeds", "x", "--depth-impairment", "off") != 0 and not e.exists())
f = tmp / "f"
f.mkdir()
(f / "stale-s1.json").write_text("{}")
check("a folder holding an item this export does not write is refused",
      export(f, "--challenges", "4", "--seeds", "1", "--depth-impairment", "off") != 0 and files(f) == {"stale-s1.json": b"{}"})

shutil.rmtree(tmp, True)
print()
print("SCENARIOS", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
