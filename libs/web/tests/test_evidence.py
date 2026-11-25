"""The shared evidence-link format (step 4.5, U24): the link builder and parser live once, in libs/web/evidence.js, and the Observatory's
shell module re-exports them rather than holding a second copy. The behaviour of the functions is checked in a browser by the apps' page tests
(Mission Control's test_look_page.py imports /lib/evidence.js; the Observatory's test_look_evidence_pages.py uses its shell). Standard library only.
Run: python3 libs/web/tests/test_evidence.py"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "libs" / "web" / "evidence.js"
SHELL = ROOT / "apps" / "observatory" / "web" / "shell" / "evidence.js"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


lib = LIB.read_text() if LIB.is_file() else ""
shell = SHELL.read_text()
check("libs/web/evidence.js exists", LIB.is_file())
exports = set(re.findall(r"export (?:async )?(?:function|const) (\w+)", lib))
check("it exports the builder, the parser, the focus list and copyText", {"momentLink", "parseMoment", "FOCUS", "copyText", "evidenceHref"} <= exports, sorted(exports))
check("it is pure: no import, no fetch, no storage, no document", not re.search(r"^import |fetch\(|localStorage|document\.", lib, re.M))
check("the Observatory's shell module re-exports it and holds no format of its own",
      "/lib/evidence.js" in shell and "URLSearchParams" not in shell and "export function momentLink" not in shell, shell[:200])
check("the Observatory still exports the four names its shell and test use",
      all(re.search(rf"\b{n}\b", shell) for n in ("FOCUS", "parseMoment", "momentLink", "copyText")))
print("test_evidence " + ("FAIL " + ", ".join(failures) if failures else "PASS"))
sys.exit(1 if failures else 0)
