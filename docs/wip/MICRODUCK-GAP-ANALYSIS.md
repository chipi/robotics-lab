# Microduck platform against our platform: a gap analysis

**Status:** research note, 2026-11-28. Read-only: nothing was run, installed or changed. It answers
fourteen questions from the operator in the order asked. Recommendations are marked as such and
are not decisions.

## What was read, and at which commit

Pollen's clones, after `git fetch -q` (it succeeded), read at `origin/HEAD` with `git show` or an
archive of that commit. The local working tree of `microduck` is at `094d4bb4`, 100 commits
behind, so it was not used.

| Repo | origin/HEAD | Citation prefix |
| --- | --- | --- |
| /work/pollen/microduck | `4024f6ee`, 2026-11-25 | `microduck:` |
| /work/pollen/microduck_rl | `0daab160`, 2026-11-10 | `rl:` |
| /work/pollen/microduck-arena | `69ff0f0`, 2026-11-16 | `arena:` |
| /work/pollen/microduck-challenges | `5cee942`, 2026-10-30 | `challenges:` |

Ours: `/work/robotics-lab/mission-control`, branch `mission-control`, `1f2066b`. Its `apps`,
`robots`, `libs` and `docs` differ from `main` (`8560dba`) only in
`docs/wip/HANDOVER-TRAINING-2026-11-26.md` (`git diff --stat main`). Citations to it have no
prefix. `/work/microduck-nav`, `32ac389`, is cited as `nav:`.

Our simulator pins are older than Pollen's tip: `robots/duck/sim/pollen-pins.json:3-4` pins
`microduck` at `094d4bb4` and `microduck_rl` at `0daab160`. The second equals Pollen's current
tip; the first is 100 commits behind. `nav:pyproject.toml:45` pins `microduck_rl` at the same
`0daab160`.

## Short version

- Pollen ships a complete robot product: eight-plus daemons, a CLI, a BLE tool, signed updates,
  skills, emotions, voice, LEDs, NFC, a gamepad, a vet book and a training repo
  (`microduck:docs/design/architecture.md:16-110`).
- We use a thin slice of that product's RPC surface. Our code calls `robot.move`, `robot.stop`,
  `robot.health`, `robot.subscribe`/`robot.state`, `robot.look`, `robot.head`, `tof.stream`,
  `tof.frame`, `map.status` and `map.grid`. A grep for quoted `policy.`, `update.`, `media.`,
  `system.`, `net.` and `pad.` method names in `apps/mission-control/src`, `libs` and
  `robots/duck/src` found none.
- Our contribution beside Pollen's product is the lab around it: a lease and STOP gate, run
  recording and replay, a challenge course, profiles and plugins, goals, sites and a training
  pipeline for one navigation residual. None of it replaces what Pollen has on the robot.

## 1. Gap table

"Ours" cites our files; "none" means the grep above or a read of the named place found nothing.
"Gap" is a statement of fact; the recommendations are in section 14.

| Capability | What Pollen has | What we have | Gap |
| --- | --- | --- | --- |
| Version | `robotctl version`: what each daemon runs against what is installed, with warnings (`microduck:docs/robot/cheatsheet.md:16-22`); RPC `robot.modelApi` (`microduck:duck-ipc-proto/src/lib.rs:906`), `update.status` (`:887`) | none for a robot. Only simulator hosts are checked, against commits: `robots/duck/sim/pollen-pins.json:3-4`, `scripts/host-check` (RFC-0021 section 4, named in the pins file `why`) | We never ask a robot what it runs. A daemon serving old code would not be seen. |
| Health | `robotctl health`, exit code gates scripts (`cheatsheet.md:24-33`); RPC `robot.health` (`lib.rs:904`) | We use it: `duck_real.py:38` (link check), health limits in `robots/duck/profile.json:23-33`, alarms (`alarms.py`), readiness (`web/readiness.js`) | Small. We read `robot.health`; I did not verify which of its fields we use. |
| Monitor | `robotctl monitor`: requested against applied with the reason, joints, IMU, fall verdict, loop rate, ToF (`t`) and camera (`c`) blocks (`cheatsheet.md:35-60`, `1168-1286`) | Observatory live view and replay (`README.md:24-26`); Mission Control Body tab with joints (`web/index.html:176`, `rp-body-joints`); `robot.subscribe` stream (`duck.py:138`) | Different tool, similar content. Not compared field by field. No camera frame, no ToF block on the robot page (sim camera only: `profile.json:228`). |
| Configure, including video quality | `robotctl configure` edits `/var/lib/robot/robotd.toml` over `/etc/robot/robotd.toml`; `media.quality` `1080p30`/`720p30`/`720p15`/`360p30`, `media.source`, `media.bitrate`, `media.congestion_control` (`cheatsheet.md:181-252`, `deploy/robotd.toml:774-`) | none on the robot. Our Settings tab edits our own profile (locomotion, joints, sensors, localisation, looking) in versions (`web/settings.js:8-20`, `api.py:188-220`) | Two different things share the word. We cannot change any robot-side setting. No configure RPC exists in Pollen's method list either (`lib.rs:853-1375`): `robotctl configure` writes the file on the board with sudo. |
| Camera and video | `mediad`: WebRTC console, `media.frame` (`lib.rs:859`), PNG at `GET /frame`; quality above; since the security update the listeners bind `127.0.0.1` by default (`microduck:docs/design/remote-webrtc.md:3-8`) | none for the real duck: the camera is simulated (`profile.json:228`, `291`; `REAL-DUCK.md:70-74`) | No video, no real recogniser. Reaching `mediad` from our workstation needs a tunnel or an authenticated gateway. |
| Policies | official set on the Hub with a manifest, `policy check/update/load/add/remove/search/list` (`cheatsheet.md:254-402`); RPC `robot.policies`, `robot.loadPolicy`, `policy.fetch`, `policy.search` (`lib.rs:1113,1137,1160,1162`) | none against the robot. The walker is Pollen's `velstand.onnx` fetched by `duck-sim` (`docs/wip/MICRODUCK.md:94-95`; `nav:README.md:52`). Our one ONNX is a host-side navigation residual (`learned.py:1-20`) | We do not manage the robot's policies at all. |
| Slots | seven named defaults: `walk`, `stand`, `sitstand`, `ground_pick`, `kick_left`, `kick_right`, `roulade` (`cheatsheet.md:503-524`; `policy-channel-design.md:44-75`) | none | Not used. See section 4. |
| Skills | named on-request behaviours, `robot.do <name>`, `policy add`, a pad button (`cheatsheet.md:364-460`); RPC `robot.do`, `robot.skills`, `robot.setSkill` (`lib.rs:981,1300-1302`) | the field exists and is empty: `capabilities.skills: []` (`robots/duck/profile.json:236`); RFC-0003:34 names `robot.do {skill}`; only gate tests call `robot.do` (`libs/gate/tests/test_gate.py:96`) | No skill can be listed, asked or bound from Mission Control. |
| Test sequence | not found under that name (searched all of `microduck`, `rl`, `arena`, `challenges`). Nearest: `robotctl endurance` (random walk/stand/sit to empty battery, `cheatsheet.md:703-729`), `scripts/workout_test.py` (servo gear sweep, `:1-12`), `robot-boot-check`, `duck-control/examples/policy-rehearsal.rs` (`recurrent-policies.md:47-60`), Arena "Got a Talent" `timeline.json` (`challenges:README.md:22-31`) | the challenge course in simulation (`README.md:19-22`, RFC-0008); `lab-measure-walk` for the real duck, through the gate (`REAL-DUCK.md:13-15`) | Nothing runs a scripted check on a real duck. If "test sequence" meant something else, this row is unanswered. |
| Gamepad | Bluetooth pad via `padd`/`configd`; pairing; bindings; D-pad modes; Start/Select (`cheatsheet.md:731-895`, `pair-a-gamepad.md`); UDP pad via `netpadd` (`udp-pad.md`); RPC `pad.*` (`lib.rs:1293-1319`) | browser drive sends `vx`, `vyaw` only (`api.py:105-111`); no pad code found | See section 2. |
| Emotions | 13 shipped, keyframes plus wav, played by `robot.do` (`cheatsheet.md:461-486`; `robotd/src/emotion.rs:1-30`) | none. We already call `robot.head` (`duck_head.py:85,106`), the same RPC the emotions drive | Not exposed. |
| Voice | per-robot synthesised voice from the SoC serial: quack, greet, peck, chirp, coo, wheee (`cheatsheet.md:897-931`; `sounds/src/lib.rs:1-20`); RPC `robot.sound`, `robot.volume` (`lib.rs:1000,1128`) | none | Not exposed. |
| Face LEDs | twelve LEDs on the beta board, one owner daemon each: status, battery, network, camera, flashlight (`cheatsheet.md:1230-1250`; `architecture.md:388-411`); RPC `robot.flashlight` (`lib.rs:1003`) | none. Our health colours are our own UI (`web/readiness.js`) | Not used. The LEDs would tell a person standing at the robot what Mission Control knows. |
| NFC tags | `nfcd`: pair a pad, switch walk/roller/laser/soccer/autonomous, write tags (`nfc-tags.md:12-77`, `96-120`); RPC `nfc.write`, `nfc.read` (`lib.rs:1035,1042`) | none | A tag can switch the robot into a mode behind our back: `autonomous_mode` (`nfc-tags.md:25`). RFC-0002 section 3.6 says to watch `autonomous` and stop (`RFC-0002-robot-brain.md:178-183`). |
| Duck detector | `mediad` finds other ducks on the NPU, model versioned on the Hub, `robotctl duck-detector check/update`, `[duck_detector]` (`cheatsheet.md:302-318`; `deploy/robotd.toml:624-649`; `duck-detect/src/lib.rs:1-6`) | none. Our recogniser is simulated (`profile.json:228`) | Not applicable until a real camera feed exists. |
| Approved third-party policies | no "approved" list. Origin is `official` (org `pollen-robotics`), `community` or `local`; community fetch is off until `policy.allow_community`; no signature; the safety boundary is clamps, fall reflex and shape gate (`policy-channel-design.md:44-75`, `412-460`; `cheatsheet.md:332-362`); `policy search` (`:337`) | RFC-0031 section 7: a promotion record, a rule on frozen sets, operator-only (`RFC-0031-learning-in-the-lab.md:425-455`) for our own learned controller | We have a promotion rule for our model and nothing for a third-party robot policy. |
| Updater | `updaterd`: signed releases, health gate, rollback, `auto_apply`, run transcripts (`cheatsheet.md:1389-1495`; `updater-design.md:287-304`, `712-790`, `865-925`); RPC `update.*` (`lib.rs:881-894`) | none | We do not update or roll back a robot. The pins above are for simulator hosts. |
| Telemetry | anonymous usage events to PostHog EU, on by default, `telemetry.set` (`microduck:docs/robot/telemetry.md:3-60`) | OTLP to the operator's Victoria stack from Mission Control (`docs/wip/TELEMETRY.md:1-25`) | Different direction: ours is the lab's own, Pollen's is the robot's usage. We do not read or change the robot's telemetry switch. |
| Vet book | the robot's lifetime record (`cheatsheet.md:622-672`) | none | See section 7. |
| Autonomy | `autod`: stands, wanders, naps, chases a laser, plays with a ball, avoids walls with the ToF; `mapd` maps (`cheatsheet.md:1138-1166`; `autonomous.md:1-20`) | our navigator, which drives through `robot.move` and uses `mapd`'s map (`REAL-DUCK-LINK.md:12-17`) | Overlap by design: RFC-0002 says the two never drive at once (`RFC-0002-robot-brain.md:65`). |
| Power and body safety | `robot.init`, `relax`, `rest`, `rebootMotors`, `shutdown`; fall reflex; pickup detector pauses the policy (`cheatsheet.md:558-621`, `779-780`; `lib.rs:952-970,1093`) | `robot.stop` plus a zero `robot.move` as STOP (`RFC-0017:195-225`); our own tilt and battery guardrails (`profile.json:23-33`) | We cannot init, relax or reboot motors. |
| Identity, wifi, account, BLE | `configd`, `btd`, `duckctl` (`duckctl.md`), `net.*`, `system.*`, `account.*` (`lib.rs:1256-1279,1187-1191`) | none | Not needed for the lab loop; needed to set a robot up. |
| Simulated duck | `scripts/duck-sim`: the real daemons against a MuJoCo body (`microduck:docs/robot/simulation.md:1-30`) | we drive it: `libs/simhost`, `docs/wip/DUCK-SIM-FOR-AGENTS.md:1-22`, challenge course | Covered. See sections 11 and 12 for the actuator model. |
| Chorale, theremin, laser track, soccer, photos | `cheatsheet.md:932-1137`; `lib.rs:1017-1091,1046-1062` | none | Not wanted yet; listed for completeness. |
| Remote access | BLE (`duckctl`), WebRTC, ssh; one JSON-RPC contract on unix sockets (`architecture.md:16-110`, `229-310`) | ssh-forwarded unix sockets for `robot`, `depth`, `map` through `lab-link` and our gate (`duck_real.py:31-39`, `REAL-DUCK-LINK.md:12-24`) | We use one of Pollen's three transports. |

## 2. Gamepad

### How Pollen supports it

- **Bluetooth.** `padd` runs from boot and drives whatever pad connects; `configd` owns pairing
  (`cheatsheet.md:731-770`, `architecture.md:167-176`). `robotctl pad pair|forget|status`, or an
  NFC tag (`nfc-tags.md:18-20`).
- **Mapping.** Face buttons and bumpers run skills (six are bindable: `cheatsheet.md:450-460`);
  D-pad picks what the sticks mean (move, head, head+move, body+head); triggers are the mouth and
  the quack (`cheatsheet.md:773-800`). Axes and gains are config: `[pad_axes]`, `[pad_drive]`
  (`cheatsheet.md:674-701`).
- **Safety on the pad.** Start stands the robot up and toggles the policy; Select held 2 s sits
  it and cuts torque; held 4 s powers off (`cheatsheet.md:456-459`, `779-780`). "There is no stop
  button: release the sticks and the robot stands, and `robotd`'s deadman stops it"
  (`cheatsheet.md:805`).
- **UDP.** `netpadd` takes a 28-byte `DKPD` datagram of pad state over the LAN, with a stale
  limit of 300 ms and a silence timeout of 1000 ms (`udp-pad.md:67-73`). `duckctl
  udp-pad` is the sender. It is described as "a quick, unauthenticated LAN tool": anyone on the
  network who reaches the port can drive, stand, sit and power off the robot (`udp-pad.md:10-13`).
  Turning it on stops the Bluetooth pad (`udp-pad.md:22-26`).
- **No lease.** `robotd` keeps the last twist, last writer wins, and publishes `move.source` from
  the sender's `hello` name (`microduck:robotd/src/intents.rs:1-10`, `350-360`). Its own rule is a
  priority and handoff, with the physical controller able to preempt remote
  (`architecture.md:525-541`).

### What RFC-0017 requires of anything that drives

Lease bound to the connection, 10 to 30 s expiry, released on disconnect; no lease, no motion;
STOP accepted from any connection and latching, ending the holder's lease; takeover only by a
named list; the gate stops the robot with `robot.stop` and a zero `robot.move` wherever a lease
ends; the deadman (0.5 s) stays as backstop; our gate cannot see other doors and RFC-0002 says to
watch `move.source`
(`RFC-0017-robot-access.md:160-225`, `293-311`; `RFC-0002-robot-brain.md:178-183`).

### Options (not a decision)

| Option | How | Fits RFC-0017 | Costs and risks |
| --- | --- | --- | --- |
| A. Leave the pad alone; show it | The Bluetooth pad stays Pollen's. Mission Control reads `move.source` and `pad.status` and shows "driven by pad"; a goal run stops and reports, as RFC-0002 already says | Yes: it is the rule we wrote for "someone else drives" | Cheapest. We still cannot use a pad through Mission Control; our STOP does not stop a pad-driven robot except by `robot.stop`, which a stick then overrides. |
| B. Browser Gamepad API to `/robots/{id}/drive` | A page script reads the pad and posts `vx`, `vyaw` with the lease (`api.py:105-111`, lock routes `:114-134`); STOP on a fixed button posts `/robots/{id}/stop` (`:135`) | Yes, fully: the lease and STOP are ours | Only `vx` and `vyaw` exist in our drive call, so no head, body pose, skills or Start/Select. Browser focus loss must release the lease. |
| C. Mission Control as the UDP sender | The server sends `DKPD` datagrams to `netpadd` only while it holds the lease; STOP means it stops sending and the robot stops after `stale_ms` | Partly: the robot-side stop is Pollen's 300 ms, ours is advisory; the gate does not sit in this path | `netpadd` is unauthenticated, disables the Bluetooth pad, and any LAN host can drive. It bypasses the gate, so "no lease, no motion" is not enforced at the robot. |
| D. A pad client of the gate | A small local program on the operator's laptop: `hello` as `pad-<name>`, `gate.acquire`, then `robot.move`/`robot.head` through the gate, mapping Pollen's layout | Yes: it is a client like the navigator | Needs code. Skills and Start/Select need new gate-passed methods (`robot.do`, `robot.init`), which the gate treats as lease-needing already (`test_gate.py:95-96`). |
| E. Physical pad preempts | Keep the Bluetooth pad as the operator's override and make the gate yield: when `move.source` is the pad, release our lease and stop | Yes; it extends RFC-0017 section 3.8 | We lose the "no stop" guarantee for our goals while a pad is connected, so it should always stop the goal and report. |

Recommendation (mine): A now, because it is the rule we already wrote and costs the least; then
D or B once a real duck is reachable, because both keep the lease.

## 3. ONNX: packaging, loading, rates

### Pollen

- **Contract.** One float32 `obs [1, 61]` in, `actions [1, 14]` out, 50 Hz, observation
  normaliser baked into the file (`recurrent-policies.md:3-6`, `12-15`;
  `policy-manifest.md:59-62`; `rl:AGENTS.md`, command list, "bakes obs normalizer").
- **Recurrent.** An LSTM export adds `h_in`/`c_in` and `h_out`/`c_out`, matched by name, state
  limited to 1,048,576 elements, published as `model_api: 2` (`recurrent-policies.md:12-25`).
- **Loaded by** `robotd`'s control crate with ONNX Runtime 1.23 or later, a warm-up inference and
  a shape gate at load (`recurrent-policies.md:17-21`, `76-81`; `cheatsheet.md:516-518`).
- **Packaged as** a Hub repo with one `policy.onnx`, a `manifest.json` (schema 2: `kind`,
  `duration_s`, `entry_pose`, `command.encoding`, `obs_len`, `action_len`, `model_api`,
  `robot.model`, `training`, `eval`) and a README (`policy-manifest.md:1-85`). `uv run publish`
  in `microduck_rl` writes it (`policy-manifest.md:10-12`; `rl:AGENTS.md`, `publish`).
- **Refused before download** when `obs_len`, `action_len`, `model_api` or `robot.model`
  disagrees; absent fields are accepted (`policy-manifest.md:52-53`, `cheatsheet.md:359-362`).
- **Official set** at `pollen-robotics/microduck-policies`, `manifest.json` lists ten files, tags
  are versions (`policy-manifest.md:118-131`, `cheatsheet.md:526-556`).

### Ours

- **Contract.** One float32 input `(1, 1343)`, one output `(1, 3)`: residuals for forward,
  lateral and yaw in [-1, 1], added to the navigator's velocity command (`learned.py:1-12`,
  constants `:34`). The ONNX file is the Beta-head actor exported at opset 18, static batch 1
  (`nav:src/microduck_nav/nav_export.py:50-63`).
- **Loaded by** `onnxruntime` on the CPU, in Python, inside the navigator process on the host
  (`learned.py:243`), with identity `learned@<sha8>` (`learned.py:239`). The profile selects it
  as `local_controller` (`profile.json:240`).
- **Packaged as** a file plus metadata: ONNX metadata properties `task`, `policy_step_s`,
  `lateral_limit`, `obs_layout` (`nav_export.py:40-47`), or a sidecar `<model>.onnx.json`, or
  `--model-rate 50|10`; a model with none of those is refused (`learned.py:67-95`). No
  `manifest.json`, no Hub repo.
- **Rates.** 50 Hz (`Mjlab-Nav-MicroDuck`, lateral 0.12) or 10 Hz (`Mjlab-Nav-Deploy-MicroDuck`,
  lateral 0) (`learned.py:39`, `nav:src/microduck_nav/tasks.py:8-19`). The navigator asks every
  0.1 s (`learned.py:13`).
- **Where it runs.** Simulator only: "in the simulator only for now (R8 decides the real duck)"
  (`learned.py:1-3`; `RFC-0031:455-465`, section 7.3).

### Differences

| | Pollen | Ours |
| --- | --- | --- |
| Level | joint targets: 14 numbers at 50 Hz | velocity residual: 3 numbers at 10 or 50 Hz |
| Input | 61 proprioceptive and command numbers | 1343: ten ticks of history of 8x8 depth, pose and goal (`learned.py:20-37`) |
| Runs | on the robot, in `robotd`, inside its safety layer | on the host, above the navigator's guards; the walker below is Pollen's |
| Metadata | `manifest.json` schema 2, checked before download | ONNX metadata or sidecar, checked at construction |
| Distribution | Hub repos, tags, official/community/local | a file path and a profile version |
| Trust | clamps, fall reflex, shape gate | reflex, cliff stop, caps, lease, promotion rule (`RFC-0031:425-455`) |

Our network cannot be published as a Pollen skill: `obs_len` 1343 disagrees with 61, and the
manifest would refuse it (`policy-manifest.md:59`). Its natural counterpart in Pollen's design is
`autod`, an unprivileged client that reads `robot.state` and `tof.frame` and sends ordinary
intents back (`autonomous.md:11-20`).

## 4. Slots

- **Definition.** "A slot is what the robot runs by default — the walking gait, the standing
  network" (`cheatsheet.md:256-258`). Seven: `walk`, `stand`, `sitstand`, `ground_pick`,
  `kick_left`, `kick_right`, `roulade` (`cheatsheet.md:505-506`; `policy-channel-design.md:44-47`).
  Slots are config in `[policy]` (`deploy/robotd.toml:169`); `load` writes the choice into
  `/var/lib/robot/robotd.toml` and survives reboots and updates (`cheatsheet.md:507-509`).
- **Rules.** `walk` cannot be empty; `none` switches any other slot off; a failed load keeps the
  running policy; a missing file costs the slot, not the robot (`cheatsheet.md:511-524`).
- **Origins.** `official`, `community`, `local`; only official is a reset target and auto-updates
  (`policy-channel-design.md:44-75`).
- **Do we use them?** No. grep for `robot.loadPolicy`, `robot.policies`, `policy.` in our code
  found none (section 1 grep). Our walker is whatever policy set `duck-sim` installed under
  `~/.cache/duck-sim/policies/current/` (`nav:README.md:52`). I did not verify which official-set
  entry fills `walk`; the set's `manifest.json` lives on the Hub and is not in the clone.

## 5. Policies, skills and our model

### Pollen's definitions

- **Policy**: a trained network in one ONNX file the robot runs 50 times a second
  (`docs/wip/MICRODUCK.md:40-43`; `policy-manifest.md:1-13`).
- **Slot**: the default behaviour (section 4).
- **Skill**: "what it runs when asked: a kick, the roulade, a bow" (`cheatsheet.md:256-258`). Three
  kinds: backed by an episodic policy, driven by the daemon (ground pick, sit/stand), or an
  emotion with no network (`docs/wip/MICRODUCK.md:44-48`; `cheatsheet.md:271-275`). Adding one needs
  no daemon release: a manifest entry or `policy add` (`policy-channel-design.md:525-560`).
- Only a constant-command `episodic` policy can be a generic skill; gaits (`perpetual`) need a
  slot (`policy-manifest.md:46-48`).

### What we do today

- **Policy**: we do not manage the robot's; we train one navigation residual (section 3).
- **Skill**: a field and an idea, not a feature. RFC-0003 maps `robot.do {skill}` to "kicks,
  roll, emotions" for the duck and "fire, run an on-brick program" for the NXT
  (`RFC-0003-robot-interface.md:34`). Profiles carry `capabilities.skills` and VDA-style
  `protocolFeatures.mobileRobotActions`, and RFC-0014 marks irreversible ones
  (`RFC-0014-mission-control.md:277`). The NXT lists `fire` as an irreversible action
  (`robots/nxt-shooterbot/profile.json:9-11`); both robots' `skills` arrays are empty
  (`robots/duck/profile.json:48,236`, `robots/nxt-shooterbot/profile.json:34`). Firing runs in
  `nxt-web` behind its own lock, not through Mission Control (`apps/nxt-web/src/nxt_lab/web.py:38,
  433-439`), and the MCP server has no fire tool by design (`mcp_server.py:16`).

### The mapping

| Pollen | Ours | Note |
| --- | --- | --- |
| Skill | an entry in `capabilities.skills` plus an action in the factsheet, called by `robot.do` | An NXT "shooter shoots a ball" is exactly a Pollen skill: a named, asked, bounded action. Ours adds `irreversible`. |
| Policy | the implementation behind a skill (Pollen); a plugin or local controller (ours: `learned@sha8`) | Pollen's policy runs inside the robot; ours runs above it. |
| Slot | none | Pollen's default network is invisible to us; our nearest is the `locomotion` plugin, which only sends `robot.move` (`interfaces.py:16-30`). |
| Goal and mission | RFC-0014 goals; RFC-0030 missions | A layer above skills. Pollen has no equivalent beyond `autod`. |

### Managing, updating and approving someone else's policy

What Pollen does: pin by org and revision, off by default (`allow_community`), refuse on
manifest mismatch, sandbox by clamps, record the repo and revision in the vet book
(`policy-channel-design.md:420-445`). "Nothing a stranger publishes is verified by anybody"
(`cheatsheet.md:356`). The Arena races a policy server-side on five perturbed seeds
(`arena:README.md:16-27`), which is a vetting path Pollen offers but does not require.

A pipeline built from parts we have (recommendation, not built): fetch by commit; check the
manifest against `obs_len` 61, `action_len` 14, `model_api`; run it in `duck-sim` through a goal's
`sim_first` rehearsal (`PHASE5-REAL-DUCK-READINESS.md:43-45`); score it on frozen sets with the
promotion rule shape of RFC-0031 section 7.2; the operator signs a promotion record under a token
identity; only then call `policy.fetch`/`robot.loadPolicy` through the gate with
`allow_community` set for that run. The simulator's walking shortfall (section 11) limits what
such a rehearsal proves.

### Big picture

Pollen's stack answers "what can this robot do and which network does it" on the robot. Ours
answers "where should it go, and was it safe" on the host. They meet at `robot.move`. A skill
layer in Mission Control would give both: a catalogue read from the robot (`robot.skills`,
`lib.rs:1300`) shown beside our goals, called through the gate so the lease and STOP rules apply.

## 6. Emotions, voice, face LEDs

**Pollen.**

- Emotions: 13 shipped in `robotd/emotions/` (`*.json` keyframes plus `*.wav`), more in
  `/var/lib/robot/emotions/`; played by `robot.do <name>`, driving `robot.head`, `robot.pose`,
  `robot.mouth` and a zero `robot.move` through the same safety; sticks wait; a fall ends it
  (`cheatsheet.md:461-486`; `robotd/src/emotion.rs:1-30`).
- Voice: derived from the SoC serial so each duck sounds different; `robot.sound`,
  `robot.volume`; greets at start, pecks at shutdown; `audio.pet_detect` off by default
  (`cheatsheet.md:897-931`; `sounds/src/lib.rs:1-20`).
- Face LEDs: twelve on the beta board; one owner daemon per LED; status LED shows `robot.health`
  (`architecture.md:388-411`; `cheatsheet.md:1230-1250`).

**Ours.** None. We already use `robot.head` for looking (`duck_head.py:85,106`) so the RPC is
reachable; nothing exposes emotions, sound or LEDs. A person standing next to a robot gets no cue
from Mission Control; the LEDs and the greeting would be the cheapest one.

## 7. Vet book

Found. It is the robot's lifetime record, not a policy-vetting tool. `robotd` keeps
`/var/lib/robot/vetbook.json` from the first start through every update until reflash
(`cheatsheet.md:622-672`; `architecture.md:105`; `robotd/src/vetbook.rs`). It holds life stats
(hours awake, walking, standing, falls, pickups, every skill by name, boots, updates), per-joint
motor wear (torque hours, current, heat, trips, how long previous servos lasted), a dated diary
(updates, servo swaps, notes), and personal bests; `mediad` and `tofd` report tallies once a minute
(`cheatsheet.md:622-672`). RPC `robot.vetbook`, `robot.vetbookNote`, `robot.vetbookTally`
(`lib.rs:1120-1125`); `robotctl vetbook` shows it. `s` shares it to a public Hugging Face dataset
`<user>/<robot name>-vetbook`, with a card on the `microduck-vetbook` Space (source
`microduck:spaces/vetbook/`; `lib.rs:1196`; `remote-access-design.md:239-242`). A community policy
loaded is written to it as a dated event (`policy-channel-design.md:438-441`).

Ours: none. The closest things are our run records and alarms, which cover our runs, not the
robot's life. Servo wear matters for a duck that will be run for hours by a lab; I did not check
whether our `joint_overload` limits (`profile.json:7-22`) were derived from vet book fields.

## 8. Does each robot need its own terminal or mini UI in Mission Control?

**Short answer.** No, if the page stays data-driven; Pollen's own tools are per-robot
(`robotctl`, `duckctl`, a console), ours is generic by design, and the gap is that its data is
thin for the duck.

**What Mission Control has per robot today.** The robot page has five tabs:
Overview, Body, Modules, Settings and Calibration (`web/index.html:175-179`, `web/app.js:292`).

- Overview: readiness, alarms, parts, a body summary (`index.html:182-200`).
- Body: the 3D body posed from live joints, a joints table (`index.html:201-214`).
- Modules: the profile's plugins (locomotion, range sensing, localisation, looking, local
  controller) with a note that "Mission Control is not told what a plugin does while a goal runs"
  (`web/settings.js:74-99`).
- Settings: the profile in blocks, versions, diff, export, import (`settings.js:8-20`,
  `api.py:188-220`).
- Calibration (`api.py:225-250`).
- Around it: STOP and STOP ALL (`index.html:33-34`), the lock routes (`api.py:114-134`), goals,
  runs, sites, areas, objects (`api.py:262-440`), an MCP server with no fire, no takeover and no
  profile write (`mcp_server.py:14-20`).
- The page and tools "offer only what is there" from `capabilities` (RFC-0014 section 3.3.2,
  `RFC-0014-mission-control.md:240-285`).

**What is missing for the duck** against section 1: robot-side config; policies and slots; skills
and emotions; sound and LEDs; the camera; pad status and bindings; updates and versions; the vet
book; init/relax/reboot-motors. Our `robots/duck/profile.json` has `capabilities.skills: []` and
`mobileRobotActions: []`.

**Options** (mine): (1) extend the capabilities model so the generic page can render a Skills
card, a Robot-settings card and an Actions card from data the robot reports, with no per-robot UI;
(2) a per-robot "console" tab that proxies Pollen's own pages; (3) keep using `robotctl` over ssh
and do nothing in the page. Option 1 matches RFC-0014 and keeps the NXT and EV3 working the same
way. A duck-specific mini UI is justified only for things no other robot has, such as the vet
book.

## 9. Is our work only autonomy (navigation)?

No. Plainly, for the duck, besides autonomous navigation and the learned residual:

- **Operate:** Mission Control: robots and readiness, manual drive with a lease, STOP and STOP
  ALL, profile versions and diff, calibration, sites, areas and objects, a goal library, an MCP
  server, per-client tokens (`README.md:19-21`; `api.py`; `RFC-0014`).
- **Gate:** lease, latching STOP, takeover list, log (`RFC-0017`, `libs/gate`).
- **Record and explain:** the Observatory: every run as MCAP, live and replay, body in 3D, belief
  against truth, anomaly detection, video rendering (`README.md:22-26`, `apps/observatory/src`).
- **Test:** a 28-challenge course with truth judging and frozen scenario sets (`README.md:27-29`).
- **Simulator integration:** host files, resets, an agent-safe `duck-sim` runner
  (`libs/simhost`, `DUCK-SIM-FOR-AGENTS.md`).
- **Body model:** a URDF and meshes generated from Pollen's MJCF with an FK fixture
  (`robots/duck/from_mjcf.py:1-16`).
- **Real-duck preparation:** a link and gate to the robot, a safety review and measurement plans
  (`REAL-DUCK*.md`, `PHASE5-REAL-DUCK-READINESS.md`). No real duck is in the lab yet per
  `docs/wip/HANDOVER.md:122`; I did not verify its current arrival state.
- **Training:** `microduck-nav`, five registered tasks, 159 tests, a DGX run recipe and a promotion
  rule (`nav:README.md:3-13`, `RFC-0031`). Latest result from the git log: neither learned arm beats
  the rules (`bf0be18`, `afa5fab`).

What we have not built for the duck: anything on the robot (no daemon of ours, by RFC-0002's
non-goal "no code of ours on the duck", quoted in `RFC-0017:151`), no walker, no skill, no
emotion, no video, no configuration, no update, no gamepad.

## 10. microduck_rl

- **What it trains.** Mjlab tasks, flat and rough variants, each with a backlash twin
  (`rl:README.md`, Tasks table): Velocity (walk with head-pose commands), VelStand (walk plus fall
  recovery), StandUp, SitStand, GroundPick, BallKick, Roulade, Rollers (velocity, swizzle, crouch,
  slope, stand-up), Spin (`rl:src/mjlab_microduck/tasks/__init__.py:84-232`). Also a pickup
  detector (`rl:scripts/pickup_train.py`), a BAM test bench, a `publish` command and a
  `duck-body` simulator server (`rl:pyproject.toml:43-57`).
- **How a task is added.** A cfg module `tasks/microduck_<name>_env_cfg.py` with a
  `make_..._env_cfg()` and an RL cfg, new functions in `tasks/mdp.py`, and one
  `register_mjlab_task(task_id=..., env_cfg=..., play_env_cfg=..., rl_cfg=..., runner_cls=...)` in
  `tasks/__init__.py` (`rl:AGENTS.md`, Repo map; `tasks/__init__.py:84-90`). Other packages join
  through the `mjlab.tasks` entry point (`rl:pyproject.toml:40-41`), which the challenges repo does
  (`challenges:pyproject.toml:20-22`).
- **Does `microduck-nav` use it?** It depends on it and does not retrain a task of it. The
  dependency is `mjlab-microduck` pinned to `0daab160` (`nav:pyproject.toml:12,45`). It loads
  Pollen's `Mjlab-VelStand-Flat-Backlash-MicroDuck` cfg as a base (`nav:env_cfg.py:39,175-176`),
  rebuilds the walker from `velstand.onnx` and freezes it (`nav:walker.py:1-5`), and registers
  five new tasks of its own (`nav:tasks.py:8-40`). Its policy is the navigation residual, not a
  walker. The walker is never retrained.
- **What we use instead** for walking: Pollen's official walker. For new robot behaviours: nothing.

## 11. BAM

- **Pollen uses it.** `microduck_rl` depends on `better-actuator-models` from
  `Rhoban/bam`, branch `mjlab_frictionloss` (`rl:pyproject.toml:19,90`), imports `bam.mjlab`
  in `actuator/friction_dr_bam.py:24` and `testbench_constants.py:9`; the README says it "encodes
  the full sim2real recipe: BAM actuator physics" (`rl:README.md:19-23`). The arena has its own
  `actuator.py` (`arena:arena/actuator.py`).
- **In the simulator.** `docs/robot/simulation.md:21-22` says `duck-body` carries "the BAM
  actuator models the policies were trained against", while `design/simulation.md:228` lists them
  as modelled and `:362` says the body server runs the MJCF's position actuators and not BAM, with
  that as "the first suspect" for the forward shortfall. The two statements disagree; I did not
  run it.
- **Do we use it.** In training only, through `microduck-nav`: `better-actuator-models` is a
  direct dependency pinned to commit `62bd8ce` (`nav:pyproject.toml:13,38`; the tip `57d13ea`
  broke the import: `nav:docs/CHECKS.md:275-277`), and the kept event `expand_bam_friction_fields`
  comes with Pollen's base task (`nav:env_cfg.py:47`; `CHECKS.md:104-107`). In `robots/duck`,
  `libs` and `apps`: not found. grep for the word `bam` in those found only two prose mentions in
  `docs/wip` (`MICRODUCK.md:11`, `PHASE0-SPIKE.md:82`).
- **Consequence.** Our measured walk at 0.3 m/s gave 0.13 m/s (`docs/wip/MICRODUCK.md:99-108`),
  and our odometry scale of 0.91 is a calibrated patch (`profile.json:` sim variant,
  `odometry.scale`). Whether BAM would close that is unverified.

## 12. The MJCF model

- **Pollen's.** In `microduck_rl`: `src/mjlab_microduck/robot/microduck/robot_walk.xml`,
  `robot_groundcontact*.xml`, `robot_allcollisions*.xml`, each with a `_backlash` twin, exported
  from Onshape by `onshape-to-robot` from `config_mjcf_*.json`, plus scenes and the apartment
  (`rl:AGENTS.md`, Repo map). In `microduck`: `kinematics/assets/alpha/robot_walk.xml`, used by the
  FK test `kinematics/tests/fk_against_mujoco.rs`. Meshes are CC-BY-NC-SA 4.0
  (`docs/wip/MICRODUCK.md:4`; `rl:LICENSE-MODELS.md`).
- **Ours.** We do not own one. The simulator runs Pollen's pinned checkouts
  (`robots/duck/sim/pollen-pins.json:3-4`); our scene builder points the scene at
  `robot_allcollisions_backlash.xml` (`libs/runner/src/labrunner/scene.py:117-132`);
  `robots/duck/robot.json:3` names the file as free text; `from_mjcf.py` compiles it to
  `robot.urdf`, 23 MB of generated meshes (not committed) and `fk_fixture.json`
  (`from_mjcf.py:1-16`, default path hard-coded to `/work/pollen/...` at `:29-30`); probes carry
  the same absolute paths (`robots/duck/sim/probes/tof_rays.py:19`). `microduck-nav` gets its
  model through `mjlab_microduck` at `0daab160`.
- **Should it be in the profile or registration?** Trade-offs:

| For | Against |
| --- | --- |
| One declared source, commit and hash that sim, Observatory body and training all read, so drift between them is a check rather than a surprise (today the pins are in two files and a hard-coded path). | The profile is robot data with `sim`/`real` variants; MJCF is simulator data. Putting it in the profile blurs that line. |
| A hash of the MJCF in `robot.json` would catch an upstream change that regenerates the URDF differently. | The MJCF's meshes are non-commercial licence; the repo must not hold a copy, only a reference. |
| `registration.json` already names `payload`, `navigator_api` and `sim`. | The NXT and EV3 have no MJCF (`RFC-0011:132-133`); the field is optional. |
| Hard-coded paths would go. | The URDF conversion drops the passive backlash joints (`RFC-0011:127-128`), so the MJCF is not what the Observatory shows. |

Recommendation (mine): a structured `simulator` block in `robot.json` (commit, relative path,
sha256) read by `from_mjcf.py`, the probes and `host-check`; not the MJCF itself and not the
profile.

## 13. mjlab

- **Pollen uses it.** `microduck_rl` pins `mjlab==1.3.0` (`rl:pyproject.toml:17`) and registers
  tasks through the `mjlab.tasks` entry point (`:40-41`); the training repo is the only Pollen
  repo found with it as a dependency. `microduck` (Rust) has no Python dependency on it; its docs
  say the recurrent exports come from "mjlab/rsl_rl" (`recurrent-policies.md:3-4`) and manifests
  carry `Mjlab-...` task ids (`policy-manifest.md:104-106`). The challenges repo depends on
  `mjlab-microduck` (`challenges:pyproject.toml:12-13`); the arena pins mjlab's mujoco and
  onnxruntime (`arena:pyproject.toml:24-28`).
- **We use it** only in `microduck-nav`, transitively: `pyproject.toml` lists
  `mjlab-microduck` and not `mjlab` (`nav:pyproject.toml:11-18`), but the source imports
  `mjlab` in 20 or more places (`nav:src/microduck_nav/__init__.py:3`, `env_cfg.py:14-21`,
  `rl_cfg.py:13-14`, `tasks.py:3`), `uv.lock` resolves `mjlab 1.3.0` (`nav:uv.lock:901-939`) and
  the entry point is `mjlab.tasks` (`nav:pyproject.toml:61-62`). In robotics-lab: five files
  mention `mjlab` (`libs/simhost/src/simhost/host.py`, `controller_args.py`, `learned.py`,
  `from_mjcf.py`, `observatory/video/robots.json`); I did not verify that none imports it.

## 14. What to do first (my recommendation, ranked by value)

1. Add a read-only "robot facts" call to our duck adapter: `robot.modelApi`, `update.status`,
   `robot.policies`, `robot.skills`, `robot.vetbook`; show them on the Overview tab.
2. Watch `move.source`, `autonomous` and `pad.status` in state frames and stop and report, as
   RFC-0002 section 3.6 already requires (`RFC-0002-robot-brain.md:178-183`).
   **Correction, 2026-11-28:** the watch exists (`Gate.observe_state`,
   `libs/gate/src/robotgate/__init__.py:272-315`) but reads none of robotd's three fields;
   see RFC-0032 section 3.2.
3. Fill `capabilities.skills` for the duck from `robot.skills`, and route `robot.do` through the
   gate with a lease, so a skill (and an NXT fire) is one concept.
4. Decide the gamepad option (section 2); start with A.
5. Move the MJCF source, commit and sha256 into `robots/duck/robot.json`; stop hard-coding
   `/work/pollen/...` paths.
6. Bring the simulator pin for `microduck` forward from `094d4bb4` and re-run phase 1 and
   challenges 1 to 5 as `pollen-pins.json:2` requires.
7. Check whether `duck-body` really lacks BAM actuators (section 11); if so, measure the walk
   with them, because it bears on every sim result we publish.
8. Expose emotions and the greeting as safe skills for the first real run, so a person can tell
   Mission Control is connected.
9. Write our own promotion path for third-party robot policies on the shape of RFC-0031
   section 7, before anyone sets `allow_community`.
10. Add our own vet-book-like page: the robot's `robot.vetbook` plus our run history.

## Not covered

What I did not read or check, in more detail than what I did:

- **No code run.** No simulator, robot, installer or test was run. Every behaviour above is read
  from code or docs, not observed. The measurements quoted (0.13 m/s at 0.3 m/s) are from our
  own notes, not rerun.
- **Pollen: read.** `README.md`, `cheatsheet.md` (sections on version, health, monitor,
  configure, policies and skills, slots, power, pickup, vet book, joystick, endurance, gamepad
  mapping, voice, chorale, laser, soccer, autod, ToF, face LEDs, camera), `architecture.md`
  (services, invariants, LEDs, safety), `policy-manifest.md`, `recurrent-policies.md`,
  `telemetry.md`, `nfc-tags.md` lines 1-120, `udp-pad.md` lines 1-260, `policy-channel-design.md`
  sections 2, 9.2, 10, `deploy/robotd.toml` around `[duck_detector]`, `robotd/src/emotion.rs` and
  `intents.rs` headers, `sounds/src/lib.rs` header, the method list in `duck-ipc-proto/src/lib.rs`,
  `rl` README, `AGENTS.md`, `pyproject.toml`, the task registry, and READMEs of arena and
  challenges.
- **Pollen: not read or only skimmed.** `pair-a-gamepad.md`, `duckctl.md` (only headings and the
  first 40 lines), `nfc-tags.md` after line 120 (photo, e-ink), `udp-pad.md` after line 260,
  `updater-design.md` (headings only), `robotd-design.md`, `mapping-design.md`,
  `app-path-design.md`,
  `mobile-app.md`, `remote-access-design.md` (two lines), `webrtc-console.md`,
  `factory-provisioning.md`,
  `boot-recovery-net.md`, `restart-order.md`, the Rust source of every daemon beyond the headers
  named above (so no claim here about `padd`, `pad-map`, `btd`, `mediad` or `updater` internals),
  the vet book's Space code, `pet-detect`, `pickup.rs`, `maploc`, `mapd`, the docs under
  `docs/ideas`, `docs/project` and `docs/superpowers`, and the `spaces/` apps.
- **Pollen: absent from the clones.** The official set's live `manifest.json` (on the Hub), the
  `microduck_emotions`, `duck_detector`, `microduck_yocto` repos, `Rhoban/bam` and
  `mujocolab/mjlab` themselves. I used the local clones only and did not fetch upstream links, so
  BAM's and mjlab's own claims are not checked; only how Pollen and we depend on them.
- **Arena and challenges.** Only the two READMEs, one `pyproject.toml` each, and the file list.
  I did not read how an entry is scored, the workshop, the Space's policy upload path or the
  six challenge recipes.
- **Ours: read.** `registration.json`, `robot.json`, `profile.json` (selected blocks),
  `learned.py` (first 120 lines and the lines cited), `rules.py`, `interfaces.py` (header),
  `duck_real.py` (first 60 lines), `index.html` (tab structure), `settings.js` (headers and
  Modules), the route list of `api.py`, `mcp_server.py` headers, RFC-0017 sections 3.1 to 3.9,
  RFC-0003 section 2.1, RFC-0014 section 3.3, RFC-0031 sections 7.1 to 7.3, `MICRODUCK.md`,
  `REAL-DUCK.md`, `PHASE5-REAL-DUCK-READINESS.md`, the first lines of `TELEMETRY.md`,
  `DUCK-SIM-FOR-AGENTS.md`, `training/index.md`, and `README.md`.
- **Ours: not read.** RFC-0018, RFC-0024 and RFC-0030 beyond their status headers and, for
  RFC-0030, the table of contents, so nothing here asserts how missions would carry skills.
  Also `REAL-DUCK-SAFETY-REVIEW.md`, `REAL-DUCK-BACKLOG.md`, `REAL-DUCK-MEASURE.md`,
  `REAL-DUCK-LINK.md` after its first 30 lines, `apps/observatory` code and `CONTRACT.md`,
  `libs/gate` and `libs/runner` source (only the lines cited), `nav/run.py` and the rest of
  `duck_lab/nav`, the fake and NXT adapters, `docs/training` pages 1 to 7, and the NXT code
  except the `fire` route lines cited.
- **microduck-nav.** Read: `README.md`, `pyproject.toml`, `tasks.py`, `walker.py` header,
  `nav_export.py` lines 1-65, `env_cfg.py` selected lines, `R7.md` first 40 lines, `M2.md` greps,
  `CHECKS.md` selected lines. Not read: the observation, reward, impairment and room modules,
  `M1.md`, `M2D.md`, the tests, `uv.lock` beyond the `mjlab` lines.
- **Claims I did not verify.** Which official-set file fills the `walk` slot; whether the real
  duck has arrived; which `robot.health` fields we read; whether the five robotics-lab files that
  name `mjlab` only mention it; the exact set of RPC methods our `libs/runner` and `libs/gate`
  forward (my method grep was over quoted literals and could miss calls built from variables);
  whether Pollen's "test sequence" means something I did not find; whether the line numbers
  of Pollen's docs match the Hub's rendering (they match `origin/HEAD` text).
