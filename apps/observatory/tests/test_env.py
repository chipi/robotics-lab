"""The environment variables after the rename (RFC-0018): OBSERVATORY_<NAME> is read first, the MINIVIEW_<NAME> of before the
rename when it is not set, and an empty value counts as not set. The helper, the data folder, the index (a command writes
its index where the variable says) and the robots folder, each with the new name, the old name, and both.
Run: cd apps/observatory && uv run python tests/test_env.py"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from helpers import FIXTURE, Checks

from runfile import env
from runfile.catalog import default_data

check = Checks("test_env")


def only(**names):
    """The process environment with every OBSERVATORY_* and MINIVIEW_* variable removed, then `names` set."""
    for k in [k for k in os.environ if k.startswith(env.PREFIXES)]:
        del os.environ[k]
    os.environ.update(names)


only(OBSERVATORY_DATA="/new", MINIVIEW_DATA="/old")
check("the new name wins when both are set", env.get("DATA") == "/new")
only(MINIVIEW_DATA="/old")
check("the old name is read when the new one is not set", env.get("DATA") == "/old")
only(OBSERVATORY_DATA="", MINIVIEW_DATA="/old")
check("an empty new name counts as not set", env.get("DATA") == "/old")
only()
check("neither: the default (None, or the one given)", env.get("DATA") is None and env.get("CACHE_MB", 1024) == 1024)

only(MINIVIEW_DATA="/old")
check("the data folder (catalog.default_data) from the old name", default_data() == Path("/old"))
only(OBSERVATORY_DATA="/new", MINIVIEW_DATA="/old")
check("... and the new name wins", default_data() == Path("/new"))

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    clean = {k: v for k, v in os.environ.items() if not k.startswith(env.PREFIXES)}
    for label, names in (("the new name", {"OBSERVATORY_INDEX": str(tmp / "new.sqlite")}),
                         ("the old name", {"MINIVIEW_INDEX": str(tmp / "old.sqlite")}),
                         ("both (the new one wins)", {"OBSERVATORY_INDEX": str(tmp / "both-new.sqlite"),
                                                      "MINIVIEW_INDEX": str(tmp / "both-old.sqlite")})):
        data = tmp / ("data-" + label.split()[1])
        (data / "runs").mkdir(parents=True)
        (data / "scenes").mkdir()
        out = subprocess.run([sys.executable, "-m", "observatory.cli", "--data", str(data), "import", str(FIXTURE), "--scene", "apartment"],
                             capture_output=True, text=True, env=dict(clean, **names))
        wanted = Path(names.get("OBSERVATORY_INDEX") or names["MINIVIEW_INDEX"])
        other = Path(names["MINIVIEW_INDEX"]) if "OBSERVATORY_INDEX" in names and "MINIVIEW_INDEX" in names else None
        check(f"a command's index is where {label} says", out.returncode == 0 and wanted.exists() and not (other and other.exists()),
              out.stderr[-200:])

    robots = tmp / "robots"
    robots.mkdir()
    for label, names in (("the new name", {"OBSERVATORY_ROBOTS": str(robots)}), ("the old name", {"MINIVIEW_ROBOTS": str(robots)})):
        out = subprocess.run([sys.executable, "-c", "from observatory import robots; print(robots.ROOT)"], capture_output=True, text=True,
                             env=dict(clean, **names))
        check(f"the robots folder from {label}", out.returncode == 0 and out.stdout.strip() == str(robots), out.stderr[-200:])

check.done()
