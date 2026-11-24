"""The shared fonts (step 4.5, U2): libs/web/fonts has fonts.css, every url() in it is a file that is there, and the licence files are
kept with the fonts. Standard library only.
Run: python3 libs/web/tests/test_fonts.py"""

import re
import sys
from pathlib import Path

FONTS = Path(__file__).resolve().parents[1] / "fonts"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


css = FONTS / "fonts.css"
check("libs/web/fonts/fonts.css exists", css.is_file())
urls = sorted(set(re.findall(r"url\(\s*['\"]?([^'\")\s]+)", css.read_text() if css.is_file() else "")))
check("fonts.css names font files", len(urls) > 0, urls)
for u in urls:
    check(f"url({u}) is a file in the folder", "/" not in u and (FONTS / u).is_file())
families = set(re.findall(r"font-family:\s*'([^']+)'", css.read_text() if css.is_file() else ""))
check("fonts.css declares Inter and JetBrains Mono", {"Inter", "JetBrains Mono"} <= families, sorted(families))
for lic in ("OFL-Inter.txt", "OFL-JetBrainsMono.txt"):
    check(f"the licence {lic} is kept with the fonts", (FONTS / lic).is_file())

print("test_fonts " + ("FAIL " + ", ".join(failures) if failures else "PASS"))
sys.exit(1 if failures else 0)
