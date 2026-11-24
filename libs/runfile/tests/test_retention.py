"""Retention (runfile.retention, docs/wip/TELEMETRY-RETENTION-DESIGN.md): which runs leave the data folder and which stay, a plan that
changes nothing, a move that renames the whole folder and logs it, and the refusals: the archive inside the data folder, a target
that exists, another filesystem, a writer that started after the plan. Only temporary folders.
Run: cd libs/runfile && uv run python tests/test_retention.py"""

import atexit
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from helpers import Checks
from runfile import keys, mcapio, retention as R

check = Checks("RETENTION")
tmp = Path(tempfile.mkdtemp(prefix="retention-"))
atexit.register(shutil.rmtree, tmp, True)
T0_NS = 1_700_000_000 * 10**9
NOW = time.time()
DAY = 86400


def make(data: Path, key: str, age_days: float, extra: dict | None = None, files=()) -> Path:
    robot, scene, _ = keys.split_key(key)
    run = mcapio.new_run(key, {"name": robot}, scene, "exploration", T0_NS)
    run.update(extra or {})
    mcapio.write(keys.run_dir(data, key), run, [])
    d = keys.run_dir(data, key)
    for f in files:
        (d / f).write_bytes(b"x" * 100)
    t = NOW - age_days * DAY
    os.utime(d / "run.mcap", (t, t))
    return d


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_size if p.is_file() else None) for p in sorted(root.rglob("*"))}


def build(name: str) -> tuple:
    data = tmp / name / "data"
    make(data, "duck/room/old", 60)
    make(data, "duck/room/old-truth", 90, {"judge_truth": {"truth": True}})
    make(data, "duck/room/old-profile", 90, {"judge_profile": {"id": "duck", "version": 3}})
    make(data, "duck/room/young", 5)
    make(data, "duck/room/edge", 30)
    make(data, "nxt/room/old-nxt", 45, files=("note.txt",))
    live = keys.run_dir(data, "duck/room/live")
    live.mkdir(parents=True)
    (live / "run.live.mcap").write_bytes(b"x")
    (live / "writer.lock").write_text("{}")
    lockonly = keys.run_dir(data, "duck/room/lockonly")
    lockonly.mkdir(parents=True)
    (lockonly / "writer.lock").write_text("{}")
    bad = keys.run_dir(data, "duck/room/garbage")
    bad.mkdir(parents=True)
    (bad / "run.mcap").write_bytes(b"this is not an mcap file")
    os.utime(bad / "run.mcap", (NOW - 80 * DAY, NOW - 80 * DAY))
    keys.run_dir(data, "duck/room/empty").mkdir(parents=True)
    return data, tmp / name / "data-archive"


data, arch = build("a")
check("the default archive sits beside the data folder", R.default_archive(Path("/x/lab/data")) == Path("/x/lab/data-archive"))
before = tree(tmp / "a")
items = {i.key: i for i in R.plan(data, arch, 30, now=NOW)}
check("planning changes nothing and creates no archive", tree(tmp / "a") == before and not arch.exists())
check("a folder with no run file is not a run", "duck/room/empty" not in items, sorted(items))
want = {"duck/room/old": "archive", "duck/room/old-truth": "keep", "duck/room/old-profile": "keep", "duck/room/young": "keep",
        "duck/room/edge": "archive", "nxt/room/old-nxt": "archive", "duck/room/live": "keep", "duck/room/lockonly": "keep",
        "duck/room/garbage": "keep"}
check("old and not official: archive; official, young, live, unreadable: keep", {k: i.action for k, i in items.items()} == want,
      {k: (i.action, i.reason) for k, i in items.items() if want.get(k) != i.action})
check("official by judge_truth, and by judge_profile", items["duck/room/old-truth"].official is True and items["duck/room/old-profile"].official is True
      and items["duck/room/old"].official is False and "official" in items["duck/room/old-truth"].reason)
check("a run exactly as old as the limit goes (younger than it stays)", items["duck/room/edge"].action == "archive"
      and items["duck/room/young"].reason == "younger than 30 days", items["duck/room/edge"])
check("live runs say so, and are not read", items["duck/room/live"].reason == "still being written" and items["duck/room/live"].official is None
      and items["duck/room/lockonly"].reason == "still being written")
check("an unreadable run is kept, saying so", "cannot read the run record" in items["duck/room/garbage"].reason, items["duck/room/garbage"])
check("age and size are reported", abs(items["duck/room/old"].age_days - 60) < 0.01 and items["nxt/room/old-nxt"].size > 100
      and items["duck/room/old"].size > 0, (items["duck/room/old"].age_days, items["nxt/room/old-nxt"].size))
only = R.plan(data, arch, 30, robot="nxt", now=NOW)
check("--robot limits the plan to that robot", [i.key for i in only] == ["nxt/room/old-nxt"], only)
check("a longer age keeps more", {i.key for i in R.plan(data, arch, 50, now=NOW) if i.action == "archive"} == {"duck/room/old"})
check("read_record gives the run's own record", R.read_record(keys.run_dir(data, "duck/room/old-truth")).get("judge_truth") == {"truth": True})

# the move
check("the archive is usable", R.refusal(data, arch) is None, R.refusal(data, arch))
moved, failed = R.apply(list(items.values()), data, arch, 30, now=NOW)
check("three runs moved, none failed", sorted(m["key"] for m in moved) == ["duck/room/edge", "duck/room/old", "nxt/room/old-nxt"] and not failed,
      (moved, failed))
check("a run folder is renamed whole, its layout kept, its other files with it", (arch / "runs/nxt/room/old-nxt/run.mcap").is_file()
      and (arch / "runs/nxt/room/old-nxt/note.txt").is_file() and not keys.run_dir(data, "nxt/room/old-nxt").exists())
check("what stays, stays untouched", all(keys.run_dir(data, k).exists() for k in want if want[k] == "keep")
      and (keys.run_dir(data, "duck/room/garbage") / "run.mcap").read_bytes() == b"this is not an mcap file")
log = [json.loads(line) for line in (arch / R.LOG).read_text().splitlines()]
check("one log line per move: key, from, to, age, size", [l["key"] for l in log] == [m["key"] for m in moved]
      and all(l["from"].startswith(str(data)) and l["to"].startswith(str(arch)) and l["size"] > 0 and l["age_days"] >= 30 for l in log), log)
moved2, failed2 = R.apply(R.plan(data, arch, 30, now=NOW), data, arch, 30, now=NOW)
check("a second run moves nothing", not moved2 and not failed2 and len((arch / R.LOG).read_text().splitlines()) == 3)
back = arch / "runs/duck/room/old"
shutil.move(str(back), str(keys.run_dir(data, "duck/room/old")))
check("restoring is a mv: the run plans as archivable again", {i.key: i.action for i in R.plan(data, arch, 30, now=NOW)}["duck/room/old"] == "archive")

# the refusals
data, arch = build("b")
keys.run_dir(arch, "duck/room/old").parent.mkdir(parents=True, exist_ok=True)
(arch / "runs/duck/room/old").mkdir()
items = {i.key: i for i in R.plan(data, arch, 30, now=NOW)}
check("a target that exists is refused for that run, saying so", items["duck/room/old"].action == "refuse" and "target exists" in items["duck/room/old"].reason
      and items["duck/room/edge"].action == "archive", items["duck/room/old"])
moved, failed = R.apply(list(items.values()), data, arch, 30, now=NOW)
check("apply moves the others and leaves the refused run where it is", sorted(m["key"] for m in moved) == ["duck/room/edge", "nxt/room/old-nxt"]
      and keys.run_dir(data, "duck/room/old").exists() and not any((arch / "runs/duck/room/old").iterdir()), (moved, failed))
data, arch = build("c")
for name, a in (("inside the data folder", data / "archive"), ("the data folder itself", data), ("deeper inside it", data / "runs/x"),
                ("holding the data folder", tmp / "c")):
    why = R.refusal(data, a)
    check(f"refused: the archive {name}", why is not None and ("inside" in why), why)
b4 = tree(tmp / "c")
try:
    R.apply(R.plan(data, data / "archive", 30, now=NOW), data, data / "archive", 30, now=NOW)
    raised = None
except ValueError as e:
    raised = str(e)
check("apply under a refusal raises and moves nothing", raised and "inside the data folder" in raised and tree(tmp / "c") == b4, raised)
check("a data folder with no runs folder is refused", "no runs folder" in (R.refusal(tmp / "nowhere", tmp / "nowhere-archive") or ""))
shm = Path("/dev/shm")
if shm.is_dir() and os.stat(shm).st_dev != os.stat(data / "runs").st_dev:
    other = Path(tempfile.mkdtemp(prefix="retention-", dir=shm))
    atexit.register(shutil.rmtree, other, True)
    why = R.refusal(data, other / "data-archive")
    check("refused: the archive on another filesystem", why is not None and "another filesystem" in why, why)
else:
    print("note: /dev/shm is on the data folder's filesystem here: the other-filesystem refusal is not exercised")

# a writer that starts between the plan and the move
data, arch = build("d")
items = R.plan(data, arch, 30, now=NOW)
(keys.run_dir(data, "duck/room/old") / "writer.lock").write_text("{}")
moved, failed = R.apply(items, data, arch, 30, now=NOW)
check("a run that got a writer after the plan is not moved", ("duck/room/old", "a writer started on it") in failed
      and keys.run_dir(data, "duck/room/old").exists() and "duck/room/old" not in [m["key"] for m in moved], (moved, failed))

check.done()
