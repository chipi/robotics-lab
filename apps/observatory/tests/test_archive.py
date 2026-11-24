"""`observatory archive` (phase 5 step 7, docs/wip/TELEMETRY-RETENTION-DESIGN.md) through the command line: a dry run that prints the table and
moves nothing, --apply that renames the old runs out of the data folder, the Observatory's index losing exactly their keys on the next
scan, the refusals, --robot, and the age from the installation file. Only temporary folders; the real data folder is never named.
Run: cd apps/observatory && uv run python tests/test_archive.py"""

import contextlib
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from helpers import Checks, catalog, make_run, scene, tick
from runfile import keys, mcapio
from observatory import cli

check = Checks("ARCHIVE")
DAY = 86400
HEAD = [(0.0, "epoch", {"map_to_world": [1.0, 0.0, 0.0]}), tick(1.0, 0.0), tick(1.1, 0.1)]
for k in [k for k in os.environ if k.startswith(("OBSERVATORY_", "MINIVIEW_DATA", "ROBOTICS_LAB"))]:
    if k not in ("OBSERVATORY_INDEX", "MINIVIEW_INDEX"):
        del os.environ[k]


def run(*argv):
    """The command line as the operator types it: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["observatory", *argv]
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
        if isinstance(e.code, str):
            err.write(e.code)
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


def age(data, key, days):
    t = time.time() - days * DAY
    os.utime(keys.run_dir(data, key) / "run.mcap", (t, t))


def official(data, key):
    rec = mcapio.new_run(key, {"name": key.split("/")[0], "radius": 0.08, "height": 0.27}, key.split("/")[1], "exploration", 1_700_000_000 * 10**9)
    rec["judge_truth"] = {"truth": True}
    mcapio.write(keys.run_dir(data, key), rec, HEAD)


with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    arch = Path(tmp) / "data-archive"
    cat = catalog(data)
    cat.put_scene(scene())
    make_run(data, "duck/room/old", HEAD)
    make_run(data, "duck/room/young", HEAD)
    make_run(data, "nxt/room/old-nxt", HEAD)
    official(data, "duck/room/old-official")
    for k, d in (("duck/room/old", 60), ("duck/room/young", 3), ("nxt/room/old-nxt", 45), ("duck/room/old-official", 100)):
        age(data, k, d)
    cat.scan()
    check("(setup) the Observatory's index knows the four runs", sorted(cat.index.keys()) == sorted(["duck/room/old", "duck/room/young", "nxt/room/old-nxt", "duck/room/old-official"]),
          cat.index.keys())

    code, out, err = run("--data", str(data), "archive", "--days", "30")
    check("a dry run prints each run with its age, official, size, decision and reason", code == 0 and all(k in out for k in (
        "duck/room/old ", "duck/room/young", "nxt/room/old-nxt", "duck/room/old-official")) and "archive: older than 30 days, not official" in out
        and "keep: official run" in out and "keep: younger than 30 days" in out, out + err)
    check("a dry run says it moved nothing and names where it would", "dry run: nothing moved" in out and str(arch) in out
          and "2 of 4 runs to archive" in out, out)
    check("a dry run moves nothing and creates no archive", not arch.exists() and all(keys.run_dir(data, k).exists() for k in cat.index.keys()))
    cat.scan()
    check("... and the index still has the four", len(cat.index.keys()) == 4)

    code, out, err = run("archive", "--data", str(data), "--days", "30", "--robot", "nxt", "--apply")
    check("--robot nxt --apply moves the nxt run only", code == 0 and "moved nxt/room/old-nxt" in out and (arch / "runs/nxt/room/old-nxt/run.mcap").is_file()
          and keys.run_dir(data, "duck/room/old").exists() and not (arch / "runs/duck").exists(), out + err)

    code, out, err = run("--data", str(data), "archive", "--days", "30", "--apply")
    check("--apply moves the rest that is old and not official", code == 0 and "archived 1 runs" in out and (arch / "runs/duck/room/old/run.mcap").is_file()
          and not keys.run_dir(data, "duck/room/old").exists(), out + err)
    check("the official run and the young run stay", (keys.run_dir(data, "duck/room/old-official") / "run.mcap").is_file()
          and (keys.run_dir(data, "duck/room/young") / "run.mcap").is_file())
    log = [json.loads(l) for l in (arch / "archive-log.jsonl").read_text().splitlines()]
    check("the log has a line per move", [l["key"] for l in log] == ["nxt/room/old-nxt", "duck/room/old"], log)
    cat.scan()
    check("the next scan drops exactly the archived keys from the index", sorted(cat.index.keys()) == ["duck/room/old-official", "duck/room/young"], cat.index.keys())
    code, out, err = run("--data", str(data), "archive", "--days", "30", "--apply")
    check("applying again has nothing to move", code == 0 and "archived 0 runs" in out, out + err)

    # the refusals
    before = sorted(str(p) for p in Path(tmp).rglob("*"))
    code, out, err = run("--data", str(data), "archive", "--archive", str(data / "old-runs"), "--apply")
    check("an archive inside the data folder is refused, nothing moved", code != 0 and "refused" in err and "inside the data folder" in err
          and sorted(str(p) for p in Path(tmp).rglob("*")) == before, err)
    code, out, err = run("--data", str(data), "archive", "--days", "0")
    check("--days below 1 is refused", code != 0 and "1 or more" in err, err)
    make_run(data, "duck/room/older", HEAD)
    age(data, "duck/room/older", 90)
    (arch / "runs/duck/room/older").mkdir(parents=True)
    code, out, err = run("--data", str(data), "archive", "--days", "30", "--apply")
    check("a target that exists is refused for that run: it stays, the exit code says so", code == 1
          and "refuse: the target exists" in out and keys.run_dir(data, "duck/room/older").exists(), out + err)
    code, out, err = run("--data", str(data), "archive", "--days", "30")
    check("the dry run shows the refusal and exits 1", code == 1 and "refuse: the target exists" in out, out + err)

    # the age from the installation file; the data folder from the global option or nothing
    inst = Path(tmp) / "installation.json"
    inst.write_text(json.dumps({"installation": 1, "runs": {"archive_after_days": 2}}))
    os.environ["ROBOTICS_LAB_INSTALLATION"] = str(inst)
    code, out, err = run("--data", str(data), "archive")
    check("with no --days the installation file's runs.archive_after_days decides (2 days: the young run is 3 days old)",
          code == 1 and "after 2 days" in out and "archive: older than 2 days, not official" in out and "duck/room/young" in out
          and out.count("archive: older than 2 days") == 1, out + err)
    inst.write_text(json.dumps({"installation": 1}))
    code, out, err = run("--data", str(data), "archive")
    check("with neither, 30 days", "after 30 days" in out, out + err)
    os.environ["ROBOTICS_LAB_INSTALLATION"] = str(Path(tmp) / "none.json")
    code, out, err = run("archive")
    check("no data folder named anywhere: said, exit non-zero", code != 0 and "no data folder" in err, err)

check.done()
