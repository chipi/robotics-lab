#!/usr/bin/env python3
"""Read a finished (or stopped) training run's log folder, read only: the checkpoints, the ONNX shape of each, and the TensorBoard curves
the milestone judges by. Needs `onnx` and `tensorboard`, so run it with the project's interpreter:

    /work/microduck-nav/.venv/bin/python checkpoint_report.py logs/rsl_rl/microduck_nav_one_wall/<timestamp>
    ... checkpoint_report.py DIR --expect-shape 1,1343:1,3 --up Episode_Reward/progress --down Episode_Termination/obstacle_collision

Prints, per signal, one line: PASS / FAIL / WARN / INFO. The curves and the shape are two of the three signals of M1 (docs/M1.md); the third,
the replay (`python -m microduck_nav.replay <model_N.pt>`, exit 0 when at least 80 % of the environments stop before the wall), is not run here.
Ends `CHECKPOINT-REPORT PASS`, `FAIL` or `INCONCLUSIVE` (a WARN: too few points to call a trend). Exit 0 / 1 / 3; 2 for usage."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

results: list = []


def line(status: str, name: str, detail: str = "") -> None:
    results.append(status)
    print(f"{status:5} {name}  {detail}")


def shape_of(vi) -> tuple:
    return tuple(d.dim_value if d.dim_value else d.dim_param or "?" for d in vi.type.tensor_type.shape.dim)


def onnx_shapes(path: Path) -> tuple:
    import onnx
    m = onnx.load(str(path), load_external_data=False)
    init = {i.name for i in m.graph.initializer}
    ins = [shape_of(i) for i in m.graph.input if i.name not in init]
    outs = [shape_of(o) for o in m.graph.output]
    return ins, outs


def curve(acc, tag: str) -> list:
    return [(e.step, e.value) for e in acc.Scalars(tag)]


def mean(xs: list) -> float:
    return sum(xs) / len(xs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run", type=Path, help="the run's log folder (holds model_N.pt, model_N.onnx and the events file)")
    ap.add_argument("--expect-shape", default="1,1343:1,3", help="input:output of the ONNX, as comma-separated dims")
    ap.add_argument("--up", action="append", default=["Episode_Reward/progress"], help="a tag that must rise (repeatable)")
    ap.add_argument("--down", action="append", default=["Episode_Termination/obstacle_collision"], help="a tag that must fall (repeatable)")
    a = ap.parse_args()
    if not a.run.is_dir():
        print(f"not a directory: {a.run}", file=sys.stderr)
        return 2

    pts = sorted(a.run.glob("model_*.pt"), key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
    onnxs = {p.stem: p for p in a.run.glob("model_*.onnx")}
    if not pts:
        line("FAIL", "checkpoints", f"no model_N.pt in {a.run}")
    else:
        its = [int(re.search(r"(\d+)", p.stem).group(1)) for p in pts]
        line("PASS" if len(pts) > 1 else "WARN", "checkpoints", f"{len(pts)}: iterations {its[:8]}{' ...' if len(its) > 8 else ''}, last model_{its[-1]}.pt"
             + ("" if len(pts) > 1 else "; only one: a run stopped without --agent.save-interval keeps only model_0"))
        missing = [p.name for p in pts if p.stem not in onnxs]
        if missing:
            line("FAIL", "onnx beside each .pt", f"missing for {missing[:4]}")

    ei, eo = (tuple(int(x) for x in s.split(",")) for s in a.expect_shape.split(":"))
    last = onnxs.get(pts[-1].stem) if pts else None
    if last is None:
        line("FAIL", "onnx shape", "no ONNX beside the last checkpoint")
    else:
        try:
            ins, outs = onnx_shapes(last)
            ok = ins == [ei] and outs == [eo]
            line("PASS" if ok else "FAIL", "onnx shape", f"{last.name}: inputs {ins} outputs {outs}; expected {[ei]} -> {[eo]}")
        except ImportError:
            line("WARN", "onnx shape", "the onnx package is not importable here; run with the project's .venv/bin/python")

    try:
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    except ImportError:
        line("WARN", "curves", "tensorboard is not importable here; run with the project's .venv/bin/python")
        EventAccumulator = None
    if EventAccumulator:
        acc = EventAccumulator(str(a.run), size_guidance={"scalars": 0})
        acc.Reload()
        tags = set(acc.Tags()["scalars"])
        for direction, wanted in (("up", a.up), ("down", a.down)):
            for tag in dict.fromkeys(wanted):
                if tag not in tags:
                    line("FAIL", tag, f"not in the events file (tags: {sorted(tags)[:6]} ...)")
                    continue
                c = curve(acc, tag)
                if len(c) < 8:
                    line("WARN", tag, f"{len(c)} points: too few to call a trend; first {c[0][1]:.4g}, last {c[-1][1]:.4g}")
                    continue
                q = max(1, len(c) // 4)
                first, lastq = mean([v for _, v in c[:q]]), mean([v for _, v in c[-q:]])
                good = lastq > first if direction == "up" else lastq < first
                line("PASS" if good else "FAIL", tag, f"{len(c)} points, first quarter mean {first:.4g}, last quarter mean {lastq:.4g} (should {'rise' if direction == 'up' else 'fall'})")
    verdict = "FAIL" if "FAIL" in results else ("INCONCLUSIVE" if "WARN" in results else "PASS")
    print(f"CHECKPOINT-REPORT {verdict}  (the replay is the third signal and is not run here)")
    return {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
