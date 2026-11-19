"""The recorded signals (cmd, room, turning, ...) of a run between two times (s from the first tick).

    uv run python sim/probes/signals_at.py RUN_DIR T_FROM T_TO [name ...]
"""

import sys
from pathlib import Path

from runfile.mcapio import Follower


def main() -> None:
    run, t_from, t_to, names = Path(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4:]
    rows = list(Follower(run).poll())
    t0 = next(t for t, k, p in rows if k == "tick")
    for t, k, p in rows:
        s = t - t0
        if not t_from <= s <= t_to:
            continue
        if k == "signals":
            v = p.get("values", {})
            keep = {n: v[n] for n in v if (not names or n in names) and not n.startswith("joint_")}
            if keep:
                print(f"{s:6.2f} {keep}")
        elif k == "event":
            print(f"{s:6.2f} EVENT {p.get('kind')}: {str(p.get('text', ''))[:100]}")


if __name__ == "__main__":
    main()
