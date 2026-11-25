# Telemetry: turning it on, checking it, the dashboard

Mission Control sends metrics, traces and logs to the operator's Victoria stack over OpenTelemetry
(OTLP/HTTP, protobuf, no token: the stack is reached over the tailnet). What it sends and why is in
[TELEMETRY-RETENTION-DESIGN.md](TELEMETRY-RETENTION-DESIGN.md); this page is how to use it.

## Turn it on

Add a `telemetry` block to the machine's installation file
(`~/.config/robotics-lab/installation.json`, or the file `$ROBOTICS_LAB_INSTALLATION` names), next
to the keys that are already there:

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

- No block, or no installation file: telemetry is off, nothing starts, nothing is sent.
- `environment` is required: any slug matching `^[a-z0-9_-]+$` (checked in
  `libs/runfile/src/runfile/installation.py`). Use `dev` for the simulator on the workstation;
  the operator chose `staging` for the X3 stack ([the handover](HANDOVER.md), decisions).
  At least one signal URL is required; leave one out and that signal is off.
- A bad block (an empty one, an unknown key) is reported with one line on start, and Mission
  Control runs without telemetry.
- **A change needs a Mission Control restart.** The file is read once, at start.
- The robot's labels are `robot_id` (the robot file's id), `robot_kind` and `host_kind`
  (RFC-0025). Mission Control's table maps the adapter type to them: `duck-sim` is
  `legged`/`pollen-duck-sim`, `duck-real` is `legged`/`microduck`, `nxt-web` is
  `tracked`/`nxt-brick`, `fake` is `fake`/`fake`; any other adapter is `unknown`. A new robot adds a
  row in `apps/mission-control/src/mission_control/telemetry.py`.

## Check the send

```sh
make telemetry-send-check
```

It sends one metric, one span and one log (`robot_id` `telemetry-check-<8 hex>`, environment
`check`, service `robotics-lab-telemetry-check`) to the three endpoints above, then asks the
stack's own query APIs for them for up to 60 s. It prints PASS or FAIL per signal with a fragment of
the answer, and ends with `EXIT=0` when all three arrived. It needs the tailnet, so it is not in CI.

How VictoriaMetrics stores the names (found by that check): with the dots kept and no `_total`, so a
query names them in a selector: `{__name__="robotics_lab.goals"}`. A histogram arrives as
`robotics_lab.goal.duration_bucket`, `_sum` and `_count`. The resource attributes are labels too
(`deployment.environment.name`, `service.name`). In VictoriaLogs the fields are `robot_id`,
`event.kind`, `severity_text` and the resource attributes; in VictoriaTraces the service is
`robotics-lab-mission-control` and a goal's span is `goal.run`.

## The dashboard

`dashboards/robotics-lab-live.json` (uid `robotics-lab-live`, "Robotics Lab — Live"), in rows by
subject: Robots (online, lock held), Goals (active, finished by state, duration p95), Anomalies and
stops (by severity, by kind, stops and errors), Logs (Mission Control's VictoriaLogs records) and
Traces (recent `goal.run`). Following the homelab's Grafana conventions, every panel names its
datasource literally (VictoriaMetrics `victoriametrics`, VictoriaLogs `victorialogs`, VictoriaTraces
`victoriatraces-jaeger`) and the template variables are filters only: `environment` (default `dev`,
`check` excluded), `robot_id` (multi, All) and a log search box (LogsQL).

```sh
make grafana-dry
GRAFANA_HTTP_URL=https://grafana.tail6d0ed4.ts.net GRAFANA_API_TOKEN=... make grafana-import
```

- `grafana-dry` prints what would be posted and sends nothing; it needs no token.
- `grafana-import` posts to `$GRAFANA_HTTP_URL/api/dashboards/db` into the folder `robotics-lab`
  (it must exist) with `overwrite`, so running it again replaces the dashboard. The URL and the
  token are read from the environment only, and the token is never printed.
- **Imported:** 5f2449f imported it (`robotics-lab-live`, folder `robotics-lab`, version 1).
- **Not verified:** how Grafana renders the panels and variables. The commit records that the
  queries return the send check's data, not that the panels render. Check the panels in
  Grafana. The p95 panel reads the SDK's default bucket bounds (0, 5, 10, 25, 50 s and up), so it is
  coarse for short goals.

## Old runs

Retention is a separate command: `observatory archive` (a dry run unless `--apply`); see the
design's Retention section.
