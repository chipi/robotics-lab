"""The training pool (labrunner.scenarios, `lab-scenarios pool`, R7a): one canonical item per line, the same format as `export`, for a
list of challenges and seeds; a manifest beside it (the file's sha256, the commit, the command, the counts); an evaluation set's
(challenge, seed) never enters (`--exclude-dataset`, as `mine` has it). No simulator. Run: cd libs/runner && uv run python tests/test_pool.py"""

import hashlib
import json
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


tmp = Path(tempfile.mkdtemp(prefix="pool-"))
FAMILIES = {"1": "corridor", "2": "doorway", "3": "corner_in_doorway", "4": "box_in_open", "14": "thin_legs", "15": "small_boxes"}
ALL = ",".join(FAMILIES)


def pool(out, *args):
    try:
        scenarios.main(["pool", "--out", str(out), *args])
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2


def lines(path):
    return [json.loads(t) for t in Path(path).read_text().splitlines()]


def manifest_of(path):
    return json.loads(Path(str(path)[:-len(".jsonl")] + ".manifest.json").read_text())


def eval_set(path, pairs):
    path.write_text(json.dumps({"format": scenarios.SET_FORMAT, "items": [{"challenge": c, "seed": s} for c, s in pairs]}))
    return path


# ---- the file ------------------------------------------------------------------------------------------------------------------------
a, b = tmp / "a.jsonl", tmp / "b.jsonl"
check("a pool runs", pool(a, "--challenges", ALL, "--seeds", "1000-1004") == 0)
pool(b, "--challenges", ALL, "--seeds", "1000-1004")
items = lines(a)
check("one line per challenge and seed, challenges in the order given, seeds ascending",
      [(i["challenge"], i["seed"]) for i in items] == [(int(c), s) for c in FAMILIES for s in range(1000, 1005)], len(items))
check("the same arguments give byte-identical bytes, pool and manifest", a.read_bytes() == b.read_bytes()
      and manifest_of(a)["items"] == manifest_of(b)["items"])
check("each line is canonical: sorted keys, floats to four places, UTF-8, one line",
      all(t + "\n" == json.dumps(json.loads(t), sort_keys=True, ensure_ascii=False) + "\n" for t in a.read_text().splitlines())
      and a.read_text().endswith("\n") and "\n\n" not in a.read_text())

# ---- the same items as export ---------------------------------------------------------------------------------------------------------
e = tmp / "e"
scenarios.main(["export", "--challenges", ALL, "--seeds", "1000-1004", "--out", str(e)])
exported = {p.stem: p.read_bytes() for p in e.glob("*.json") if p.name != "manifest.json"}
want = [t + "\n" for t in a.read_text().splitlines()]
check("every line is, byte for byte, the file `export` writes for that challenge and seed",
      len(exported) == 30 and {f"{i['layout']}-s{i['seed']}": w.encode() for i, w in zip(items, want)} == exported)
check("the format is the export's: robotics-scenario/1, start, goal, obstacles, limits, sensor off",
      all(i["format"] == scenarios.FORMAT and {"start", "goal", "obstacles", "limits", "sensor"} <= set(i)
          and i["sensor"] == {"impairment": "off", "seed": 0} for i in items))

# ---- the manifest ---------------------------------------------------------------------------------------------------------------------
m = manifest_of(a)
head = subprocess.run(["git", "-C", str(Path(scenarios.__file__).parent), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
check("the manifest has the file's sha256, its name, the item count", m["format"] == scenarios.POOL_FORMAT and m["file"] == "a.jsonl"
      and m["sha256"] == hashlib.sha256(a.read_bytes()).hexdigest() and m["items"] == 30)
check("the manifest names the commit, dirty or not, and the command line", m["robotics_lab"]["commit"] == head[:12]
      and isinstance(m["robotics_lab"]["dirty"], bool) and m["command"].startswith("lab-scenarios pool ") and "--seeds 1000-1004" in m["command"])
check("the manifest counts by challenge: layout, items, excluded",
      m["challenges"] == {c: {"layout": n, "items": 5, "excluded": 0} for c, n in FAMILIES.items()}, m["challenges"])
check("the manifest records the most obstacles any item holds (the slot count the training needs)",
      m["max_obstacles"] == max(len(i["obstacles"]) for i in items))

# ---- the seeds can be disjoint from an evaluation set ----------------------------------------------------------------------------------------
ex = eval_set(tmp / "eval.json", [(4, 1002), (4, 1003), (2, 1000), (99, 1000)])
c = tmp / "c.jsonl"
check("--exclude-dataset runs", pool(c, "--challenges", ALL, "--seeds", "1000-1004", "--exclude-dataset", str(ex)) == 0)
got = {(i["challenge"], i["seed"]) for i in lines(c)}
check("an evaluation set's (challenge, seed) never enter; the rest do (99 is not a challenge here: no error)",
      got == {(int(ch), s) for ch in FAMILIES for s in range(1000, 1005)} - {(4, 1002), (4, 1003), (2, 1000)} and len(got) == 27, len(got))
mc = manifest_of(c)
check("the manifest lists the sets and what they removed",
      mc["exclude_datasets"] == [{"file": str(ex), "items": 4}] and mc["excluded"] == 3 and mc["items"] == 27
      and mc["challenges"]["4"]["excluded"] == 2 and mc["challenges"]["2"]["excluded"] == 1 and mc["challenges"]["1"]["excluded"] == 0, mc["challenges"])
more = eval_set(tmp / "more.json", [(1, 1001)])
d = tmp / "d.jsonl"
pool(d, "--challenges", ALL, "--seeds", "1000-1004", "--exclude-dataset", str(ex), "--exclude-dataset", str(more))
check("several --exclude-dataset add up", (1, 1001) not in {(i["challenge"], i["seed"]) for i in lines(d)} and len(lines(d)) == 26)

# the real evaluation set of the training: avoidance_v1's seeds are 1-5, so seeds 1-5 are the ones that must be refused
real = eval_set(tmp / "real.json", [(int(ch), s) for ch in FAMILIES for s in range(1, 6)])
f = tmp / "f.jsonl"
pool(f, "--challenges", ALL, "--seeds", "1-8", "--exclude-dataset", str(real))
check("seeds 1-5 of every family are refused when an evaluation set holds them; 6-8 stay",
      {i["seed"] for i in lines(f)} == {6, 7, 8} and len(lines(f)) == 18)

# ---- refusals; nothing is written ----------------------------------------------------------------------------------------------------------
g = tmp / "g.jsonl"
check("an unknown challenge is refused, nothing written", pool(g, "--challenges", "4,99", "--seeds", "1") != 0 and not g.exists())
check("a challenge that is not one goal to reach is refused (21 is ten goals)", pool(g, "--challenges", "21", "--seeds", "1") != 0 and not g.exists())
check("a challenge whose floor has a drop or a step is refused: the format does not carry it (8 is a step down)",
      pool(g, "--challenges", "8", "--seeds", "1") != 0 and not g.exists())
check("a bad seed list is refused", pool(g, "--challenges", "4", "--seeds", "5-1") != 0 and pool(g, "--challenges", "4", "--seeds", "x") != 0
      and not g.exists())
check("a missing or wrong --exclude-dataset is refused, as mine refuses it",
      pool(g, "--challenges", "4", "--seeds", "1", "--exclude-dataset", str(tmp / "nope.json")) != 0
      and pool(g, "--challenges", "4", "--seeds", "1", "--exclude-dataset", str(a)) != 0 and not g.exists())
check("an out that is not a .jsonl is refused (the manifest takes its name from it)", pool(tmp / "g.json", "--challenges", "4", "--seeds", "1") != 0)
everything = eval_set(tmp / "all.json", [(4, 1)])
check("a pool left empty by the exclusions is refused", pool(g, "--challenges", "4", "--seeds", "1", "--exclude-dataset", str(everything)) != 0
      and not g.exists())

# ---- the pool's own draw is the generator's: seeds outside the evaluation's range differ from it --------------------------------------
scene, jitter = challenges.draw("15", 4321)
h = tmp / "h.jsonl"
pool(h, "--challenges", "15", "--seeds", "4321")
(item,) = lines(h)
check("an item is the generator's draw for its seed (start is the jitter; the obstacles are the scene's boxes)",
      item["start"]["x"] == round(jitter[0], 4) and len(item["obstacles"]) == len(scene.boxes) and item["goal"]["x"] == round(scene.goal[0], 4))

shutil.rmtree(tmp, True)
print()
print("POOL", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
