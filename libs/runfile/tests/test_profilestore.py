"""A machine's profile versions (phase 5 step 1, runfile/profilestore.py): seed from the robot's own file, save a change as the next
version, refuse a change that changes nothing, go back to an older version, a `current` that names a missing version is an error
saying so, export and import (a checksum that does not match its profile is refused, nothing written; an already-known checksum is
not saved twice), the diff of two versions, and two robots keeping two chains. No robot's package.
Run: cd libs/runfile && uv run python tests/test_profilestore.py"""

import atexit
import copy
import json
import shutil
import tempfile
from pathlib import Path

from helpers import Checks, small_profile
from runfile.profile import checksum
from runfile.profilestore import Store, StoreError, diff

check = Checks("PROFILE STORE")
tmp = Path(tempfile.mkdtemp(prefix="profilestore-"))
atexit.register(shutil.rmtree, tmp, True)


def raises(fn, why):
    try:
        fn()
    except StoreError as e:
        return why in str(e), str(e)
    return False, "no error"


repo = tmp / "repo-profile.json"
repo.write_text(json.dumps(small_profile()))
store = Store(tmp / "state" / "profiles")

check("an empty store: no versions, no current", store.versions("rover") == [] and store.current("rover") is None)
ok, why = raises(lambda: store.read("rover"), "no version yet")
check("reading an empty store says to seed it", ok, why)
check("seed: version 1 from the robot's own file, made current", store.seed("rover", repo) == 1 and store.current("rover") == 1
      and store.read("rover") == small_profile())
check("seeding again changes nothing", store.seed("rover", repo) == 1 and store.versions("rover") == [1])

v2 = small_profile()
v2["locomotion"]["cruise_mps"] = 0.25
check("save: a change is the next version, made current", store.save("rover", v2) == 2 and store.current("rover") == 2
      and store.read("rover")["locomotion"]["cruise_mps"] == 0.25)
check("version 1 is kept as it was", store.read("rover", 1)["locomotion"]["cruise_mps"] == 0.3)
ok, why = raises(lambda: store.save("rover", copy.deepcopy(v2)), "nothing to save")
check("saving the same content again is refused: no version that changes nothing", ok, why)
bad = small_profile()
bad["locomotion"]["cruise_mps"] = 0.9          # above the factsheet's maximum speed
ok, why = raises(lambda: store.save("rover", bad), "not a valid profile")
check("an invalid profile is refused before anything is written", ok and store.versions("rover") == [1, 2], why)
check("no half-written file is left behind", not list((tmp / "state" / "profiles" / "rover").glob(".*.tmp")))

store.use("rover", 1)
check("use: an older version made current again (going back)", store.current("rover") == 1)
ok, why = raises(lambda: store.use("rover", 9), "no such version")
check("use of a version that does not exist is refused", ok, why)
store.use("rover", 2)

(tmp / "state" / "profiles" / "rover" / "current").write_text("5\n")
ok, why = raises(lambda: store.current("rover"), "names version 5")
check("a current that names a missing version is an error saying which", ok, why)
(tmp / "state" / "profiles" / "rover" / "current").write_text("two\n")
ok, why = raises(lambda: store.current("rover"), "not a version number")
check("a current that is not a number is an error", ok, why)
(tmp / "state" / "profiles" / "rover" / "current").write_text("2\n")

# export and import
exp = store.export("rover")
check("export: the profile, its version here and its checksum", exp["version"] == 2 and exp["robot"] == "rover"
      and exp["checksum"] == checksum(v2) and exp["profile"] == v2)
other = Store(tmp / "other" / "profiles")
check("import into another machine's store: saved as its next version (1 there)", other.import_("rover", exp) == 1
      and other.read("rover") == v2 and other.current("rover") == 1)
check("importing the same checksum again saves nothing: the version that has it", other.import_("rover", exp) == 1
      and other.versions("rover") == [1])
tampered = copy.deepcopy(exp)
tampered["profile"]["locomotion"]["cruise_mps"] = 0.2
ok, why = raises(lambda: other.import_("rover", tampered), "does not match its profile")
check("must fail: an export whose checksum does not match its profile is refused", ok, why)
check("and nothing was written", other.versions("rover") == [1])
ok, why = raises(lambda: other.import_("rover", {"profile": v2}), "not a profile export")
check("something that is not an export is refused", ok, why)

# the diff
d = diff(store.read("rover", 1), store.read("rover", 2))
check("diff: the one number that changed, with both values", d == [("locomotion.cruise_mps", 0.3, 0.25)], d)
v3 = copy.deepcopy(v2)
v3["subsystems"][1]["what"] = "the front camera"
v3["footprint"]["why"] = "measured with a ruler"
d3 = diff(v2, v3)
check("diff: a field added in a list of objects is named by its index", ("subsystems[1].what", None, "the front camera") in d3, d3)
check("diff: measured and why are left out unless asked", all(not p.endswith(".why") for p, _, _ in d3)
      and ("footprint.why", None, "measured with a ruler") in diff(v2, v3, notes=True))

# two robots, two chains
store.seed("rover-b", repo)
check("two robots of one kind keep two chains", store.versions("rover-b") == [1] and store.versions("rover") == [1, 2])
ok, why = raises(lambda: store.folder("../escape"), "registered robot's name")
check("a robot name cannot leave the store's folder", ok, why)

check.done()
