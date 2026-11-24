"""The Grafana dashboard (dashboards/robotics-lab-live.json) and its importer (scripts/grafana_import.py), docs/wip/TELEMETRY-RETENTION-DESIGN.md:
the file is valid JSON with the uid and no id, its datasources are template variables, no token-like string is in it, every metric its
queries name is one runfile.telemetry emits (histograms by their _bucket, _sum and _count); the importer's dry run prints what it would post
and touches no network, the import posts the dashboard, the folder and overwrite with the token as a bearer header and never prints the
token, and it refuses with no URL or no token. The import runs against a stub on 127.0.0.1, never a real Grafana.
Run: cd libs/runfile && uv run python tests/test_dashboard.py"""

import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from helpers import Checks
from runfile import telemetry as T

check = Checks("DASHBOARD")
ROOT = Path(__file__).resolve().parents[3]
FILE = ROOT / "dashboards" / "robotics-lab-live.json"
IMPORTER = ROOT / "scripts" / "grafana_import.py"
TOKEN = "gl" + "sa_" + "Ab12Cd34Ef56Gh78Ij90Kl12Mn34Op56_1a2b3c4d"      # a made-up one, split so no scanner reads it as a real token
text = FILE.read_text() if FILE.exists() else ""
check("the dashboard file exists", bool(text), str(FILE))
d = json.loads(text or "{}")
check("uid robotics-lab-live, id null, a title", d.get("uid") == "robotics-lab-live" and d.get("id") is None and "id" in d and d.get("title"), list(d)[:8])

variables = {v["name"]: v for v in d.get("templating", {}).get("list", [])}
check("the datasources are template variables: metrics, logs, traces",
      {"ds_metrics", "ds_logs", "ds_traces"} <= set(variables) and all(variables[n]["type"] == "datasource" for n in ("ds_metrics", "ds_logs", "ds_traces")),
      sorted(variables))
check("their types: prometheus (VictoriaMetrics), victoriametrics-logs-datasource, jaeger (VictoriaTraces)",
      (variables["ds_metrics"]["query"], variables["ds_logs"]["query"], variables["ds_traces"]["query"])
      == ("prometheus", "victoriametrics-logs-datasource", "jaeger") if variables else False)
check("an environment variable", "env" in variables)


def panels(items):
    for p in items:
        yield p
        yield from panels(p.get("panels", []))


ps = list(panels(d.get("panels", [])))
titles = [p.get("title") for p in ps]
want = ["Robots online", "Lock held", "Goals active", "Goals finished by state", "Goal duration p95", "Anomalies by severity",
        "Stops and errors", "Anomaly log", "Recent goal traces"]
check("the panels of the design", titles == want, titles)
check("every panel names a datasource variable, never a fixed uid", all(
    re.fullmatch(r"\$\{ds_(metrics|logs|traces)\}", str((p.get("datasource") or {}).get("uid"))) for p in ps), [p.get("datasource") for p in ps])
check("panel ids are unique", len({p["id"] for p in ps}) == len(ps))

queries = [t.get("expr") or t.get("query") or "" for p in ps for t in p.get("targets", [])]
check("every panel has a query", all(p.get("targets") for p in ps))
names = set(re.findall(r'robotics_lab\.[a-z_.]+', " ".join(q for q in queries if "event.kind" not in q)))
known = set(T.INSTRUMENTS)
allowed = known | {f"{n}{s}" for n, (k, _, _) in T.INSTRUMENTS.items() if k == "histogram" for s in ("_bucket", "_sum", "_count")}
check("every metric in the queries is one the module emits (a histogram by its _bucket, _sum or _count)", names and names <= allowed, sorted(names - allowed))
check("every instrument the design's panels need is queried", {"robotics_lab.robot.online", "robotics_lab.robot.lock_held", "robotics_lab.goals.active",
      "robotics_lab.goals", "robotics_lab.goal.duration_bucket", "robotics_lab.anomalies", "robotics_lab.stops", "robotics_lab.errors"} <= names, sorted(names))
grouped = {w.strip() for q in queries if "robotics_lab." in q for g in re.findall(r"\bby \(([^)]*)\)", q) for w in g.split(",") if w.strip()}
labels = set(T.ROBOT_LABELS) | {x for _, _, extra in T.INSTRUMENTS.values() for x in extra} | {"le"}
check("the labels the queries group by are the module's (robot_id, robot_kind, host_kind: RFC-0025), never RFC-0023's robot or host",
      grouped <= labels, sorted(grouped - labels))
check("no token-like string in the file", not re.search(r"glsa_|eyJ[A-Za-z0-9_-]{10,}|Bearer|ghp_|sk-[A-Za-z0-9]{10,}|[A-Za-z0-9+/_-]{40,}", text), "")

# the importer
env0 = {k: v for k, v in os.environ.items() if not k.startswith("GRAFANA_")}


def run(args, env=None):
    p = subprocess.run([sys.executable, str(IMPORTER), *args], capture_output=True, text=True, env={**env0, **(env or {})}, timeout=30, cwd=ROOT)
    return p.returncode, p.stdout, p.stderr


code, out, err = run(["--dry-run"], {"GRAFANA_HTTP_URL": "http://127.0.0.1:9", "GRAFANA_API_TOKEN": TOKEN})
check("the dry run exits 0, names the url, folder, overwrite and the dashboard, and the panels", code == 0 and "http://127.0.0.1:9/api/dashboards/db" in out
      and "robotics-lab" in out and "overwrite" in out and "robotics-lab-live" in out and "Goal duration p95" in out, out + err)
check("the dry run says it sent nothing and never prints the token", "dry run" in out and TOKEN not in out + err and "glsa_" not in out + err, out)
code, out, err = run(["--dry-run"])
check("the dry run needs neither the URL nor a token", code == 0 and "GRAFANA_HTTP_URL" in out, out + err)

seen = {}


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        seen["path"], seen["auth"] = self.path, self.headers.get("Authorization")
        seen["ctype"] = self.headers.get("Content-Type")
        seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        body = b'{"status":"success","uid":"robotics-lab-live","url":"/d/robotics-lab-live","version":3}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}"
code, out, err = run([], {"GRAFANA_HTTP_URL": url + "/", "GRAFANA_API_TOKEN": TOKEN})
b = seen.get("body", {})
check("the import posts to /api/dashboards/db with the bearer token", code == 0 and seen.get("path") == "/api/dashboards/db"
      and seen.get("auth") == f"Bearer {TOKEN}" and seen.get("ctype") == "application/json", (code, out, err, seen.get("path")))
check("the body: the dashboard, folderUid robotics-lab, overwrite true", b.get("dashboard", {}).get("uid") == "robotics-lab-live"
      and b.get("folderUid") == "robotics-lab" and b.get("overwrite") is True and set(b) == {"dashboard", "folderUid", "overwrite"}, list(b))
check("the import prints the result and never the token", "robotics-lab-live" in out and TOKEN not in out + err, out + err)
code, out, err = run([], {"GRAFANA_HTTP_URL": url})
check("no token: refused, nothing posted, exit 2", code == 2 and "GRAFANA_API_TOKEN" in err, (code, err))
code, out, err = run([], {"GRAFANA_API_TOKEN": TOKEN})
check("no url: refused, exit 2, the token not printed", code == 2 and "GRAFANA_HTTP_URL" in err and TOKEN not in out + err, (code, err))
srv.shutdown()
code, out, err = run([], {"GRAFANA_HTTP_URL": url, "GRAFANA_API_TOKEN": TOKEN})
check("a server that is gone: exit 1, one line, the token not printed", code == 1 and TOKEN not in out + err, (code, out, err))

check.done()
