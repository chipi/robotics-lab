"""The real send (phase 5 step 6, docs/wip/TELEMETRY-RETENTION-DESIGN.md): one metric, one span and one log through
runfile.telemetry to the operator's Victoria stack, then a poll of the stack's own query APIs until each arrives. It is the check that
the three endpoints take what the module sends, and it prints the names the stack stores, which the dashboard's queries use.

Not in CI: it needs the tailnet. Needs the OpenTelemetry packages, so it runs in Mission Control's environment:
    make telemetry-send-check
    cd apps/mission-control && uv run --frozen python ../../scripts/telemetry_send_check.py [--timeout 60]

The send is marked: robot_id telemetry-check-<8 hex>, environment "check", service robotics-lab-telemetry-check. No token: the stack is
reached over the tailnet. Ends with EXIT=0 when all three signals arrived."""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import uuid

from runfile import telemetry as T
from runfile.installation import Telemetry

TRACES = "https://vtraces.tail6d0ed4.ts.net/insert/opentelemetry/v1/traces"
METRICS = "https://vm.tail6d0ed4.ts.net/opentelemetry/v1/metrics"
LOGS = "https://vlogs.tail6d0ed4.ts.net/insert/opentelemetry/v1/logs"
VM, VL, VT = "https://vm.tail6d0ed4.ts.net", "https://vlogs.tail6d0ed4.ts.net", "https://vtraces.tail6d0ed4.ts.net"
SERVICE = "robotics-lab-telemetry-check"


def get(url: str, **params) -> str:
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    with urllib.request.urlopen(urllib.request.Request(full), timeout=10) as r:
        return r.read().decode("utf-8", "replace")


def frag(text: str, around: str = "", n: int = 300) -> str:
    i = max(0, text.find(around) - 80) if around and around in text else 0
    return text[i:i + n].replace("\n", " ")


def q_metrics(rid: str):
    body = get(VM + "/api/v1/query", query=f'{{robot_id="{rid}"}}')
    result = json.loads(body).get("data", {}).get("result", [])
    return (bool(result), sorted({r["metric"].get("__name__", "?") for r in result}), body)


def q_logs(rid: str):
    body = get(VL + "/select/logsql/query", query=f'_time:30m robot_id:"{rid}"', limit="5")
    return (rid in body, None, body)


def q_traces(rid: str):
    body = get(VT + "/select/jaeger/api/traces", service=SERVICE, lookback="1h", limit="20")
    return (rid in body, None, body)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for the stack to answer with the data (default 60)")
    args = ap.parse_args()

    rid = f"telemetry-check-{uuid.uuid4().hex[:8]}"
    labels = {"robot_id": rid, "robot_kind": "check", "host_kind": "check"}
    sink = T.start(Telemetry("check", TRACES, METRICS, LOGS, 5), SERVICE, version="check")
    if type(sink) is T.Sink:
        print("FAIL telemetry did not start (the SDK is missing? run it through `make telemetry-send-check`)")
        print("EXIT=1")
        return 1
    print(f"sending robot_id={rid} environment=check service={SERVICE}")
    sink.count("robotics_lab.stops", 1, **labels)
    sink.span_start("check", "telemetry.check", **labels)
    sink.span_end("check")
    sink.log("info", f"telemetry send check {rid}", kind="telemetry-check", **labels)
    sink.close(timeout=10.0)
    if sink.dropped:
        print(f"note: the Sink dropped {sink.dropped} point(s) before sending")

    queries = {"metric": q_metrics, "span": q_traces, "log": q_logs}
    found: dict = {}
    deadline = time.monotonic() + args.timeout
    while queries and time.monotonic() < deadline:
        for name, fn in list(queries.items()):
            try:
                ok, names, body = fn(rid)
            except Exception as e:
                ok, names, body = False, None, f"{type(e).__name__}: {e}"
            if ok:
                found[name] = (names, body)
                del queries[name]
            else:
                found[name + "?"] = (names, body)
        if queries:
            time.sleep(5)
    failed = 0
    for name in ("metric", "span", "log"):
        if name in found:
            names, body = found[name]
            print(f"PASS {name}: arrived" + (f", stored as {names}" if names else "") + f"\n     {frag(body, rid)}")
        else:
            failed += 1
            _, body = found.get(name + "?", (None, "no answer"))
            print(f"FAIL {name}: not found within {args.timeout:g} s\n     last answer: {frag(body)}")
    print(f"EXIT={1 if failed else 0}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
