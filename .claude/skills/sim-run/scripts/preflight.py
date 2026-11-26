#!/usr/bin/env python3
"""Preflight before a simulator job, read only: who holds the simulator lock, whether the simulator is up, and which installation file a run
would read. It starts nothing, takes no lock, runs no sudo, writes nothing.

    preflight.py                  # the lock, the host, the simulator, the installation
    preflight.py --json

One line per check (PASS / WARN / FAIL / INFO), then `SIM-PREFLIGHT READY`, `BUSY` or `NOT READY`.
Exit 0 READY, 3 BUSY (another job holds the lock: wait, do not start), 1 NOT READY.
Standard library only; Linux (/proc/locks) with a fallback that says it cannot tell."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SUDO_ASK = 'if sudo systemctl is-active --quiet "$name"'     # simhost.simulator.SUDO_ASK: the unpatched duck-sim's line
DEFAULT_INSTALLATION = Path("~/.config/robotics-lab/installation.json").expanduser()
DEFAULT_HOST = Path("~/.config/robotics-lab/host.json").expanduser()

lines: list = []


def line(status: str, name: str, detail: str = "") -> None:
    lines.append({"status": status, "check": name, "detail": detail})


def lock_path() -> Path:
    """The file scripts/sim-lock locks (its lock_path(), repeated here so this script takes nothing from it)."""
    explicit = os.environ.get("ROBOTICS_LAB_SIM_LOCK")
    if explicit:
        return Path(os.path.expanduser(explicit))
    return Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "robotics-lab-sim.lock"


def holder_pids(path: Path) -> list | None:
    """Pids holding a flock on `path`, from /proc/locks (no lock is taken); None when it cannot be read."""
    try:
        st = path.stat()
        table = Path("/proc/locks").read_text()
    except OSError:
        return None
    tag = f"{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}"
    pids = []
    for row in table.splitlines():
        f = row.split()
        if len(f) >= 6 and f[1] == "FLOCK" and f[5] == tag:
            pids.append(int(f[4]))
    return pids


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()[:160]
    except OSError:
        return "(gone)"


def listening(port: int) -> bool:
    """Is something listening on 127.0.0.1:port: read from /proc/net/tcp, no connection made."""
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            f = row.split()
            if f[3] == "0A" and int(f[1].rsplit(":", 1)[1], 16) == port:
                return True
    return False


def read_json(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError) as exc:
        return exc


def check_lock() -> bool:
    """True when the lock is free."""
    path = lock_path()
    default = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "robotics-lab-sim.lock"
    info = f"{path}" + ("" if path == default else f"  (not the default {default}: every job on this machine must name this same file)")
    if not path.exists():
        line("PASS", "lock", f"{info} does not exist yet: nobody has taken it")
        return True
    pids = holder_pids(path)
    if pids is None:
        line("WARN", "lock", f"{info}: /proc/locks unreadable, cannot tell who holds it; `scripts/sim-lock` will say when it waits")
        return True
    if not pids:
        line("PASS", "lock", f"{info} is free")
        return True
    note = ""
    try:
        note = path.read_text().strip()[:200]
    except OSError:
        pass
    line("FAIL", "lock", f"{info} is HELD by pid {pids[0]} ({cmdline(pids[0])})" + (f"; its record: {note}" if note else "") +
         ": wait for it, do not start a second job")
    return False


def check_host() -> dict | None:
    f = Path(os.path.expanduser(os.environ.get("ROBOTICS_LAB_HOST") or str(DEFAULT_HOST)))
    h = read_json(f)
    if isinstance(h, Exception) or not isinstance(h, dict):
        line("FAIL", "host file", f"{f}: {h if isinstance(h, Exception) else 'not an object'}  (`simhost show`; `scripts/host-check`)")
        return None
    line("PASS", "host file", f"{f}: kind {h.get('kind')}, robot {h.get('robot')}, truth_port {h.get('truth_port')}")
    md = h.get("pollen", {}).get("microduck")
    script = Path(os.path.expanduser(md or "/nonexistent")) / "scripts" / "duck-sim"
    try:
        body = script.read_text()
    except OSError as exc:
        line("FAIL", "duck-sim", f"{script}: {exc}")
        return h
    if SUDO_ASK in body:
        line("FAIL", "duck-sim sudo patch", f"{script} still asks sudo on every `down`: ten failures with no terminal lock the user's sudo; "
             "apply robots/duck/sim/patches/duck-sim-sudo-free-down.patch (docs/wip/DUCK-SIM-FOR-AGENTS.md)")
    else:
        line("PASS", "duck-sim sudo patch", "applied (the unpatched sudo check is absent)")
    return h


def check_sim(h: dict | None) -> None:
    if not h:
        return
    port = h.get("truth_port") or 0
    state = Path(os.path.expanduser(h.get("state") or "~/.cache/duck-sim"))
    up = bool(port) and listening(int(port))
    pids = {}
    for pf in sorted(state.glob("*.pid")):
        try:
            pid = int(pf.read_text().strip())
        except (OSError, ValueError):
            continue
        if alive(pid):
            pids[pf.stem] = pid
    if up or pids:
        line("INFO", "simulator", f"UP: body server {'listening on ' + str(port) if up else 'not listening'}; live pid files: "
             + (", ".join(f"{k}={v}" for k, v in pids.items()) or "none") + ". Every run resets it (`down` then `up`, about 40 s): never share it with a job that is running")
    else:
        line("INFO", "simulator", f"DOWN: nothing listening on {port}, no live pid file in {state}; the job's own reset brings it up")


def check_installation() -> None:
    env = os.environ.get("ROBOTICS_LAB_INSTALLATION")
    default = DEFAULT_INSTALLATION
    if not env:
        line("WARN", "installation", f"ROBOTICS_LAB_INSTALLATION is not set: a run reads {default}, the operator's own file, and writes its "
             "data and index. Set it to a scratch file outside the repo (docs/wip/NXT-SIM.md 'A test installation file'); never edit the operator's")
        return
    f = Path(os.path.expanduser(env))
    inst = read_json(f)
    if isinstance(inst, Exception) or not isinstance(inst, dict):
        line("FAIL", "installation", f"{f}: {inst if isinstance(inst, Exception) else 'not an object'}")
        return
    if f.resolve() == default.resolve():
        line("WARN", "installation", f"{f} IS the operator's installation file: runs write its data and index; use a scratch copy")
        return
    detail = f"{f} (scratch: not the operator's {default})"
    base = read_json(default)
    shared = []
    if isinstance(base, dict):
        for k in ("data", "index", "state"):
            if inst.get(k) and base.get(k) and os.path.expanduser(str(inst[k])) == os.path.expanduser(str(base[k])):
                shared.append(k)
    if shared:
        line("WARN", "installation", detail + f"; but its {', '.join(shared)} is the operator's own folder: runs would write there")
    else:
        line("PASS", "installation", detail + f"; data {inst.get('data')}, robots {sorted((inst.get('robots') or {}))}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    free = check_lock()
    check_sim(check_host())
    check_installation()
    bad = [x for x in lines if x["status"] == "FAIL"]
    busy = not free
    verdict = "BUSY" if busy else ("NOT READY" if bad else "READY")
    if a.json:
        print(json.dumps({"checks": lines, "verdict": verdict}, indent=1))
    else:
        for x in lines:
            print(f"{x['status']:5} {x['check']}  {x['detail']}")
        print(f"SIM-PREFLIGHT {verdict}")
    return 3 if busy else (1 if bad else 0)


if __name__ == "__main__":
    sys.exit(main())
