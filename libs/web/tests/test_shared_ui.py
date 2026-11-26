"""The UI pieces both apps share live in libs/web and not in either app (look-and-feel U26): the Layout menu (layout/menu.js and menu.css) and the
opening of the command palette (lazy.js). Neither app builds a menu or loads the palette by itself. Standard library only.
Run: python3 libs/web/tests/test_shared_ui.py"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "libs" / "web"
MC = ROOT / "apps" / "mission-control" / "src" / "mission_control" / "web"
OBS = ROOT / "apps" / "observatory" / "web" / "shell"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


layouts = {"Mission Control": MC / "layout.js", "Observatory": OBS / "layout.js"}
for app, f in layouts.items():
    src = f.read_text()
    check(f"{app}: layout.js builds its menu with the shared createLayoutMenu", "createLayoutMenu" in src and "/lib/layout/menu.js" in src)
    check(f"{app}: layout.js builds no menu elements of its own", not re.search(r"createElement|class: 'laymenu'|'lay-save'|'lay-list'", src), "")

for app, f in {"Mission Control": MC / "style.css", "Observatory": OBS / "shell.css"}.items():
    css = f.read_text()
    own = sorted(set(re.findall(r"^\.(layhead|laygroup|layrow|layline)\b", css, re.M)))
    check(f"{app}: the stylesheet has no rule of the Layout menu's inside (menu.css has them); only where the menu sits and its buttons", not own, own)

menu_css = (LIB / "layout" / "menu.css").read_text()
check("menu.css has the menu's rules", all(f".{c}" in menu_css for c in ("layhead", "laygroup", "layrow", "layline")))
check("menu.js links menu.css itself", "needSheet(import.meta.url, './menu.css')" in (LIB / "layout" / "menu.js").read_text())

lazy = (LIB / "lazy.js").read_text()
check("lazy.js has no import (a page may load it at start) and no 'palette' in its file name", not re.search(r"^import ", lazy, re.M) and "palette" not in "lazy.js")
for app, f in {"Mission Control": MC / "app.js", "Observatory": OBS / "shell.js"}.items():
    src = f.read_text()
    check(f"{app}: the palette is opened through lazyOpen; the page keeps no loader or key guard of its own",
          "lazyOpen" in src and "paletteBusy" not in src and "ev.key.toLowerCase() !== 'k'" not in src and 'ev.key.toLowerCase() !== "k"' not in src)

print("WEB SHARED UI", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
