#!/usr/bin/env python3
"""Local preflight before asking the homelab session for a DGX training run. Read only: it touches no DGX, no docker, no network except
`git ls-remote` (a read), and writes nothing. It checks what only the project's repo can tell, and prints the request to send.

    preflight.py /work/microduck-nav --task Mjlab-Nav-OneWall-MicroDuck --num-envs 4096 --max-runtime 30m \\
        --args="--agent.max-iterations 200 --agent.save-interval 50 --agent.logger tensorboard" [--start 2026-11-27T04:00Z]

Checks, one line each (PASS / FAIL / WARN / INFO):
  repo       the working tree is clean (untracked files count) and HEAD is on origin (git ls-remote), so the DGX can check out the commit
  lock       uv.lock pins torch to a +cu129 build with a cp312 aarch64 wheel for linux-aarch64 (the GB10), and no +cpu torch resolves there
  task       the task id is registered in the repo (a source file names it)
  walker     the walker policy file's sha256 is ce894d30...63e0a (policies v10), at $MICRODUCK_WALKER_ONNX or ~/.cache/duck-sim/policies/current
  args       --agent.save-interval (rsl_rl does not save on a stop) and --agent.logger tensorboard (mjlab's default, W&B, stops without a key)
  runtime    ROBOTICS_MAX_RUNTIME is one number and one unit (`210m`; GNU timeout refuses `3h30m`)
  window     the run, with its swaps, ends before 23:20Z and starts at or after 03:00Z: the nightly window 23:45Z-03:00Z stays clear

Ends `DGX-PREFLIGHT READY` or `NOT READY` and, when ready, the request block. Exit 0 / 1. Python 3.11+ (tomllib)."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

WALKER_SHA = "ce894d30b3343036d499bfac1102bdaa58d59a21c1b58401ecb70fb6a2f63e0a"
WALKER_ENV = "MICRODUCK_WALKER_ONNX"
WALKER_DEFAULT = "~/.cache/duck-sim/policies/current/velstand.onnx"
BACK_BY = dt.time(23, 20)       # the operator's: prod back by 23:20Z (the recipe says 23:30Z; the earlier one holds)
NIGHTLY_END = dt.time(3, 0)
SWAP_IN_MIN, SWAP_OUT_MIN = 2, 8         # measured 2026-11-13: 1 min in, 6 m 18 s out; a margin on each
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

results: list = []


def line(status: str, name: str, detail: str = "") -> None:
    results.append(status)
    print(f"{status:5} {name}  {detail}", flush=True)


def git(repo: Path, *a: str) -> tuple:
    p = subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def check_repo(repo: Path) -> str | None:
    rc, sha, err = git(repo, "rev-parse", "HEAD")
    if rc:
        line("FAIL", "repo", f"{repo} is not a git repository: {err}")
        return None
    _, porcelain, _ = git(repo, "status", "--porcelain")
    _, branch, _ = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if porcelain:
        line("FAIL", "repo clean", f"{len(porcelain.splitlines())} changed or untracked paths (the DGX checks out a commit, not your tree): {porcelain.splitlines()[0]} ...")
        return None
    line("PASS", "repo clean", f"branch {branch}, HEAD {sha[:12]}")
    rc, out, err = git(repo, "ls-remote", "origin", f"refs/heads/{branch}")
    if rc == 0 and out:
        remote = out.split()[0]
        if remote == sha:
            line("PASS", "pushed", f"origin/{branch} is {sha[:12]} (git ls-remote)")
            return sha
        rc2, _, _ = git(repo, "merge-base", "--is-ancestor", sha, remote)
        line("PASS" if rc2 == 0 else "FAIL", "pushed",
             f"origin/{branch} is {remote[:12]}, HEAD {sha[:12]} " + ("is in it (origin is ahead)" if rc2 == 0 else "is NOT on origin: push it first"))
        return sha if rc2 == 0 else None
    rc3, tracked, _ = git(repo, "rev-parse", f"origin/{branch}")
    if rc3 == 0 and tracked == sha:
        line("WARN", "pushed", f"git ls-remote failed ({err or 'no such branch'}); the local origin/{branch} is {sha[:12]} as of the last fetch, not proof")
        return sha
    line("FAIL", "pushed", f"HEAD {sha[:12]} is not on origin/{branch} ({err or 'ls-remote empty'}): push it first")
    return None


def check_lock(repo: Path) -> None:
    lock = repo / "uv.lock"
    try:
        data = tomllib.loads(lock.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        line("FAIL", "lock", f"{lock}: {exc}")
        return
    torch = [p for p in data.get("package", []) if p["name"] == "torch"]
    cu = [p for p in torch if p["version"].endswith("+cu129")]
    arm_wheels = [w["url"] for p in cu for w in p.get("wheels", []) if "aarch64" in w["url"] and "cp312" in w["url"]]
    cpu_arm = [p["version"] for p in torch if p["version"].endswith("+cpu") and any("aarch64" in m for m in p.get("resolution-markers", []))]
    if not cu:
        line("FAIL", "lock", f"no torch +cu129 in {lock.name} (versions: {[p['version'] for p in torch]}): the DGX would get a CPU torch (the recipe's troubleshooting)")
    elif not arm_wheels:
        line("FAIL", "lock", f"torch {cu[0]['version']} has no cp312 aarch64 wheel in the lock")
    elif cpu_arm:
        line("FAIL", "lock", f"a +cpu torch resolves for aarch64: {cpu_arm}")
    else:
        line("PASS", "lock", f"torch {cu[0]['version']} from {cu[0]['source']['registry']}, wheel {arm_wheels[0].rsplit('/', 1)[-1]}")


def check_task(repo: Path, task: str) -> None:
    hits = [str(p.relative_to(repo)) for p in (repo / "src").rglob("*.py") if task in p.read_text(errors="replace")] if (repo / "src").is_dir() else []
    line("PASS" if hits else "FAIL", "task", f"{task!r} " + (f"is named in {hits[0]}" if hits else "is named nowhere under src/: the trainer will not find it"))


def check_walker() -> None:
    path = Path(os.path.expanduser(os.environ.get(WALKER_ENV) or WALKER_DEFAULT))
    try:
        h = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        line("FAIL", "walker", f"{path}: {exc}")
        return
    line("PASS" if h == WALKER_SHA else "FAIL", "walker", f"{path} sha256 {h[:8]}...{h[-5:]} " + ("matches policies v10 (ce894d30...63e0a)" if h == WALKER_SHA else "is NOT ce894d30...63e0a"))
    print("      the DGX's own copy (/opt/robotics/cache/assets/walker-seed-v10/velstand.onnx) is the homelab session's to check; we do not touch the DGX")


def check_args(args: str) -> None:
    norm = args.replace("_", "-")
    miss = []
    if not re.search(r"--agent\.save-interval[ =]\d+", norm):
        miss.append("--agent.save-interval N (rsl_rl does not save when a run is stopped: only model_0 would survive a timeout)")
    if not re.search(r"--agent\.logger[ =]tensorboard", norm):
        miss.append("--agent.logger tensorboard (W&B stops at once without a key)")
    if miss:
        line("FAIL", "args", "missing " + "; ".join(miss))
    else:
        line("PASS", "args", args)
    if "--agent.max-iterations" not in norm:
        line("WARN", "args", "no --agent.max-iterations: the task's own length applies (a full task is tens of hours) and only the timeout ends it")


def parse_runtime(s: str) -> int | None:
    m = re.fullmatch(r"(\d+)([smhd])", s)
    return int(m[1]) * UNITS[m[2]] if m else None


def check_window(runtime: str, start: dt.datetime) -> None:
    secs = parse_runtime(runtime)
    if secs is None:
        line("FAIL", "runtime", f"{runtime!r}: one number and one unit (210m), as GNU timeout reads it; `3h30m` failed the first swap on 2026-11-14")
        return
    line("PASS", "runtime", f"{runtime} = {secs // 60} min")
    end = start + dt.timedelta(minutes=SWAP_IN_MIN + SWAP_OUT_MIN) + dt.timedelta(seconds=secs)
    back = dt.datetime.combine(start.date(), BACK_BY, tzinfo=dt.timezone.utc)
    open_at = dt.datetime.combine(start.date(), NIGHTLY_END, tzinfo=dt.timezone.utc)
    when = f"start {start:%Y-%m-%d %H:%MZ}, runtime {runtime}, swaps +{SWAP_IN_MIN + SWAP_OUT_MIN} min: prod is back at {end:%Y-%m-%d %H:%MZ}"
    if start < open_at:
        line("FAIL", "window", f"{when}; the start is before 03:00Z, inside the nightly window (23:45Z-03:00Z)")
    elif end > back:
        line("FAIL", "window", f"{when}; that is after {BACK_BY:%H:%M}Z (the operator's deadline; the recipe says 23:30Z)")
    else:
        line("PASS", "window", f"{when}, before {BACK_BY:%H:%M}Z; the operator still gives the window and the homelab checks prod is idle")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--task", required=True)
    ap.add_argument("--entry", default="train")
    ap.add_argument("--num-envs", type=int, default=4096)
    ap.add_argument("--args", dest="train_args", default="", help='the trainer flags to send, as ROBOTICS_TRAIN_ARGS (a string)')
    ap.add_argument("--max-runtime", required=True)
    ap.add_argument("--start", help="when the swap would start, e.g. 2026-11-27T04:00Z (default: now, UTC)")
    a = ap.parse_args()
    start = dt.datetime.fromisoformat(a.start.replace("Z", "+00:00")) if a.start else dt.datetime.now(dt.timezone.utc)
    start = start.astimezone(dt.timezone.utc)

    sha = check_repo(a.repo)
    check_lock(a.repo)
    check_task(a.repo, a.task)
    check_walker()
    check_args(a.train_args)
    check_window(a.max_runtime, start)
    ok = "FAIL" not in results
    print("DGX-PREFLIGHT " + ("READY" if ok else "NOT READY"))
    if ok:
        print("REQUEST for the homelab session (it runs the swap, .env and prepare.sh; we run nothing on the DGX):")
        print(f"  project {a.repo.name}  commit {sha}")
        print(f"  entry {a.entry}  task {a.task}  num-envs {a.num_envs}  max runtime {a.max_runtime}")
        print(f"  args {a.train_args}")
        print(f"  window start {start:%Y-%m-%dT%H:%MZ}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
