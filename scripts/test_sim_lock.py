"""Self-test of scripts/sim-lock: the command runs with its own exit status when nobody holds the lock, waits for a holder (a plain
flock(2) one, as `flock(1)` takes) and runs once it lets go, gives up with 75 after its timeout without running the command,
holds the lock while the command runs, does not wait for itself when nested, and finds its file from the environment. No simulator.
Run by `make test-sim-lock`.

    python3 scripts/test_sim_lock.py"""

import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SIM_LOCK = str(Path(__file__).resolve().parent / "sim-lock")
tmp = Path(tempfile.mkdtemp(prefix="simlock-"))
LOCK = tmp / "sim.lock"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


def env(**extra):
    e = {k: v for k, v in os.environ.items() if not k.startswith("ROBOTICS_LAB_SIM_LOCK")}
    e["ROBOTICS_LAB_SIM_LOCK"] = str(LOCK)
    e.update(extra)
    return e


def run(*args, timeout=30, **extra):
    return subprocess.run([sys.executable, SIM_LOCK, *args], env=env(**extra), capture_output=True, text=True, timeout=timeout)


def try_lock() -> bool:
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


try:
    r = run("--", "sh", "-c", "echo ran; exit 3")
    check("with nobody holding the lock the command runs and its exit status and output are the command's own",
          r.returncode == 3 and r.stdout == "ran\n" and r.stderr == "", (r.returncode, r.stdout, r.stderr))
    check("... and the lock is free again after it", try_lock())

    p = subprocess.Popen([sys.executable, SIM_LOCK, "--", "sleep", "3"], env=env())
    time.sleep(0.5)
    check("while the command runs the lock is held (a second taker is refused)", not try_lock())
    p.wait(timeout=10)
    check("... and free when it exits", try_lock())

    held = os.open(LOCK, os.O_RDWR | os.O_CREAT)
    fcntl.flock(held, fcntl.LOCK_EX)
    t0 = time.monotonic()
    r = run("--timeout", "1", "--", "sh", "-c", "echo should-not-run")
    check("a lock held by someone else: waits the timeout, exits 75, never runs the command, says it waited",
          r.returncode == 75 and "should-not-run" not in r.stdout and 1 <= time.monotonic() - t0 < 10 and "waiting for" in r.stderr, (r.returncode, r.stdout, r.stderr))

    w = subprocess.Popen([sys.executable, SIM_LOCK, "--timeout", "20", "--", "sh", "-c", "echo got-it"], env=env(), stdout=subprocess.PIPE, text=True)
    time.sleep(1.0)
    check("a job that is waiting has not run", w.poll() is None)
    fcntl.flock(held, fcntl.LOCK_UN)
    os.close(held)
    out, _ = w.communicate(timeout=15)
    check("... and runs once the holder lets go", w.returncode == 0 and out == "got-it\n", (w.returncode, out))

    r = run("--timeout", "20", "--", sys.executable, SIM_LOCK, "--timeout", "1", "--", "echo", "inner")
    check("a sim-lock inside a sim-lock does not wait for the outer one (`sim-lock -- make sim-duck`)", r.returncode == 0 and r.stdout == "inner\n", (r.returncode, r.stdout, r.stderr))

    r = run("--", "no-such-command-xyz")
    check("a command that does not exist is 127, said, and the lock is free", r.returncode == 127 and "cannot run" in r.stderr and try_lock(), (r.returncode, r.stderr))
    r = run()
    check("no command is a usage error (2)", r.returncode == 2, (r.returncode, r.stderr))

    r = run("--path")
    check("--path prints the file ROBOTICS_LAB_SIM_LOCK names", r.stdout.strip() == str(LOCK), r.stdout)
    e = env(XDG_RUNTIME_DIR="/run/user/xyz")
    del e["ROBOTICS_LAB_SIM_LOCK"]
    r = subprocess.run([sys.executable, SIM_LOCK, "--path"], env=e, capture_output=True, text=True)
    check("the default is ${XDG_RUNTIME_DIR}/robotics-lab-sim.lock", r.stdout.strip() == "/run/user/xyz/robotics-lab-sim.lock", r.stdout)
    del e["XDG_RUNTIME_DIR"]
    r = subprocess.run([sys.executable, SIM_LOCK, "--path"], env=e, capture_output=True, text=True)
    check("... and /tmp/robotics-lab-sim.lock with no XDG_RUNTIME_DIR", r.stdout.strip() == "/tmp/robotics-lab-sim.lock", r.stdout)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    print(f"\nFAIL {len(failures)}: {failures}")
    sys.exit(1)
print("\nPASS test_sim_lock")
