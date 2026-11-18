"""nxt-web's exclusive control lock (RFC-0017 step 4): the rules with a fake clock, then /api/lock
against the simulated brick (--fake; nothing here touches a real robot).
Run: make test-unit, or python nxt/tests/test_lock.py from the repo."""

import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from nxt_lab.lock import Lock, LockError, load_names

NXT_DIR = Path(__file__).resolve().parents[1]
NXT_WEB = os.environ.get("NXT_WEB", str(NXT_DIR / ".venv" / "bin" / "nxt-web"))

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:160]}]" if detail else ""))
    if not cond:
        failures.append(name)


def refused(fn, *args):
    try:
        fn(*args)
    except LockError as exc:
        return exc
    return None


# --- the rules, fake clock ------------------------------------------------------------------
now = [100.0]
stops, log = [], []
lock = Lock(lambda: stops.append(now[0]), clock=lambda: now[0], wall=lambda: 1_000_000.0, lease_s=20.0,
            takeover_names={"operator"}, event=lambda kind, **d: log.append((kind, d)))

check("free: anyone without a session may still drive (the page does not take the lock yet)", lock.check(None) is None)
a = lock.acquire("mission-control")
check("acquire gives a session and a lease id", a["lease_id"] == 1 and len(a["session"]) == 16, a)
err = refused(lock.acquire, "script")
check("a second acquire is refused with who and since", err and err.code == "held" and "mission-control since" in str(err) and err.data["holder"] == "mission-control", err and str(err))
check("a drive without a session is refused while held", refused(lock.check, None).code == "held")
check("a drive with a made-up session is refused", refused(lock.check, "deadbeef").code == "no_lease")
check("the holder's drive passes", lock.check(a["session"]) is None)
check("a peer cannot release it", refused(lock.release, "deadbeef").code == "not_holder")
check("who is open", lock.who()["holder"] == "mission-control" and lock.who()["since"] == 1_000_000.0, lock.who())
check("takeover is refused to a name not on the list", refused(lock.takeover, "script").code == "not_allowed")
check("a peer did not eject the holder", lock.who()["holder"] == "mission-control")

# expiry, renewal
now[0] += 15
lock.check(a["session"])
now[0] += 15
check("a drive renews the lease", lock.who()["holder"] == "mission-control")
lock.keepalive(a["session"])
now[0] += 19
check("a keepalive renews the lease", lock.who()["holder"] == "mission-control")
n = len(stops)
now[0] += 2
check("silence past the lease frees the robot on the lock's own clock", lock.who()["holder"] is None)
check("expiry stops the motors", len(stops) == n + 1, stops)
err = refused(lock.check, a["session"])
check("the frozen holder is refused with the reason", err and err.code == "lease_ended" and err.data["reason"] == "expired", err and str(err))
b = lock.acquire("script")
check("a peer acquires after expiry", b["lease_id"] == 2)
check("the frozen holder is still refused, now that the robot is held", refused(lock.check, a["session"]).code == "lease_ended")
lock.release(b["session"])
check("release stops the motors and frees the robot", lock.who()["holder"] is None and len(stops) == n + 2)
check("the released session is refused afterwards", refused(lock.check, b["session"]).data["reason"] == "released")
check("a stale session is refused even when the robot is free", refused(lock.check, a["session"]) is not None)

# STOP latches
c = lock.acquire("navigator")
n = len(stops)
lock.stop_from("bystander")
check("STOP from anyone ends the lease and stops the motors", lock.who()["holder"] is None and len(stops) == n + 1)
err = refused(lock.check, c["session"])
check("the holder's next drive is refused with the reason", err and err.data["reason"] == "stopped_by bystander", err and str(err))
check("and again (the page resends every 200 ms)", refused(lock.check, c["session"]) is not None)
check("a keepalive does not clear the latch", refused(lock.keepalive, c["session"]).code == "lease_ended")
c2 = lock.acquire("navigator")
check("acquiring again clears it, with a new session", c2["session"] != c["session"] and lock.check(c2["session"]) is None)
lock.release(c2["session"])
n = len(stops)
lock.stop_from("anyone")
check("STOP with nobody holding does nothing here (the caller stops the motors)", len(stops) == n)

# takeover
d = lock.acquire("friend")
n = len(stops)
t = lock.takeover("operator")
check("an owner takes a lent robot back", t["lease_id"] == d["lease_id"] + 1 and lock.who()["holder"] == "operator", t)
check("the robot is stopped when it is taken", len(stops) == n + 1)
check("the old holder is refused with the reason", refused(lock.check, d["session"]).data["reason"] == "taken_over_by operator")
check("the old holder cannot take it back", refused(lock.takeover, "friend").code == "not_allowed")
lock.release(t["session"])
check("takeover of a free robot is an acquire", lock.takeover("operator")["lease_id"] > t["lease_id"])

kinds = [k for k, _ in log]
check("the log has acquired, expired, released, stopped, taken over",
      {"lock acquired", "lock released", "lock taken over", "lock ended by stop"} <= set(kinds) and any(x.get("reason") == "expired" for _, x in log), kinds)
check("a STOP is logged with the name", any(x.get("by") == "bystander" for _, x in log))
check("a takeover is logged: who and from whom", any(k == "lock taken over" and x["by"] == "operator" and x["client"] == "friend" for k, x in log))


def failing_stop():
    raise RuntimeError("link gone")


broken = Lock(failing_stop, clock=lambda: now[0])
broken.acquire("x")
broken.stop_from("y")
check("a motor stop that fails still ends the lease", broken.who()["holder"] is None)

tmp = Path(tempfile.mkdtemp())
names = tmp / "takeover.txt"
names.write_text("# the operator's own\noperator\n\n  phone  # mine\n")
check("takeover list: one name per line, comments skipped", load_names(names) == {"operator", "phone"}, load_names(names))
check("no list, or a missing file: nobody", load_names(None) == frozenset() and load_names(tmp / "none") == frozenset())

# --- /api/lock against the simulated brick ----------------------------------------------------
ENV = dict(os.environ, NXT_LAB_DATA=str(tmp), MINIVIEW_DATA=str(tmp / "miniview"))


def call(base, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def upload(base, name, data, session=None):
    """POST /api/files/upload: the file is the body, so the session rides in the query."""
    url = f"{base}/api/files/upload?name={name}" + (f"&session={session}" if session else "")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def on_brick(base):
    return {f["name"] for f in call(base, "/api/files")[1]["files"]}


port = 8764
p = subprocess.Popen([NXT_WEB, "--fake", "--port", str(port), "--config", str(tmp / "config.json"), "--takeover-names", str(names)],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=ENV)
print("server:", p.stdout.readline().strip())
base = f"http://127.0.0.1:{port}"
try:
    check("GET /api/lock: free", call(base, "/api/lock")[1]["holder"] is None)
    code, r = call(base, "/api/drive", {"left": 30, "right": 30})
    check("free: an unlocked drive still works", code == 200, (code, r))
    code, a = call(base, "/api/lock", {"action": "acquire", "client": "mission-control"})
    check("acquire over HTTP", code == 200 and a["ok"] and a["session"] and a["lease_id"] == 1, a)
    code, r = call(base, "/api/lock", {"action": "acquire", "client": "page"})
    check("a second acquire: 409 with who", code == 409 and r["lock"] == "held" and r["holder"] == "mission-control", r)
    code, r = call(base, "/api/drive", {"left": 30, "right": 30})
    check("an unlocked drive is refused while held", code == 409 and r["lock"] == "held", r)
    code, r = call(base, "/api/drive", {"left": 30, "right": 30, "session": "nope"})
    check("a wrong session is refused", code == 409 and r["lock"] == "no_lease", r)
    code, r = call(base, "/api/drive", {"left": 40, "right": 40, "session": a["session"]})
    check("the holder drives", code == 200, (code, r))
    status = call(base, "/api/status")[1]
    check("and the motors moved", (status["left"], status["right"]) == (40, 40), status)
    code, r = call(base, "/api/fire", {})
    check("fire is locked too", code == 409 and r["lock"] == "held", r)
    code, r = call(base, "/api/program/stop", {})
    check("program stop is locked too", code == 409 and r["lock"] == "held", r)
    # what is on the brick: upload and delete pass the lock; config, connect and the reads stay open
    code, r = upload(base, "locked.rxe", b"\x01\x02")
    check("an upload without the session is refused while held", code == 409 and r["lock"] == "held" and r["holder"] == "mission-control", r)
    check("and nothing reached the brick", "locked.rxe" not in on_brick(base))
    code, r = upload(base, "locked.rxe", b"\x01\x02", session="nope")
    check("an upload with a wrong session is refused", code == 409 and r["lock"] == "no_lease", r)
    code, r = upload(base, "locked.rxe", b"\x01\x02", session=a["session"])
    check("the holder's upload goes through", code == 200 and "locked.rxe" in on_brick(base), r)
    code, r = call(base, "/api/files/delete", {"name": "locked.rxe"})
    check("a delete without the session is refused while held", code == 409 and r["lock"] == "held" and "locked.rxe" in on_brick(base), r)
    code, r = call(base, "/api/files/delete", {"name": "locked.rxe", "session": "nope"})
    check("a delete with a wrong session is refused", code == 409 and r["lock"] == "no_lease" and "locked.rxe" in on_brick(base), r)
    code, r = call(base, "/api/files/delete", {"name": "locked.rxe", "session": a["session"]})
    check("the holder's delete goes through", code == 200 and "locked.rxe" not in on_brick(base), r)
    code, r = call(base, "/api/files")
    check("listing files is open while held", code == 200 and r["files"])
    with urllib.request.urlopen(base + "/api/files/download?name=demo.rxe", timeout=5) as dl:
        check("downloading is open while held", dl.status == 200)
    code, r = call(base, "/api/config", {"sample_hz": 10})
    check("config stays open while held", code == 200 and r.get("lock") is None, (code, r))
    code, r = call(base, "/api/connect", {"link": "auto"})
    check("connect stays open while held", r.get("lock") is None, (code, r))
    code, r = call(base, "/api/status")
    check("reads are open", code == 200 and r["connected"])
    code, r = call(base, "/api/lock", {"action": "takeover", "client": "page"})
    check("takeover is refused to a name not on the list", code == 409 and r["lock"] == "not_allowed", r)
    code, r = call(base, "/api/lock", {"action": "keepalive", "session": a["session"]})
    check("keepalive", code == 200 and r["lease_id"] == 1, r)
    code, r = call(base, "/api/stop", {"client": "page"})
    check("STOP from a peer is accepted", code == 200, r)
    status = call(base, "/api/status")[1]
    check("STOP stopped the motors", (status["left"], status["right"]) == (0, 0), status)
    code, r = call(base, "/api/drive", {"left": 40, "right": 40, "session": a["session"]})
    check("the holder's next drive is refused: STOP latched", code == 409 and r["lock"] == "lease_ended" and r["reason"] == "stopped_by page", r)
    check("the robot is free after STOP", call(base, "/api/lock")[1]["holder"] is None)
    code, r = upload(base, "late.rxe", b"\x01", session=a["session"])
    check("the latched session cannot upload either", code == 409 and r["lock"] == "lease_ended" and r["reason"] == "stopped_by page" and "late.rxe" not in on_brick(base), r)
    code, r = upload(base, "free.rxe", b"\x01")
    check("free: an upload with no session still works (the page does not take the lock)", code == 200 and "free.rxe" in on_brick(base), r)
    code, r = call(base, "/api/files/delete", {"name": "free.rxe"})
    check("free: so does a delete", code == 200 and "free.rxe" not in on_brick(base), r)
    code, a2 = call(base, "/api/lock", {"action": "acquire", "client": "mission-control"})
    check("acquire clears it", code == 200 and a2["lease_id"] == 2)
    code, t = call(base, "/api/lock", {"action": "takeover", "client": "operator"})
    check("an owner takes it back over HTTP", code == 200 and t["lease_id"] == 3 and call(base, "/api/lock")[1]["holder"] == "operator", t)
    code, r = call(base, "/api/drive", {"left": 40, "right": 40, "session": a2["session"]})
    check("the old holder is refused with the reason", code == 409 and r["reason"] == "taken_over_by operator", r)
    code, r = call(base, "/api/lock", {"action": "release", "session": a2["session"]})
    check("a stale session cannot release", code == 409 and r["lock"] == "not_holder", r)
    code, r = call(base, "/api/lock", {"action": "release", "session": t["session"]})
    check("release", code == 200 and call(base, "/api/lock")[1]["holder"] is None, r)
    code, r = call(base, "/api/lock", {"action": "acquire"})
    check("acquire needs a client name", code == 409 and "client" in r["error"], r)
    code, r = call(base, "/api/lock", {"action": "dance"})
    check("an unknown action is refused", code == 409, r)
    ev = call(base, "/api/events?since=0")[1]["events"]
    kinds = [e["kind"] for e in ev]
    check("the command log has the lock's events", {"lock acquired", "lock released", "lock taken over", "lock ended by stop"} <= set(kinds), kinds)
    check("no session id reaches the log", not any("session" in e for e in ev))
finally:
    p.terminate()
    p.communicate(timeout=10)

print()
print("FAIL: " + ", ".join(failures) if failures else "all passed")
raise SystemExit(1 if failures else 0)
