# Telemetry and retention (phase 5 steps 6 and 7): the design

Planned 2026-11-24 (a planner's read of the tree; line numbers as of `4f0507d`). It settles what
[PHASE5-STEP1-DESIGN.md](PHASE5-STEP1-DESIGN.md) item 7 left open: the installation file's
`telemetry` block. Decided before it: OpenTelemetry out to the operator's Victoria stack, nothing
kept by us ([EXECUTION-PLAN.md](EXECUTION-PLAN.md)); robot-neutral labels (RFC-0025); the two
OpenTelemetry dependencies (approved 2026-11-22); `runs.archive_after_days`, default 30, official
runs always kept.

## What emits

Only Mission Control, at MVP 1. It sees every robot (the duck, the NXT, the fake) through one
seam, its `EventBus` (`events.py:25-39`). A second listener beside the alarms
(`core.py:53`) maps the bus's events to telemetry: `robot-online`, `robot-offline`, `lock`,
`goal-run`, `anomaly` (the navigator's, `rtf_low` included, already reach the bus), `stop`,
`stop-all` and `error`. The listener runs on the emitting thread, so it only enqueues into the
SDK's batch processors and never raises.

Left out on purpose:

- The Observatory, a viewer.
- nxt-web, which Mission Control sees through its adapter.
- The runner and navigator, which may not read the installation file.
- The gate's log.
- Per-tick pose and joint metrics (RFC-0019's health work).
- Trace propagation across processes.
- A health gauge.
- The run files, which stay in the data folder.

## The installation file

```json
"telemetry": {
  "environment": "dev",
  "traces":  "https://vtraces.tail6d0ed4.ts.net/insert/opentelemetry/v1/traces",
  "metrics": "https://vm.tail6d0ed4.ts.net/opentelemetry/v1/metrics",
  "logs":    "https://vlogs.tail6d0ed4.ts.net/insert/opentelemetry/v1/logs",
  "metrics_interval_s": 15
},
"runs": { "archive_after_days": 30 }
```

Each URL is used as given (OTLP/HTTP, protobuf, no token).

- **The `telemetry` block:**
  - An absent block means telemetry is off; an empty block is an error.
  - `environment` is required and matches `^[a-z0-9_-]+$`.
  - At least one signal URL is required, `http(s)://` only.
  - `metrics_interval_s` is 5 to 300.
  - Unknown keys are errors.
- **The `runs` block:** it holds `archive_after_days` only, an int of 1 or more (a bool is refused).

The version stays 1, because the change is additive.

## The module: `runfile.telemetry`

- `start(cfg, service, version=) -> Sink`. With no block it returns a sink that does nothing: no
  threads, no OpenTelemetry import. It imports the SDK only then, so `libs/runfile` stays
  standard library at import.
- The Sink's methods are `count`, `gauge`, `observe`, `span_start`, `span_end`, `span_event`, `log`,
  `logging_handler` and `close`. Every one of them swallows its errors.
- Exporters time out at 3 s with bounded queues and no retry loop. `close()` is bounded.
- No `Authorization` header anywhere.
- A failed SDK import or provider build prints one line and returns the sink that does nothing.

**Resource attributes:** `service.name` (`robotics-lab-mission-control`), `service.namespace`
`robotics-lab`, `service.version`, `deployment.environment.name`.

**Labels:** `robot_id`, `robot_kind` and `host_kind` (RFC-0025). This supersedes RFC-0023 D7's
`robot` and `host`. `run_key` is a span and log attribute, never a metric label.

| Instrument | Type | Unit | Extra labels |
| --- | --- | --- | --- |
| `robotics_lab.robot.online` | gauge 0/1 | `1` | |
| `robotics_lab.robot.lock_held` | gauge 0/1 | `1` | |
| `robotics_lab.goals.active` | gauge | `{goal}` | |
| `robotics_lab.goals` | counter | `{goal}` | `state` |
| `robotics_lab.goal.duration` | histogram | `s` | `state` |
| `robotics_lab.anomalies` | counter | `{anomaly}` | `anomaly`, `severity`, `source` |
| `robotics_lab.stops` | counter | `{stop}` | |
| `robotics_lab.errors` | counter | `{error}` | |

**Spans:**

- `goal.run` runs from the accepted or running event to the run's end, with an error status when a
  goal fails or breaks.
- `goal.refused` is a span of zero length.
- An anomaly is an event on the active `goal.run`, else a span of zero length.

**Logs:** a bridge for the `mission_control` logger, and structured records with `event.kind`. The
severities map as minor to WARN, major to ERROR and critical to FATAL.

**The robot table:** Mission Control's hook holds one table, keyed by adapter type, that gives
`robot_kind` and `host_kind`:

- `duck-sim` gives `legged`, `pollen-duck-sim`;
- `nxt-web` gives `tracked`, `nxt-brick`;
- `fake` gives `fake`, `fake`.

A TurtleBot adds a row, with no rename.

**Dependencies:** `opentelemetry-sdk` and `opentelemetry-exporter-otlp-proto-http`, both `>=1.45,<2`,
in `apps/mission-control/pyproject.toml` only, with its lock. The tests decode with
`opentelemetry-proto`, which comes with the exporter.

## Tests and the real send

- **A local receiver:** `apps/mission-control/tests/otlp_stub.py`, a stdlib HTTP server that
  decodes with the proto classes. Its modes are ok, 500, hang and refuse.
- **`test_telemetry.py`** checks:
  - the block absent: nothing sent, no threads;
  - names, units, the label set, the span status and the log severities;
  - the must-fail cases, where the run goes on: a closed port with 1000 events and a bounded
    close, a 500, a hang, a bad label value, an SDK that does not import;
  - a TurtleBot row in the table labels the same metrics;
  - no token in the module.
- **`make telemetry-send-check`** sends one metric, span and log with a unique `robot_id` and
  `environment` `check`. It queries VictoriaMetrics, VictoriaLogs and VictoriaTraces until they
  answer, and prints PASS or FAIL per signal. The names it finds fix the dashboard's. It is not in
  CI: it needs the tailnet.

## The dashboard

- **The file:** `dashboards/robotics-lab-live.json`, uid `robotics-lab-live`, with the datasources as
  template variables.
- **The panels:** robots online, lock held, goals active, goals finished by state, goal duration p95,
  anomalies by severity, stops and errors, the anomaly log, recent goal traces.
- **The import:** `scripts/grafana_import.py` (`make grafana-dry`, `make grafana-import`) reads the
  token over ssh and keeps it in memory. It posts to `/api/dashboards/db` into the folder
  `robotics-lab`.

## Retention

The command is `observatory archive [--days N] [--data P] [--archive P] [--robot R] [--apply]`. It is
**a dry run unless `--apply`** is given. It prints per run the key, age, official or not, size, the
decision and the reason.

**What archiving does:** it renames the whole run folder from `data/runs/<robot>/<scene>/<run>` to
`<data>-archive/runs/...`, with the layout kept. It deletes nothing. It appends one line per move to
`<data>-archive/archive-log.jsonl`. It refuses when the archive is inside the data folder, when the
target exists, or when the two are on different filesystems.

**What it keeps:**

- official runs;
- runs younger than N days (by the mtime of `run.mcap`);
- runs still being written (`run.live.mcap`, `writer.lock`);
- anything it cannot read.

**Official runs (to confirm with the operator before any apply):** the run record carries no
marker. The proposal is that a run is official when its record has `judge_truth` or
`judge_profile`, the fields the runner's truth copy writes. How explore runs, NXT recordings and
imported runs fall under this is not verified; the dry run's table shows it.

**The index:** the tool never opens it. The Observatory's follower drops a key whose folder is gone
(`catalog.py:360`, rescan every 2 s), or the next `observatory index` does.

**Not covered:**

- rendered videos and screenshots, which stay and are listed as left behind;
- restore, which is a manual `mv`;
- running it on the real data folder, which is the operator's action.

## Units

| Unit | What | Gate |
| --- | --- | --- |
| U1 | The `telemetry` and `runs` blocks in `runfile.installation`, tests | `make test-libs lint` |
| U2 | `runfile.telemetry`, the deps and lock, the stub, `test_telemetry.py` | `make control-sync lint test-control` |
| U3 | Mission Control's hook and wiring (`core.py:53`, `cli.py`) | `make test-control` |
| U4 | `scripts/telemetry_send_check.py`, the make target | the real send, output in the commit |
| U5 | The dashboard and its importer, its test | the test, `make grafana-dry` |
| U6 | Retention, `observatory archive`, tests | `make test-libs test-observatory lint` |
| U7 | Docs: step 1's item 7 settled, RFC-0023 D7's labels, a recipe | `docs-lint`, strict build |
