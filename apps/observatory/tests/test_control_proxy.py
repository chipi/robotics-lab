"""Mission Control behind the Observatory's origin (RFC-0024 step 3, the operator's answer to question 3): /control/... is forwarded, whatever the
method, to OBSERVATORY_CONTROL, with the Authorization header and nothing of the browser's cookies; a stream stays a stream; a Mission Control that does not
answer is a 502 in its own error shape. The upstream here is a stand-in that records what it was asked (the real pair is tested by Mission Control's
tests/test_one_origin_page.py). Run: cd apps/observatory && uv run python tests/test_control_proxy.py"""

import http.client
import json
import os
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from helpers import Checks, catalog, serve

check = Checks("CONTROL PROXY")
SEEN: list = []
RELEASE = threading.Event()


class Upstream(BaseHTTPRequestHandler):
    """HTTP/1.0 like Mission Control's own server: an answer ends at the close unless it says its length."""

    def log_message(self, *a):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _answer(self, code, body: bytes, ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _handle(self):
        body = self._body()
        SEEN.append({"method": self.command, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        path = self.path.split("?")[0]
        if path == "/":
            return self._answer(200, b"<html>mission control</html>", "text/html; charset=utf-8", {"ETag": '"abc"'})
        if path == "/api/v1/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b": connected\n\nevent: first\ndata: 1\n\n")
            self.wfile.flush()
            RELEASE.wait(10)
            self.wfile.write(b"event: second\ndata: 2\n\n")
            return
        if path == "/api/v1/locked":
            return self._answer(401, json.dumps({"ok": False, "error": {"code": "unauthorized", "message": "a token"}}).encode())
        if path == "/api/v1/cached":
            self.send_response(304)
            self.send_header("ETag", '"abc"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._answer(201 if self.command == "POST" else 200, json.dumps({"method": self.command, "path": self.path, "n": len(body)}).encode())

    do_GET = do_POST = do_PUT = do_DELETE = _handle


up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
up.daemon_threads = True
threading.Thread(target=up.serve_forever, daemon=True).start()
UP = f"http://127.0.0.1:{up.server_address[1]}"


def call(base, method, path, body=None, headers=None):
    u = base.replace("http://", "")
    host, port = u.split(":")
    c = http.client.HTTPConnection(host, int(port), timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    out = (r.status, data, {k.lower(): v for k, v in r.getheaders()})
    c.close()
    return out


with tempfile.TemporaryDirectory() as tmp:
    cat = catalog(Path(tmp) / "data")
    httpd, base = serve(cat, follow=False)

    os.environ.pop("OBSERVATORY_CONTROL", None)
    os.environ.pop("MINIVIEW_CONTROL", None)
    st, body, _ = call(base, "GET", "/control/")
    check("with no Mission Control named, /control/ is a 404 that says so", st == 404 and b"OBSERVATORY_CONTROL" in body, (st, body[:120]))
    st, body, _ = call(base, "POST", "/control/api/v1/stop", b"{}", {"Content-Type": "application/json"})
    check("... and so is a POST", st == 404, st)

    os.environ["OBSERVATORY_CONTROL"] = UP + "/"
    st, body, h = call(base, "GET", "/control/")
    check("the page: /control/ is Mission Control's /, its headers (type, ETag) kept", st == 200 and body == b"<html>mission control</html>"
          and h["content-type"].startswith("text/html") and h["etag"] == '"abc"' and SEEN[-1]["path"] == "/", (st, h))
    st, body, h = call(base, "GET", "/control")
    check("/control with no slash goes to /control/ (the page's relative addresses need it)", st == 301 and h["location"] == "/control/", (st, h.get("location")))
    st, body, _ = call(base, "GET", "/control/api/v1/echo?a=1&b=x%20y")
    check("a GET: the path after /control and the query go across as they are", st == 200 and SEEN[-1]["path"] == "/api/v1/echo?a=1&b=x%20y"
          and json.loads(body)["method"] == "GET", SEEN[-1]["path"])

    payload = json.dumps({"vx": 0.2}).encode()
    st, body, _ = call(base, "POST", "/control/api/v1/robots/duck/drive", payload,
                       {"Content-Type": "application/json", "Authorization": "Bearer mc_secret", "Cookie": "session=observatory", "X-Client": "phone"})
    seen = SEEN[-1]
    check("a POST: the body, the Authorization header and X-Client are forwarded, 201 comes back", st == 201 and seen["body"] == payload
          and seen["headers"].get("authorization") == "Bearer mc_secret" and seen["headers"].get("x-client") == "phone"
          and seen["headers"].get("content-type") == "application/json", (st, seen["headers"]))
    check("the browser's cookie is not forwarded", "cookie" not in seen["headers"], seen["headers"])
    for method in ("PUT", "DELETE"):
        st, body, _ = call(base, method, "/control/api/v1/goals/3", b"{}" if method == "PUT" else None, {"Content-Type": "application/json"})
        check(f"a {method} goes across", st == 200 and SEEN[-1]["method"] == method and SEEN[-1]["path"] == "/api/v1/goals/3", (st, SEEN[-1]["method"]))
    st, body, _ = call(base, "GET", "/control/api/v1/locked")
    check("a 401 comes back as a 401, with Mission Control's own error", st == 401 and json.loads(body)["error"]["code"] == "unauthorized", (st, body))
    st, body, h = call(base, "GET", "/control/api/v1/cached", headers={"If-None-Match": '"abc"'})
    check("a 304 comes back with no body", st == 304 and body == b"" and SEEN[-1]["headers"].get("if-none-match") == '"abc"', (st, body))
    st, body, h = call(base, "HEAD", "/control/")
    check("HEAD: the headers, no body", st == 200 and body == b"" and h["content-type"].startswith("text/html"), (st, body))
    st, body, _ = call(base, "POST", "/control/api/v1/plan", b"x" * 1_000_001, {"Content-Type": "application/json"})
    check("a body over Mission Control's limit is a 413 here, not sent", st == 413, st)

    # a stream is passed a chunk at a time: the first event is here while the upstream still holds the second back
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
    c.request("GET", "/control/api/v1/events", headers={"Last-Event-ID": "7"})
    r = c.getresponse()
    first = r.read1(4096)
    check("the event stream arrives while it is open, not when it ends", r.status == 200 and r.getheader("Content-Type") == "text/event-stream"
          and b"event: first" in first and not RELEASE.is_set(), (r.status, first))
    check("... with the browser's Last-Event-ID", SEEN[-1]["headers"].get("last-event-id") == "7", SEEN[-1]["headers"])
    RELEASE.set()
    rest = b""
    while True:
        part = r.read1(4096)
        if not part:
            break
        rest += part
    check("... and the rest follows until the upstream closes", b"event: second" in rest, rest)
    c.close()

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead = s.getsockname()[1]
    s.close()
    os.environ["OBSERVATORY_CONTROL"] = f"http://127.0.0.1:{dead}"
    st, body, h = call(base, "GET", "/control/api/v1/health")
    err = json.loads(body)
    check("a Mission Control that does not answer is a 502 in its own error shape", st == 502 and err["ok"] is False and err["error"]["code"] == "control_unreachable", (st, body))

    os.environ["OBSERVATORY_CONTROL"] = UP
    st, body, _ = call(base, "GET", "/controls/")
    check("only /control is Mission Control's: /controls/ is the Observatory's own 404", st == 404 and b"OBSERVATORY_CONTROL" not in body, (st, body))
    st, body, _ = call(base, "PUT", "/api/v1/health", b"{}")
    check("the Observatory's own paths still allow GET and HEAD only (and its one POST)", st == 405, st)
    st, body, _ = call(base, "GET", "/api/v1/health")
    check("the Observatory's own API is unchanged", st == 200 and json.loads(body)["ok"] is True, (st, body))
    httpd.shutdown()

up.shutdown()
check.done()
