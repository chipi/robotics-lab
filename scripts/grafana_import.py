"""Import dashboards/robotics-lab-live.json into the operator's Grafana (docs/wip/TELEMETRY-RETENTION-DESIGN.md).

    make grafana-dry      what would be posted; no network, no token needed
    make grafana-import   POST $GRAFANA_HTTP_URL/api/dashboards/db

The URL and the token come from the environment only (GRAFANA_HTTP_URL, GRAFANA_API_TOKEN): never an argument, never a file here, never
printed. The folder `robotics-lab` (uid robotics-lab) must exist; the dashboard's uid is fixed, so an import again replaces it
(overwrite). Standard library only."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "dashboards" / "robotics-lab-live.json"
FOLDER = "robotics-lab"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print what would be posted and stop: no network")
    ap.add_argument("--file", type=Path, default=FILE)
    args = ap.parse_args()

    try:
        dashboard = json.loads(args.file.read_text())
    except (OSError, ValueError) as e:
        print(f"grafana-import: {args.file}: {e}", file=sys.stderr)
        return 2
    payload = {"dashboard": dashboard, "folderUid": FOLDER, "overwrite": True}
    base = (os.environ.get("GRAFANA_HTTP_URL") or "").rstrip("/")
    token = os.environ.get("GRAFANA_API_TOKEN") or ""
    url = f"{base or '$GRAFANA_HTTP_URL'}/api/dashboards/db"

    if args.dry_run:
        print(f"dry run: nothing is sent. Would POST {url}")
        print(f"  header Authorization: Bearer <$GRAFANA_API_TOKEN, {'set' if token else 'not set'}>")
        print(f"  folderUid {FOLDER}, overwrite true, dashboard uid {dashboard.get('uid')}: {dashboard.get('title')}")
        for p in dashboard.get("panels", []):
            print(f"  panel {p.get('title')} ({p.get('type')})")
            for t in p.get("targets", []):
                print(f"    {t.get('expr') or t.get('query') or t}")
        print(f"  body: {len(json.dumps(payload))} bytes")
        return 0
    if not base:
        print("grafana-import: set GRAFANA_HTTP_URL (the Grafana's address)", file=sys.stderr)
        return 2
    if not token:
        print("grafana-import: set GRAFANA_API_TOKEN (a service-account token that can write dashboards)", file=sys.stderr)
        return 2
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            reply = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print(f"grafana-import: {url}: HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"grafana-import: {url}: {type(e).__name__}: {e}".replace(token, "<token>"), file=sys.stderr)
        return 1
    print(f"imported dashboard {dashboard.get('uid')} into folder {FOLDER}: {reply[:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
