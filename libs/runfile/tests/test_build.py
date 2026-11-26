"""A run's build identity (runfile/build.py): the string and its parts, the commit read with git, a dirty tree marked and never
refused, the walking policy hashed from the file the simulator's config names (else `unknown`), the simulator's commit (else `real`),
the impairment's preset and seed. No robot's package. Run: cd libs/runfile && uv run python tests/test_build.py"""

import atexit
import hashlib
import shutil
import subprocess
import tempfile
import types
from pathlib import Path

from helpers import Checks
from runfile import build

check = Checks("BUILD")
tmp = Path(tempfile.mkdtemp(prefix="build-"))
atexit.register(shutil.rmtree, tmp, True)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def repo(name: str) -> Path:
    r = tmp / name
    r.mkdir()
    git(r, "init", "-q")
    (r / "a.txt").write_text("one\n")
    git(r, "add", "a.txt")
    git(r, "commit", "-q", "-m", "first")
    return r


# ---- the string and its parts -----------------------------------------------------------------------------------------------
b = build.identity("0123456789ab", "rules@1", "ce894d30", "0daab160", "nvidia", 7)
check("the string is brain, ctrl, walker, sim, tof and the seed, in that order",
      b["id"] == "brain@0123456789ab+ctrl@rules@1+walker@ce894d30+sim@0daab160+tof@nvidia-s7", b["id"])
check("each part is its own field, as the string writes it",
      {k: b[k] for k in ("brain", "ctrl", "walker", "sim", "tof", "seed")}
      == {"brain": "0123456789ab", "ctrl": "rules@1", "walker": "ce894d30", "sim": "0daab160", "tof": "nvidia", "seed": 7}, b)
check("a clean brain is not dirty", b["dirty"] is False)
d = build.identity("0123456789ab-dirty", "rules@1", "unknown", "real", "off", 0)
check("a dirty brain is written -dirty in the string and says so", d["dirty"] is True and d["id"].startswith("brain@0123456789ab-dirty+"), d)
check("off and no seed: tof@off-s0, walker unknown, sim real", d["id"].endswith("+walker@unknown+sim@real+tof@off-s0"), d["id"])

# ---- the commit, and a dirty tree --------------------------------------------------------------------------------------------
r = repo("clean")
head = git(r, "rev-parse", "HEAD")
check("the commit is HEAD's first 12", build.commit(r, 12) == head[:12] and len(build.commit(r, 12)) == 12, build.commit(r, 12))
check("a clean checkout is not dirty", build.dirty(r) is False)
(r / "untracked.txt").write_text("x")
check("an untracked file does not make it dirty", build.dirty(r) is False)
(r / "a.txt").write_text("two\n")
check("a changed tracked file makes it dirty", build.dirty(r) is True)
host = types.SimpleNamespace(microduck_rl=r, state=tmp / "state", robot="duck-a")
got = build.of(r, host, "real", None)
check("a dirty tree is recorded with -dirty, never refused", got["brain"] == head[:12] + "-dirty" and got["dirty"] is True, got)
git(r, "checkout", "--", "a.txt")
check("the same tree restored: the same commit, no -dirty", build.of(r, host, "real", None)["brain"] == head[:12])
check("not a checkout: the commit is None, the build says unknown (not refused)",
      build.commit(tmp, 12) is None and build.of(tmp / "nothing", host, "real", None)["brain"] == "unknown")

# ---- the walking policy and the simulator --------------------------------------------------------------------------------------
state = tmp / "state"
state.mkdir()
policy = tmp / "velstand.onnx"
policy.write_bytes(b"a walking policy")
(state / "robotd-duck-a.toml").write_text(f'[policy]\nenabled = true\nwalk = "{policy}"\n')
want = hashlib.sha256(b"a walking policy").hexdigest()[:8]
check("the walker is 8 of the sha256 of the file robotd's config names", build.walker(host) == want, build.walker(host))
sim = build.of(r, host, "sim", None)
check("in the simulator: the simulator's commit (8) and the policy's sha", sim["sim"] == head[:8] and sim["walker"] == want, sim)
check("on a real robot: sim is real and the walker unknown (this machine cannot reach its policy)",
      build.of(r, host, "real", None)["sim"] == "real" and build.of(r, host, "real", None)["walker"] == "unknown")
(state / "robotd-duck-a.toml").write_text('[policy]\nwalk = "/nonexistent/velstand.onnx"\n')
check("a policy file that is not there: unknown, not a guess", build.walker(host) == "unknown")
(state / "robotd-duck-a.toml").unlink()
check("no config: unknown", build.walker(host) == "unknown")

# ---- the impairment ------------------------------------------------------------------------------------------------------------
check("off by default: preset off, seed 0", build.tof(None) == ("off", 0) and build.tof({"enabled": False, "seed": 0}) == ("off", 0))
check("on: the preset's name and the seed", build.tof({"enabled": True, "seed": 5}) == ("nvidia", 5))
on = build.of(r, host, "sim", {"enabled": True, "seed": 5})
check("the build says tof@nvidia-s5 for it", on["id"].endswith("+tof@nvidia-s5") and on["tof"] == "nvidia" and on["seed"] == 5, on["id"])
check.done()
