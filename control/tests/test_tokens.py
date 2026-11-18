"""Per-client tokens (RFC-0014 §3.9, step 7): the token store, tokens required on the API with STOP and the health check open to
everybody, the token naming the client (the lease, the event stream and the goal run's record say who), revocation, the event
stream's ?token=, the command line, the MCP server's token, and the store's migration to the schema that has them.
Run: cd control && uv run python tests/test_tokens.py"""

import contextlib
import io
import json
import sqlite3
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from common import Clock, check, finish, make_mc, robot_file, run_for

from mission_control import cli
from mission_control.api import serve
from mission_control.auth import Tokens
from mission_control.errors import ApiError
from mission_control.mcp_server import Api
from mission_control.store import SCHEMA_VERSION, Store

POINT = {"kind": "point", "params": {"x": 2.0, "y": 0.0}}

# --- the store --------------------------------------------------------------------------------------------------------
store = Store(None)
tokens = Tokens(store, Clock())
tid, tok = tokens.create(" phone ")
check("a token is mc_ and random, made for a client", tok.startswith("mc_") and len(tok) > 30 and tokens.verify(tok) == "phone")
check("only its hash is kept: the token is not in the store", tok not in json.dumps(store.all("SELECT * FROM tokens")) and len(store.one("SELECT hash FROM tokens")["hash"]) == 64)
check("a token that is not known, or not a token, names nobody", tokens.verify("mc_nope") is None and tokens.verify("nope") is None and tokens.verify(None) is None and tokens.verify("") is None)
check("the list has no secrets", tokens.list() == [{"id": tid, "client": "phone", "created_at": tokens.list()[0]["created_at"], "revoked_at": None}])
_, tok2 = tokens.create("agent")
check("two tokens are two names", tok != tok2 and tokens.verify(tok2) == "agent" and tokens.active() == 2)
rev = tokens.revoke(tid)
check("revoking ends it, and records when", tokens.verify(tok) is None and rev["revoked_at"] is not None and tokens.active() == 1)
for fn, args, code in ((tokens.revoke, (tid,), 409), (tokens.revoke, (99,), 404), (tokens.create, ("",), 422), (tokens.create, (None,), 422)):
    try:
        fn(*args)
        check(f"{fn.__name__}{args} is refused", False)
    except ApiError as exc:
        check(f"{fn.__name__}{args} is a {code}", exc.status == code)

# --- the API, with tokens required ----------------------------------------------------------------------------------------
clock = Clock()
mc = make_mc(clock, robot_file("fake-1"), robot_file("fake-2", takeover=["laptop"]))
run_for(mc, clock, 0.3)
_, T_PHONE = mc.tokens.create("phone")
_, T_LAPTOP = mc.tokens.create("laptop")
rid_old, T_OLD = mc.tokens.create("old-client")
srv = serve(mc, "127.0.0.1", 0, require_tokens=True)
URL = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()


def call(method, path, body=None, token=None, headers=None, base=None):
    h = {"Content-Type": "application/json", **(headers or {}), **({"Authorization": f"Bearer {token}"} if token else {})}
    req = urllib.request.Request((base or URL + "/api/v1") + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


st, b = call("GET", "/robots")
check("with tokens required, a call with no token is 401 unauthorized", st == 401 and b["error"]["code"] == "unauthorized", b)
st, b = call("GET", "/robots", token="mc_forged")
check("a token that is not known is 401, and says so", st == 401 and "not valid" in b["error"]["message"], b)
check("a token works", call("GET", "/robots", token=T_PHONE)[0] == 200)
check("the health check is open", call("GET", "/health")[0] == 200)
with urllib.request.urlopen(URL + "/", timeout=5) as r:
    check("and the page's own files: it must load to ask for a token", r.status == 200 and b"tokenbox" in r.read())
check("a goal needs one", call("POST", "/goal-runs", {"goal": POINT, "robots": ["fake-1"]})[0] == 401)

# STOP is open to all
st, b = call("POST", "/robots/fake-1/stop", {"client": "bystander"})
check("STOP needs no token, from anybody", st == 200 and b["stop"]["confirmed"] is True)
check("STOP-all too", call("POST", "/stop")[0] == 200)
check("and with a token that is wrong or revoked: still accepted", call("POST", "/stop", token="mc_forged")[0] == 200)
stops = [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "stop"]
check("an anonymous STOP is logged with the name it gave", any(e["client"] == "bystander" for e in stops))
call("POST", "/robots/fake-1/stop", {"client": "claims-to-be-someone"}, token=T_PHONE)
check("a STOP with a token is logged with the token's name, whatever the body says", mc.bus.since(0, 100000)[0][-1]["client"] in ("phone",)
      or any(e["kind"] == "stop" and e["client"] == "phone" for e in mc.bus.since(0, 100000)[0]))

# the token names the client
st, b = call("POST", "/robots/fake-1/lock", {"client": "operator-laptop"}, token=T_PHONE)
check("the lease is held in the token's name: a body that says another is ignored", st == 200 and mc.get_robot("fake-1")["lock"]["holder"] == "phone", mc.get_robot("fake-1")["lock"])
sess = b["lock"]["session"]
st, b = call("POST", "/robots/fake-1/lock", {"client": "phone"}, token=T_LAPTOP)
check("another client is refused with who holds it: the name the token gave", st == 409 and b["error"]["holder"] == "phone")
call("DELETE", "/robots/fake-1/lock", {"session": sess}, token=T_PHONE)
st, b = call("POST", "/robots/fake-2/lock/takeover", {"client": "laptop"}, token=T_PHONE)
check("takeover is for the names on the robot's list: a client cannot say it is the laptop", st == 403)
call("POST", "/robots/fake-2/lock", {}, token=T_PHONE)
st, b = call("POST", "/robots/fake-2/lock/takeover", {}, token=T_LAPTOP)
check("the laptop's token is the laptop: it may take the robot", st == 200 and mc.get_robot("fake-2")["lock"]["holder"] == "laptop")
call("DELETE", "/robots/fake-2/lock", {"session": b["lock"]["session"]}, token=T_LAPTOP)

# who commanded a goal run
st, b = call("POST", "/goal-runs", {"goal": POINT, "robots": ["fake-1"], "client": "lies"}, token=T_PHONE)
run_id = b["run"]["id"]
check("a goal run records the client that commanded it, from the token", st == 201 and b["run"]["client"] == "phone", b["run"].get("client"))
ev = [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "goal-run" and e["goal_run"] == run_id]
check("the event stream says who too", ev and ev[0]["client"] == "phone", ev[:1])
run_for(mc, clock, 60, until=lambda: mc.get_run(run_id)["state"] != "running")
check("the run is in the record with its client, after it ends", mc.get_run(run_id)["client"] == "phone" and call("GET", f"/goal-runs/{run_id}", token=T_PHONE)[1]["run"]["client"] == "phone")
check("a group records its client, and its children", (lambda g: g["client"] == "laptop" and all(k["client"] == "laptop" for k in g["children"]))(
    call("POST", "/goal-runs", {"goal": POINT, "robots": ["fake-1", "fake-2"]}, token=T_LAPTOP)[1]["run"]))
run_for(mc, clock, 60)

# the event stream takes ?token=
for url, want in ((URL + "/api/v1/events", 401), (URL + f"/api/v1/events?token={T_PHONE}&since=0", 200)):
    try:
        resp = urllib.request.urlopen(url, timeout=5)
        first = resp.readline()
        resp.close()
        check(f"the event stream {'takes ?token=' if want == 200 else 'needs a token'}", want == 200 and first.startswith(b":"), first)
    except urllib.error.HTTPError as exc:
        check(f"the event stream {'takes ?token=' if want == 200 else 'needs a token'}", exc.code == want)

# revocation
st, b = call("GET", "/tokens", token=T_PHONE)
check("GET /tokens: who has one, never the token", st == 200 and b["required"] is True and {t["client"] for t in b["tokens"]} == {"phone", "laptop", "old-client"} and "token" not in json.dumps(b["tokens"]))
st, b = call("POST", "/tokens", {"client": "tablet"}, token=T_PHONE)
check("POST /tokens makes one, shown once", st == 201 and b["token"]["token"].startswith("mc_") and call("GET", "/robots", token=b["token"]["token"])[0] == 200)
check("DELETE /tokens/{id} revokes: the next call is 401", call("DELETE", f"/tokens/{rid_old}", token=T_PHONE)[0] == 200 and call("GET", "/robots", token=T_OLD)[0] == 401)
check("and STOP is still open to it", call("POST", "/stop", token=T_OLD)[0] == 200)
check("revoking twice is 409, an unknown token 404", call("DELETE", f"/tokens/{rid_old}", token=T_PHONE)[0] == 409 and call("DELETE", "/tokens/999", token=T_PHONE)[0] == 404)
check("tokens are managed with a token", call("GET", "/tokens")[0] == 401 and call("POST", "/tokens", {"client": "x"})[0] == 401)
srv.shutdown()
srv.server_close()

# without the requirement, as before: a client names itself; a valid token still names it
srv = serve(mc, "127.0.0.1", 0)
URL = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
check("tokens not required: every call works with none (the tailnet is the authentication)", call("GET", "/robots")[0] == 200)
st, b = call("POST", "/robots/fake-1/lock", {"client": "script"})
check("and the caller names itself", b["lock"]["session"] and mc.get_robot("fake-1")["lock"]["holder"] == "script")
call("DELETE", "/robots/fake-1/lock", {"session": b["lock"]["session"]})
st, b = call("POST", "/robots/fake-1/lock", {"client": "pretender"}, token=T_PHONE)
check("a valid token still names the client when tokens are not required", mc.get_robot("fake-1")["lock"]["holder"] == "phone")
check("and a bad token is ignored, not an error, when they are not", call("GET", "/robots", token="mc_forged")[0] == 200)
srv.shutdown()
srv.server_close()

# --- the MCP server carries a token ---------------------------------------------------------------------------------------
srv = serve(mc, "127.0.0.1", 0, require_tokens=True)
URL = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
_, T_AGENT = mc.tokens.create("claude")
try:
    Api(URL).call("GET", "/robots")
    check("the MCP server with no token is refused by a server that wants one", False)
except Exception as exc:
    check("the MCP server with no token is refused by a server that wants one", "unauthorized" in str(exc), str(exc))
check("with its token it works, and speaks as the token's client", Api(URL, token=T_AGENT).call("GET", "/robots")["ok"])
a = Api(URL, token=T_AGENT).call("POST", "/robots/fake-2/lock", {"client": "mcp-agent"})
check("the lease it takes is in the token's name, not the name the MCP server was configured with", mc.get_robot("fake-2")["lock"]["holder"] == "claude", mc.get_robot("fake-2")["lock"])
Api(URL, token=T_AGENT).call("DELETE", "/robots/fake-2/lock", {"session": a["lock"]["session"]})
try:
    Api(URL, token=T_AGENT).call("POST", "/tokens", {"client": "me"})
    check("the MCP server cannot make tokens: not an allowed route", False)
except Exception as exc:
    check("the MCP server cannot make tokens: not an allowed route", "refused" in str(exc), str(exc))
srv.shutdown()
srv.server_close()

# --- the command line ----------------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    def run(*argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    code, out, err = run("token", "create", "--client", "page", "--state", tmp)
    token = out.split(": ")[1].strip()
    check("token create prints the token once and says so", code == 0 and token.startswith("mc_") and "only time" in err, (out, err))
    code, out, _ = run("token", "list", "--state", tmp)
    check("token list shows the client and its state, not the token", code == 0 and "page\tactive" in out and token not in out, out)
    st2 = Store(Path(tmp) / "mission-control.sqlite")
    check("the server's store verifies it", Tokens(st2).verify(token) == "page")
    st2.close()
    check("token revoke", run("token", "revoke", "1", "--state", tmp)[0] == 0 and "revoked" in run("token", "list", "--state", tmp)[1])
    check("token create without a client is refused", run("token", "create", "--state", tmp)[0] == 2)
    check("token revoke without an id, or of one that is not there, is refused", run("token", "revoke", "--state", tmp)[0] == 2 and run("token", "revoke", "42", "--state", tmp)[0] == 2)

    robots = Path(tmp) / "robots"
    robots.mkdir()
    (robots / "fake-1.json").write_text(json.dumps(robot_file("fake-1")))
    code, _, err = run("serve", "--robots", str(robots), "--state", str(Path(tmp) / "empty"), "--require-tokens", "--port", "0")
    check("serve --require-tokens with no token made refuses to start, and says how to make one", code == 2 and "token create" in err, err)

# --- the migration --------------------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "v2.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE goal_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, goal TEXT NOT NULL, robot TEXT NOT NULL, state TEXT NOT NULL,
        parent_id INTEGER, share TEXT);
        INSERT INTO goal_runs (goal, robot, state) VALUES ('{}', 'fake-1', 'reached');
        PRAGMA user_version = 2;""")
    db.commit()
    db.close()
    s = Store(path)
    check("a store of version 2 is brought to this one: goal runs gain client, the tokens table exists, the old run is kept",
          "client" in {r["name"] for r in s.all("PRAGMA table_info(goal_runs)")} and s.one("SELECT COUNT(*) AS n FROM tokens")["n"] == 0
          and s.one("SELECT COUNT(*) AS n FROM goal_runs")["n"] == 1 and s.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION == 3)
    s.close()

finish("test_tokens")
