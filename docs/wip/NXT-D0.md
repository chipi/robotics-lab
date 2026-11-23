# NXT D0: what the second host kind needs, the NXT's sensors, and its profile route

**Status:** draft for the operator's review, 2026-11-23. Written with D2 (built) and before D3 and
D4 (not built). The defaults below are what D2, D3 and D4 are built on until the operator says
otherwise; each is numbered so a "no" names it. **Builds on:** [NXT-MVP1.md](NXT-MVP1.md) (unit D0),
RFC-0025 §3.4, §3.9, §3.10, §6.0, RFC-0021 §3.1.

**An ADR?** No project rule I found demands one. `docs/adr/README.md` gives a rule of thumb ("would
a future contributor need to know this to make a consistent change?"), and NXT-MVP1.md says "an ADR
is warranted: D0", which is the survey's opinion, not a rule. There is no `AGENTS.md` or `CLAUDE.md`
in this repository (checked at its root). I did not write one: this note is a set of defaults the
operator has not accepted, and RFC-0028 and profile v2 will supersede parts of it. If the operator
accepts it as the starting point of the host-kind contract, promote it to an ADR then.

**Evidence:** `file:line` and "read" mean I read it this session. "Ran" means a command, quoted.
Anything else is marked not verified.

## 1. What `simhost` needs for a second kind

What is the duck's today (read): `host.py` `KINDS = ("pollen-duck-sim",)`; `parse()` requires
`pollen` (the two checkouts), `cargo_bin` and the five socket names, and rejects any key it does not
know; `Host` has `microduck`, `microduck_rl`, `cargo_bin`, `sockets` as fields; `simulator.py` is
`duck-sim`, mapd and robotd, all Pollen's; `truth.py` `Body` speaks Pollen's body server and gives
`(pose, z, quat, sim_time)`. The runner and the robot registry read `host.truth_port`,
`host.sockets[...]`, `host.scenarios`, `host.scene_dir` (`labrunner/robots.py:65,71`,
`remote.py:106,151`, `scene.py:116`).

RFC-0021 §3.1 says a kind provides four things: reset, connections, a truth reader, a scene writer.
For the NXT:

| | `pollen-duck-sim` (built) | `nxt-kinematic-sim` (D3) |
| --- | --- | --- |
| Reset | restart duck-sim, about 40 s | restart `nxt-web --sim` with the start pose, about 1 s; settled when `/api/status` says connected and the truth reads the start pose |
| Connections | five sockets | one address: nxt-web's URL |
| Truth | Pollen's body server | `GET /api/sim/truth` on nxt-web: `{"wall_ns", "pose": [x, y, yaw]}` |
| Scene writer | MJCF from Pollen's scene | none: `SimRobot` reads `scene.json` itself |
| Sensors it simulates | depth grid, IMU, camera stand-in (RFC-0025 §3.9) | one range sensor (the ultrasonic) |

**What the NXT kind needs from `simhost`, and no more** (the minimal dispatch RFC-0028 starts from):

1. **`parse()` dispatches on `kind` first.** A table `KINDS = {kind: Kind(parse, reset, truth,
   simulates)}`: three functions and one tuple per kind. The duck's entry is today's code moved, not
   changed. Nothing else is generalised: no plugin registry, no entry points, no shared base class.
   Two kinds do not yet show what a base class would hold.
2. **Two host dataclasses, not one with optional fields.** `Host` stays as it is (the runner and the
   duck use its Pollen fields, and `make sim-duck` must stay green). The NXT kind returns
   `NxtHost(source, kind, robot, state, url, scene, start, params)`. A caller that needs
   `host.microduck` on an NxtHost gets an `AttributeError` at once. Cost: the runner's
   `host.truth_port` and `host.sockets` checks do not see an NxtHost; D3 gives it a `truth_port`
   property (nxt-web's port) and a `connections()` method, and no `sockets`.
3. **No Pollen keys for this kind.** `pollen`, `cargo_bin` and `sockets` in an NXT host file are
   errors (the parser already rejects unknown keys per kind), so a copy-paste of a duck file onto
   the NXT kind is caught. The NXT keys: `{"host": 1, "kind": "nxt-kinematic-sim", "robot": "nxt-1",
   "state": "~/.cache/nxt-sim", "nxt_web": {"url": "http://127.0.0.1:8000"}, "scene": "<path to
   scene.json>", "start": [0, 0, 0], "params": null}`.
4. **Truth as `(wall_ns, pose)`.** `SimRobot.truth()` (built, D2) returns `(time.time_ns(), (x, y,
   yaw))`, the model's ideal pose. `truthcopy.py` and `truth.py`'s `Sample` also carry `z` and a
   quaternion; the NXT reader fills `z = 0.0` and the quaternion from the yaw, and `sim_time = None`
   (the kinematic sim runs on the wall clock; it has no real-time factor to report). It is read-only
   and open without the control lock: it carries no command.
5. **A reset that returns only when settled** (RFC-0025 §3.4, decided). The contract in `simhost`:
   `reset(host, scene)` returns after a sample stamped after the reset has been read. The NXT kind
   meets it trivially (a restart answers its first status with the start pose), so **it does not
   exercise the contract**; Gazebo's `reset all` plus a post-reset `/odom` does, in RFC-0028. Said
   here so nobody takes the NXT for proof of it.
6. **Each kind declares which sensor kinds it can simulate** (RFC-0025 §3.9, rule 3): `simulates` is
   one tuple in the kind's entry. The NXT's is `("range",)`. D3 only records it; refusing a profile
   that asks for more is spike §16's proposal and is not built.

**Not needed from `simhost`, and why:** a scene writer (the kind reads `scene.json`); a sensor
simulator (nxt-web's `SimRobot` makes the readings, as the real robot's programs make the duck's); a
process supervisor beyond restart (the host file names how nxt-web is started: a command line is the
host's, not the kind's, and is D3's to decide: not decided here).

**What this does to RFC-0025:** step 4's "stub Gazebo host" starts from two working kinds and a
three-function table. It does not exercise the scene writer or the settled reset (RFC-0025 §6.0 says
so already).

## 2. The NXT sim's sensor declaration

Today's schema has two sensor kinds, `tof8x8` and `camera`, in the profile's `sensors` block
(`profile.py:190-199`, read), and a `sensors` block needs a `range_sensing` plugin (`NEEDS`, read).
RFC-0025 §3.5 says no generalisation of that schema beyond the one sensor that is real. So the NXT's
sensors do **not** go into the `sensors` block. They go into `capabilities.sensors`, a free-form
list (`capabilities` is `"any"` in the schema, read; `nxt-1.json` has the list, empty, today), as
plain entries:

```json
"sensors": [
  {"id": "ultrasonic", "kind": "range",  "port": "4", "source": "nxt-web", "range_m": 2.55},
  {"id": "colour",     "kind": "colour", "port": "3", "source": "nxt-web"}
]
```

- **`kind: "range"`: a single distance**, not a grid. The second sensor kind RFC-0025 expects
  (conflict 2 in NXT-MVP1.md): declared as a list entry with id, kind, port and range, nothing more.
  The cone, its mount height and its angle are **not** in the declaration: until D1 measures them
  they are the sim's parameters (`WorldParams`, below), and when measured they move into profile
  v2's `mount` and `fov`.
- **`source` names a connection** (the key in the installation's `connections`, section 3). Today
  every sensor's source is `nxt-web`. The Pi module adds entries with `source: "pi"` and the Pi's
  own kinds, with no change to the shape (RFC-0025 §3.10, "a source per sensor").
- **The colour sensor is declared and not simulated.** `scene.json` has no floor colour. The sim
  reads it as empty (`{"value": null, "label": null}`), not as a made-up value (D2). Rule 3 says a
  profile asking for a kind its host cannot simulate is refused at start, so the sim variant's
  `capabilities` omits the colour entry (a variant replaces an `"any"` block whole: `merge_variant`,
  read, not run). Alternative: a `"simulated": false` field. Default: the variant, no new field.
- **The 15 cm obstacle stop is not a sensor.** It is robotd-lite's behaviour on the ultrasonic's
  reading; in the sim it is `FakeDeadman`, firing on the world's distance (D2).

**D2's parameters** (`nxt_lab/world.py` `WorldParams`; every one is an assumption until D1 or D9
measures it):

| Parameter | Default | Where it comes from |
| --- | --- | --- |
| `speed_m_s`, `turn_rad_s` | 0.3, 1.5 | K16's assumed full speeds, the same two numbers as `nxt-1.json` |
| `turn_slip` | 0.9 | a guess; nothing measured it |
| `body_radius_m`, `body_height_m` | 0.10, 0.12 | the footprint the run format draws (`adapters/nxt.py` `FOOTPRINT`), nominal |
| `us_cone_deg`, `us_max_cm`, `us_resolution_cm` | 30, 255, 1 | memory of the sensor's data sheet, not checked against the brick; 255 is also robotd's `NO_ECHO` (`common.nxh`, read) |
| `us_forward_m`, `us_height_m` | 0.10, 0.08 | guesses; D1 measures height and angle (the operator's answer 2) |
| `us_rays` | 9 | a sampling choice: thin things (the apartment's 3.6 cm table legs) can fall between rays |
| `tacho_deg_s_per_power` | 9.0 | what `FakeRobot` uses; "about an NXT motor unloaded", not measured |

## 3. The NXT profile route

**The operator's answer 6:** a stand-in profile in today's schema now, migrated when profile v2
comes. Today's schema is duck-shaped: `footprint`, `locomotion` and `plugins` are required, and a
`locomotion` block needs a `locomotion` plugin. **Ran** (`runfile.profile.validate_profile` on a
candidate): `plugins: {}` with a `locomotion` block fails with "the locomotion block needs a
locomotion plugin"; with `plugins: {"locomotion": "nxt-tracks@1"}` the profile validates (printed
`OK`), with `capabilities.sensors` as above and `variants: {"sim": {}, "real": {}}`; without a
`locomotion` block it fails with "locomotion is required".

The stand-in (D4 builds it; nothing here is written to `robots/` yet):

```json
{"profile_version": 1, "id": "nxt-shooterbot", "label": "NXT Shooterbot", "kind": "nxt-shooterbot",
 "factsheet": {"typeSpecification": {"seriesName": "LEGO NXT 2.0 (8547)", "mobileRobotKinematics": "DIFFERENTIAL"}},
 "footprint": {"shape": "circle", "radius_m": 0.10, "height_m": 0.12},
 "locomotion": {"cruise_mps": 0.3, "yaw_max_rad_s": 1.5, "measured": "assumed", "why": "K16: not measured until D1"},
 "plugins": {"locomotion": "nxt-tracks@1"},
 "control": {"deadman_s": 0.6, "lease_s": 20.0, "takeover": []},
 "capabilities": {"sensors": [ ...as above... ]},
 "variants": {"sim": {"capabilities": {"sensors": [ ...the range sensor only... ]}}, "real": {}}}
```

The plugin name is a label nothing implements (the NXT has no navigator: `nxt.py:178-179` per
NXT-MVP1.md, not re-read). The two speeds move from the adapter file into `locomotion` (D4);
`nxt-1.json` with its own `full_speed_mps` and `full_turn_rps` keeps loading.

**Profile v2's decided shapes, taken now:**

| Shape | Decided in | In the stand-in |
| --- | --- | --- |
| A source per sensor | RFC-0025 §3.9, §3.10 | `source` on every `capabilities.sensors` entry (section 2) |
| Supported placements, in the registration | §3.8, question 18 | `registration.json` gets `"placements": ["workstation"]`; the Pi module adds `"robot"` or `"split"` (which names: not decided, §3.8 lists three placements) |
| The placement and the connector's address, in the installation entry | §3.8, question 18 | the robot's installation entry gets `"placement": "workstation"` and `"connections": {"nxt-web": "http://127.0.0.1:8000"}`; Mission Control reads the address from it, never a hard-coded localhost (NXT-MVP1.md); the Pi module adds `"pi": "http://..."` |

Both files reject unknown keys today (`registry.py:26,67-69` and `installation.py:29` `ROBOT_KEYS`,
read), so D4 adds `placements` to `REG_KEYS` and `placement` and `connections` to `ROBOT_KEYS`. The
key names are my defaults; RFC-0026 (the connector's address, §3.8) may rename them. **Not taken
now:** the `sensors` block for a range kind; `mount`, `fov` and noise per variant; a per-kind block
set; the plugin set made optional. Those are profile v2 (RFC-0025 step 2) and migrate the stand-in.

## 4. Room for the Pi module (MVP 2)

Nothing built; what the three decisions above leave open so it fits (RFC-0025 §3.10):

- **Two sensor sources.** `source` is a name, so the Pi's sensors are more list entries; the
  connector hides the source (§3.9).
- **Software on the robot.** `placement` is a per-robot, per-machine setting, and `connections`
  holds one address per machine, so a Pi-hosted connector is a different address in the same entry.
- **The sim.** A second source has no sim today: the host kind's `simulates` is the place a Pi
  sensor's simulator would be declared. Whether the sim runs the Pi's sensors is not decided.
- **The last-hop watchdog** covers both links (§3.3, §3.10); the Pi's link is not measured.
- Not decided: what the Pi runs, who runs the connector between the brick and the Pi, the Pi's
  sensors (the operator's, §3.10).

## 5. Defaults to confirm

| # | Default | If "no", what changes |
| --- | --- | --- |
| 1 | `KINDS` becomes a table of `(parse, reset, truth, simulates)`; nothing more is generalised | D3's size |
| 2 | Two host dataclasses: `Host` unchanged, `NxtHost` new | the runner's checks on `Host` fields |
| 3 | Reset is a restart of `nxt-web --sim`; no reset endpoint | an endpoint would need an answer to who may reset a robot someone holds the lease on |
| 4 | Truth is `GET /api/sim/truth` on nxt-web's own port, read-only, no lock, 404 outside `--sim` | D3's reader |
| 5 | Truth fills `z = 0`, a yaw quaternion, `sim_time = None` | `Sample` fields |
| 6 | The NXT's sensors live in `capabilities.sensors`, not the profile's `sensors` block | the schema generalisation RFC-0025 §3.5 forbids until a stub draws it |
| 7 | A range entry is `{id, kind, port, source, range_m}`; cone and mount are sim parameters until D1 | what moves to profile v2 |
| 8 | Colour is declared and not simulated; the sim variant omits it | a `simulated` field |
| 9 | Stand-in `plugins: {"locomotion": "nxt-tracks@1"}`, a label only | D4's profile |
| 10 | Registration `placements`, installation `placement` and `connections`, as named in section 3 | D4, RFC-0026 |
| 11 | The host file's `scene` is a path to a `scene.json`, `start` is `[x, y, yaw]` in metres and radians | D3's host file |
| 12 | No ADR now | the ADR on acceptance |

## 6. Not verified

- Nothing in sections 1 to 4 about D3 and D4 has been built or run; the table and the host file are
  design, not code. The only run behind this note is D2's test file and the profile check quoted
  above.
- That a restart of `nxt-web --sim` is fast and leaves nothing behind (an open recording, the events
  log): D3 measures it.
- That the runner's code outside the lines I read tolerates an `NxtHost` (`challenge.py`,
  `evaluate.py`, `go.py`, `explore_run.py` all call `simhost.load` and read `host.truth_port`): D3
  must read each before the dispatch lands.
- That `merge_variant` replaces `capabilities` whole: read in `profile.py:327-343`, not run with a
  list.
- Mission Control's use of `capabilities.sensors` (D5), the Body tab and the description for a robot
  with no registration.
- The sensor's cone, range, resolution and mount; the slip; the speeds: all assumptions (section 2).
- RFC-0026 and RFC-0028 are not written; the names in section 3 may change.
