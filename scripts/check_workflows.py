"""Parse every GitHub workflow as YAML and check its step names are strings, before CI sees it.

A workflow GitHub cannot parse fails with no job at all ("a workflow file issue"); on 2026-11-15
an unquoted step name with ": " in it did exactly that. Run by `make lint`."""
import sys
from pathlib import Path

import yaml

ok = True
for f in sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.y*ml")):
    try:
        doc = yaml.safe_load(f.read_text())
    except yaml.YAMLError as e:
        print(f"FAIL {f.name}: {e}")
        ok = False
        continue
    for job, spec in (doc.get("jobs") or {}).items():
        for step in spec.get("steps", []):
            if "name" in step and not isinstance(step["name"], str):
                print(f"FAIL {f.name}: job {job}: a step name is not text: {step['name']!r}")
                ok = False
print("workflows", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
