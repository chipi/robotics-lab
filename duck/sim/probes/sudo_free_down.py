"""Does stopping the simulator from a script stay clear of sudo? One `duck-sim down` through the runner's own path
(simreset.down), and the user's pam_faillock tally before and after: a sudo that asks for a password with no terminal to
ask on is a failed login, and ten of them lock the user's sudo for two minutes (docs/wip/DUCK-SIM-FOR-AGENTS.md).

    uv run python sim/probes/sudo_free_down.py

Exit 1 when the tally was written during the down. Also prints the tally's records (time, service or terminal), which is
how a lockout is read without root.
"""

import datetime
import getpass
import os
import struct
import sys
import time

from duck_lab.nav import simreset

TALLY = f"/run/faillock/{getpass.getuser()}"


def records() -> list:
    """pam_faillock's tally: struct tally {char source[52]; uint16 reserved; uint16 status; uint64 time}."""
    try:
        data = open(TALLY, "rb").read()
    except FileNotFoundError:
        return []
    out = []
    for i in range(len(data) // 64):
        rec = data[i * 64:(i + 1) * 64]
        _, _, t = struct.unpack("<HHQ", rec[52:64])
        out.append((t, rec[:52].split(b"\0")[0].decode(errors="replace")))
    return out


def written() -> float | None:
    try:
        return os.stat(TALLY).st_mtime
    except FileNotFoundError:
        return None


def main() -> None:
    before = written()
    t0 = time.monotonic()
    simreset.down()
    after = written()
    print(f"duck-sim down: {time.monotonic() - t0:.1f} s")
    for t, source in records():
        print(f"  tally: {datetime.datetime.fromtimestamp(t):%H:%M:%S}  {source}")
    ok = after == before
    print("SUDO-FREE DOWN", "PASS" if ok else "FAIL: the faillock tally was written during the down")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
