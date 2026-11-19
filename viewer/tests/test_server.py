"""The service (ADR-0005, ADR-0010): the API by run key, windows, JSON errors, gzip, static caching, and live runs
followed by record with resume. No fixed sleeps: every wait is for a condition. Run: cd viewer && uv run python tests/test_server.py"""

import gzip
import http.client
import io
import json
import logging
import threading
import time
import tempfile
import urllib.request
from pathlib import Path

from helpers import Checks, catalog, get, import_fixture, make_run, scene, serve, tick, wait_until
from miniview import query, server
from runfile.catalog import FOLLOW_EVERY_S

check = Checks("SERVER")
MARGIN = 3 * FOLLOW_EVERY_S          # what a record may take to reach a stream: three rounds of the follower
HEAD = [(0.0, "epoch", {"map_to_world": [1.0, 0.0, 0.0]})]


class Stream:
    """A live stream read in a thread: (event, id, data) as they arrive."""

    def __init__(self, base, key, since=None, last_id=None):
        self.events, self.connected, self.closed = [], threading.Event(), threading.Event()
        url = f"{base}/api/v1/runs/{key}/live" + (f"?since={since}" if since is not None else "")
        req = urllib.request.Request(url, headers={"Last-Event-ID": str(last_id)} if last_id is not None else {})
        self.thread = threading.Thread(target=self._run, args=(req,), daemon=True)
        self.thread.start()
        self.connected.wait(10)

    def _run(self, req):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.connected.set()
                ev = eid = None
                for raw in resp:
                    line = raw.decode().rstrip("\n")
                    if line.startswith("id: "):
                        eid = int(line[4:])
                    elif line.startswith("event: "):
                        ev = line[7:]
                    elif line.startswith("data: "):
                        self.events.append((ev, eid, json.loads(line[6:]), time.monotonic()))
                        ev = eid = None
                    elif line.startswith(": "):
                        self.events.append(("heartbeat", None, line[2:], time.monotonic()))
        except Exception as e:
            self.events.append(("error", None, repr(e), time.monotonic()))
        finally:
            self.connected.set()
            self.closed.set()

    def kinds(self):
        return [e[0] for e in list(self.events)]

    def records(self):
        return [(k, i, d) for k, i, d, _ in list(self.events) if k not in ("status", "heartbeat", "error")]


with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    cat = catalog(data)
    cat.put_scene(scene("apartment"))
    cat.put_scene(scene("room"))
    import_fixture(data)                                                 # explore9: a real run
    import_fixture(data, "explore9", robot="rover")                       # the same name under another robot
    make_run(data, "duck/room/done1", HEAD + [tick(1.0, 0.0), tick(1.1, 0.03), (1.2, "plan", {"path": [[0, 0], [1, 0]]}),
                                             tick(1.2, 0.06), (2.5, "event", {"kind": "trapped", "text": "trapped"}),
                                             (2.5, "end", {"verdict": "trapped"})])
    make_run(data, "duck/room/empty1", [(0.0, "epoch", {"map_to_world": [1.0, 0.0, 0.0]}), (0.5, "event", {"kind": "cleared", "text": "cleared"})])
    junk = data / "runs/duck/room/junk1"
    junk.mkdir(parents=True)
    (junk / "run.mcap").write_bytes(b"not an mcap")
    httpd, base = serve(cat)
    K = "duck/apartment/explore9"

    def api(path, **kw):
        return get(base, "/api/v1" + path, **kw)

    code, body, _ = api("/health")
    check("health", code == 200 and body["ok"] and body["runs"] == 5, body)
    code, body, _ = api("/scenes")
    check("scenes with their runs, by key, newest first; the broken one is listed with its error",
          code == 200 and body["format"] == 2 and {r["key"] for s in body["scenes"] for r in s["runs"]} ==
          {K, "rover/apartment/explore9", "duck/room/done1", "duck/room/empty1", "duck/room/junk1"}
          and next(r for s in body["scenes"] for r in s["runs"] if r["key"] == "duck/room/junk1")["status"] == "broken", body["scenes"][0]["id"])
    code, body, _ = api("/runs?robot=duck&scene=apartment&status=ended")
    check("the runs list filters by robot, scene and status", [r["key"] for r in body] == [K], body)
    check("the same run name under two robots is two runs, each with its own key and robot",
          api("/runs/rover/apartment/explore9")[1]["robot"]["name"] == "rover"
          and api("/runs/rover/apartment/explore9")[1]["key"] == "rover/apartment/explore9")

    # ---- a run by key ----------------------------------------------------------------------------------------------
    code, r, _ = api(f"/runs/{K}")
    check("the run: key, status, seq, span, streams with their counts", code == 200 and r["key"] == K and r["status"] == "ended"
          and r["ticks"] == 116 and r["seq"] > 116 and r["t0"] == 31.771
          and next(s for s in r["streams"] if s["id"] == "belief.pose")["count"] == 116 and r["segments"], {k: r[k] for k in ("key", "status", "seq", "ticks")})
    code, full, hdrs = api(f"/runs/{K}/frames", headers={"Accept-Encoding": "identity"})
    code, w, _ = api(f"/runs/{K}/frames?from=33&to=35")
    ts = full["t"]
    check("frames for a window: its ticks, and only the plans and worlds they refer to, keyed by index",
          w["t"] == [t for t in ts if 33 <= t <= 35] and w["i0"] == ts.index(w["t"][0])
          and set(w["plans"]) == {str(i) for i in w["plan_at"] if i >= 0} and set(w["worlds"]) == {str(i) for i in w["world_at"] if i >= 0}
          and len(w["worlds"]) < len(full["worlds"]), (len(w["t"]), list(w["plans"]), list(w["worlds"])))
    sc = {s_["id"]: s_["count"] for s_ in r["streams"]}
    check("stream counts, kept as records arrive, equal a recount of the frames",
          sc["truth.pose"] == sum(1 for x in full["truth"] if x) and sc["sensors.depth"] == sum(1 for d in full["depth"] if d)
          and sc["sensors.depth.obstacle"] == sum(1 for d in full["depth"] for p in d or () if p[3] == "o")
          and sc["sensors.tilt"] == sum(1 for x in full["tilt"] if x), sc)
    check("a window is a fraction of the run's bytes", len(json.dumps(w)) < 0.2 * len(json.dumps(full)), (len(json.dumps(w)), len(json.dumps(full))))
    code, s, _ = api(f"/runs/{K}/state?t=36")
    check("state at a time", code == 200 and s["run"] == "explore9" and s["tick"] > 0 and s["depth"]["returns"], s["tick"])
    code, ev, _ = api(f"/runs/{K}/events?kinds=refused")
    check("events filtered by kind", code == 200 and ev and all(e["kind"] == "refused" for e in ev))
    code, pr, _ = api(f"/runs/{K}/presence")
    check("presence: spans and times", code == 200 and pr["streams"]["belief.pose"]["spans"] and pr["streams"]["plan.path"]["times"])
    d1 = api("/runs/duck/room/done1")[1]
    check("a small run end to end: span over every record, verdict", d1["status"] == "ended" and d1["verdict"] == "trapped" and d1["t0"] == 1.0 and d1["t1"] == 2.5, d1["verdict"])
    page = urllib.request.urlopen(base + "/web/three/", timeout=10)
    check("the pages are served", page.status == 200 and b"<html" in page.read().lower())

    # ---- errors are JSON, and a request always gets an answer -------------------------------------------------------
    bad = {"from is not a number": f"/runs/{K}/frames?from=abc", "from is nan": f"/runs/{K}/frames?from=nan",
           "to is infinite": f"/runs/{K}/frames?to=inf", "from after to": f"/runs/{K}/frames?from=9&to=1",
           "state t is text": f"/runs/{K}/state?t=x", "live since is text": f"/runs/{K}/live?since=abc",
           "live since is negative": f"/runs/{K}/live?since=-4", "key with a capital": "/runs/Duck/apartment/explore9",
           "key with dots": "/runs/duck/apartment/..", "key with a space": "/runs/duck/apartment/ex%20plore"}
    results = {n: api(p) for n, p in bad.items()}
    check("bad input is a 400 with a JSON error, never a dropped connection",
          all(c == 400 and isinstance(b, dict) and b.get("error") for c, b, _ in results.values()), {n: r[0] for n, r in results.items()})
    check("unknown run, scene, route and sub-route are 404 JSON",
          [api(p)[0] for p in ("/runs/duck/apartment/nope", "/scenes/nope", "/nothing", f"/runs/{K}/nothing")] == [404] * 4
          and api("/runs/duck/apartment/nope")[1]["error"])
    conn = http.client.HTTPConnection(base.split("//")[1])
    conn.request("POST", "/api/v1/runs", body=b"{}")
    resp = conn.getresponse()
    check("a method that is not GET or HEAD is a 405 JSON", resp.status == 405 and json.loads(resp.read())["error"])
    check("a run with no ticks yet: state is a 409", api("/runs/duck/room/empty1/state")[0] == 409
          and api("/runs/duck/room/empty1/presence")[0] == 409 and api("/runs/duck/room/empty1")[0] == 200)
    check("a broken run: its summary says so, its data is a 409 with the reason", api("/runs/duck/room/junk1")[1]["status"] == "broken"
          and api("/runs/duck/room/junk1/frames")[0] == 409 and "not an MCAP" in api("/runs/duck/room/junk1/frames")[1]["error"])
    logbuf = io.StringIO()
    handler = logging.StreamHandler(logbuf)
    logging.getLogger("miniview").addHandler(handler)
    real = query.state
    query.state = lambda *a, **k: 1 / 0
    try:
        code, body, _ = api(f"/runs/{K}/state?t=36")
    finally:
        query.state = real
        logging.getLogger("miniview").removeHandler(handler)
    check("an internal error is a 500 JSON with an id, the same id is in the log, no traceback to the client",
          code == 500 and body["id"] and body["id"] in logbuf.getvalue() and "Traceback" not in json.dumps(body) and "ZeroDivision" in logbuf.getvalue(), body)
    check("the service still answers after all of that", api("/health")[0] == 200)

    # ---- gzip, ETag, caching ------------------------------------------------------------------------------------------
    code, body, hdrs = get(base, f"/api/v1/runs/{K}/frames", headers={"Accept-Encoding": "gzip"})
    raw = urllib.request.urlopen(urllib.request.Request(f"{base}/api/v1/runs/{K}/frames", headers={"Accept-Encoding": "gzip"}))
    check("JSON over 1 KB is gzipped when the client accepts it", raw.headers["Content-Encoding"] == "gzip"
          and json.loads(gzip.decompress(raw.read()))["t"] == ts)
    plain = urllib.request.urlopen(urllib.request.Request(f"{base}/api/v1/runs/{K}/frames"))
    check("... and not when it does not", plain.headers["Content-Encoding"] is None)
    small = urllib.request.urlopen(urllib.request.Request(f"{base}/api/v1/health", headers={"Accept-Encoding": "gzip"}))
    check("... and not when it is small", small.headers["Content-Encoding"] is None)
    st = urllib.request.urlopen(base + "/web/shell/shell.js")
    etag = st.headers["ETag"]
    cond = urllib.request.Request(base + "/web/shell/shell.js", headers={"If-None-Match": etag})
    try:
        urllib.request.urlopen(cond)
        code304 = 200
    except urllib.error.HTTPError as e:
        code304 = e.code
    check("static files carry an ETag and answer a matching If-None-Match with 304", bool(etag) and code304 == 304, (etag, code304))
    vendor = next((WEB for WEB in [server.WEB / "three" / "vendor"] if WEB.exists()))
    lib = next(p for p in vendor.iterdir() if p.is_file())
    vh = urllib.request.urlopen(f"{base}/web/three/vendor/{lib.name}").headers
    check("vendored libraries are cached for a day; the pages revalidate", "max-age=86400" in vh["Cache-Control"]
          and st.headers["Cache-Control"] == "no-cache", (vh["Cache-Control"], st.headers["Cache-Control"]))
    h = http.client.HTTPConnection(base.split("//")[1])
    h.request("HEAD", f"/api/v1/runs/{K}")
    hr = h.getresponse()
    check("HEAD answers with the headers of the GET and no body", hr.status == 200 and int(hr.getheader("Content-Length")) > 0 and hr.read() == b"")

    # ---- a live run: by record, with resume, for two viewers ------------------------------------------------------------
    rec = make_run(data, "duck/room/live1", HEAD + [tick(1.0, 0.0)], close=False)
    wait_until(lambda: any(r["key"] == "duck/room/live1" for r in api("/runs")[1]), what="the live run to be listed")
    lr = api("/runs/duck/room/live1")[1]
    check("a run being written is listed as live", lr["status"] == "live" and lr["ticks"] == 1, lr["status"])
    h = http.client.HTTPConnection(base.split("//")[1], timeout=5)
    h.request("HEAD", "/api/v1/runs/duck/room/live1/live")
    hr = h.getresponse()
    check("HEAD on a live stream returns its headers and ends (it does not stream)", hr.status == 200
          and hr.getheader("Content-Type") == "text/event-stream" and hr.read() == b"")
    a, b = Stream(base, "duck/room/live1", since=lr["seq"]), Stream(base, "duck/room/live1", since=lr["seq"])
    t_write = time.monotonic()
    rec.add(*tick(1.1, 0.03))
    wait_until(lambda: all(any(k == "tick" for k, *_ in s.events) for s in (a, b)), 5, what="both viewers to get the tick")
    latency = max(next(e[3] for e in s.events if e[0] == "tick") for s in (a, b)) - t_write
    check(f"two viewers each get the new tick within three follower rounds ({MARGIN:.2f} s)", latency < MARGIN, f"{latency:.2f} s")
    rec.add(1.2, "event", {"kind": "cliff_stop", "text": "cliff_stop"})
    rec.add(*tick(1.3, 0.09))
    wait_until(lambda: len(a.records()) >= 3 and len(b.records()) >= 3, 5, what="three records on both streams")
    ra = a.records()
    check("each record is an event named by its kind, its seq the id, in order", [k for k, *_ in ra] == ["tick", "event", "tick"]
          and [i for _, i, _ in ra] == list(range(lr["seq"] + 1, lr["seq"] + 4)) and ra[1][2]["kind"] == "cliff_stop" and ra == b.records(), ra[:2])
    first_seq = ra[0][1]
    c = Stream(base, "duck/room/live1", last_id=first_seq)
    wait_until(lambda: len(c.records()) >= 2, 5, what="the resume to replay")
    check("a resume by Last-Event-ID replays only what comes after that id", [i for _, i, _ in c.records()] == [first_seq + 1, first_seq + 2], c.records())
    d = Stream(base, "duck/room/live1", since=0, last_id=first_seq + 1)
    wait_until(lambda: len(d.records()) >= 1, 5, what="the Last-Event-ID resume")
    check("Last-Event-ID wins over `since` (a reconnect keeps the id the client last saw)", [i for _, i, _ in d.records()] == [first_seq + 2], d.records())
    # a burst: no record waits for the 1 s timeout (the notify cannot be missed between looking and waiting)
    burst = Stream(base, "duck/room/live1", since=cat.get("duck/room/live1").data.seq)
    stamps = {}
    for i in range(40):
        rec.add(*tick(2.0 + i * 0.01, 0.1))
        stamps[i] = time.monotonic()
        wait_until(lambda: len([r for r in burst.records() if r[0] == "tick"]) > i, 3, every=0.001, what=f"burst record {i}")
    lat = [e[3] - stamps[i] for i, e in enumerate([e for e in burst.events if e[0] == "tick"])]
    check(f"40 records written one after another: each reaches the stream within three follower rounds ({MARGIN:.2f} s)", max(lat) < MARGIN, f"max {max(lat):.3f} s")
    check("a stream pins its run in the cache while it is open", cat.get("duck/room/live1").pins >= 4 and not a.closed.is_set())
    # a heartbeat
    server.HEARTBEAT_S = 0.2
    hb = Stream(base, "duck/room/live1", since=cat.get("duck/room/live1").data.seq)
    wait_until(lambda: "heartbeat" in hb.kinds(), 5, what="a heartbeat")
    server.HEARTBEAT_S = 15.0
    check("a heartbeat keeps a quiet stream alive", "heartbeat" in hb.kinds())
    rec.add(5.0, "end", {"verdict": "trapped"})
    rec.close()
    wait_until(lambda: a.closed.is_set() and b.closed.is_set(), 10, what="the streams to close")
    st_ = [e for e in a.events if e[0] == "status"][-1][2]
    check("the end arrives and the stream closes as ended", "end" in a.kinds() and st_["status"] == "ended" and st_.get("done"), st_)
    wait_until(lambda: api("/runs/duck/room/live1")[1]["status"] == "ended", 5, what="ended status")
    wait_until(lambda: cat.get("duck/room/live1").pins == 0, 5, what="the streams to release the run")
    check("closed streams release the run", cat.get("duck/room/live1").pins == 0)

    # ---- a viewer that connects after the end, from the middle ------------------------------------------------------------
    late = Stream(base, "duck/room/live1", since=0)
    wait_until(late.closed.is_set, 10, what="a stream of a finished run to close")
    check("a finished run replays its records and closes", late.records()[0][1] == 1 and late.records()[-1][0] == "end")
    httpd.shutdown()

check.done()
