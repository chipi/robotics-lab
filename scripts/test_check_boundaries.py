"""Self-test of scripts/check_boundaries.py: a forbidden import fails, an allowed one passes, an exception and a stale
baseline entry behave as documented, and a path source is held to the table. Run by `make lint`.

    python3 scripts/test_check_boundaries.py"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_boundaries as cb  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def project(root: Path, where: str, package: str, files: dict, sources: str = ""):
    """A project at root/where with src/<package>/ holding `files` ({relative path: text}), and a tests/ folder for the keys
    starting with tests/."""
    p = root / where
    (p / "src" / package).mkdir(parents=True)
    (p / "src" / package / "__init__.py").write_text("")
    (p / "pyproject.toml").write_text(f'[project]\nname = "{package}"\n{sources}')
    for rel, text in files.items():
        f = p / ("src/" + package + "/" + rel if not rel.startswith("tests/") else rel)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)


def run(build, baseline=None, exceptions=None) -> list:
    saved = cb.BASELINE, cb.EXCEPTIONS
    cb.BASELINE = {} if baseline is None else baseline
    cb.EXCEPTIONS = {} if exceptions is None else exceptions
    try:
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp))
            return cb.check(Path(tmp))
    finally:
        cb.BASELINE, cb.EXCEPTIONS = saved


# an allowed import: the Observatory reads the run format; the duck reads the format, the gate and the world model
got = run(lambda r: (project(r, "libs/runfile", "runfile", {"keys.py": "X = 1\n"}),
                     project(r, "apps/observatory", "observatory", {"a.py": "from runfile import keys\nimport runfile.keys\n"}),
                     project(r, "robots/duck", "duck_lab", {"n.py": "from runfile import keys\nfrom robotgate import gate\nimport worldmodel.site\n"})))
check("allowed imports pass", got == [], got)

# a library importing the app above it
got = run(lambda r: (project(r, "libs/runfile", "runfile", {"x.py": "import observatory.server\n"}),
                     project(r, "apps/observatory", "observatory", {})))
check("a library importing an app fails, with file and line", len(got) == 1 and "libs/runfile/src/runfile/x.py:1" in got[0]
      and "observatory" in got[0], got)

# an app importing an app, a robot importing an app, a nested (function-level) import
got = run(lambda r: (project(r, "apps/observatory", "observatory", {"x.py": "def f():\n    from mission_control import core\n"}),
                     project(r, "apps/mission-control", "mission_control", {}),
                     project(r, "robots/duck", "duck_lab", {"y.py": "import observatory\n"})))
check("an app importing an app, a robot importing an app, and a nested import all fail", len(got) == 2 and any("x.py:2" in g for g in got), got)

# a module whose unit differs from its package (the carve-out in progress: MODULES maps a prefix, not a folder)
cb.MODULES.update({"miniview": "observatory", "miniview.keys": "runfile"})
got = run(lambda r: (project(r, "viewer", "miniview", {"keys.py": "", "server.py": ""}),
                     project(r, "duck", "duck_lab", {"a.py": "from miniview import keys\nfrom miniview.keys import X\n"})))
check("`from miniview import keys` is the format when the table says so, not the Observatory", got == [], got)
del cb.MODULES["miniview.keys"]
got = run(lambda r: (project(r, "viewer", "miniview", {"keys.py": "", "server.py": ""}),
                     project(r, "duck", "duck_lab", {"a.py": "from miniview import server\n"})))
check("`from miniview import server` is the Observatory, which the duck may not import", len(got) == 1, got)
del cb.MODULES["miniview"]

# a test may import its neighbour the table gives it, and nothing else
got = run(lambda r: (project(r, "apps/nxt-web", "nxt_lab", {"tests/t.py": "from observatory.shots import launch\n"}),
                     project(r, "apps/observatory", "observatory", {})))
check("nxt-web's test may launch Chromium through the Observatory", got == [], got)
got = run(lambda r: (project(r, "apps/nxt-web", "nxt_lab", {"nxt.py": "from observatory.shots import launch\n"}),
                     project(r, "apps/observatory", "observatory", {})))
check("... its source may not", len(got) == 1, got)

# an exception is by module and unit, and only that
exc = {"mission_control.duck": {"duck_nav"}}     # (duck_lab.nav is the navigator's own unit, RFC-0022)
got = run(lambda r: (project(r, "apps/mission-control", "mission_control", {"duck.py": "from duck_lab.nav.client import Rpc\n",
                                                                           "other.py": "from duck_lab.nav.client import Rpc\n"}),
                     project(r, "robots/duck", "duck_lab", {})), exceptions=exc)
check("a listed exception passes, the same import elsewhere fails", len(got) == 1 and "other.py" in got[0], got)

# a baseline entry lets a breach through, and fails when it is no longer needed
base = {"worldmodel.objects": {"duck_nav"}}
got = run(lambda r: project(r, "libs/worldmodel", "worldmodel", {"objects.py": "from duck_lab.nav.cliff import OVERHEAD_M\n"}), baseline=base)
check("a baseline entry lets its breach through", got == [], got)
got = run(lambda r: project(r, "libs/worldmodel", "worldmodel", {"objects.py": "OVERHEAD_M = 0.3\n"}), baseline=base)
check("a baseline entry that no longer breaks the table is a failure (the list only shrinks)", len(got) == 1 and "BASELINE" in got[0], got)

# the runner and the navigator (RFC-0022): the navigator never imports the runner or the host library, the runner never a
# robot's package, and a robot's tools may use the runner
got = run(lambda r: (project(r, "robots/duck", "duck_lab", {"nav/run.py": "import labrunner.remote\n",
                                                             "payload.py": "import simhost\n",
                                                             "site_cli.py": "from labrunner.rooms import ROOMS\nimport simhost\n"}),
                     project(r, "libs/runner", "labrunner", {}), project(r, "libs/simhost", "simhost", {})))
check("the navigator may not import the runner nor the host library; the duck's tools may",
      len(got) == 2 and any("nav/run.py" in g for g in got) and any("payload.py" in g for g in got), got)
got = run(lambda r: (project(r, "libs/runner", "labrunner", {"remote.py": "from duck_lab.nav.client import Rpc\n",
                                                             "go.py": "import duck_lab.robot\n"}),
                     project(r, "robots/duck", "duck_lab", {})))
check("the runner may not import a robot's package (it finds robots by name)", len(got) == 2, got)
got = run(lambda r: (project(r, "robots/duck", "duck_lab", {"nav/server.py": "from runfile import installation\n",
                                                             "profile.py": "import runfile.registry\nfrom runfile.profile import checksum\n",
                                                             "site_cli.py": "from runfile import installation\n"}),
                     project(r, "libs/runfile", "runfile", {})))
check("must fail: the navigator may not read the installation file (runfile.installation, runfile.registry; the operator's "
      "decision i); the rest of runfile and the duck's tools may",
      len(got) == 2 and any("nav/server.py:1" in g for g in got) and any("profile.py:1" in g for g in got), got)

# a path source is held to the table
got = run(lambda r: (project(r, "libs/runfile", "runfile", {}, '[tool.uv.sources]\nduck-lab = { path = "../../robots/duck" }\n'),
                     project(r, "robots/duck", "duck_lab", {})))
check("a library with a path source to a robot fails", len(got) == 1 and "pyproject.toml" in got[0], got)
got = run(lambda r: (project(r, "robots/duck", "duck_lab", {}, '[tool.uv.sources]\nrunfile = { path = "../../libs/runfile" }\n'),
                     project(r, "libs/runfile", "runfile", {})))
check("a robot with a path source to the format passes", got == [], got)
got = run(lambda r: project(r, "robots/duck", "duck_lab", {}, '[tool.uv.sources]\nrunfile = { path = "../../libs/nowhere" }\n'))
check("a path source that is not a project is a failure", len(got) == 1, got)

# a file that does not parse is a failure, not silence
got = run(lambda r: project(r, "libs/runfile", "runfile", {"bad.py": "def (:\n"}))
check("a file that does not parse fails", len(got) == 1 and "does not parse" in got[0], got)

print("test_check_boundaries", "FAIL" if failures else "PASS")
sys.exit(1 if failures else 0)
