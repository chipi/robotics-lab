"""Self-test of scripts/deploy.py (phase 5 item 4c, units C2 and C3), with no Docker: a deploy names its commit and builds that commit's files, not the
working tree's; the overlay holds what the installation file asks of Mission Control's container and nothing of the runs (RFC-0024 question 5); a gate's
socket is mounted without handing the container the robot's own sockets; the record of what is deployed feeds the rollback; a dry run changes nothing.
Run by `make test-deploy`.

    python3 scripts/test_deploy.py"""

import contextlib
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy as d  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:200]}]" if detail else ""))
    if not cond:
        failures.append(name)


def sh(*cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def listen(path: Path):
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    return s


def main_out(*argv) -> tuple:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = d.main(list(argv))
    return code, out.getvalue()


def tree_files(root: Path) -> list:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")) if root.exists() else []


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    # --- a repository with two commits, the working tree ahead of both ----------------------------------------------------
    repo = tmp / "repo"
    for rel, text in {"compose.yml": "name: x\n", "apps/observatory/Dockerfile": "FROM a\n", "apps/mission-control/Dockerfile": "FROM b\n",
                      "libs/web/tokens.css": "one\n", "docs/big.md": "not built\n"}.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    sh("git", "init", "-q", "-b", "main", cwd=repo)
    sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "add", ".", cwd=repo)
    sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one", cwd=repo)
    one = d.resolve_commit("HEAD", repo)
    (repo / "libs/web/tokens.css").write_text("two\n")
    sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "two", cwd=repo)
    two = d.resolve_commit("HEAD", repo)
    (repo / "libs/web/tokens.css").write_text("three, not committed\n")
    S = {**d.DEFAULTS, "deploy_state": str(tmp / "deploy-state"), "robots_dir": str(tmp / "robots"), "control_robots": None, "tokens": "off",
         "installation": str(tmp / "installation.json"), "data": str(tmp / "data"), "viewer_state": str(tmp / "vs"), "control_state": str(tmp / "cs"),
         "project": "robotics-lab-test"}

    check("a commit is named by a ref or a sha, and resolved to the whole sha", one != two and len(one) == 40 and d.resolve_commit(one[:10], repo) == one
          and d.resolve_commit("main~1", repo) == one)
    try:
        d.resolve_commit("no-such-commit", repo)
        check("a name that is not a commit is refused", False)
    except d.DeployError as exc:
        check("a name that is not a commit is refused", "not a commit" in str(exc), exc)
    t1, t2 = d.export_tree(S, one, repo), d.export_tree(S, two, repo)
    check("a commit's tree holds that commit's files: not the working tree's, and not another commit's",
          (t1 / "libs/web/tokens.css").read_text() == "one\n" and (t2 / "libs/web/tokens.css").read_text() == "two\n", [(t1 / "libs/web/tokens.css").read_text(), (t2 / "libs/web/tokens.css").read_text()])
    check("only what the images and compose files read is exported", not (t1 / "docs").exists() and (t1 / "compose.yml").is_file() and (t1 / ".deployed-from").read_text().strip() == one)
    (t1 / "libs/web/tokens.css").write_text("edited\n")
    check("an export that is there is reused as it is (a rollback builds what was built), under the sha's own folder", d.export_tree(S, one, repo) == t1
          and (t1 / "libs/web/tokens.css").read_text() == "edited\n" and t1.name == one[:12])

    # --- the installation, the overlay -----------------------------------------------------------------------------------------------
    folder = tmp / "duck-folder"
    folder.mkdir()
    (folder / "registration.json").write_text("{}")
    gate_dir = tmp / "gate-only"
    gate_dir.mkdir()
    gate = gate_dir / "gate.sock"
    keep = [listen(gate)]
    state = tmp / "state"
    inst_file = tmp / "installation.json"
    inst_file.write_text(json.dumps({"installation": 1, "data": str(tmp / "data"), "index": str(tmp / "idx.sqlite"), "observatory": "http://127.0.0.1:18070",
                                     "state": str(state), "robots": {"duck": {"navigator": "127.0.0.1:18061", "gate": str(gate), "registration": str(folder / "registration.json"),
                                                                              "profile": str(state / "profiles" / "duck")}}}))
    inst = d.inst_mod.load(inst_file)
    mounts, notes = d.installation_mounts(inst, create=False)
    text = "\n".join(mounts)
    check("a dry look makes no folder: the profile store is a note until it is there", not (state / "profiles").exists() and any("profile store" in n for n in notes), notes)
    mounts, notes = d.installation_mounts(inst, create=True)
    text = "\n".join(mounts)
    check("the profile store is made when asked", (state / "profiles").is_dir())
    check("the installation file, the gate's folder (only the gate lives there), the robot's folder and the store are mounted at the same paths",
          all(f'source: "{p}", target: "{p}"' in text for p in (inst_file, gate_dir, folder, state / "profiles")), mounts)
    ro = {p: f'source: "{p}", target: "{p}", read_only: true' in text for p in (inst_file, folder, gate_dir, state / "profiles")}
    check("the installation and the robot's folder are read only; the gate's folder and the profile store are not (a socket is written to; versions are saved)",
          ro[inst_file] and ro[folder] and not ro[gate_dir] and not ro[state / "profiles"], ro)
    check("no mount makes a path that is not there (create_host_path false): a missing socket is an error, not a folder", all("create_host_path: false" in m for m in mounts))
    check("Mission Control gets no data folder, no index (RFC-0024 question 5: it reads runs through the Observatory's API)",
          str(tmp / "data") not in text and str(tmp / "idx.sqlite") not in text)

    shared = tmp / "duck-sim"
    shared.mkdir()
    gate2 = shared / "duck-a-gate.sock"
    keep += [listen(gate2), listen(shared / "duck-a.sock")]
    inst2 = d.inst_mod.parse({"installation": 1, "robots": {"duck": {"gate": str(gate2)}}}, tmp / "i2.json")
    m2, n2 = d.installation_mounts(inst2, create=False)
    t2s = "\n".join(m2)
    check("a gate's folder that holds the robot's own socket is not handed over: the gate's socket alone is mounted, and it is said",
          f'source: "{gate2}"' in t2s and f'source: "{shared}"' not in t2s and any("duck-a.sock" in n for n in n2), (m2, n2))
    gate2.unlink()
    m3, n3 = d.installation_mounts(inst2, create=False)
    check("... and with no gate socket yet it is not mounted at all, and it is said", not any(str(shared) in m for m in m3) and any("NOT mounted" in n for n in n3), (m3, n3))
    for s_ in keep:
        s_.close()

    ov = d.overlay({**S, "viewer_port": 18070, "control_port": 18060, "robots_dir": "/r"}, inst, t2, mounts, "actions")
    check("both containers share the host's network and publish no port (the published ones are reset)", ov.count("network_mode: host") == 2 and ov.count("ports: !reset []") == 2)
    check("both listen on loopback only: the Observatory's command says 127.0.0.1 and its port, Mission Control's environment too",
          '"--host", "127.0.0.1", "--port", "18070"' in ov and "MC_HOST: 127.0.0.1" in ov and 'MC_PORT: "18060"' in ov and "0.0.0.0" not in ov)
    check("the Observatory is told where Mission Control is; the health checks name the ports", 'OBSERVATORY_CONTROL: "http://127.0.0.1:18060"' in ov
          and "127.0.0.1:18070/api/v1/health" in ov and "127.0.0.1:18060/api/v1/health" in ov)
    check("Mission Control reads the installation by its own path, with HOME set so `~` means the same", f'ROBOTICS_LAB_INSTALLATION: "{inst_file}"' in ov and "HOME:" in ov)
    check("tokens for actions: MC_REQUIRE_TOKENS says so; with none asked it is not set", "MC_REQUIRE_TOKENS: actions" in ov
          and "MC_REQUIRE_TOKENS" not in d.overlay(S, inst, t2, mounts, None))

    # Docker drops a loopback resolver from a container's resolv.conf even on the host's network, so systemd-resolved's stub (the tailnet's
    # MagicDNS names, the telemetry hosts) went missing: telemetry could not resolve vm.tail6d0ed4.ts.net (2026-11-24)
    stub = t2 / "stub-resolv.conf"
    stub.write_text("nameserver 127.0.0.53\noptions edns0 trust-ad\nsearch tail6d0ed4.ts.net\n")
    link = t2 / "resolv.conf"
    link.symlink_to(stub)
    rm = d.resolver_mount(link)
    check("a host whose resolver is the loopback stub: Mission Control gets the stub's file as its /etc/resolv.conf, read only",
          rm is not None and f'source: "{stub}"' in rm and "target: /etc/resolv.conf" in rm and "read_only: true" in rm, rm)
    plain = t2 / "plain-resolv.conf"
    plain.write_text("nameserver 192.168.1.1\n")
    check("a host with an ordinary resolver: nothing is mounted (Docker's own copy works)", d.resolver_mount(plain) is None)
    check("no resolv.conf at all: nothing is mounted", d.resolver_mount(t2 / "missing") is None)
    ov_r = d.overlay(S, inst, t2, [*mounts, rm], None)
    check("the overlay carries it under Mission Control's volumes", "target: /etc/resolv.conf" in ov_r.split("mission-control:")[1])
    check("without an installation file Mission Control gets none", "ROBOTICS_LAB_INSTALLATION" not in d.overlay(S, None, t2, [], None))

    # --- tokens: auto -------------------------------------------------------------------------------------------------------------------
    cs = tmp / "cs"
    cs.mkdir()
    check("tokens auto, no store: none, with the warning and the command that makes one", d.pick_scope("auto", cs)[0] is None and "token create" in d.pick_scope("auto", cs)[1])
    con = sqlite3.connect(cs / "mission-control.sqlite")
    con.execute("CREATE TABLE tokens (id INTEGER PRIMARY KEY, client TEXT, hash TEXT, created_at REAL, revoked_at REAL)")
    con.execute("INSERT INTO tokens (client, hash, created_at, revoked_at) VALUES ('old', 'h', 1, 2)")
    con.commit()
    check("... a store whose only token is revoked: none", d.pick_scope("auto", cs)[0] is None)
    con.execute("INSERT INTO tokens (client, hash, created_at) VALUES ('page', 'h2', 1)")
    con.commit()
    con.close()
    check("... an active token: for actions only (RFC-0024 question 4)", d.pick_scope("auto", cs)[0] == "actions")
    check("... and what is asked for wins", d.pick_scope("all", cs)[0] == "all" and d.pick_scope("off", cs)[0] is None)

    # --- the record, and the rollback ---------------------------------------------------------------------------------------------------
    S2 = {**S, "deploy_state": str(tmp / "rec")}
    check("nothing is recorded to begin with", d.read_state(S2) == {})
    d.write_state(S2, one, one[:12], t1)
    st = d.read_state(S2)
    check("the first deploy records what is current and no previous", st["current"]["sha"] == one and st["previous"] is None)
    d.write_state(S2, two, two[:12], t2)
    d.write_state(S2, two, two[:12], t2)
    st = d.read_state(S2)
    check("the second makes the first the previous, and a redeploy of the same commit does not lose it", st["current"]["sha"] == two and st["previous"]["sha"] == one and len(st["history"]) == 3, st)
    check("the record is by project: another project's is its own", d.read_state({**S2, "project": "other"}) == {})
    calls = []
    real_deploy = d.deploy
    d.deploy = lambda s, sha, dry, browser=True, verb="deploy", one_origin=True: calls.append((sha, dry, verb, one_origin)) or True
    try:
        class A:
            dry_run, no_browser, commit = True, False, None
        ok = d.cmd_rollback(A, S2)
        check("rollback deploys the recorded previous commit", ok and calls == [(one, True, "rollback", False)], calls)
        try:
            d.cmd_rollback(A, {**S2, "project": "nothing-recorded"})
            check("rollback with nothing recorded says so", False)
        except d.DeployError as exc:
            check("rollback with nothing recorded says so, and how to record", "no previous deployment" in str(exc), exc)
        try:
            d.cmd_up(type("A", (), {"commit": None, "dry_run": False, "no_browser": True}), S2)
            check("a deploy with no commit is refused (it names what it deploys)", False)
        except d.DeployError as exc:
            check("a deploy with no commit is refused (it names what it deploys)", "--commit" in str(exc), exc)
    finally:
        d.deploy = real_deploy

    # --- a dry run changes nothing -----------------------------------------------------------------------------------------------------
    real_solo = d.solo_running
    d.solo_running = lambda project, context=None: ["abc"]
    dr = tmp / "dry-state"
    before = (tree_files(dr), tree_files(tmp / "data"), tree_files(tmp / "vs"), tree_files(tmp / "cs"))
    code, out = main_out("up", "--commit", one, "--dry-run", "--no-browser", "--project", "robotics-lab-dry", "--deploy-state", str(dr), "--installation", str(inst_file),
                         "--data", str(tmp / "data"), "--viewer-state", str(tmp / "vs"), "--control-state", str(tmp / "cs"), "--robots-dir", str(tmp / "robots"))
    # `one` is a commit of the temporary repository, not of this one: the dry run must refuse it, naming it
    check("a commit of another repository is not a commit here", code == 2 and "is not a commit" in out, out[-200:])
    here = d.resolve_commit("HEAD")
    code, out = main_out("up", "--commit", here, "--dry-run", "--no-browser", "--project", "robotics-lab-dry", "--deploy-state", str(dr), "--installation", str(inst_file),
                         "--data", str(tmp / "data"), "--viewer-state", str(tmp / "vs"), "--control-state", str(tmp / "cs"), "--robots-dir", str(tmp / "robots"))
    after = (tree_files(dr), tree_files(tmp / "data"), tree_files(tmp / "vs"), tree_files(tmp / "cs"))
    check("a dry run exits 0 and says it changed nothing", code == 0 and "DRY RUN END: nothing was changed." in out, out[-300:])
    check("... it names the project before anything else", out.splitlines()[0] == "project: robotics-lab-dry", out.splitlines()[0])
    check("... it changes no folder: no export, no overlay, no state, no data folder made", before == after and not dr.exists(), (before, after))
    check("... it prints the overlay, the compose commands, the solo project it would take down, and the record it would write",
          "network_mode: host" in out and "docker compose -p robotics-lab-dry" in out and "build" in out and "would: take down the solo project 'observatory' (running now: 1" in out
          and "rollback" in out and f"commit {here}" in out, out[-600:])
    code, out = main_out("record", "--commit", here, "--dry-run", "--deploy-state", str(dr))
    check("record --dry-run changes nothing either", code == 0 and not dr.exists() and "would record" in out, out)

    # --- --context: every docker call runs against the named engine (the X3's prod engine), by the flag and not by the environment ----------
    seen_ctx = []
    d.solo_running = lambda project, context=None: seen_ctx.append(context) or ["abc"]
    base_args = ["--dry-run", "--no-browser", "--project", "robotics-lab-dry", "--deploy-state", str(dr), "--installation", str(inst_file),
                 "--data", str(tmp / "data"), "--viewer-state", str(tmp / "vs"), "--control-state", str(tmp / "cs"), "--robots-dir", "/srv/elsewhere/robots"]
    saved_env = os.environ.pop("DOCKER_CONTEXT", None)
    try:
        code, out = main_out("up", "--commit", here, "--context", "prod", *base_args)
        dock = [ln for ln in out.splitlines() if ln.startswith("  $ ") and "docker" in ln]
        check("--context prod: a dry run exits 0 and prints docker command lines", code == 0 and len(dock) >= 4, out[-300:])
        check("... every one of them is `docker --context prod ...` (compose: `docker --context prod compose -p ...`)",
              all("docker --context prod " in ln for ln in dock) and any("docker --context prod compose -p robotics-lab-dry" in ln for ln in dock), dock)
        check("... including the solo project's `down`, and the solo project is looked for in that context", any(" down" in ln for ln in dock) and seen_ctx == ["prod"], (dock, seen_ctx))
        check("... --robots-dir may be a folder outside the checkout", 'source: "/srv/elsewhere/robots", target: /robots' in out, out[-300:])
        code, out = main_out("up", "--commit", here, *base_args)
        check("no --context: today's command lines, no --context flag", code == 0 and "--context" not in out and "  $ " in out and "docker compose -p robotics-lab-dry" in out, out[-300:])
        os.environ["DOCKER_CONTEXT"] = "default"
        code, out = main_out("up", "--commit", here, "--context", "prod", *base_args)
        check("DOCKER_CONTEXT differing from --context is refused, naming both, before anything is printed about a deploy",
              code == 2 and "DOCKER_CONTEXT" in out and "'default'" in out and "'prod'" in out and "project:" not in out, out)
        os.environ["DOCKER_CONTEXT"] = "prod"
        code, out = main_out("up", "--commit", here, "--context", "prod", *base_args)
        check("DOCKER_CONTEXT equal to --context is accepted", code == 0 and "DRY RUN END" in out, out[-200:])
        code, out = main_out("status", "--context", "other", "--deploy-state", str(dr))
        check("... the refusal holds for every verb (status here)", code == 2 and "DOCKER_CONTEXT" in out, out)
    finally:
        os.environ.pop("DOCKER_CONTEXT", None)
        if saved_env is not None:
            os.environ["DOCKER_CONTEXT"] = saved_env

    argvs = []
    real_run = d.subprocess.run
    d.subprocess.run = lambda cmd, **kw: argvs.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0, "", "")
    try:
        d.solo_running = real_solo
        d.solo_running("p", "prod")
        d.solo_running("p")
        d.cmd_status(type("A", (), {}), {**S2, "context": "prod"})
        d.cmd_status(type("A", (), {}), {**S2, "context": None})
    finally:
        d.subprocess.run = real_run
    docker_argvs = [a_ for a_ in argvs if a_[0] == "docker"]
    check("solo_running and status call `docker --context prod ps` with the flag, and plain `docker ps` with none",
          [a_[:4] for a_ in docker_argvs] == [["docker", "--context", "prod", "ps"], ["docker", "ps", "-q", "--filter"], ["docker", "--context", "prod", "ps"], ["docker", "ps", "--filter",
                                                                                                                                                         "label=com.docker.compose.project=robotics-lab-test"]], docker_argvs)

    # --- the smoke without the browser needs no uv, no Observatory environment: only the standard library ------------------------------------
    calls = []
    d.subprocess.run = lambda cmd, **kw: calls.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0, "", "")
    real_get = d._get
    d._get = lambda url, timeout=10.0: (200, json.dumps({"ok": True, "service": "mission-control", "required": False}).encode())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ok_nb = d.smoke(S, browser=False)
        calls_nb = list(calls)
        with contextlib.redirect_stdout(io.StringIO()):
            d.smoke(S, browser=True)
    finally:
        d.subprocess.run, d._get = real_run, real_get
    check("smoke --no-browser runs no subprocess at all (no uv, no Observatory venv), and passes on healthy answers", ok_nb and calls_nb == [], calls_nb)
    check("... and the browser smoke is the one that runs uv", [c_[0] for c_ in calls] == ["uv"], calls)

    # --- the stack's defaults are the deployed one's ---------------------------------------------------------------------------------------
    check("the defaults are the deployed stack's: project robotics-lab, the Observatory on 8070, Mission Control on 8060, loopback",
          d.DEFAULTS["project"] == "robotics-lab" and d.DEFAULTS["viewer_port"] == 8070 and d.DEFAULTS["control_port"] == 8060)
    mk = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    check("... and the Makefile's folders agree (data, the Observatory's state, Mission Control's state)",
          all(v in mk for v in (d.DEFAULTS["data"], d.DEFAULTS["viewer_state"], d.DEFAULTS["control_state"])))

print("test_deploy", "FAIL: " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
