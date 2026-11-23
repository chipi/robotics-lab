# Starting the NXT simulator

**Status:** written 2026-11-23 for plan unit D8. Every command and key below was checked by reading
the code (argparse, `Makefile`, the host and installation parsers) and, for `--help`, by running
it. None of sections 1 to 4 was started by hand: no server, no reset, no brick. Section 5 (unit D7,
`make sim-nxt`) was run, and its scenarios do much of what sections 1 to 4 describe, through the
API. What that leaves unchecked is in [Not verified](#not-verified). For the design behind it see
[NXT-D0.md](NXT-D0.md); for the real brick see [NXT-D1-CHECKLIST.md](NXT-D1-CHECKLIST.md).

## Why this exists

`nxt-web --sim` is a simulated NXT in a world: it integrates the two track powers into a pose,
stops at the scene's boxes, and reads the ultrasonic from the world, so the 15 cm obstacle stop
fires on a real distance. Mission Control drives it exactly as it drives the real brick, because
nxt-web is the robot's gate. Its numbers (0.3 m/s, 1.5 rad/s, turn slip 0.9, a 30 degree cone)
are assumptions until D1 measures them at the brick. Colour is not simulated.

## Quick reference

All paths are from the repository root (`/work/robotics-lab/main` on the workstation).

| What | Command |
| --- | --- |
| nxt-web venv, once | `make nxt-sync` |
| Mission Control venv, once | `make control-sync` |
| simhost venv, once | `make libs-sync` |
| nxt-web in the apartment | `apps/nxt-web/.venv/bin/nxt-web --sim --world scenes/apartment/scene.json --start 0 2 90` |
| Its truth | `curl -s http://127.0.0.1:8000/api/sim/truth` |
| Mission Control on the NXT | `ROBOTICS_LAB_INSTALLATION=<file> mission-control serve --robots apps/mission-control/robots.nxt-registered --state <dir>` |
| Reset through simhost | `simhost --host <host file> reset` |

`--start` takes metres, metres and **degrees** (counter-clockwise). The host file's `start` takes
metres, metres and **radians**. Mixing them up is the likeliest mistake in this recipe.

## 1. Start nxt-web in the apartment

```sh
make nxt-sync
apps/nxt-web/.venv/bin/nxt-web --sim --world scenes/apartment/scene.json --start 0 2 90
```

- `--sim` needs `--world` and cannot be combined with `--fake`; `--world` and `--sim-params` go
  only with `--sim` (the parser says so and exits).
- The default address is `http://127.0.0.1:8000`; `--host` and `--port` change it. Keep it on
  loopback: the page has no login.
- `--sim-params FILE` is a JSON file that overrides the world's parameters
  (`nxt_lab.world.WorldParams`: `speed_m_s`, `turn_rad_s`, `turn_slip`, the ultrasonic's
  `us_cone_deg` and others).
- The page is at `http://127.0.0.1:8000/`; its Drive tab drives the simulated robot, space fires.
- Recordings made in `--sim` go to `miniview/` in nxt-web's own data folder unless
  `--miniview-data` is given. Pass `--miniview-data "$OBSERVATORY_DATA"` only if a sim run should
  appear in the Observatory.

`make nxt-web-fake` is a different thing: a brick with made-up readings in no world.

## 2. Read the truth

```sh
curl -s http://127.0.0.1:8000/api/sim/truth
```

The answer is `{"wall_ns": <int>, "pose": [x, y, yaw]}`: the model's own pose, metres and
**radians**. It is read-only and needs no control lock. A server that is not running `--sim`
(`--fake` or a real brick) answers 404 `no truth`, never an invented pose. The truth is the
simulator's; the robot's belief (`/api/status`, Mission Control's state) has no pose for the NXT.

## 3. Drive it from Mission Control

Mission Control finds the NXT through its registration and an installation file, and nxt-web's
address comes from the installation, not from the robot file.

The files that are already in the repository, read:

- `robots/nxt-shooterbot/registration.json`: name `nxt-shooterbot`, its `profile.json`, and the
  one placement `workstation`.
- `robots/nxt-shooterbot/profile.json`: the stand-in profile with variants `sim` and `real`. In
  `sim` only the ultrasonic is declared; in `real` the colour sensor is declared too.
- `apps/mission-control/robots.nxt-registered/nxt-1.json`: the robot file. It names the robot
  (`"robot": "nxt-shooterbot"`) and the adapter `{"type": "nxt-web"}`, nothing else.

The old file `apps/mission-control/robots.nxt/nxt-1.json` still loads, and holds the robot itself
(no profile). Use `robots.nxt-registered` for the simulator.

### A test installation file

Write it outside the repository, and point to it with `ROBOTICS_LAB_INSTALLATION` so the
operator's own `~/.config/robotics-lab/installation.json` is not touched:

```json
{
  "installation": 1,
  "robots": {
    "nxt-shooterbot": {
      "registration": "/work/robotics-lab/main/robots/nxt-shooterbot/registration.json",
      "variant": "sim",
      "placement": "workstation",
      "connections": {"nxt-web": "http://127.0.0.1:8000"}
    }
  }
}
```

Save it as, say, `~/.config/robotics-lab/nxt-sim-installation.json`. Unknown keys are errors.
`variant` picks the profile's environment (`sim` or `real`); with none named the NXT runs as
`real`. `connections.nxt-web` must match the address nxt-web listens on.

### Serve and drive

```sh
make control-sync
export ROBOTICS_LAB_INSTALLATION=~/.config/robotics-lab/nxt-sim-installation.json
cd apps/mission-control
.venv/bin/mission-control serve --robots robots.nxt-registered \
  --state /tmp/mc-nxt-state --host 127.0.0.1 --port 8060
```

Use any state folder you do not mind losing in place of `/tmp/mc-nxt-state`. Then open
`http://127.0.0.1:8060/#robot/nxt-1`. The page's drive and STOP act through nxt-web's lock; the
facts line shows the ultrasonic's range and the `obstacle_stop` and `deadman_stop` flags.

The same from the API (routes from `apps/mission-control/CONTRACT.md`, all under `/api/v1`):

| Call | What |
| --- | --- |
| `POST /robots/nxt-1/lock` with `{"client": "me"}` | returns a `session` |
| `POST /robots/nxt-1/drive` with `{"vx": 0.15, "vyaw": 0, "session": "<session>"}` | a command lasts the deadman time (0.6 s), so a driver repeats it |
| `POST /robots/nxt-1/stop` | accepted always, needs no lock |
| `GET /robots/nxt-1` | `status`, with `sensors` and `flags` |

Drive toward a wall: the ultrasonic reads the wall's distance, and the robot stops at 15 cm with
`obstacle_stop` set until the next motion command or STOP.

## 4. Reset through simhost

`simhost` restarts nxt-web at the start pose and returns when it answers, is connected, and its
truth reads the start pose (within 1 mm and 1 mrad). Its second kind, `nxt-kinematic-sim`, is
chosen by the host file's `kind`. `simhost init` writes only the duck's host file, so the NXT's is
written by hand, for example `~/.config/robotics-lab/nxt-sim-host.json`:

```json
{
  "host": 1,
  "kind": "nxt-kinematic-sim",
  "robot": "nxt-1",
  "state": "~/.cache/nxt-sim",
  "nxt_web": {"url": "http://127.0.0.1:8000", "project": "/work/robotics-lab/main/apps/nxt-web"},
  "scene": "/work/robotics-lab/main/scenes/apartment/scene.json",
  "start": [0, 2, 1.5707963],
  "params": null
}
```

```sh
make libs-sync
libs/simhost/.venv/bin/simhost --host ~/.config/robotics-lab/nxt-sim-host.json show
libs/simhost/.venv/bin/simhost --host ~/.config/robotics-lab/nxt-sim-host.json reset
libs/simhost/.venv/bin/simhost --host ~/.config/robotics-lab/nxt-sim-host.json down
```

- Keys: exactly `host`, `kind`, `robot`, `state`, `nxt_web` (with `url` and `project`), `scene`,
  `start` and `params`. Any Pollen key (`pollen`, `cargo_bin`, `sockets`) is an error. `url` must
  be `http://host:port`. `params` is a path to a `--sim-params` file, or null.
- `reset [SCENE]` takes a scene.json path that replaces the host's for that start.
- `reset` starts `<project>/.venv/bin/nxt-web --sim --world ... --start ...` itself (so `make
  nxt-sync` first), keeps its pid and log in `state` (`nxt-web.pid`, `nxt-web.log`), and stops the
  one it started before starting again (SIGTERM, which takes nxt-web's stop-the-motors path).
- It refuses, saying so, if something at `url` answers that it did not start: **stop the nxt-web
  of section 1 first**, or use one or the other.
- It gives up after 15 s with the tail of `nxt-web.log`.
- A reset kills the nxt-web process, so its lock goes with it; take the lock again from Mission
  Control afterwards (my reading of the code, not run).
- `show` prints `# <file>` then the host as read; `down` stops the nxt-web it started.
- The line `standing, mapd listening` that `reset` prints is the duck's wording; for the NXT it
  only means the reset returned.

## 5. Runs, and `make sim-nxt`

Since D6 every Mission Control drive session leaves a run: the first session that holds the robot
starts nxt-web's recorder, the last one to let go stops it, and a recording someone else started on
nxt-web's page is never stopped by it. In `--sim` the run is `nxt/<scene>/<run>` in the folder
nxt-web records into (`$OBSERVATORY_DATA`, or `--miniview-data`), with the simulator's truth beside
the belief on every tick and the scene's id and sha256 in the run. The Observatory opens it like
any run.

`make sim-nxt` is the whole of this as one scenario, in the foreground, `PASS sim_nxt` and exit 0
at the end:

```sh
make sim-nxt                              # all six scenarios, about 40 seconds
make sim-nxt ARGS="--only wall,replay"    # drive, wall, stop, takeover, deadman, replay
```

It needs `make control-sync nxt-sync observatory-sync` (the target runs them), no Pollen and no
brick, and writes only into a folder of its own in the system temp dir (`--keep` leaves it). It
writes its own installation and host file, so neither of the operator's is read. It starts the
simulator through simhost (kind `nxt-kinematic-sim`) on a free loopback port and the Observatory's
server on another, and drives only through Mission Control's HTTP API: the lock, drive, STOP,
takeover.

- `drive` moves it and turns it on the spot, judged by the truth.
- `wall` runs at full speed into the north wall and checks the 15 cm stop against the scene file's
  wall, the alarm, and backing away.
- `stop` is STOP from a client that holds nothing; `deadman` goes quiet while holding the lock.
- `takeover` is refused on the process simhost started (nxt-web is given no takeover list there),
  then runs the same nxt-web command itself with a list, since simhost has no way to pass one.
- `replay` opens the wall run in the Observatory's API and finds the truth on every tick, ending
  where the live truth stopped.

## Verification

0. `make sim-nxt` does steps 1 to 4 below through the API and adds the run's replay.
1. Section 1, then `curl -s http://127.0.0.1:8000/api/sim/truth`: the pose is the start pose,
   about `[0.0, 2.0, 1.5708]`.
2. Drive forward from Mission Control or nxt-web's page, read the truth again: it moved along the
   heading.
3. Drive at a wall: `obstacle_stop` is set and the robot stops when the ultrasonic reads 15 cm.
4. `simhost ... reset`: the truth is the start pose again.

The tests that already cover this: `apps/nxt-web/tests/test_sim.py` (`make test-unit`),
`libs/simhost/tests/test_simhost.py` (in `LIBS_TESTS`), `apps/mission-control/tests/test_nxt_registered.py`
(`make test-control`) and `test_nxt_page.py`.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `--sim takes --world and is not combined with --fake` | `--sim` without `--world`, or with `--fake` |
| `no truth: this server is not running --sim` (404) | the server is `--fake` or a real brick |
| the robot starts facing the wrong way | `--start` is degrees, the host file's `start` radians |
| `.venv/bin/nxt-web does not exist` from `simhost reset` | run `make nxt-sync`, or fix `nxt_web.project` |
| `something already answers at ... that this reset did not start` | another nxt-web holds the port |
| Mission Control cannot reach nxt-web | `connections.nxt-web` in the installation file is wrong |
| the NXT shows as `real` with a colour sensor | the installation file names no `variant` |

## Not verified

- Sections 1 to 4 as typed: I did not run `nxt-web --sim`, `mission-control serve` or the
  `simhost` command line by hand. `make sim-nxt` ran the same pieces (simhost's reset and truth
  reader as a library, Mission Control's API, nxt-web's 15 cm stop at the apartment's north wall),
  so those are seen; the page at `#robot/nxt-1` and the Observatory's pages in a browser are not.
- The turn rate: Mission Control turns the tracks to plus and minus 50 % for the profile's 1.5 rad/s,
  while the world reads its `turn_rad_s` of 1.5 as the tracks at plus and minus 100 %. So a client's
  1 rad/s turned the simulated robot about 0.45 rad in a second (with the 0.9 slip), not 0.9. Which
  of the two is right is the brick's to say (D1, K16); `make sim-nxt` checks only the direction.
- That `(0, 2)` is free floor in the apartment: `make sim-nxt` starts there and the robot drove
  north from it, but I did not check it against every box of `scenes/apartment/scene.json`.
- That `~` is expanded in the installation file's `registration` (the parser calls a path helper
  I did not read); the example uses absolute paths.
- The request bodies of the API table are taken from the contract's table, not sent.
- The Body tab needs built meshes (`make robots-lego`, which needs the LDraw library); I did not
  check what the page shows without them.
- Nothing here touches the brick. The speeds and the turn slip are assumptions until D1.
