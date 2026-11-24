# Deploying the platform (phase 5 item 4c)

The Observatory and Mission Control, one origin, from a named commit. `scripts/deploy.py` is the
whole procedure; the `make` targets wrap it. It replaces `make stack-up` for the machine that
runs the robot: that target builds whatever the checkout holds under the tag `local`, gives
Mission Control no robot, and leaves a solo Observatory project holding the port.

## The one-line commands

```bash
make deploy COMMIT=<sha>            # build it, replace what runs, record it, run the smoke
make deploy-dry COMMIT=<sha>        # the same, printed: nothing is done
make deploy-rollback                # deploy the commit that ran before the current one
make deploy-smoke                   # the smoke alone, against what runs now
scripts/deploy.py record --commit <sha>   # say what runs now was built from <sha> (no container touched)
```

`scripts/deploy.py --help` lists the flags (`--project`, `--viewer-port`, `--control-port`,
`--installation`, `--tokens`, ...). The defaults are the deployed stack's: project
`robotics-lab`, the Observatory on 8070, Mission Control on 8060, the data and state folders of
the Makefile, `~/.config/robotics-lab/installation.json`.

There is no default commit. A deploy names what it deploys: a sha, or a ref that resolves to
one. The files come from `git archive <sha>` into `<deploy-state>/trees/<sha12>` (default
`/work/robotics-lab/state/deploy`), never from the working tree, and stay there; the images are
`observatory:<sha12>` and `mission-control:<sha12>`, so nothing is built over the tag `local`.

## What a deploy does

1. Resolves the commit, prints the project name and what it will use.
2. Exports the commit's files, writes the overlay (below) next to the record, and checks it with
   `docker compose config`.
3. Builds both images. The running stack is untouched until now.
4. Takes down the solo Observatory project (`observatory`) if it runs: after the build, so the
   viewer is down only for the switch.
5. `docker compose up -d --wait`: both containers healthy.
6. Writes the commit to `<deploy-state>/<project>.json` (`current`, and the one before it as
   `previous`). `rollback` reads this.
7. The smoke: both health checks, Mission Control through the Observatory's address, `/lib/`
   served by both, what `GET /tokens` says against what the deploy asked for, and the pages in
   headless Chromium (the Observatory's 3D page, Mission Control's page from `/control/` and from
   its own port, the robot page of each robot, the newest run's watch page) with no console error
   and no failed request. It ends `SMOKE PASS` or `SMOKE FAIL`, and the deploy `DEPLOY PASS` or
   `DEPLOY FAIL` (exit 0 or 1).

A deploy that fails its smoke leaves the stack up and recorded, and says so; `make deploy-rollback`
returns to the one before it. A rollback leaves out the checks of the one origin, because the
commit it goes back to may predate the proxy; the tokens check stays, so a commit that does not
know `actions` fails it instead of starting with no tokens.

The first deploy has nothing to roll back to. Before it, say what runs now was built from
`36670fb` (`scripts/deploy.py record --commit 36670fb`); a rollback then rebuilds that commit with
the same overlay.

## The overlay

`deploy.py` writes a compose file over the repository's two (`scripts/deploy.py --dry-run`
prints it). The repository's files stay as they are for `make stack-up`.

| What | Why |
| --- | --- |
| Both containers on the host's network, 127.0.0.1 only, published ports reset | The navigator API is TCP on the host's loopback (`127.0.0.1:8061` in the installation file): a bridged container cannot reach it. With the host's network the file's addresses mean the same inside as outside. |
| `OBSERVATORY_CONTROL=http://127.0.0.1:<control port>` | The Observatory proxies Mission Control at `/control/` (RFC-0024 step 3). |
| The installation file, read only, at its own path; `HOME` as the host's | `~` in the file means the same path inside. |
| Each robot's gate: the socket's folder when nothing else that is a socket lives there, else the socket alone, else nothing | The container reaches the robot only through the gate (RFC-0017). The sim's `~/.cache/duck-sim/` holds robotd's own socket: its gate needs a folder of its own, or a restart of Mission Control after the gate restarts. |
| Each robot's registration folder, read only | The description and the meshes. |
| The profile store `<state>/profiles`, read write, made if missing | Mission Control saves versions. |
| Under the same UID | `MC_UID` and `MC_GID` are the deploying user's. |
| No data folder, no index in Mission Control | It reads runs only through the Observatory's API (RFC-0024 question 5). |
| Health checks on the configured ports | The images' own name 8070 and 8060. |

Tokens (RFC-0024 question 4): `--tokens auto` (the default) turns on `actions` when the state
folder holds an active token, and otherwise says so and runs with none, because Mission Control
refuses to start with tokens required and none made. Make the first with
`docker compose -p <project> exec mission-control mission-control token create --client page`, then
deploy again. The page asks for the token when an action is refused; STOP never needs one.

## What it does not do

- It does not start the gate, the navigator or the simulator; they run on the host.
- It does not make the profile store's first version (`runfile.profilestore.Store.seed`).
- It does not give Mission Control robot files of its own: the default is the commit's
  `robots.example` (the fake robot). `--control-robots <folder>` names a folder with the duck's file
  (`robots.sim/duck-sim.json`).
- The Observatory's `robots/` (descriptions, meshes) is the checkout's, because `make robots`
  makes the meshes there and git does not hold them: `--robots-dir`.

## Proof, on a test stack

Another project (`robotics-lab-test`), other ports (18070, 18060), folders under
`~/.cache/robotics-lab-tests`, a test installation file; the deployed stack was never touched.

```bash
make sim-deployed COMMIT=<sha> ROOT=<folder> PROJECT=robotics-lab-test VIEWER_PORT=18070 CONTROL_PORT=18060
```

It starts the simulator, the gate and the navigator as `make sim-duck` does, deploys twice (the
second after a token exists), starts a point goal from the page at `/control/` of the
Observatory's address, and checks that the duck got there, that the run is in the Observatory,
what the container was given, and the smoke after it.
