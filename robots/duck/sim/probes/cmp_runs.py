"""Compare two runs' ticks.jsonl tick for tick: the commands (vx, vyaw of every row that has one) and the decisions (the rule of
every row that carries one). Prints where they first differ and how much of each sequence is shared.

    python sim/probes/cmp_runs.py A B        (run folders: MCAP runs or folders with ticks.jsonl; or the ticks.jsonl files)
"""

import json
import sys
from pathlib import Path

import legacy_rows


def _rows(path):
    p = Path(path)
    return legacy_rows.load(p.parent if p.name == "ticks.jsonl" else p)[1]


def read(path):
    cmds, rules, events = [], [], []
    for r in _rows(path):
        if "vx" in r and "vyaw" in r:
            cmds.append((r["vx"], r["vyaw"]))
        if r.get("decision"):
            rules.append(r["decision"]["rule"])
        if r.get("event"):
            events.append(r["event"])
    return cmds, rules, events


def first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def compare(pa, pb):
    ca, ra, ea = read(pa)
    cb, rb, eb = read(pb)
    out = {}
    for name, a, b in (("commands", ca, cb), ("decisions", ra, rb), ("events", ea, eb)):
        i = first_diff(a, b)
        out[name] = {"a": len(a), "b": len(b), "identical": i is None, "first_diff_index": i}
    return out


if __name__ == "__main__":
    res = compare(sys.argv[1], sys.argv[2])
    print(json.dumps(res))
    sys.exit(0 if all(v["identical"] for v in res.values()) else 1)
