#!/usr/bin/env python3
"""Deploy the platform (the Observatory and Mission Control, one origin) from a NAMED commit, then prove it with a smoke (phase 5 item 4c, units C2, C3).

    scripts/deploy.py up --commit <sha|ref> [--dry-run] [options]     build that commit, replace what runs, record it, run the smoke
    scripts/deploy.py rollback [--dry-run]                            deploy the commit that ran before the current one
    scripts/deploy.py record --commit <sha>                           say what runs now was built from that commit (nothing is touched), so the first deploy can be rolled back
    scripts/deploy.py smoke                                           health of both, /lib/, the pages in headless Chromium, now
    scripts/deploy.py status                                          what is recorded, what runs

Why it is a script and not `make stack-up`: that builds whatever the checkout holds, under the tag `local`, and a solo Observatory project holding
:8070 has to be taken down by hand first. Here the commit is an argument (there is no default: a deploy names what it deploys), it is exported with
`git archive` into a folder of its own (<deploy-state>/trees/<sha12>, never the working tree), the images are tagged by it (observatory:<sha12>,
mission-control:<sha12>), the solo project is taken down after the build and not before it, and the deployed sha is written to
<deploy-state>/<project>.json, which `rollback` reads.

What the stack is, beyond the two compose files (they stay as they are, bridge networking, for `make stack-up`): the two containers share the host's
network and listen on loopback only. The navigator API is TCP on the host's 127.0.0.1 (the installation names `127.0.0.1:8061`), and a bridged
container cannot reach a host loopback port; with the host's network the installation file's addresses mean the same in the container as outside. The
Observatory is told where Mission Control is (OBSERVATORY_CONTROL) and proxies it at /control/ (RFC-0024 step 3). Mission Control's container gets,
from the installation file, at the same paths and under the same UID: the file itself (read only), each robot's gate socket, its registration's folder
(description and meshes, read only) and the profile store (read write). It gets no data folder, no index: it reads runs only through the Observatory's
API (RFC-0024 question 5). All of it is the generated overlay (`overlay()`), printed by --dry-run.

`--context NAME` (the X3's prod engine: `--context prod`) puts `--context NAME` on every docker call; a DOCKER_CONTEXT in the environment that differs from it is refused. `--robots-dir` may be a folder outside
the checkout (the generated meshes are not in git).

Standard library only. Needs Docker Compose 2.24 or newer (`!reset`) and git; the browser smoke alone also needs `uv` and the Observatory's environment (`make observatory-sync`): `--no-browser` needs neither."""

import argparse
import datetime
import fcntl
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "libs" / "runfile" / "src"))
from runfile import installation as inst_mod  # noqa: E402

# the deployed stack's settings: the Makefile's defaults (STACK_*, OBSERVATORY_*, CONTROL_*) and the projects' names
DEFAULTS = {
    "project": "robotics-lab", "solo_project": "observatory", "viewer_port": 8070, "control_port": 8060,
    "data": "/work/robotics-lab/data", "viewer_state": "/work/robotics-lab/state/miniview", "control_state": "/work/robotics-lab/state/control",
    "deploy_state": "/work/robotics-lab/state/deploy", "installation": "~/.config/robotics-lab/installation.json",
}
ARCHIVE = ["compose.yml", "apps/observatory", "apps/mission-control", "libs"]       # what the two Dockerfiles and compose files read
WAIT_S = 900        # the Observatory indexes every run on its first start (its image allows 600 s before it must answer)


class DeployError(Exception):
    pass


def docker_cli(context: str | None) -> list:
    """The docker command every call starts from: with a context, `--context NAME` on the command line (not the environment alone, which a caller can
    lose), so the X3's prod engine is never confused with the shared one."""
    return ["docker", "--context", context] if context else ["docker"]


def say(text: str = "") -> None:
    print(text, flush=True)


def run(cmd: list, env: dict | None = None, check: bool = True, capture: bool = False, cwd: Path | None = None) -> subprocess.CompletedProcess:
    say("  $ " + " ".join(str(c) for c in cmd))
    p = subprocess.run([str(c) for c in cmd], env={**os.environ, **(env or {})}, cwd=cwd, text=True, capture_output=capture)
    if check and p.returncode:
        raise DeployError(f"{cmd[0]} {cmd[1] if len(cmd) > 1 else ''} failed (exit {p.returncode})" + (f": {p.stderr.strip()[-400:]}" if capture else ""))
    return p


# --- the commit and its tree ------------------------------------------------------------------------------------------

def resolve_commit(ref: str, repo: Path = REPO) -> str:
    p = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], text=True, capture_output=True)
    if p.returncode:
        raise DeployError(f"{ref!r} is not a commit of {repo}")
    return p.stdout.strip()


def tree_of(settings: dict, sha: str) -> Path:
    return Path(settings["deploy_state"]) / "trees" / sha[:12]


def export_tree(settings: dict, sha: str, repo: Path = REPO) -> Path:
    """The commit's files that the build reads, in a folder of their own; one that is there already (marked with its sha) is reused, so a rollback
    builds what the first deploy built."""
    dest = tree_of(settings, sha)
    mark = dest / ".deployed-from"
    if mark.is_file() and mark.read_text().strip() == sha:
        return dest
    if dest.exists():
        raise DeployError(f"{dest} exists and is not the export of {sha}: move it away")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + f".part{os.getpid()}")
    part.mkdir()
    with subprocess.Popen(["git", "-C", str(repo), "archive", "--format=tar", sha, "--", *ARCHIVE], stdout=subprocess.PIPE) as p:
        with tarfile.open(fileobj=p.stdout, mode="r|") as tar:
            tar.extractall(part, filter="data")
        if p.wait():
            raise DeployError(f"git archive {sha} failed")
    (part / ".deployed-from").write_text(sha + "\n")
    part.rename(dest)
    return dest


# --- the overlay: what the installation file asks the container for ----------------------------------------------------

def _bind(path: Path, read_only: bool) -> str:
    """One bind mount at the same path inside; a source that is missing is an error, not a folder Docker makes (a socket's path made a directory
    would hide the gate that comes later)."""
    return (f"      - {{type: bind, source: {json.dumps(str(path))}, target: {json.dumps(str(path))}, read_only: {str(read_only).lower()}, "
            f"bind: {{create_host_path: false}}}}")


def _sockets_in(folder: Path, but: Path) -> list:
    try:
        return sorted(e.name for e in folder.iterdir() if e != but and stat.S_ISSOCK(e.lstat().st_mode))
    except OSError:
        return []


def installation_mounts(inst, create: bool) -> tuple:
    """(the mounts, the notes) Mission Control's container needs for the robots this installation runs. A gate's socket is mounted by its folder when
    nothing else that is a socket lives there (the gate may then restart; its new socket is seen), by the socket itself when the folder holds
    other sockets (the robot's own: the container must reach the robot only through the gate, RFC-0017), else not at all. The profile store is
    the one writable mount; `create` makes it on the host when it is not there."""
    mounts, notes = [], []
    seen: set = set()

    def add(path: Path, ro: bool):
        if path not in seen:
            seen.add(path)
            mounts.append(_bind(path, ro))

    add(inst.source, True)
    store = inst.state / "profiles" if inst.state else None
    for name, r in sorted(inst.robots.items()):
        if r.gate:
            folder = r.gate.parent
            others = _sockets_in(folder, r.gate)
            if others and r.gate.exists():
                add(r.gate, False)
                notes.append(f"{name}: the gate's folder {folder} holds other sockets ({', '.join(others)}): only the gate's socket {r.gate.name} is mounted, "
                             f"so after the gate restarts, `docker restart` Mission Control (or give the gate a folder of its own)")
            elif others:
                notes.append(f"{name}: the gate's socket {r.gate} is not there and its folder holds other sockets ({', '.join(others)}): NOT mounted "
                             f"(the container would reach the robot past the gate); start the gate, then deploy again")
            elif folder.is_dir():
                add(folder, False)
            else:
                notes.append(f"{name}: the gate's folder {folder} is not there: not mounted; start the gate, then deploy again")
        if r.registration:
            if r.registration.parent.is_dir():
                add(r.registration.parent, True)
            else:
                notes.append(f"{name}: the registration's folder {r.registration.parent} is not there: not mounted")
        if r.profile and r.profile.parent != store:
            add(r.profile.parent, False)
    if store:
        if create and not store.is_dir():
            store.mkdir(parents=True, exist_ok=True)
        if store.is_dir():
            add(store, False)
        else:
            notes.append(f"the profile store {store} is not there yet (it is made at the deploy); until then the robot's own profile is read")
    return mounts, notes


def resolver_mount(conf: Path = Path("/etc/resolv.conf")) -> str | None:
    """The host's resolver file, mounted as the container's, when every nameserver in it is loopback (systemd-resolved's stub). Docker drops a
    loopback nameserver from a container's copy even on the host's network, and the tailnet's MagicDNS names (the telemetry hosts) then do not
    resolve; on the host's network the stub itself is reachable. None for an ordinary resolver, or no file."""
    try:
        real = conf.resolve(strict=True)
        servers = [ln.split()[1] for ln in real.read_text().splitlines() if ln.startswith("nameserver") and len(ln.split()) > 1]
    except OSError:
        return None
    if not servers or not all(s.startswith("127.") or s == "::1" for s in servers):
        return None
    return (f"      - {{type: bind, source: {json.dumps(str(real))}, target: /etc/resolv.conf, read_only: true, "
            f"bind: {{create_host_path: false}}}}")


def overlay(s: dict, inst, tree: Path, mounts: list, scope: str | None) -> str:
    """The compose file laid over the repository's two (YAML; JSON strings are YAML strings)."""
    vport, cport = s["viewer_port"], s["control_port"]

    def check(port: int) -> str:
        return json.dumps(["CMD", "python", "-c", f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}/api/v1/health', timeout=2)"])

    home = os.environ.get("HOME", "/")
    env = [f"      MC_HOST: 127.0.0.1", f"      MC_PORT: \"{cport}\"", f"      HOME: {json.dumps(home)}"]
    if inst is not None:
        env.append(f"      ROBOTICS_LAB_INSTALLATION: {json.dumps(str(inst.source))}")
    if scope:
        env.append(f"      MC_REQUIRE_TOKENS: {scope}")
    return "\n".join([
        "# generated by scripts/deploy.py: do not edit (see its docstring)",
        "services:",
        "  observatory:",
        "    network_mode: host",
        "    ports: !reset []",
        f"    command: [\"observatory\", \"--data\", \"/data\", \"serve\", \"--host\", \"127.0.0.1\", \"--port\", \"{vport}\"]",
        "    environment:",
        f"      OBSERVATORY_CONTROL: \"http://127.0.0.1:{cport}\"",
        "    healthcheck:",
        f"      test: {check(vport)}",
        "    volumes:",
        f"      - {{type: bind, source: {json.dumps(s['robots_dir'])}, target: /robots, read_only: true}}",
        "  mission-control:",
        "    network_mode: host",
        "    ports: !reset []",
        "    environment:", *env,
        "    healthcheck:",
        f"      test: {check(cport)}",
        "    volumes:", *mounts,
        "",
    ])


def pick_scope(requested: str, control_state: Path) -> tuple:
    """(the value for MC_REQUIRE_TOKENS or None, a note). `auto`: tokens for actions (RFC-0024 question 4) when the store holds a token, else none and
    a warning: Mission Control refuses to start when tokens are required and none exists."""
    if requested in ("actions", "all"):
        return requested, f"tokens for {requested}, as asked"
    if requested == "off":
        return None, "no tokens, as asked: every client may act (the tailnet is the authentication)"
    db = control_state / "mission-control.sqlite"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        n = con.execute("SELECT COUNT(*) FROM tokens WHERE revoked_at IS NULL").fetchone()[0]
        con.close()
    except sqlite3.Error:
        n = 0
    if n:
        return "actions", f"tokens for actions only: {n} active token(s) in {db}"
    return None, (f"WARNING: no token exists in {db}, so actions need none. Make one, then deploy again: "
                  f"docker compose -p <project> exec mission-control mission-control token create --client page")


# --- settings, state ----------------------------------------------------------------------------------------------------

def settings_of(a) -> dict:
    s = {k: getattr(a, k) if getattr(a, k, None) is not None else v for k, v in DEFAULTS.items()}
    s["robots_dir"] = str(Path(a.robots_dir).resolve()) if a.robots_dir else str(REPO / "robots")
    s["control_robots"], s["context"] = a.control_robots, a.context
    s["tokens"], s["installation"] = a.tokens, str(Path(s["installation"]).expanduser())
    return s


def state_file(s: dict) -> Path:
    return Path(s["deploy_state"]) / f"{s['project']}.json"


def read_state(s: dict) -> dict:
    try:
        return json.loads(state_file(s).read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise DeployError(f"{state_file(s)} is not JSON ({e})") from None


def write_state(s: dict, sha: str, tag: str, tree: Path, now=None) -> dict:
    st = read_state(s)
    at = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(timespec="seconds")
    cur = st.get("current")
    if not cur or cur["sha"] != sha:        # a redeploy of the same commit keeps the one before it as `previous`
        st["previous"] = cur
    st["current"] = {"sha": sha, "tag": tag, "tree": str(tree), "at": at}
    st["project"] = s["project"]
    st.setdefault("history", []).append({"sha": sha, "at": at})
    state_file(s).parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file(s).with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2) + "\n")
    tmp.rename(state_file(s))
    return st


# --- the smoke ----------------------------------------------------------------------------------------------------------

def _get(url: str, timeout: float = 10.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e).encode()


def smoke(s: dict, browser: bool = True, extra: list | None = None, one_origin: bool = True, expect_scope: str | None = None) -> bool:
    """Health of both (and of Mission Control through the Observatory's origin), /lib/ served from both, the pages in headless Chromium with no console
    error and no failed request. Every line says PASS or FAIL; the last says SMOKE PASS or SMOKE FAIL. `one_origin` False (a rollback to a commit that has
    no proxy) leaves out what needs /control/; `expect_scope` (what the deploy asked of Mission Control) must be what the server reports: an older one
    that does not know `actions` would start with no tokens at all, and that must not pass."""
    viewer, control = f"http://127.0.0.1:{s['viewer_port']}", f"http://127.0.0.1:{s['control_port']}"
    failed = []

    def check(name: str, ok: bool, detail=""):
        say(("PASS " if ok else "FAIL ") + name + (f"  [{str(detail)[:160]}]" if detail else ""))
        if not ok:
            failed.append(name)

    def js(url):
        st, body = _get(url)
        try:
            return st, json.loads(body)
        except ValueError:
            return st, body[:80]

    st, h = js(viewer + "/api/v1/health")
    check("the Observatory is healthy", st == 200 and isinstance(h, dict) and h.get("ok") is True, h)
    st, h = js(control + "/api/v1/health")
    check("Mission Control is healthy", st == 200 and isinstance(h, dict) and h.get("ok") is True and h.get("service") == "mission-control", h)
    if one_origin:
        st, h2 = js(viewer + "/control/api/v1/health")
        check("... and so is it through the Observatory's address (one origin)", st == 200 and h2 == h, (st, h2))
    st, t = js((viewer + "/control" if one_origin else control) + "/api/v1/tokens")
    seen = (t.get("scope") or "all") if st == 200 and isinstance(t, dict) and t.get("required") else None      # a server before the scopes says only `required`
    check("tokens: " + (f"required for {seen}" if seen else "not required (every client may act)") + (f", as asked ({expect_scope})" if expect_scope and seen == expect_scope else ""),
          st == 200 and isinstance(t, dict) and "required" in t and (expect_scope is None or seen == expect_scope),
          t if st != 200 else ("" if seen == expect_scope or expect_scope is None else f"asked {expect_scope}, the server says {seen}"))
    for base, who in ((viewer, "the Observatory"), (control, "Mission Control")):
        for path, what in (("tokens.css", "the tokens"), ("vendor/three.module.js", "three.js"), ("body/body.js", "the robot body")):
            st, _ = _get(f"{base}/lib/{path}")
            check(f"/lib/{path} ({what}) is served by {who}", st == 200, st)
    if browser:
        cmd = ["uv", "run", "--project", str(REPO / "apps" / "observatory"), "--frozen", "python", str(REPO / "scripts" / "smoke_pages.py"),
               "--viewer", viewer, "--control", control, *(extra or []), *([] if one_origin else ["--no-one-origin"])]
        say("  $ " + " ".join(cmd))
        p = subprocess.run(cmd, env={**os.environ, "TMPDIR": os.environ.get("TMPDIR", str(Path.home() / ".cache" / "robotics-lab-tests"))})
        check("the pages load in headless Chromium with no console error and no failed request", p.returncode == 0, f"exit {p.returncode}")
    say("SMOKE FAIL: " + "; ".join(failed) if failed else "SMOKE PASS")
    return not failed


# --- the deploy ---------------------------------------------------------------------------------------------------------

class Compose:
    def __init__(self, s: dict, tree: Path | None, overlay_file: Path | None, tag: str, scope: str | None):
        self.s, self.tree, self.overlay_file = s, tree, overlay_file
        robots = s["control_robots"] or (str(tree / "apps" / "mission-control" / "robots.example") if tree else "<tree>/apps/mission-control/robots.example")
        self.env = {
            "OBSERVATORY_DATA": s["data"], "OBSERVATORY_STATE": s["viewer_state"], "OBSERVATORY_IMAGE_TAG": tag,
            "OBSERVATORY_UID": str(os.getuid()), "OBSERVATORY_GID": str(os.getgid()),
            "OBSERVATORY_PORT": str(s["viewer_port"]), "MC_PORT": str(s["control_port"]),
            "MC_STATE_DIR": s["control_state"], "MC_ROBOTS_DIR": robots, "MC_IMAGE_TAG": tag, "MC_UID": str(os.getuid()), "MC_GID": str(os.getgid()),
        }

    def base(self) -> list:
        return [*docker_cli(self.s.get("context")), "compose", "-p", self.s["project"], "-f", str(self.tree / "compose.yml" if self.tree else "<tree>/compose.yml"),
                "-f", str(self.overlay_file or "<overlay>")]

    def show(self, *args) -> str:
        return "  $ " + " ".join(f"{k}={v}" for k, v in sorted(self.env.items()) if k in ("OBSERVATORY_IMAGE_TAG", "MC_ROBOTS_DIR")) + " " + " ".join([*self.base(), *args])

    def do(self, *args, **kw):
        return run([*self.base(), *args], env=self.env, **kw)


def solo_running(project: str, context: str | None = None) -> list:
    p = subprocess.run([*docker_cli(context), "ps", "-q", "--filter", f"label=com.docker.compose.project={project}"], text=True, capture_output=True)
    return p.stdout.split() if p.returncode == 0 else []


def plan(s: dict, sha: str, create: bool) -> dict:
    """Everything the deploy would use, worked out from the installation file and the state folder; `create` makes the store folder first."""
    inst, notes = None, []
    ipath = Path(s["installation"])
    if s["installation"] != "none":
        try:
            inst = inst_mod.load(ipath, required=False)
        except inst_mod.InstallationError as exc:
            raise DeployError(str(exc)) from None
        if inst is None:
            notes.append(f"no installation file {ipath}: Mission Control gets none, so a robot that points at a profile cannot load; only the fake robot runs")
    mounts, mnotes = installation_mounts(inst, create) if inst else ([], [])
    if (rm := resolver_mount()) is not None:
        mounts = [*mounts, rm]
    scope, snote = pick_scope(s["tokens"], Path(s["control_state"]))
    tag, tree = sha[:12], tree_of(s, sha)
    ov_file = Path(s["deploy_state"]) / s["project"] / f"overlay-{tag}.yml"
    return {"inst": inst, "ipath": ipath, "notes": notes + mnotes, "scope": scope, "snote": snote, "tag": tag, "tree": tree, "ov_file": ov_file,
            "text": overlay(s, inst, tree, mounts, scope), "compose": Compose(s, tree, ov_file, tag, scope)}


def deploy(s: dict, sha: str, dry: bool, browser: bool = True, verb: str = "deploy", one_origin: bool = True) -> bool:
    say(f"project: {s['project']}" + ("   (the deployed stack's name)" if s["project"] == DEFAULTS["project"] else ""))
    if s["solo_project"] == s["project"]:
        raise DeployError("--solo-project is the project being deployed")
    pl = plan(s, sha, create=False)
    c, tag, tree, ov_file = pl["compose"], pl["tag"], pl["tree"], pl["ov_file"]
    say(f"{verb}: commit {sha}  tag {tag}  tree {tree}" + ("" if one_origin else "   (the smoke leaves out the one origin: the commit may predate it)"))
    say(f"  the Observatory 127.0.0.1:{s['viewer_port']}  Mission Control 127.0.0.1:{s['control_port']} (also at /control/ of the Observatory's)")
    say(f"  data {s['data']} (read only)  viewer state {s['viewer_state']}  control state {s['control_state']}  robots (the Observatory's) {s['robots_dir']}")
    say(f"  installation {pl['ipath'] if pl['inst'] else 'none'}  robot files {c.env['MC_ROBOTS_DIR']}")
    say(f"  {pl['snote']}")
    for n in pl["notes"]:
        say(f"  NOTE {n}")
    if dry:
        running = solo_running(s["solo_project"], s.get("context"))
        say("DRY RUN: nothing below is done.")
        say(f"--- the overlay, {ov_file}:\n{pl['text']}---")
        say(f"would: export {sha[:12]} with `git archive` into {tree} (kept)" + ("   [already there: reused]" if tree.exists() else ""))
        say("would: write the overlay above; mkdir -p the data, state and profile store folders that are missing")
        say(c.show("config", "-q"))
        say(c.show("build"))
        say(f"would: take down the solo project {s['solo_project']!r} " + (f"(running now: {len(running)} container(s))" if running else "(not running now: nothing to take down)"))
        say("  $ " + " ".join([*docker_cli(s.get("context")), "compose", "-p", s["solo_project"], "down"]) + "   (only when it runs)")
        say(c.show("up", "-d", "--wait", "--wait-timeout", str(WAIT_S)))
        say(f"would: record {sha} as current in {state_file(s)} (the one before it is kept for `rollback`)")
        say("would: run the smoke" + (" (without the browser)" if not browser else "") + f": health of both, /lib/, the pages in Chromium ({REPO / 'scripts' / 'smoke_pages.py'})")
        say("DRY RUN END: nothing was changed.")
        return True
    lock = Path(s["deploy_state"]) / ".lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise DeployError(f"another deploy is running ({lock})") from None
        for d in (s["data"] + "/runs", s["data"] + "/scenes", s["viewer_state"], s["control_state"]):
            Path(d).mkdir(parents=True, exist_ok=True)
        pl = plan(s, sha, create=True)
        c = pl["compose"]
        c.tree = export_tree(s, sha)
        ov_file.parent.mkdir(parents=True, exist_ok=True)
        ov_file.write_text(pl["text"])
        c.do("config", "-q")
        c.do("build")
        if solo_running(s["solo_project"], s.get("context")):
            say(f"the solo project {s['solo_project']!r} is running: taking it down (its image and state folder stay)")
            run([*docker_cli(s.get("context")), "compose", "-p", s["solo_project"], "down"])
        c.do("up", "-d", "--wait", "--wait-timeout", str(WAIT_S))
        write_state(s, sha, tag, c.tree)
        say(f"recorded: {state_file(s)}")
    ok = smoke(s, browser, one_origin=one_origin, expect_scope=pl["scope"])
    say(f"{verb.upper()} {'PASS' if ok else 'FAIL'} commit {sha[:12]} project {s['project']}"
        + ("" if ok else ": the stack is up and recorded; `scripts/deploy.py rollback` returns to the one before it"))
    return ok


def cmd_up(a, s) -> bool:
    if not a.commit:
        raise DeployError("up needs --commit: a deploy names what it deploys (a sha or a ref)")
    return deploy(s, resolve_commit(a.commit), a.dry_run, not a.no_browser)


def cmd_record(a, s) -> bool:
    """Say what runs now was built from this commit, so that the first deploy has something to roll back to. Touches no container."""
    if not a.commit:
        raise DeployError("record needs --commit: the commit what runs now was built from")
    sha = resolve_commit(a.commit)
    say(f"project: {s['project']}")
    if a.dry_run:
        say(f"DRY RUN: would record {sha} as current in {state_file(s)}")
        return True
    write_state(s, sha, "local", tree_of(s, sha))
    say(f"recorded {sha[:12]} as what runs in {s['project']}: {state_file(s)}")
    return True


def cmd_rollback(a, s) -> bool:
    st = read_state(s)
    prev, cur = st.get("previous"), st.get("current")
    if not prev:
        raise DeployError(f"no previous deployment is recorded in {state_file(s)}"
                          + (f" (current: {cur['sha'][:12]}). To record what ran before this script, deploy that commit by name: up --commit <sha>" if cur else ""))
    return deploy(s, prev["sha"], a.dry_run, not a.no_browser, verb="rollback", one_origin=False)


def cmd_smoke(a, s) -> bool:
    return smoke(s, not a.no_browser)


def cmd_status(a, s) -> bool:
    say(f"project {s['project']}  state file {state_file(s)}")
    st = read_state(s)
    say(json.dumps({k: st.get(k) for k in ("current", "previous")}, indent=2) if st else "nothing recorded")
    running = subprocess.run([*docker_cli(s.get("context")), "ps", "--filter", f"label=com.docker.compose.project={s['project']}", "--format", "{{.Names}}  {{.Image}}  {{.Status}}"],
                             text=True, capture_output=True).stdout
    say(running.strip() or "no container of this project is running")
    return True


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deploy.py", description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("up", "rollback", "record", "smoke", "status"))
    p.add_argument("--commit", help="the commit to deploy: a sha or a ref (up, record; rollback takes the recorded previous one)")
    p.add_argument("--dry-run", action="store_true", help="print what would be done, and do none of it")
    p.add_argument("--no-browser", action="store_true", help="the smoke without Chromium (it then needs no uv and no Observatory environment)")
    p.add_argument("--context", help="run every docker and docker compose call against this Docker context (docker --context NAME ...); default: none, the CLI's own")
    p.add_argument("--project", help=f"the compose project (default {DEFAULTS['project']})")
    p.add_argument("--solo-project", help=f"the solo Observatory project to take down when it runs (default {DEFAULTS['solo_project']})")
    p.add_argument("--viewer-port", type=int, help=f"the Observatory's port (default {DEFAULTS['viewer_port']})")
    p.add_argument("--control-port", type=int, help=f"Mission Control's port (default {DEFAULTS['control_port']})")
    p.add_argument("--data", help=f"the lab's data folder, mounted read only (default {DEFAULTS['data']})")
    p.add_argument("--viewer-state", help=f"the Observatory's state folder, the one index (default {DEFAULTS['viewer_state']})")
    p.add_argument("--control-state", help=f"Mission Control's state folder (default {DEFAULTS['control_state']})")
    p.add_argument("--deploy-state", help=f"where the trees and the record of what is deployed live (default {DEFAULTS['deploy_state']})")
    p.add_argument("--installation", help=f"this machine's installation file, or none (default {DEFAULTS['installation']})")
    p.add_argument("--robots-dir", help="the robots' descriptions and meshes the Observatory mounts (default: robots/ of the checkout this script is in)")
    p.add_argument("--control-robots", help="Mission Control's robot files (default: apps/mission-control/robots.example of the commit: the fake robot)")
    p.add_argument("--tokens", choices=("auto", "actions", "all", "off"), default="auto",
                   help="auto: tokens for actions when a token exists, else none and a warning (default); actions, all, off: as named")
    return p


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    env_ctx = os.environ.get("DOCKER_CONTEXT")
    if a.context and env_ctx and env_ctx != a.context:
        say(f"deploy.py: DOCKER_CONTEXT is {env_ctx!r} but --context is {a.context!r}: they must agree (unset one, or make them equal)")
        return 2
    s = settings_of(a)
    try:
        ok = {"up": cmd_up, "rollback": cmd_rollback, "record": cmd_record, "smoke": cmd_smoke, "status": cmd_status}[a.command](a, s)
    except DeployError as exc:
        say(f"deploy.py: {exc}")
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
