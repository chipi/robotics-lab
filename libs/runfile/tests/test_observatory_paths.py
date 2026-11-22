"""Where the Observatory's data and index are on this machine (phase 5 step 1, K44): $OBSERVATORY_DATA / $OBSERVATORY_INDEX, else
the installation file's `data` / `index`; no machine's path built in. An index named nowhere is an error saying where to name it.
Run: cd libs/runfile && uv run python tests/test_observatory_paths.py"""

import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

from helpers import Checks
from runfile import installation
from runfile.catalog import default_data
from runfile.index import default_index

check = Checks("OBSERVATORY PATHS")
tmp = Path(tempfile.mkdtemp(prefix="observatory-paths-"))
atexit.register(shutil.rmtree, tmp, True)
for k in ("OBSERVATORY_DATA", "OBSERVATORY_INDEX", "MINIVIEW_DATA", "MINIVIEW_INDEX"):
    os.environ.pop(k, None)

os.environ[installation.ENV] = str(tmp / "none.json")
check("no variable, no installation file: no data folder", default_data() is None)
try:
    default_index()
    said = "an index"
except installation.NotNamed as e:
    said = str(e)
check("must fail: no variable, no installation file: no index, and the error says where to name one",
      "OBSERVATORY_INDEX" in said and "none.json" in said, said)

inst = tmp / "installation.json"
inst.write_text(json.dumps({"installation": 1, "data": str(tmp / "data"), "index": str(tmp / "state/index.sqlite")}))
os.environ[installation.ENV] = str(inst)
check("the installation file's data folder", default_data() == tmp / "data", default_data())
check("the installation file's index", default_index() == tmp / "state/index.sqlite", default_index())

os.environ["OBSERVATORY_DATA"] = str(tmp / "env-data")
os.environ["OBSERVATORY_INDEX"] = str(tmp / "env-index.sqlite")
check("a variable that is set wins over the installation file", default_data() == tmp / "env-data"
      and default_index() == tmp / "env-index.sqlite", (default_data(), default_index()))

check.done()
