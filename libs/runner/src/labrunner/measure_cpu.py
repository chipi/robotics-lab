"""What the robot's daemons cost the board's processor (phase 5 item 4b unit B9; RFC-0002 phase 5: "mapd's CPU cost on the board"). Upstream
leaves mapd off by default because its standing cost was never measured; this is the measurement. Read-only: it reads /proc, sends nothing
to any socket and never moves the robot.

It must run ON the board, because a forwarded socket says nothing about the board's processor. One file, standard library only, so it can
be piped to the duck's python without installing anything (not verified: that the duck has a python3):

    ssh microduck@duck python3 - --seconds 120 --label map-on < libs/runner/src/labrunner/measure_cpu.py
    lab-measure-cpu --seconds 60 --label sim                  # on this machine, against the simulator's processes (proves the script only)

Run it twice with the duck standing, the same posture each time: once with `[map] enabled = false` in robotd.toml and once with it true.
mapd's cost is its own row and the difference between the two machine rows. Do it standing and again walking: mapd works at stops and
on frames, so an idle number understates it.

Numbers: a process's cpu_pct is of ONE core (100 = a core fully busy, a 4-core board tops out at 400); machine_busy_pct is of all cores.
The sample is one second by default; p95 and max are over those windows, so a burst shorter than the window is smoothed."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

DEFAULT_PROCESSES = ("mapd", "robotd", "tofd")
THERMAL = "/sys/class/thermal"


def parse_proc_stat(text: str) -> tuple:
    """(cpu ticks used, threads, resident pages) from a /proc/<pid>/stat line. The name in field 2 may hold spaces and brackets, so the
    rest is read from after its last ')'."""
    rest = text[text.rindex(")") + 2:].split()          # rest[0] is field 3, the state
    return int(rest[11]) + int(rest[12]), int(rest[17]), int(rest[21])


def parse_cpu_line(text: str) -> tuple:
    """(busy, total) jiffies of the machine from the first line of /proc/stat; idle and iowait are not busy."""
    v = [int(x) for x in text.split()[1:9]]             # user nice system idle iowait irq softirq steal
    total = sum(v)
    return total - v[3] - v[4], total


def percentile(values: list, p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(p / 100.0 * len(s)))]


def pids_by_name(names, proc: Path = Path("/proc")) -> dict:
    """name -> the lowest pid whose comm is exactly that name (comm is cut at 15 characters by the kernel)."""
    found = {}
    for d in sorted(proc.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 0):
        if not d.name.isdigit():
            continue
        try:
            comm = (d / "comm").read_text().strip()
        except OSError:
            continue
        if comm in names and comm not in found:
            found[comm] = int(d.name)
    return found


def summarise(samples: list, clk_tck: int, page_bytes: int, ncpu: int) -> dict:
    """samples: [{"t": s, "busy": j, "total": j, "procs": {name: (ticks, threads, pages) or None}, "temp_c": x or None}] one per window.
    Per process the CPU in each window (of one core), then its mean, p95 and max; a process missing from a window counts for neither."""
    out = {"windows": len(samples) - 1, "processes": {}}
    for name in samples[0]["procs"]:
        pct, rss, thr = [], [], []
        for a, b in zip(samples, samples[1:]):
            pa, pb = a["procs"].get(name), b["procs"].get(name)
            if pa is None or pb is None:
                continue
            pct.append((pb[0] - pa[0]) / clk_tck / (b["t"] - a["t"]) * 100.0)
            rss.append(pb[2] * page_bytes / 1048576.0)
            thr.append(pb[1])
        out["processes"][name] = ({"cpu_pct_mean": round(sum(pct) / len(pct), 2), "cpu_pct_p95": round(percentile(pct, 95), 2),
                                   "cpu_pct_max": round(max(pct), 2), "rss_mb_max": round(max(rss), 1), "threads": max(thr)}
                                  if pct else None)
    busy = [(b["busy"] - a["busy"]) / max(1, b["total"] - a["total"]) * 100.0 for a, b in zip(samples, samples[1:])]
    temps = [s["temp_c"] for s in samples if s["temp_c"] is not None]
    out["machine"] = {"ncpu": ncpu, "busy_pct_mean": round(sum(busy) / len(busy), 2), "busy_pct_p95": round(percentile(busy, 95), 2),
                      "busy_pct_max": round(max(busy), 2), "temp_c_max": round(max(temps), 1) if temps else None}
    return out


def table(result: dict) -> str:
    m = result["machine"]
    lines = [f"cpu cost  label={result['label']}  host={result['host']}  {result['seconds']} s in {result['windows']} windows of "
             f"{result['interval_s']} s",
             f"{'process':<10}{'pid':>8}{'cpu% mean':>11}{'p95':>8}{'max':>8}{'rss MB':>9}{'threads':>9}   (cpu% of one core)"]
    for name, p in result["processes"].items():
        pid = result["pids"].get(name)
        if p is None:
            lines.append(f"{name:<10}{'-':>8}  not running (no process of that name)")
        else:
            lines.append(f"{name:<10}{pid:>8}{p['cpu_pct_mean']:>11.2f}{p['cpu_pct_p95']:>8.2f}{p['cpu_pct_max']:>8.2f}"
                         f"{p['rss_mb_max']:>9.1f}{p['threads']:>9}")
    lines.append(f"machine: {m['ncpu']} cores, busy mean {m['busy_pct_mean']:.2f} %  p95 {m['busy_pct_p95']:.2f} %  max {m['busy_pct_max']:.2f} %"
                 + (f", hottest {m['temp_c_max']} C" if m["temp_c_max"] is not None else ", no thermal zone read"))
    return "\n".join(lines)


def read_temp_c() -> float | None:
    temps = []
    try:
        for z in sorted(Path(THERMAL).glob("thermal_zone*/temp")):
            try:
                temps.append(int(z.read_text()) / 1000.0)
            except (OSError, ValueError):
                pass
    except OSError:
        pass
    return max(temps) if temps else None


def sample(pids: dict) -> dict:
    busy, total = parse_cpu_line(Path("/proc/stat").read_text().splitlines()[0])
    procs = {}
    for name, pid in pids.items():
        try:
            procs[name] = parse_proc_stat(Path(f"/proc/{pid}/stat").read_text())
        except (OSError, ValueError):
            procs[name] = None                       # exited, or restarted under another pid: said by the table
    return {"t": time.monotonic(), "busy": busy, "total": total, "procs": procs, "temp_c": read_temp_c()}


def measure(names, seconds: float, interval_s: float, label: str, pids: dict | None = None) -> dict:
    pids = pids if pids is not None else pids_by_name(names)
    samples = [sample(pids)] if pids else []
    if not samples:
        raise SystemExit(f"none of {', '.join(names)} is running here: this runs on the machine that runs the daemons")
    end = samples[0]["t"] + seconds
    while time.monotonic() < end:
        time.sleep(interval_s)
        samples.append(sample(pids))
    res = summarise(samples, os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE"), os.cpu_count() or 1)
    for n in names:                                  # asked for but never found: a row that says so, not a silent gap
        res["processes"].setdefault(n, None)
    return {"kind": "cpu_cost", "label": label, "host": platform.node(), "seconds": round(samples[-1]["t"] - samples[0]["t"], 1),
            "interval_s": interval_s, "pids": pids, **res}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--process", action="append", help=f"a process by its comm name, repeatable (default {', '.join(DEFAULT_PROCESSES)})")
    ap.add_argument("--label", default="unlabelled", help="what was going on: map-off-standing, map-on-walking, ...")
    ap.add_argument("--json", action="store_true", help="print JSON, for the profile's `measured` notes, instead of the table")
    a = ap.parse_args(argv)
    if a.seconds < 2 * a.interval:
        ap.error("--seconds must cover at least two windows")
    result = measure(tuple(a.process or DEFAULT_PROCESSES), a.seconds, a.interval, a.label)
    print(json.dumps(result, indent=1) if a.json else table(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
