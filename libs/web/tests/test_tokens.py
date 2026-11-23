"""The shared web library (RFC-0024 step 1): the design tokens are one file and no app declares them again, the light set is the same in
its two blocks, every page loads the file, and there is one copy of three.js. Standard library only.
Run: python3 libs/web/tests/test_tokens.py"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "libs" / "web"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def block(text: str, opening: str) -> str:
    i = text.index(opening) + len(opening)
    depth, j = 1, i
    while depth:
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        j += 1
    return text[i:j - 1]


def decls(body: str) -> dict:
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))


css = (LIB / "tokens.css").read_text()
dark = decls(block(css, ":root {"))
light = decls(block(css, ':root[data-theme="light"] {'))
media = decls(block(css, ':root:not([data-theme="dark"]) {'))
check("the tokens have a dark set, a light set and the light set again for a page with no theme chosen", bool(dark) and bool(light) and bool(media))
check("the light set in the media query is the light set (same names, same values)", media == light, sorted(set(media.items()) ^ set(light.items()))[:4])
check("every token the light set changes the dark set has", set(light) <= set(dark), sorted(set(light) - set(dark)))
check("the status colours the body uses are in both sets", {"--ok", "--warn", "--error"} <= set(light) and {"--ok", "--warn", "--error"} <= set(dark))
check("the warn and the error colours differ from each other in both themes", dark["--warn"] != dark["--error"] and light["--warn"] != light["--error"])

SHEETS = [ROOT / "apps" / "mission-control" / "src" / "mission_control" / "web" / "style.css",
          *sorted((ROOT / "apps" / "observatory" / "web").rglob("*.css"))]
redeclared = {}
for sheet in SHEETS:
    own = set(decls(re.sub(r"/\*.*?\*/", "", sheet.read_text(), flags=re.S))) & set(dark)
    if own:
        redeclared[str(sheet.relative_to(ROOT))] = sorted(own)
check("no app stylesheet declares a token again (the values live in libs/web/tokens.css only)", not redeclared, redeclared)

PAGES = [ROOT / "apps" / "mission-control" / "src" / "mission_control" / "web" / "index.html", *(ROOT / "apps" / "observatory" / "web" / p for p in ("three/index.html", "three/watch.html", "deck/index.html"))]
check("every page that uses the tokens loads them from /lib/tokens.css, before its own stylesheet",
      all(re.search(r'href="/lib/tokens\.css".*?href="[^"]*(?:style|shell)\.css"', p.read_text(), re.S) for p in PAGES), [p.name for p in PAGES if "/lib/tokens.css" not in p.read_text()])

copies = []
for dirpath, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in (".git", ".venv", "node_modules", "site", "__pycache__")]
    copies += [str(Path(dirpath, f).relative_to(ROOT)) for f in files if f == "three.module.js"]
check("there is one copy of three.js, in libs/web/vendor", copies == ["libs/web/vendor/three.module.js"], copies)
imports = [p for p in PAGES if '"three": "/lib/vendor/three.module.js"' not in p.read_text() and "import" in p.read_text() and "importmap" in p.read_text()]
check("every page's import map points three at /lib/vendor", not imports, [p.name for p in imports])

print("WEB TOKENS", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
