"""The shared web library (RFC-0024 step 1, tokens v2 of ADR-0021): the design tokens are one file and no app declares them again, the
themes and the density and motion pairs have the same keys, no page or script uses a token name of before tokens v2, there is no literal colour outside the token file, the colours meet
their contrast and colour-blind limits, every page loads the file, and there is one copy of three.js. Standard library only.
Run: python3 libs/web/tests/test_tokens.py"""

import itertools
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from colorlib import DEUTAN, PROTAN, contrast, delta_e, oklab, parse, simulate  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "libs" / "web"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def strip(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def block(text: str, opening: str) -> str:
    i = text.index(opening) + len(opening)
    depth, j = 1, i
    while depth:
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        j += 1
    return text[i:j - 1]


def decls(body: str) -> dict:
    return {k: re.sub(r"\s+", " ", v.strip()) for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)}


def try_block(text: str, opening: str) -> str:
    return block(text, opening) if opening in text else ""


css = strip((LIB / "tokens.css").read_text())
first = decls(block(css, ":root {"))
light = decls(block(css, ':root[data-theme="light"] {'))
media = decls(block(css, ':root:not([data-theme="dark"]) {'))
compact = decls(try_block(css, ':root[data-density="compact"] {'))
regular = decls(try_block(css, ':root[data-density="regular"] {'))
reduce_media = decls(try_block(try_block(css, "@media (prefers-reduced-motion: reduce) {"), ':root:not([data-motion="full"]) {'))
reduce_attr = decls(try_block(css, ':root[data-motion="reduce"] {'))
phone = decls(try_block(try_block(css, "@media (max-width: 700px) {"), ":root {"))

ALIAS = re.compile(r"var\((--[\w-]+)\)")
INVARIANT = re.compile(r"--(font-(ui|mono|num)|fs-[1-5]|lh-(tight|body)|sp-[1-8]|radius-([1-3]|pill)|elev-[0-3]|z-(base|sticky|popover|drawer|palette|toast|stop)"
                       r"|dur-(fast|base|slow)|ease|ctl-h-touch|tap-min|stop-h)")
DENSITY = {"--ctl-h", "--fs-base", "--pad"}
MOTION = {"--dur-fast", "--dur-base", "--dur-slow", "--ease"}
invariants = {k for k in first if INVARIANT.fullmatch(k)}

# the frozen contract (docs/wip/LOOK-AND-FEEL-PLAN.md, "Frozen contracts > Tokens"); neutral is the ninth status of status.js, offline the tenth (review round 1)
STATUSES = ["ok", "info", "warn", "alert", "error", "unknown", "stale", "neutral", "live", "offline"]
THEMED = (
    ["surface-" + n for n in ("0", "1", "2", "3", "field", "hover", "press", "selected", "section", "section-hover", "tip")]
    + ["line-" + n for n in ("subtle", "strong", "hover", "focus")] + ["line"]
    + [f"hairline-{i}" for i in range(1, 6)] + ["veil-1", "veil-2", "veil-scrim", "elev-shadow"]
    + ["text-1", "text-2", "text-3", "text-on-solid", "text-on-light"]
    + ["accent", "accent-soft", "accent-ring", "accent-text", "accent-on", "accent-hover", "danger-solid"]
    + [f"status-{s}{x}" for s in STATUSES for x in ("", "-soft", "-on")]
    + ["data-" + n for n in ("belief", "truth", "plan", "obstacle", "drop", "floor", "depth-obstacle", "depth-overhead", "box", "occupied", "free", "gap", "object", "landmark", "seen", "wedge", "area")]
    + ["axis-x", "axis-y", "axis-z"] + ["hud-" + n for n in ("bg", "line", "text", "key", "value", "warn")]
    + ["scene-" + n for n in ("bg", "floor", "grid", "grid-major", "label", "rel", "select", "box-fill", "gap-hatch", "sky", "ground", "sun", "shadow", "sky-k", "sun-k")]
    + [f"ramp-seq-{i}" for i in range(1, 10)] + [f"ramp-div-{i}" for i in range(1, 10)] + [f"ramp-cat-{i}" for i in range(1, 9)]
    + ["control-track", "control-knob", "control-border"]
)
THEMED = ["--" + n for n in THEMED]

# ---- the three theme blocks, the density pair, the motion pair ----
check("the tokens have a dark set, a light set and the light set again for a page with no theme chosen", bool(first) and bool(light) and bool(media))
check("the light set in the media query is the light set (same names, same values)", media == light, sorted(set(media.items()) ^ set(light.items()))[:4])
check("every token the light set changes the dark set has", set(light) <= set(first), sorted(set(light) - set(first)))
dark_themed = set(first) - invariants - DENSITY
check("dark and light have the same keys (the first block also holds the invariants and the density default)",
      dark_themed == set(light), {"dark_only": sorted(dark_themed - set(light))[:6], "light_only": sorted(set(light) - dark_themed)[:6]})
check("every token of the contract is in dark and light", all(t in dark_themed and t in light for t in THEMED), [t for t in THEMED if t not in light][:8])
check("the invariants are in the first block only (not in light, the media block, or a density block)",
      not (invariants & (set(light) | set(media) | set(compact) | set(regular))), sorted(invariants & (set(light) | set(compact) | set(regular))))
check("the invariants of the contract are all declared (fonts, type, space, radius, elevation, z, motion, controls)",
      len(invariants) >= 3 + 5 + 2 + 8 + 4 + 4 + 7 + 3 + 3 and {"--z-stop", "--dur-fast", "--ease", "--stop-h", "--tap-min", "--ctl-h-touch", "--radius-pill"} <= invariants, len(invariants))
check("the density blocks (compact, regular) have the same keys, and the first block has the default", compact and set(compact) == set(regular) == DENSITY and DENSITY <= set(first), [sorted(compact), sorted(regular)])
check("the two reduced-motion blocks have the same keys and the same values", reduce_media and reduce_media == reduce_attr, [reduce_media, reduce_attr])
check("the reduced-motion blocks cover the motion tokens, and every duration is 0", set(reduce_media) == MOTION and all(reduce_media[k] in ("0ms", "0s") for k in MOTION if k.startswith("--dur")), reduce_media)
check("the only other override of an invariant is --stop-h on a phone, 56px (the first block says 40px)",
      set(phone) == {"--stop-h"} and phone["--stop-h"] == "56px" and first.get("--stop-h") == "40px", phone)
check("the scale tokens are the contract's (type 11/12/14/16/20, space 4..40, radius 2/4/8, z-stop the highest)",
      [first[f"--fs-{i}"] for i in range(1, 6)] == ["11px", "12px", "14px", "16px", "20px"]
      and [first[f"--sp-{i}"] for i in range(1, 9)] == ["4px", "8px", "12px", "16px", "20px", "24px", "32px", "40px"]
      and [first[f"--radius-{i}"] for i in range(1, 4)] == ["2px", "4px", "8px"]
      and first["--ctl-h-touch"] == "56px" and first["--tap-min"] == "44px"
      and compact["--ctl-h"] == "24px" and regular["--ctl-h"] == "36px"
      and first["--z-stop"] and all(int(first["--z-stop"]) > int(first[f"--z-{n}"]) for n in ("base", "sticky", "popover", "drawer", "palette", "toast")))
zs = [int(first[f"--z-{n}"]) for n in ("base", "sticky", "popover", "drawer", "palette", "toast", "stop")]
check("the z scale rises in the contract's order", zs == sorted(zs) and len(set(zs)) == 7, zs)


# ---- the resolved values of a theme (the first block is the dark set; a token is never another token's alias) ----
R = {"dark": dict(first), "light": {**first, **light}}
check("no token is an alias of another (a value is a value; the invariants hold var() only inside a longer value)", not [k for k, v in first.items() if ALIAS.fullmatch(v)], [k for k, v in first.items() if ALIAS.fullmatch(v)])
# a value pinned on purpose: round 2 made the dark floor grid brighter, and the 2D views read the same token
check("the dark grid is the round-2 value", R["dark"]["--scene-grid"] == "#3a3d45", R["dark"]["--scene-grid"])
check("the two inks for a canvas cell are white and black in both themes (the pin texture and the heat-map text rely on it)",
      all(R[t]["--text-on-solid"] == "#ffffff" and R[t]["--text-on-light"] == "#000000" for t in R), [(R[t]["--text-on-solid"], R[t]["--text-on-light"]) for t in R])


def rgb_of(theme, name):
    c = parse(R[theme][name])
    return c[:3], c[3]


SURF = ["--surface-0", "--surface-1", "--surface-2", "--surface-3", "--surface-field"]
for th in ("dark", "light"):
    check(f"{th}: the surfaces are opaque", all(rgb_of(th, s)[1] == 1 for s in SURF))

    def worst(fg, bgs=SURF):
        return min((contrast(rgb_of(th, fg)[0], rgb_of(th, b)[0]), b) for b in bgs)
    for tok, need in (("--text-1", 4.5), ("--text-2", 4.5), ("--text-3", 3.0)):
        w = worst(tok)
        check(f"{th}: {tok} reaches {need}:1 on surface-0..3 and the field", w[0] >= need, f"{w[0]:.2f} on {w[1]}")
    for tok in ("--control-border", "--control-knob", "--line-focus"):
        w = worst(tok)
        check(f"{th}: {tok} (a UI boundary) reaches 3:1 on surface-0..3 and the field", w[0] >= 3.0, f"{w[0]:.2f} on {w[1]}")
    w = (contrast(rgb_of(th, "--text-on-solid")[0], rgb_of(th, "--danger-solid")[0]))
    check(f"{th}: the text on the STOP colour reaches 4.5:1", w >= 4.5, f"{w:.2f}")
    low = []
    for s in STATUSES:
        soft = rgb_of(th, f"--status-{s}-soft")
        r = contrast(rgb_of(th, f"--status-{s}-on")[0], soft[0])
        if soft[1] != 1 or r < 4.5:
            low.append((s, round(r, 2)))
    check(f"{th}: every status -on reaches 4.5:1 on its opaque -soft", not low, low)
    for fg, bg in (("--accent-on", "--accent"), ("--accent-on", "--accent-hover")):
        c = contrast(rgb_of(th, fg)[0], rgb_of(th, bg)[0])
        check(f"{th}: the text of a solid primary button ({fg} on {bg}) reaches 4.5:1", c >= 4.5, f"{c:.2f}")
    off = rgb_of(th, "--status-offline")[0]
    near = {s: round(delta_e(off, rgb_of(th, f"--status-{s}")[0]), 3) for s in ("unknown", "neutral")}
    check(f"{th}: offline is grey like unknown and neutral, at least 0.05 from both in OKLab (the glyph and the word do the rest)", min(near.values()) >= 0.05, near)
    check(f"{th}: any two status colours are at least 0.03 apart in OKLab (the rest is the glyph and the word)",
          all(delta_e(rgb_of(th, f"--status-{a}")[0], rgb_of(th, f"--status-{b}")[0]) >= 0.03
              for a, b in itertools.combinations(STATUSES, 2)), "")

# ---- live (yellow) against warn (amber) ----
LIVE_WARN_MIN = 0.08   # OKLab units; about 4 just-noticeable differences, for the normal eye and for both simulations


def hue(rgb):
    _, a, b = oklab(rgb)
    return math.degrees(math.atan2(b, a)) % 360


for th in ("dark", "light"):
    live, warn = rgb_of(th, "--status-live")[0], rgb_of(th, "--status-warn")[0]
    d = {"normal": delta_e(live, warn), "deutan": delta_e(simulate(live, DEUTAN), simulate(warn, DEUTAN)), "protan": delta_e(simulate(live, PROTAN), simulate(warn, PROTAN))}
    check(f"{th}: live is yellow and warn is amber (hue in OKLCH 90..110 and 55..85 degrees)", 90 <= hue(live) <= 110 and 55 <= hue(warn) <= 85, f"live {hue(live):.0f}, warn {hue(warn):.0f}")
    check(f"{th}: live and warn are at least {LIVE_WARN_MIN} apart in OKLab, normal and under both simulations", min(d.values()) >= LIVE_WARN_MIN, {k: round(v, 3) for k, v in d.items()})

# ---- the ramps ----
SEQ_CVD_MIN = 0.04     # adjacent steps under deuteranopia or protanopia (about 2 just-noticeable differences)
CAT_MIN, CAT_CVD_MIN = 0.09, 0.07   # any two of the 8 categories: normal, and under either simulation


def ramp(th, kind, n):
    return [rgb_of(th, f"--ramp-{kind}-{i}")[0] for i in range(1, n + 1)]


def steps(rgbs, m=None):
    s = rgbs if m is None else [simulate(r, m) for r in rgbs]
    return [delta_e(s[i], s[i + 1]) for i in range(len(s) - 1)]


for th in ("dark", "light"):
    for kind in ("seq", "div"):
        rs = ramp(th, kind, 9)
        Ls = [oklab(r)[0] for r in rs]
        d = steps(rs)
        mean = sum(d) / len(d)
        if kind == "seq":
            check(f"{th}: ramp-seq lightness is monotonic in OKLab", all(b > a for a, b in zip(Ls, Ls[1:])) or all(b < a for a, b in zip(Ls, Ls[1:])), [round(x, 3) for x in Ls])
        else:
            c5 = math.hypot(*oklab(rs[4])[1:])
            arms = [hue(rs[0]), hue(rs[8])]
            check(f"{th}: ramp-div has a neutral middle, lightness monotonic away from it on both arms, and blue and orange ends (not red and green)",
                  c5 <= 0.02 and (all(Ls[i] > Ls[i + 1] for i in range(4)) and all(Ls[i] < Ls[i + 1] for i in range(4, 8)) or all(Ls[i] < Ls[i + 1] for i in range(4)) and all(Ls[i] > Ls[i + 1] for i in range(4, 8)))
                  and 220 <= arms[0] <= 280 and 40 <= arms[1] <= 80, {"mid chroma": round(c5, 3), "end hues": [round(x) for x in arms]})
        check(f"{th}: ramp-{kind} steps are uniform in OKLab (each within 25% of the mean {mean:.3f})", all(abs(x - mean) <= 0.25 * mean for x in d), [round(x, 3) for x in d])
        cv = {"deutan": min(steps(rs, DEUTAN)), "protan": min(steps(rs, PROTAN))}
        check(f"{th}: ramp-{kind} adjacent steps stay {SEQ_CVD_MIN} apart under deuteranopia and protanopia", min(cv.values()) >= SEQ_CVD_MIN, {k: round(v, 3) for k, v in cv.items()})
    cs = ramp(th, "cat", 8)
    worst_pair = {}
    for nm, m in (("normal", None), ("deutan", DEUTAN), ("protan", PROTAN)):
        s = cs if m is None else [simulate(c, m) for c in cs]
        worst_pair[nm] = min(delta_e(a, b) for a, b in itertools.combinations(s, 2))
    check(f"{th}: ramp-cat, any two of the 8 are {CAT_MIN} apart (normal) and {CAT_CVD_MIN} apart under either simulation",
          worst_pair["normal"] >= CAT_MIN and min(worst_pair["deutan"], worst_pair["protan"]) >= CAT_CVD_MIN, {k: round(v, 3) for k, v in worst_pair.items()})

# ---- the scene differs between the themes where it must ----
check("the scene's lights and background differ between light and dark", all(light[k] != first[k] for k in ("--scene-bg", "--scene-sky-k", "--scene-sun-k", "--scene-sky", "--scene-sun", "--scene-shadow")), "")
check("the scene's lights are numbers", all(re.fullmatch(r"\d*\.?\d+", v) for v in (first["--scene-sky-k"], first["--scene-sun-k"], light["--scene-sky-k"], light["--scene-sun-k"])))
check("the major grid line is stronger than the grid in both themes", all(contrast(parse(t["--scene-grid-major"])[:3], parse(t["--scene-floor"])[:3]) > contrast(parse(t["--scene-grid"])[:3], parse(t["--scene-floor"])[:3]) for t in (first, light)))
check("the status and the data are not the same token (data colours are never a status)", not any(first[f"--data-{d}"] == first[f"--status-{s}"] for d in ("belief", "truth", "plan", "obstacle") for s in STATUSES if s != "unknown"))

# ---- no app declares a token again; no hex in an app stylesheet ----
SHEETS = [ROOT / "apps" / "mission-control" / "src" / "mission_control" / "web" / "style.css",
          *sorted((ROOT / "apps" / "observatory" / "web").rglob("*.css"))]
redeclared = {}
for sheet in SHEETS:
    own = set(decls(strip(sheet.read_text()))) & (set(first) | set(light) | set(compact) | MOTION)
    if own:
        redeclared[str(sheet.relative_to(ROOT))] = sorted(own)
check("no app stylesheet declares a token again (the values live in libs/web/tokens.css only)", not redeclared, redeclared)

# No literal colour outside tokens.css (U26 took the allowlist to zero): a #hex, a 0xRRGGBB, or an rgb()/rgba()/hsl() with a number in it, in the
# stylesheets, scripts and pages of both apps and of libs/web. A colour a script needs is read from a token (getComputedStyle). Not scanned:
# the vendored libraries, the font files, the standalone mockup/ and proto/ pages (they declare their own variables and load no token file),
# and the tests. The cap per file is 0 for every file; a file may not be added here.
HEX_ALLOWED: dict = {}
WEB_DIRS = [ROOT / "apps" / "mission-control" / "src" / "mission_control" / "web", ROOT / "apps" / "observatory" / "web", LIB]
SKIP_DIRS = {"vendor", "fonts", "mockup", "proto", "tests", "__pycache__"}
CODE = [p for base in WEB_DIRS for p in sorted(base.rglob("*"))
        if p.is_file() and p.suffix in (".css", ".js", ".html") and not (set(p.relative_to(base).parts[:-1]) & SKIP_DIRS) and p != LIB / "tokens.css"]
LITERAL = re.compile(r"(?<![\w&-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])|\b0x[0-9a-fA-F]{6}\b|\b(?:rgba?|hsla?)\(\s*[\d.]")


def code_only(text: str) -> str:
    text = re.sub(r"/\*.*?\*/|<!--.*?-->", "", text, flags=re.S)
    return re.sub(r"(?m)(^|\s)//[^\n]*", r"\1", text)


literals = {}
for f in CODE:
    found = LITERAL.findall(code_only(f.read_text()))
    if len(found) > HEX_ALLOWED.get(str(f.relative_to(ROOT)), 0):
        literals[str(f.relative_to(ROOT))] = found[:6]
check("no literal colour (hex, 0x, rgb(), hsl()) in the apps' web code or libs/web outside tokens.css; the allowlist is empty", not literals and not HEX_ALLOWED, literals)
check("the colour check scans the pages it should (both apps' scripts and stylesheets, libs/web)", len(CODE) >= 40 and any(p.name == "shell.js" for p in CODE) and any(p.name == "app.js" for p in CODE) and any(p.name == "stage.js" for p in CODE), len(CODE))

# The names tokens v2 replaced (U26 removed the aliases): none may be used in the same files, as var(--old), as '--old' or, for the longer ones, as a bare 'old'
LEGACY = ("bg-app bg-viewport bg-panel bg-header bg-field bg-hover bg-selected bg-shead bg-shead-hover bg-press border border-strong border-hover text text-dim text-faint "
          "on-accent ok warn error hair hair-2 hair-3 hair-4 hair-5 veil shadow scrim tip-bg range-bar range-knob check-border box-fill gap-hatch ui mono "
          "c-belief c-truth c-plan c-obst c-drop c-floor c-ob c-over c-box c-occ c-free c-x c-y c-z c-gap draw-grid draw-label draw-rel draw-sel").split()
OLD_VAR = re.compile(r"(?<![\w-])--(" + "|".join(sorted(map(re.escape, LEGACY), key=len, reverse=True)) + r")(?![\w-])")
# a bare name is only checked where it cannot be a word or another token's tail (the stage reads 'box-fill' as --scene-box-fill)
BARE = [n for n in LEGACY if re.fullmatch(r"(bg-\w+(-hover)?|border-\w+|text-(dim|faint)|on-accent|tip-bg|range-\w+|check-border|c-\w+|draw-\w+)", n)]
OLD_BARE = re.compile(r"""(?<=['"`])(""" + "|".join(sorted(map(re.escape, BARE), key=len, reverse=True)) + r""")(?=['"`])""")
legacy_uses = {}
for f in CODE:
    text = code_only(f.read_text())
    hits = [m.group(0) for m in OLD_VAR.finditer(text)] + OLD_BARE.findall(text)
    if hits:
        legacy_uses[str(f.relative_to(ROOT))] = hits[:6]
check("no page or script uses a token name from before tokens v2 (--bg-*, --border, --text-dim, --c-*, --draw-*, --ok/--warn/--error ...)", not legacy_uses, legacy_uses)
declared = set(first) | set(light)
check("none of those names is declared in tokens.css either", not [n for n in LEGACY if "--" + n in declared], [n for n in LEGACY if "--" + n in declared])

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
