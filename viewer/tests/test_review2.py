"""Round 2 of the miniview review (docs/wip/REVIEW-2026-11-16-miniview-round2.md): one test per finding, each failed
before its fix. Run: cd viewer && uv run python tests/test_review2.py"""

import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import tracemalloc
import urllib.request
from pathlib import Path

from helpers import T0_NS, Checks, catalog, get, make_run, run_record, scene, serve, tick, wait_until
from miniview import keys, mcapio, server, validate, wire
from miniview.mcapio import Follower, Recorder

check = Checks("REVIEW 2")
HEAD = [(0.0, "epoch", {"map_to_world": [1.0, 0.0, 0.0]})]


def dead_pid() -> int:
    import subprocess

    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def age(path: Path, s: float) -> None:
    t = path.stat().st_mtime - s
    os.utime(path, (t, t))


class Stream:
    """A live stream's lines, read in a thread."""

    def __init__(self, base, key, since=None, headers=None, stop_after=None):
        self.lines, self.done = [], threading.Event()
        url = f"{base}/api/v1/runs/{key}/live" + (f"?since={since}" if since is not None else "")
        self.th = threading.Thread(target=self._run, args=(urllib.request.Request(url, headers=headers or {}),), daemon=True)
        self.th.start()

    def _run(self, req):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                for raw in r:
                    self.lines.append(raw.decode().rstrip("\n"))
        except Exception as e:
            self.lines.append("ERR " + repr(e))
        self.done.set()

    def events(self):
        return [line[7:] for line in list(self.lines) if line.startswith("event: ")]


ONLY = {x for x in os.environ.get("ONLY", "").split(",") if x}


def want(*ids):
    return not ONLY or bool(ONLY & set(ids))


# ---- A5: a normal compaction is not a rewrite -----------------------------------------------------------------------
if want('A5'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        rec = make_run(data, "duck/room/a5", HEAD + [tick(1.0, 0.0)], close=False)
        cat.scan()
        ld = cat.get("duck/room/a5")
        rec.add(2.0, "end", {"verdict": "ended"})
        ld.poll()
        rec.close()
        ld.poll()
        cat.scan()
        r = cat.get("duck/room/a5").data.run
        check("A5: end, poll, close (compaction), poll, scan: rewritten is 0 and the run is whole", r["rewritten"] == 0 and r["ticks"] == 1 and r["status"] == "ended", r["rewritten"])

# ---- A1: a stream across a rewritten file ------------------------------------------------------------------------------
if want('A1'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        rec = make_run(data, "duck/room/a1", HEAD + [tick(1.0 + i * 0.1, 0.01 * i) for i in range(5)], close=False)
        httpd, base = serve(cat, follow=False)
        ld = cat.get("duck/room/a1")
        st = Stream(base, "duck/room/a1", since=ld.data.seq)
        wait_until(lambda: ld.pins >= 1, 5, what="the stream to open")
        other = Path(tmp) / "other"
        rec_other = make_run(other, "duck/room/a1", HEAD + [tick(50.0 + i * 0.1, 0.5) for i in range(20)], close=False)
        os.replace(other / "runs/duck/room/a1/run.live.mcap", data / "runs/duck/room/a1/run.live.mcap")
        ld.poll()
        wait_until(lambda: "rewritten" in st.events() or st.done.is_set(), 6, what="a `rewritten` event")
        ticks_seen = [json.loads(line[6:])["t"] for line in st.lines if line.startswith("data: ") and '"belief"' in line]
        check("A1: a live stream across a rewrite (a longer file, another inode) sends `rewritten` and no tick of the new file", "rewritten" in st.events()
              and all(t < 40 for t in ticks_seen), (st.events(), ticks_seen[:3]))
        code, summary, _ = get(base, "/api/v1/runs/duck/room/a1")
        check("A1: the summary carries the generation the stream's status events carry", "generation" in summary and summary["generation"] >= 1, summary.get("generation"))
        # a reconnect: Last-Event-ID is what the browser keeps current, `since` is the first URL's: the id wins
        wait_until(lambda: summary["generation"] >= 1, 1, what="generation")
        st2 = Stream(base, "duck/room/a1", since=0, headers={"Last-Event-ID": str(summary["seq"])})
        wait_until(lambda: ld.pins >= 1, 5, what="the reconnected stream")
        rec_other.add(*tick(60.0, 0.6))
        ld.poll()
        wait_until(lambda: any(line.startswith("id: ") for line in st2.lines), 6, what="a record on the reconnected stream")
        ids = [int(line[4:]) for line in st2.lines if line.startswith("id: ")]
        check("A1: Last-Event-ID is preferred to `since` (a reconnect resumes where the client was)", ids and min(ids) > summary["seq"], (ids[:3], summary["seq"]))
        httpd.shutdown()

# ---- A2: a lock from another host; a stopped file that grows again --------------------------------------------------------
if want('A2'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        rec = make_run(data, "duck/room/a2", HEAD + [tick(1.0, 0.0)], close=False)
        d = data / "runs/duck/room/a2"
        rec._fh.close()
        lock = json.loads((d / "writer.lock").read_text())
        (d / "writer.lock").write_text(json.dumps(dict(lock, host="the-host", pid=4000000)))
        age(d / "run.live.mcap", 100000)
        cat.scan()
        st_ = {r["key"]: r["status"] for r in cat.list_runs()}
        check("A2: a lock from another host is unknown, not alive: idle for a day, the run is stopped", st_ == {"duck/room/a2": "stopped"}, st_)
        fresh = make_run(data, "duck/room/a2b", HEAD + [tick(1.0, 0.0)], close=False)
        d2 = data / "runs/duck/room/a2b"
        (d2 / "writer.lock").write_text(json.dumps(dict(json.loads((d2 / "writer.lock").read_text()), host="the-host", pid=1)))
        cat.scan()
        check("A2: ... and while that file grows (a foreign lock, fresh mtime) it is live", {r["key"]: r["status"] for r in cat.list_runs()}["duck/room/a2b"] == "live")

    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        rec = make_run(data, "duck/room/a2r", HEAD + [tick(1.0, 0.0), tick(1.1, 0.1)], close=False)
        d = data / "runs/duck/room/a2r"
        lock = json.loads((d / "writer.lock").read_text())
        (d / "writer.lock").write_text(json.dumps(dict(lock, pid=dead_pid())))
        age(d / "run.live.mcap", 1000)
        cat.scan()
        check("A2 (setup): a paused writer's run is stopped", {r["key"]: r["status"] for r in cat.list_runs()}["duck/room/a2r"] == "stopped")
        rec.add(*tick(1.2, 0.2))                                     # it wakes up and writes
        cat.scan()
        r = cat.get("duck/room/a2r").data.run
        check("A2: a stopped live file that grows again resumes: live, the new tick in, rewritten 0", cat.status(cat.get("duck/room/a2r")) == "live"
              and r["ticks"] == 3 and r["rewritten"] == 0 and r["status"] == "live", (r["status"], r["ticks"], r["rewritten"]))
        rec.add(2.0, "end", {"verdict": "ended"})
        cat.follow_once()
        check("A2: ... and it follows on to its end", cat.status(cat.get("duck/room/a2r")) == "ended")

# ---- A3: the same file cut and rewritten longer than the follower's offset ---------------------------------------------------
if want('A3'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        rec = make_run(data, "duck/room/a3", HEAD + [tick(1.0 + i * 0.1, 0.01 * i) for i in range(5)], close=False)
        ld = cat.get("duck/room/a3")
        other = Path(tmp) / "other"
        rec2 = make_run(other, "duck/room/a3", HEAD + [tick(50.0 + i * 0.1, 0.5) for i in range(20)], close=False)
        live = data / "runs/duck/room/a3/run.live.mcap"
        with open(live, "r+b") as fh:
            fh.truncate(0)
            fh.write((other / "runs/duck/room/a3/run.live.mcap").read_bytes())
        for i in range(3):
            rec2.add(*tick(60.0 + i, 0.6))
            shutil.copyfile(other / "runs/duck/room/a3/run.live.mcap", live)
            ld.poll()
        r = ld.data.run
        check("A3: a file rewritten longer than the offset is read again from its start: all 23 ticks, rewritten counted, not broken",
              r["ticks"] == 23 and r["rewritten"] >= 1 and not ld.error, {k: r[k] for k in ("ticks", "rewritten", "rejects")})

# ---- A4: scan and get open one run at once ------------------------------------------------------------------------------------
if want('A4'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        rec = make_run(data, "duck/room/a4", HEAD + [tick(1.0, 0.0)], close=False)
        real_open = cat._open
        scan_in, go = threading.Event(), threading.Event()

        def slow_open(key, path):
            if threading.current_thread().name == "scan":
                scan_in.set()
                go.wait(5)
            return real_open(key, path)

        cat._open = slow_open
        th = threading.Thread(target=cat.scan, name="scan")
        th.start()
        scan_in.wait(5)
        ld_get = cat.get("duck/room/a4")
        go.set()
        th.join(5)
        check("A4: the run a request got is the one the cache keeps (a stream on it sees new ticks)", cat.loaded.get("duck/room/a4") is ld_get)

# ---- B1: started_at_ns past SQLite's integers; an index failure is that run's ---------------------------------------------------
if want('B1'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        make_run(data, "duck/room/big", HEAD + [tick(1.0, 0.0), (2.0, "end", {"verdict": "ended"})], started_at_ns=2**63 + 5)
        make_run(data, "duck/room/ok", HEAD + [tick(1.0, 0.0), (2.0, "end", {"verdict": "ended"})])
        httpd, base = serve(cat, follow=False)
        listed = {r["key"]: r["status"] for r in cat.list_runs()}
        code, body, _ = get(base, "/api/v1/runs/duck/room/big")
        check("B1: started_at_ns of 2**63 or more is an invalid run record: the run is listed broken, its summary is a 200, never a 500",
              listed.get("duck/room/big") == "broken" and code == 200 and body["status"] == "broken" and "started_at_ns" in body["error"], (listed, code))
        real_write = cat.index.write

        def failing_write(row, *a, **k):
            if row["key"] == "duck/room/ok":
                raise RuntimeError("the index is full")
            return real_write(row, *a, **k)

        cat.index.write = failing_write
        cat.loaded.pop("duck/room/ok", None)
        code, body, _ = get(base, "/api/v1/runs/duck/room/ok")
        cat.index.write = real_write
        check("B1: an index write that fails marks that run broken (with the reason) instead of a 500", code == 200 and body["status"] == "broken" and "index is full" in body["error"], (code, body.get("error")))
        httpd.shutdown()

# ---- B2: a /map inside a tick is counted, not silent ----------------------------------------------------------------------------
if want('B2'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        rec = make_run(data, "duck/room/b2", HEAD + [tick(1.0, 0.0)], close=False)
        base_ns = rec.base_ns
        msgs = wire.to_messages(1.1, "tick", tick(1.1, 0.1)[2], base_ns)
        world = wire.to_messages(1.1, "world", {"grid": {"res": 0.1, "origin": [0, 0], "w": 2, "h": 2, "cells": "..##"}, "obstacles": [], "drops": []}, base_ns)
        for topic, ns, pub, dat in msgs[:1] + world + msgs[1:]:
            rec._w.add_message(rec._ch[topic], ns, dat, pub)
        rec.flush()
        rec.add(*tick(1.2, 0.2))
        ld = cat.get("duck/room/b2")
        r = ld.data.run
        check("B2: a tick interrupted by another record is a reject with its reason, not a silent drop", r["rejects"] >= 1 and "interrupted" in (r["first_error"] or ""), (r["rejects"], r["first_error"]))

# ---- C1: a stalled client is dropped ---------------------------------------------------------------------------------------------
if want('C1'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        big = [[0.001 * k, 0.0, 0.0, "o"] for k in range(3000)]
        rec = make_run(data, "duck/room/c1", HEAD + [tick(1.0, 0.0)], close=False)
        httpd, base = serve(cat)
        ld = cat.get("duck/room/c1")
        server.STREAM_TIMEOUT_S = 0.5
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        s.connect(("127.0.0.1", httpd.server_address[1]))
        s.sendall(b"GET /api/v1/runs/duck/room/c1/live?since=0 HTTP/1.1\r\nHost: x\r\n\r\n")           # and never reads
        wait_until(lambda: ld.pins >= 1, 5, what="the stream to open")
        for i in range(400):
            rec.add(*tick(1.1 + i * 0.01, 0.1, depth=big))
        wait_until(lambda: ld.pins == 0, 20, what="the stalled stream to be dropped")
        check("C1: a client that stops reading is dropped after the stream timeout, and its run is unpinned", ld.pins == 0)
        s.close()
        server.STREAM_TIMEOUT_S = 60.0
        httpd.shutdown()

# ---- C3: a follower round costs a finished run nothing ------------------------------------------------------------------------------
if want('C3'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        make_run(data, "duck/room/c3", HEAD + [tick(1.0, 0.0), (2.0, "end", {"verdict": "ended"})])
        ld = cat.get("duck/room/c3")
        import miniview.store as store

        n, real = [0], store.streams
        store.streams = lambda *a, **k: (n.__setitem__(0, n[0] + 1), real(*a, **k))[1]
        for _ in range(10):
            cat.follow_once()
        store.streams = real
        check("C3: ten follower rounds over a finished run recompute nothing", n[0] == 0, n[0])

# ---- C4: a scan reads the index once ---------------------------------------------------------------------------------------------------
if want('C4'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        for i in range(12):
            make_run(data, f"duck/room/c4-{i}", HEAD + [tick(1.0, 0.0), (2.0, "end", {"verdict": "ended"})])
        cat.scan()
        cat2 = catalog(data, index=cat.index.path)
        calls = [0]
        real_row = cat2.index.row
        cat2.index.row = lambda k: (calls.__setitem__(0, calls[0] + 1), real_row(k))[1]
        cat2.scan()
        check("C4: a restart's scan reads the index's rows in one query, not one per run", calls[0] == 0 and not cat2.loaded and len(cat2.list_runs()) == 12, calls[0])

# ---- C5: the readers do not hold a file in memory --------------------------------------------------------------------------------------------
if want('C5'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        big = [[0.001 * k, 0.5, 0.1, "o"] for k in range(5000)]
        key = "duck/room/c5"
        rec = Recorder(keys.run_dir(data, key), run_record(key))
        for i in range(300):
            rec.add(*tick(1.0 + i * 0.1, 0.001 * i, depth=big))
        live_size = (keys.run_dir(data, key) / "run.live.mcap").stat().st_size
        rec._fh.close()
        tracemalloc.start()
        mcapio.compact(keys.run_dir(data, key))
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        check("C5: compacting a %d MB live file peaks well under its size (streamed)" % (live_size >> 20), live_size > 15 << 20 and peak < live_size / 4, f"peak {peak >> 20} MB of {live_size >> 20} MB")
        f = Follower(keys.run_dir(data, key))
        tracemalloc.start()
        n = 0
        for _ in f.iter_poll():
            n += 1
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        check("C5: reading the finished file record by record peaks well under its size", n > 300 and peak < live_size / 3, f"peak {peak >> 20} MB, {n} records")

# ---- C6: unknown keys do not rescan the folder every time -----------------------------------------------------------------------------------
if want('C6'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        make_run(data, "duck/room/c6", HEAD + [tick(1.0, 0.0)])
        cat.scan()
        scans = [0]
        real_sp = cat.scan_paths
        cat.scan_paths = lambda: (scans.__setitem__(0, scans[0] + 1), real_sp())[1]
        for _ in range(30):
            cat.get("duck/room/nope")
        check("C6: thirty requests for an unknown run rescan the folder at most twice", scans[0] <= 2, scans[0])

# ---- D1, D3: static files and headers -----------------------------------------------------------------------------------------------------
if want('D1', 'D3'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        httpd, base = serve(cat, follow=False)
        host, port = base.split("//")[1].split(":")
        c = http.client.HTTPConnection(host, int(port))
        c.putrequest("GET", "/web/../src", skip_host=False, skip_accept_encoding=True)
        c.endheaders()
        resp = c.getresponse()
        resp.read()
        check("D1: a directory outside web/ asked for as /web/../src is a 404, not a 301 that names it", resp.status == 404, (resp.status, resp.getheader("Location")))
        c = http.client.HTTPConnection(host, int(port))
        c.request("GET", "/api/v1/health")
        r = c.getresponse()
        r.read()
        check("D3: the server does not name its software or Python's version", "Python" not in (r.getheader("Server") or "") and "BaseHTTP" not in (r.getheader("Server") or ""), r.getheader("Server"))
        check("D3: every answer says nosniff", r.getheader("X-Content-Type-Options") == "nosniff")
        c = http.client.HTTPConnection(host, int(port))
        c.request("GET", "/web/three/")
        r = c.getresponse()
        r.read()
        csp = r.getheader("Content-Security-Policy") or ""
        check("D3: a page carries a same-origin Content-Security-Policy", "default-src 'self'" in csp and "connect-src 'self'" in csp, csp)
        c = http.client.HTTPConnection(host, int(port))
        c.request("POST", "/api/v1/runs", body=b"x" * 10)
        r = c.getresponse()
        r.read()
        check("D3: a method that is not allowed closes the connection", r.status == 405 and (r.getheader("Connection") or "").lower() == "close", r.getheader("Connection"))
        httpd.shutdown()

# ---- D4: a scene whose id is not its folder's -------------------------------------------------------------------------------------------------
if want('D4'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        cat = catalog(data)
        (data / "scenes/aaa").mkdir(parents=True)
        (data / "scenes/aaa/scene.json").write_text(json.dumps(scene("bbb")))
        cat.put_scene(scene("ok"))
        cat.scan()
        ids = [s_["id"] for s_ in cat.scenes_with_runs()["scenes"]]
        check("D4: a scene whose id differs from its folder is not indexed", ids == ["ok"], ids)

# ---- G1, G4, G5: the tick protocol, flush per tick, /tf frames ----------------------------------------------------------------------------------
if want('G1', 'G4', 'G5'):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        key = "duck/room/g1"
        rec = Recorder(keys.run_dir(data, key), run_record(key))
        flushes = [0]
        real_flush = rec._fh.flush
        rec._fh.flush = lambda: (flushes.__setitem__(0, flushes[0] + 1), real_flush())[1]
        base_flushes = flushes[0]
        rec.add(*tick(1.0, 0.0, depth=[[1, 2, 3, "f"]]))
        check("G4: a whole tick (up to six messages) is flushed once", flushes[0] - base_flushes == 1, flushes[0] - base_flushes)
        rec.begin_tick(1.1, [0.1, 0.0, 0.0], t_src=1.1)
        try:
            rec.add(1.1, "event", {"kind": "x", "text": "x"})
            refused = False
        except ValueError:
            refused = True
        check("G1: between begin_tick and end_tick the recorder refuses any other record", refused)
        rec.tick_truth([1.1, 0.0, 0.0])
        rec.tick_depth([[1, 2, 3, "o"]])
        rec.tick_command(0.3, 0.0)
        try:
            rec.tick_truth([1, 2, 3])
            twice = False
        except ValueError:
            twice = True
        check("G1: a part is written once, in the protocol's order (truth, depth, command, tilt)", twice)
        before = flushes[0]
        rec.end_tick(raw={"n": 1})
        check("G1: end_tick writes the closing message and flushes once", flushes[0] - before == 1, flushes[0] - before)
        try:
            rec.end_tick()
            rec_end = False
        except ValueError:
            rec_end = True
        check("G1: end_tick without begin_tick is refused", rec_end)
        rec.add(2.0, "end", {"verdict": "ended"})
        rec.close()
        got = [(k, p) for _, k, p in Follower(keys.run_dir(data, key)).poll() if k == "tick"]
        check("G1: a tick written in parts reads as one tick with all of them", len(got) == 2 and got[1][1]["truth"] == [1.1, 0.0, 0.0] and got[1][1]["cmd"] == [0.3, 0.0]
              and got[1][1]["depth"] == [[1.0, 2.0, 3.0, "o"]], got[-1])

        asm = wire.Assembler()
        run_msg = wire.to_messages(0.0, "run", run_record("duck/room/g5"), T0_NS)[0]
        asm.feed(run_msg[0], run_msg[1], run_msg[3])
        bad = wire._pb("/tf", {"parent_frame_id": "map", "child_frame_id": "world", "translation": {"x": 0, "y": 0, "z": 0}, "rotation": {"x": 0, "y": 0, "z": 0, "w": 1}}, T0_NS)
        try:
            asm.feed("/tf", T0_NS, bad)
            rejected = False
        except ValueError:
            rejected = True
        check("G5: a /tf that is not world -> map is refused", rejected)
        unknown = wire.to_messages(1.0, "tick", tick(1.0, 0.0, depth=[[1, 2, 3, "z"]])[2], T0_NS)
        got = []
        for topic, ns, pub, dat in unknown:
            got += asm.feed(topic, ns, dat)
        check("G5: an unknown depth kind (not f, o, v, b) is kept as written, one character: the renderers draw it as `o`", got and got[0][2]["depth"][0][3] == "z", got)

check.done()
