"""A local OTLP/HTTP receiver for the telemetry tests (docs/wip/TELEMETRY-RETENTION-DESIGN.md): the standard library's HTTP server,
decoding each request with the proto classes that come with the exporter. Modes: ok (200), 500, hang (takes the request and never
answers), refuse (nothing listens: a port that was free a moment ago). Nothing here leaves 127.0.0.1."""

import gzip
import socket
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

MODES = ("ok", "500", "hang", "refuse")


def _value(v):
    kind = v.WhichOneof("value")
    return getattr(v, kind) if kind else None


def _attrs(kvs) -> dict:
    return {kv.key: _value(kv.value) for kv in kvs}


class OtlpStub:
    def __init__(self, mode="ok"):
        assert mode in MODES, mode
        self.mode, self.requests, self.headers = mode, [], []
        self.metrics, self.spans, self.logs = [], [], []
        self._lock, self._release = threading.Lock(), threading.Event()
        if mode == "refuse":
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
            s.close()
            self._server = None
            return
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                stub._take(self.path, dict(self.headers), body)
                if stub.mode == "hang":
                    stub._release.wait(60)
                    return
                self.send_response(500 if stub.mode == "500" else 200)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True, name="otlp-stub").start()

    def url(self, signal: str) -> str:
        return f"http://127.0.0.1:{self.port}/v1/{signal}"

    def _take(self, path: str, headers: dict, body: bytes):
        enc = headers.get("Content-Encoding", "").lower()
        if enc == "gzip":
            body = gzip.decompress(body)
        elif enc == "deflate":
            body = zlib.decompress(body)
        with self._lock:
            self.requests.append(path)
            self.headers.append({k.lower(): v for k, v in headers.items()})
            try:
                if path.endswith("/metrics"):
                    self._metrics(body)
                elif path.endswith("/traces"):
                    self._traces(body)
                elif path.endswith("/logs"):
                    self._logs(body)
            except Exception as e:
                self.requests.append(f"undecodable {path}: {e}")

    def _metrics(self, body):
        req = ExportMetricsServiceRequest.FromString(body)
        for rm in req.resource_metrics:
            res = _attrs(rm.resource.attributes)
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    kind = m.WhichOneof("data")
                    for p in getattr(m, kind).data_points:
                        val = p.sum if kind == "histogram" else (p.as_double if p.WhichOneof("value") == "as_double" else p.as_int)
                        self.metrics.append({"name": m.name, "unit": m.unit, "kind": kind, "attrs": _attrs(p.attributes), "resource": res,
                                             "value": val, "count": getattr(p, "count", None)})

    def _traces(self, body):
        req = ExportTraceServiceRequest.FromString(body)
        for rs in req.resource_spans:
            res = _attrs(rs.resource.attributes)
            for ss in rs.scope_spans:
                for s in ss.spans:
                    self.spans.append({"name": s.name, "status": s.status.code, "status_message": s.status.message,
                                       "attrs": _attrs(s.attributes), "events": [e.name for e in s.events],
                                       "event_attrs": [_attrs(e.attributes) for e in s.events], "resource": res,
                                       "start": s.start_time_unix_nano, "end": s.end_time_unix_nano})

    def _logs(self, body):
        req = ExportLogsServiceRequest.FromString(body)
        for rl in req.resource_logs:
            res = _attrs(rl.resource.attributes)
            for sl in rl.scope_logs:
                for r in sl.log_records:
                    self.logs.append({"severity": r.severity_text, "severity_number": r.severity_number, "body": _value(r.body),
                                      "attrs": _attrs(r.attributes), "resource": res})

    def snapshot(self):
        with self._lock:
            return list(self.metrics), list(self.spans), list(self.logs)

    def stop(self):
        self._release.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
