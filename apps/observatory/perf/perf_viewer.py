"""`make perf-viewer` (not in CI): a real run (robots/duck/runs/phase1-run18) replayed at 20 Hz through the writer while the service
follows it and both pages watch it. Prints the follower's latency (write to applied in memory), each page's latency
(write to applied in the page), the bytes each page receives per second, and how long the run's lock is held.

    cd apps/observatory && uv run --frozen python perf/perf_viewer.py [--log DIR] [--hz 20] [--ticks N]
"""

import argparse
import json
import statistics
import sys
import tempfile
import threading
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tests"))

from helpers import T0_NS, catalog, get, scene, serve, wait_until  # noqa: E402

from runfile import keys, mcapio, store  # noqa: E402
from runfile.adapters.duck import DuckLog  # noqa: E402
from observatory.shots import launch  # noqa: E402


class TimedCondition(threading.Condition):
    """A Condition that records how long each thread holds it (outermost hold only; waiting is not holding)."""

    def __init__(self):
        super().__init__()
        self.local = threading.local()
        self.holds = []                       # (thread ident, seconds)

    def _stop(self):
        d = time.perf_counter() - self.local.start
        self.holds.append((threading.get_ident(), d))

    def __enter__(self):
        r = super().__enter__()
        depth = getattr(self.local, "depth", 0)
        if depth == 0:
            self.local.start = time.perf_counter()
        self.local.depth = depth + 1
        return r

    def __exit__(self, *a):
        self.local.depth -= 1
        if self.local.depth == 0:
            self._stop()
        return super().__exit__(*a)

    def wait(self, timeout=None):
        depth = self.local.depth
        self._stop()
        self.local.depth = 0
        try:
            return super().wait(timeout)
        finally:
            self.local.depth = depth
            self.local.start = time.perf_counter()


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(HERE.parents[2] / "robots" / "duck" / "runs" / "phase1-run18"))
    ap.add_argument("--hz", type=float, default=20.0)
    ap.add_argument("--ticks", type=int, default=0, help="stop after this many ticks (0: the whole log)")
    ap.add_argument("--warm", type=int, default=20, help="ticks written before the pages open")
    args = ap.parse_args()
    log_dir = Path(args.log)
    if not (log_dir / "ticks.jsonl").exists():
        sys.exit(f"no {log_dir / 'ticks.jsonl'}: the source log is not in git; pass --log")

    conds = []
    orig_init, orig_feed = store.RunData._init, store.RunData.feed
    applied = []                              # when each tick was applied in the service's memory

    def timed_init(self):
        orig_init(self)
        if hasattr(self, "changed") and not isinstance(self.changed, TimedCondition):
            self.changed = TimedCondition()
            conds.append(self.changed)

    def timed_feed(self, t, kind, p):
        ok = orig_feed(self, t, kind, p)
        if ok and kind == "tick":
            applied.append(time.time())
        return ok

    store.RunData._init, store.RunData.feed = timed_init, timed_feed

    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        cat.put_scene(scene("apartment"))
        httpd, base = serve(cat)
        follower_ident = next(t.ident for t in threading.enumerate() if getattr(t, "_target", None) == cat.follow_forever)

        run_id = "duck/apartment/perf1"
        log = DuckLog(log_dir, "apartment")
        run = mcapio.new_run(run_id, dict(log.robot, name="duck"), "apartment", log.kind, T0_NS, "given")
        rec = mcapio.Recorder(keys.run_dir(data, run_id), run)
        for r in log.header:
            rec.add(*r)
        written = []                          # wall time each tick was written

        lines = (log_dir / "ticks.jsonl").read_text().splitlines()

        def write_one(line):
            for r in log.feed(line):
                rec.add(*r)
                if r[1] == "tick":
                    written.append(time.time())

        it = iter(lines)
        while len(written) < args.warm:
            write_one(next(it))

        wait_until(lambda: any(r["key"] == run_id for r in get(base, "/api/v1/runs")[1]), 15, what="the service to list the run")

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = launch(p)
            pages = {}
            for lib in ("three", "deck"):
                pg = b.new_page(viewport={"width": 1200, "height": 800})
                cdp = pg.context.new_cdp_session(pg)
                cdp.send("Network.enable")
                urls, got = {}, defaultdict(lambda: defaultdict(int))     # request id -> url; second -> bytes, by kind
                t_origin = {}

                def on_req(ev, urls=urls):
                    urls[ev["requestId"]] = ev["request"]["url"]

                def on_data(ev, urls=urls, got=got, t_origin=t_origin):
                    sec = int(ev["timestamp"])
                    kind = "live" if "/live" in urls.get(ev["requestId"], "") else "other"
                    got[kind][sec] += ev["dataLength"]
                    got["all"][sec] += ev["dataLength"]
                    t_origin.setdefault("first", ev["timestamp"])
                    t_origin["last"] = ev["timestamp"]

                cdp.on("Network.requestWillBeSent", on_req)
                cdp.on("Network.dataReceived", on_data)
                pg.goto(f"{base}/web/{lib}/index.html")
                pg.wait_for_function("window.miniview !== undefined", timeout=60000)
                pg.wait_for_function("window.__ready === true", timeout=60000)
                pg.evaluate(f"window.miniview.load('apartment', '{run_id}')")
                pg.wait_for_function("window.__ready === true", timeout=60000)
                pg.evaluate("""(() => { const st = window.miniview.internals.store, orig = st.onRecord; window.__arr = [];
                  st.onRecord = (k, d) => { if (k === 'tick') window.__arr.push(Date.now()); return orig(k, d); }; })()""")
                pages[lib] = (pg, got, urls)
            n_open = len(written)
            for g in (v[1] for v in pages.values()):
                for k in g:
                    g[k].clear()
            print(f"pages open at tick {n_open}; replaying the rest at {args.hz:g} Hz ...", flush=True)

            period, t_start, n = 1.0 / args.hz, time.monotonic(), 0
            for line in it:
                is_tick = '"event"' not in line
                if is_tick:
                    n += 1
                    delay = t_start + n * period - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                write_one(line)
                if args.ticks and n >= args.ticks:
                    break
            v = log.finish()
            for r in v:
                rec.add(*r)
            rec.close()
            t_end = time.monotonic()
            for lib, (pg, got, urls) in pages.items():
                pg.wait_for_function("window.miniview.state().status === 'ended'", timeout=60000)
            duration = t_end - t_start
            results = {}
            for lib, (pg, got, urls) in pages.items():
                arr = pg.evaluate("window.__arr")
                lat = [(a / 1000.0 - written[n_open + i]) * 1000 for i, a in enumerate(arr) if n_open + i < len(written)]
                live, allb = got["live"], got["all"]
                secs = sorted(live)
                results[lib] = {"ticks_seen": len(arr), "latency_ms": lat, "live_total": sum(live.values()), "all_total": sum(allb.values()),
                                "live_per_s": [live[s] for s in secs[1:-1]] or [0]}
            b.close()
        httpd.shutdown()

    follower = [(a - w) * 1000 for a, w in zip(applied[n_open:], written[n_open:])]      # the warm-up ticks were read by the first scan
    holds = [(i, d) for c in conds for i, d in c.holds]
    f_holds = [d * 1000 for i, d in holds if i == follower_ident]
    r_holds = [d * 1000 for i, d in holds if i != follower_ident]

    print()
    print(f"replayed {len(written) - n_open} ticks of {log_dir.name} in {duration:.1f} s at {args.hz:g} Hz ({len(written)} written in all)")
    print(f"follower latency (write to applied in the service's memory): median {statistics.median(follower):.1f} ms, "
          f"p95 {pct(follower, 0.95):.1f} ms, max {max(follower):.1f} ms  ({len(follower)} ticks)")
    for lib, r in results.items():
        lat = r["latency_ms"]
        print(f"{lib:>5}: ticks received live {r['ticks_seen']}; write to applied in the page: median {statistics.median(lat):.1f} ms, "
              f"p95 {pct(lat, 0.95):.1f} ms, max {max(lat):.1f} ms")
        print(f"       bytes received: live stream {r['live_total'] / duration / 1024:.1f} KiB/s on average "
              f"(1-s buckets: median {statistics.median(r['live_per_s']) / 1024:.1f}, max {max(r['live_per_s']) / 1024:.1f} KiB/s); "
              f"everything the page received during the replay {r['all_total'] / duration / 1024:.1f} KiB/s")
    print(f"the run's lock, held by the follower applying a batch: {len(f_holds)} holds, median {statistics.median(f_holds):.3f} ms, "
          f"p95 {pct(f_holds, 0.95):.3f} ms, max {max(f_holds):.3f} ms")
    if r_holds:
        print(f"the run's lock, held by requests (snapshots): {len(r_holds)} holds, median {statistics.median(r_holds):.3f} ms, "
              f"max {max(r_holds):.3f} ms")
    print(json.dumps({"follower_ms": {"median": statistics.median(follower), "max": max(follower)},
                      "pages": {k: {"median_ms": statistics.median(v["latency_ms"]), "max_ms": max(v["latency_ms"]),
                                    "live_kib_s": v["live_total"] / duration / 1024} for k, v in results.items()},
                      "lock_ms": {"follower_max": max(f_holds), "request_max": max(r_holds) if r_holds else None}}))


if __name__ == "__main__":
    main()
