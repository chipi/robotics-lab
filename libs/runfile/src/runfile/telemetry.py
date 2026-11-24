"""Telemetry out of the lab (phase 5 steps 6 and 7, docs/wip/TELEMETRY-RETENTION-DESIGN.md): OpenTelemetry over OTLP/HTTP (protobuf) to
the operator's Victoria stack, nothing kept by us. `start(cfg, service)` returns a `Sink`; with no `telemetry` block in the installation
file (cfg None) it returns the Sink that does nothing: no threads, no OpenTelemetry import. The SDK is imported inside `start` only, so
this module stays standard library at import and any part of the lab may import it; only a process that has the two OpenTelemetry
packages (Mission Control) can turn it on.

Telemetry never takes the lab down: every Sink method swallows its errors (a point it cannot record is counted in `dropped`), exporters
time out at 3 s with bounded queues, `close` returns within its timeout, a failed import or provider build prints one line and gives
the Sink that does nothing. The module sets no request header: the stack is reached over the tailnet, with no credential.

Metrics carry the robot-neutral labels robot_id, robot_kind and host_kind (RFC-0025) and the extra labels of the instrument, no
others (run_key is a span and log attribute, never a metric label)."""

from __future__ import annotations

import logging
import math
import sys
import threading
import time

EXPORT_TIMEOUT_S = 3.0
QUEUE = 512
OPEN_SPANS = 1000
CLOSE_TIMEOUT_S = 4.0
ROBOT_LABELS = ("robot_id", "robot_kind", "host_kind")
INSTRUMENTS = {         # name -> (kind, unit, extra labels)
    "robotics_lab.robot.online": ("gauge", "1", ()),
    "robotics_lab.robot.lock_held": ("gauge", "1", ()),
    "robotics_lab.goals.active": ("gauge", "{goal}", ()),
    "robotics_lab.goals": ("counter", "{goal}", ("state",)),
    "robotics_lab.goal.duration": ("histogram", "s", ("state",)),
    "robotics_lab.anomalies": ("counter", "{anomaly}", ("anomaly", "severity", "source")),
    "robotics_lab.stops": ("counter", "{stop}", ()),
    "robotics_lab.errors": ("counter", "{error}", ()),
}
SEVERITIES = {"debug": "DEBUG", "info": "INFO", "warn": "WARN", "minor": "WARN", "error": "ERROR", "major": "ERROR",
              "critical": "FATAL", "fatal": "FATAL"}
_LABEL_MAX = 128
_ATTR_MAX = 512


class Sink:
    """The Sink that does nothing; the live one overrides every method. The same calls work on both. A span is opened by
    span_start(key, name, **attrs) and closed by span_end(key, error=None): a text for `error` gives it the error status. span_event(key,
    name) is an event on the open span `key`, else a span of zero length called `name` (goal.refused: key None)."""
    dropped = 0

    def count(self, name, n=1, **labels): pass
    def gauge(self, name, value, **labels): pass
    def observe(self, name, value, **labels): pass
    def span_start(self, key, name, **attrs): pass
    def span_end(self, key, error=None, **attrs): pass
    def span_event(self, key, name, **attrs): pass
    def log(self, severity, body, kind=None, **attrs): pass
    def logging_handler(self, level=logging.INFO): return logging.NullHandler()
    def close(self, timeout=CLOSE_TIMEOUT_S): pass


def start(cfg, service: str, version: str = "") -> Sink:
    """The Sink for this process: cfg is the installation's `Telemetry` (None: off). `service` is like "mission-control"."""
    if cfg is None:
        return Sink()
    try:
        return _Live(cfg, service, version)
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        print(f"telemetry: off ({type(e).__name__}: {e})", file=sys.stderr)
        return Sink()


def _attr(v):
    if isinstance(v, (bool, int, float)):
        return v
    return str(v)[:_ATTR_MAX]


def _attrs(d: dict) -> dict:
    return {k: _attr(v) for k, v in d.items() if v is not None}


def _label(v):
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (str, int)) and 0 < len(str(v)) <= _LABEL_MAX:
        return str(v)
    raise ValueError(f"bad label value {v!r}")


def _number(v) -> float:
    v = float(v)
    if not math.isfinite(v):
        raise ValueError(f"bad value {v!r}")
    return v


def _guarded(fn):
    def run(self, *a, **kw):
        try:
            if not self._closed:
                fn(self, *a, **kw)
        except Exception:
            self.dropped += 1
    run.__name__ = fn.__name__
    return run


class _Live(Sink):
    def __init__(self, cfg, service: str, version: str):
        from opentelemetry import metrics as ot_metrics, trace as ot_trace
        from opentelemetry._logs import SeverityNumber
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.trace import Status, StatusCode

        self.dropped, self._closed = 0, False
        self._status, self._code, self._sev = Status, StatusCode, SeverityNumber
        self._lock = threading.Lock()
        self._spans: dict = {}
        self._tracer = self._logger = self._handler_cls = None
        self._instruments: dict = {}
        self._providers: list = []
        name = service if service.startswith("robotics-lab-") else f"robotics-lab-{service}"
        resource = Resource.create({"service.name": name, "service.namespace": "robotics-lab", "service.version": version,
                                    "deployment.environment.name": cfg.environment})
        kw = {"timeout": EXPORT_TIMEOUT_S}
        ms = EXPORT_TIMEOUT_S * 1000
        try:
            if cfg.traces:
                tp = TracerProvider(resource=resource, shutdown_on_exit=False)
                tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.traces, **kw), max_queue_size=QUEUE,
                                                         schedule_delay_millis=2000, export_timeout_millis=ms))
                self._tracer, self._providers = tp.get_tracer("robotics_lab"), self._providers + [tp]
            if cfg.metrics:
                reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=cfg.metrics, **kw),
                                                       export_interval_millis=cfg.metrics_interval_s * 1000, export_timeout_millis=ms)
                mp = MeterProvider(metric_readers=[reader], resource=resource, shutdown_on_exit=False)
                meter = mp.get_meter("robotics_lab")
                for n, (kind, unit, _) in INSTRUMENTS.items():
                    make = {"gauge": meter.create_gauge, "counter": meter.create_counter, "histogram": meter.create_histogram}[kind]
                    self._instruments[n] = make(n, unit=unit)
                self._providers.append(mp)
            if cfg.logs:
                lp = LoggerProvider(resource=resource, shutdown_on_exit=False)
                lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=cfg.logs, **kw), max_queue_size=QUEUE,
                                                                    schedule_delay_millis=2000, export_timeout_millis=ms))
                self._logger, self._lp = lp.get_logger("robotics_lab"), lp
                self._providers.append(lp)

                class Handler(LoggingHandler):
                    def emit(self, record):
                        try:
                            if not record.name.startswith("opentelemetry"):
                                super().emit(record)
                        except Exception:
                            pass
                self._handler_cls = Handler
        except BaseException:
            self.close(0.5)
            raise

    @_guarded
    def count(self, name, n=1, **labels):
        self._metric(name, "counter", labels).add(_number(n), self._metric_labels(name, labels))

    @_guarded
    def gauge(self, name, value, **labels):
        self._metric(name, "gauge", labels).set(_number(value), self._metric_labels(name, labels))

    @_guarded
    def observe(self, name, value, **labels):
        self._metric(name, "histogram", labels).record(_number(value), self._metric_labels(name, labels))

    def _metric(self, name, kind, labels):
        spec = INSTRUMENTS.get(name)
        if spec is None or spec[0] != kind:
            raise KeyError(name)
        return self._instruments[name]

    def _metric_labels(self, name, labels) -> dict:
        return {k: _label(labels[k]) for k in ROBOT_LABELS + INSTRUMENTS[name][2]}

    @_guarded
    def span_start(self, key, name, **attrs):
        if self._tracer is None:
            return
        span = self._tracer.start_span(name, attributes=_attrs(attrs))
        with self._lock:
            old = self._spans.pop(key, None)
            self._spans[key] = span
            evict = self._spans.pop(next(iter(self._spans))) if len(self._spans) > OPEN_SPANS else None
        for s in (old, evict):
            if s is not None:
                s.end()

    @_guarded
    def span_end(self, key, error=None, **attrs):
        with self._lock:
            span = self._spans.pop(key, None)
        if span is None:
            return
        span.set_attributes(_attrs(attrs))
        if error:
            span.set_status(self._status(self._code.ERROR, str(error)[:_ATTR_MAX]))
        span.end()

    @_guarded
    def span_event(self, key, name, **attrs):
        if self._tracer is None:
            return
        with self._lock:
            span = self._spans.get(key)
        if span is not None:
            span.add_event(name, _attrs(attrs))
        else:
            t = time.time_ns()
            self._tracer.start_span(name, attributes=_attrs(attrs), start_time=t).end(end_time=t)

    @_guarded
    def log(self, severity, body, kind=None, **attrs):
        if self._logger is None:
            return
        text = SEVERITIES[str(severity).lower()]
        a = _attrs(attrs)
        if kind:
            a["event.kind"] = str(kind)
        self._logger.emit(severity_number=getattr(self._sev, text), severity_text=text, body=str(body)[:_ATTR_MAX * 4], attributes=a)

    def logging_handler(self, level=logging.INFO):
        try:
            return self._handler_cls(level=level, logger_provider=self._lp) if self._handler_cls else logging.NullHandler()
        except Exception:
            return logging.NullHandler()

    def close(self, timeout=CLOSE_TIMEOUT_S):
        """Flush and stop every signal, in parallel; returns within `timeout` whatever the receiver does."""
        if self._closed:
            return
        self._closed = True
        try:
            with self._lock:
                for s in self._spans.values():
                    try:
                        s.end()
                    except Exception:
                        pass
                self._spans.clear()
            deadline = time.monotonic() + timeout
            threads = []
            for p in self._providers:
                t = threading.Thread(target=self._quiet, args=(p,), daemon=True, name="telemetry-close")
                t.start()
                threads.append(t)
            for t in threads:
                t.join(max(0.0, deadline - time.monotonic()))
        except Exception:
            pass

    @staticmethod
    def _quiet(provider):
        try:
            provider.shutdown()
        except Exception:
            pass
