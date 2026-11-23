# NXT D1: the checklist for the brick

**For:** the operator's visit to the brick this week (unit D1 of [NXT-MVP1.md](NXT-MVP1.md), item
4d). **Status:** prepared 2026-11-23 from what is in the repository. I ran none of it: nothing here
touched the brick. Each step names where it comes from; **"not verified"** marks anything I could
not check by reading code or by a run.

**Order of the day:** A (safety and setup) then B (the five scripts) then C (K15) then D (K16 and
the geometry) then E (the 15 cm stop and the ultrasonic) then F (the brick-side stop, for Bluetooth)
then G (what to write down). B before everything that moves the robot on the floor; F before any
drive over Bluetooth (D10).

## A. Before you start

- [ ] The robot is **lifted** (tracks off the floor) for every script marked MOVES in B. Back on the
      floor for D and E.
- [ ] No other process on the brick's link: **one connection at a time**. `nxt-web` stopped (`ps`
      for `nxt-web`; stop only your own). Rerun, the Lichtblick container and the deployed stack are
      not involved and stay as they are.
- [ ] USB: the udev rule is installed (`apps/nxt-web/70-lego-nxt.rules`, README step 1). The brick
      is on and shows in `lsusb` (not verified: the vendor id).
- [ ] `make nxt-sync` (the environment). `make nxt-programs` compiles `robotd.rxe` with `nbc` in
      Docker into `apps/nxt-web/build/`; a copy is already there (`build/robotd.rxe`, in the tree)
      but is it current is not verified, so rebuild (`make test-hardware` does it as its first
      step). Needs Docker: use the dev engine (`devengine start`), not the production socket.
- [ ] Battery: `hw_read_sensors.py` or the Setup tab shows it. Not verified: a threshold. Fresh
      batteries make the speed measurements in D repeatable.

## B. The five scripts, in the order `make test-hardware` runs them

`make test-hardware` does all of them (after a `[y/N]` prompt, `Makefile` target `test-hardware`),
one after the other, and stops at the first failure. Or run each by hand:
`apps/nxt-web/.venv/bin/python apps/nxt-web/tests/<script>`.

| # | Script | Moves the robot | What it does (its own docstring) | Pass |
| --- | --- | --- | --- | --- |
| 0 | `make nxt-programs` (inside `test-hardware`) | no | compiles `robotd.nxc` to `build/robotd.rxe` | a file in `build/`, no error |
| 1 | `hw_read_sensors.py` | no | stops any program, reads the colour sensor on port 3 and the ultrasonic on 4, five times | **prints only, no PASS line**: look for a number in cm (255 with nothing in range) and a colour name, and no `Error` in a line. Hold a hand 20 cm and 50 cm in front of the ultrasonic between readings: the numbers follow |
| 2 | `hw_link_speed.py` | no | Bluetooth only (`/dev/rfcomm0`): info, battery, 20 reads, median, min and max in ms. Skipped by the Makefile when `/dev/rfcomm0` is absent. | **prints only**: write the median and max down; they are D10's first numbers. USB is not measured by it |
| 3 | `hw_deadman.py` | **yes**, power 25 for about 1 s | uploads `robotd.rxe`, drives through its mailbox, stops sending, reads the motors directly | last line `DEADMAN PASS`: the tracks ran while commands came and stopped 0.4 to 0.9 s after the last one with the deadman flag set. This closes RFC-0001 §7 item 1 |
| 4 | `hw_stop_on_sigterm.py` | **yes**, power 30 for about 0.2 s | starts nxt-web, takes the control lock, drives, SIGTERMs it within 0.2 s, reads every motor | `SIGTERM-REAL PASS`: all motors idle, and the server said `stopped: motors idled` |
| 5 | `hw_stop_on_connect.py` | **yes**, power 25 | runs the tracks, drops the connection, starts nxt-web, reads the command log | `STOP-ON-CONNECT PASS`: motors idle and the log names ports B and C |

Notes, all from the scripts' text:

- `hw_deadman.py` drives with the forward flag off, so a table in front of the sensor does not
  trigger the obstacle stop; it does **not** test the obstacle stop (E does).
- `hw_stop_on_sigterm.py` and `hw_stop_on_connect.py` start `nxt-web` on ports 8763 and 8764; free
  those ports.
- After 3, `robotd.rxe` is left on the brick, stopped.
- Write each result (the last line, or the numbers) into G.

## C. K15: nxt-web's lock, page lock and adapter on the real brick

K15 (`docs/wip/KNOWN-ISSUES.md`): "The NXT's lock, page lock and adapter have never run on the real
brick." Tested on `nxt-web --fake` only (`make test-unit`, `make test-nxt-page`). The steps follow
NXT-MVP1.md Part 1, item 2.

1. Start nxt-web on the real brick, USB first: `make nxt-web NXT_LINK=usb` (from the repository
   root; default `http://127.0.0.1:8000`). For the takeover step, start the binary yourself with a
   names file instead: `apps/nxt-web/.venv/bin/nxt-web --link usb --takeover-names <file with one
   client name per line>` (the Makefile target does not pass `--takeover-names`).
2. Check on the page (Drive tab): connected, link `usb`, robotd (deadman) running, the status shows
   battery.
3. **Lease:** the Drive tab takes the control lock; hold a direction, the tracks move; let go, they
   stop.
4. **A second client is refused:** open the page in a second tab or call `POST /api/lock
   {"action":"acquire","client":"b"}`; expect a refusal that names the holder (`test_lock.py` has
   the exact answers, from the fake; the real brick's are not verified).
5. **STOP:** `POST /api/stop {}` from anyone stops the tracks and ends the lease (`lock.py`
   `stop_from`).
6. **Takeover:** a client on the names file takes the lock (`action: "takeover"`); one not on it is
   refused (`not_allowed`).
7. **Kill nxt-web** with `kill <its own pid>` while the tracks move: they stop within about 0.6 s
   (the server's watchdog) or at once (SIGTERM path); with `kill -9` only robotd's 0.5 s covers it:
   see F.
8. **The adapter:** start Mission Control with the NXT's robot file: `cd apps/mission-control && uv
   run --frozen mission-control serve --robots robots.nxt --state <a scratch folder> --port <free
   port>` (the `serve` flags are from `cli.py`; running it against `robots.nxt` is not verified).
   Check: the robot is online with `link: usb`, drive and STOP through the API move and stop the
   tracks, the lease is the one nxt-web holds, and after killing nxt-web the robot shows offline.
   The robot file's URL is `http://127.0.0.1:8000`; `control.lease_s` and `takeover` in `nxt-1.json`
   do not apply (they are nxt-web's, NXT-MVP1.md).
9. **The page lock in the browser** (`test_page_lock.py` does it headless against `--fake`): with
   Mission Control holding the lease, nxt-web's page shows it is held and refuses to drive; not
   verified on the real brick.

K15 closes when steps 3 to 8 each have a result in G. Fire (the shooter) stays on nxt-web's own
page, outside the gate; do not fire during the checks (`shooter_enabled` is off by default).

## D. K16: the speeds, the track width and the sprocket

K16: "The NXT's speeds are assumed, not measured (0.3 m/s, 1.5 rad/s full)." Both numbers are in
`apps/mission-control/robots.nxt/nxt-1.json` (`full_speed_mps`, `full_turn_rps`). The geometry
procedure is ADR-0013, "Calibration (the operator's to run; the robot on the floor)": calibrate on
the floor it will drive on, at the power it will use. Tools: a tape measure, masking tape, a
stopwatch or the recording's timestamps, a pen.

Record each run with nxt-web's Record button (Sensors and log tab): the CSV in `apps/nxt-web/runs/`
has the tacho counts of B and C (first and last rows) and `t`. Without the geometry set, the run has
no pose; that is expected.

1. **Straight speed** (K16, NXT-MVP1.md Part 1 item 3). Tape a line of at least 2 m on the floor.
   Drive both tracks at 100 along it, starting from rest, until the front of the robot passes the
   end mark. Speed = length / time over the steady part (skip the first 0.3 s). Three runs, take the
   mean. Also 50, for the curve: the model assumes speed is linear in power (not verified; measuring
   50 shows whether it is).
2. **Turn rate.** Tracks at +100 and -100 (spin in place), N full turns against a mark on the floor,
   N at least 3; turn rate = N * 2 pi / time. Three runs, mean. Also +50 and -50.
3. **Sprocket diameter `D`** (ADR-0013 step 1). Drive straight along a taped line of known length
   `L` (2 m or more), stop, and take the mean of the two tracks' counts in degrees, from the CSV's
   first and last rows: `delta = (|B_end - B_start| + |C_end - C_start|) / 2`. Then
   `D = L / (delta / 360 * pi)` in metres, with `L` in metres and `delta` in degrees. Three runs,
   mean. Nothing in the repo gives the sprocket's size (not verified): measure it across the teeth
   with callipers or a ruler too, and compare.
4. **Effective track width `W`** (ADR-0013 step 2). N spins in place (N at least 3), counted against
   a mark; `a_L` and `a_R` are the two tracks' counts over the spins, in degrees, as magnitudes: `W
   = (a_L + a_R) * D / (720 * N)`. Three runs, mean. `W` is not the distance between the track
   centres; it is the number that makes a measured turn come out right. Measure the centre distance
   with a ruler too, and write both down: the gap is the slip, which feeds the sim's `turn_slip`
   (D9). The ratio is not derived here; D9 does that.
5. **Set** `odom_sprocket_diameter_m` and `odom_track_width_m` in nxt-web's Setup (or
   `config.json`), and the two speeds in `nxt-1.json`. Check (ADR-0013 step 3): record a 1 m
   straight drive and a quarter turn, open the run in the Observatory, and compare the drawn pose
   with the floor. Adjust `W` for a turn that is short or long, `D` for a distance that is.
6. **Inversion and ports:** the config says B right, C left, positive power forward (checked
   2026-11-14, `config.py`). Confirm forward is forward when you drive 50/50 (a quick look, not a
   number).

## E. The 15 cm obstacle stop, and the ultrasonic's cone and mount

The obstacle stop is robotd's: with the forward flag set and `dist < 15` cm the program stops the
tracks, sets flag 2 and plays a 1500 Hz tone (`programs/robotd.nxc:76-79`, `MIN_CM 15`).
`hw_deadman.py` does not test it. The sim reproduces it from the ultrasonic reading (D2); this step
measures the real one so the sim can be set against it (D9).

1. Robotd running (nxt-web connects and starts it in deadman mode), robot on the floor, a box or a
   flat board in front.
2. From 60 cm away, drive forward at **power 25** from the Drive tab (low power: it coasts). Expect
   the tracks to stop and the page or `GET /api/status` (`deadman.state.obstacle_stop: true`,
   `dist`) to show it. **Measure with a ruler** the gap between the sensor's face and the box when
   the robot has stopped, and note the `dist` the program reported. Three runs; then at power 50 and
   100 (the stop distance will grow with speed: that is a finding, not a failure).
3. **Backing away is allowed:** after the stop, drive in reverse; it moves.
4. **A drive with the forward flag off does not stop** (turning in place near the box): confirm,
   with the box out of the way of the body.
5. **The cone.** Put a narrow thing (a bottle, a tube) 40 cm in front at the sensor's height. Move
   it sideways in 5 cm steps, reading `dist` in the Sensors tab (or `hw_read_sensors.py`): the
   offset at which the reading jumps to 255 is the half-width; `half angle = atan(offset / 40)`.
   Repeat at 80 cm. The sim assumes a 30 degree full cone: not verified against the brick.
6. **Mount:** measure the height of the sensor's centre above the floor, its distance forward from
   the middle of the body, and the tilt (a level on the sensor; the operator's answer 2: height and
   angle are measured here). These are the sim's `us_height_m`, `us_forward_m` and the angle that
   profile v2 will take.
7. **Min and max:** with a hand, note the smallest reading before it misbehaves (not verified: the
   sensor's minimum), and that nothing in range reads 255.
8. Optional: whether a table-leg-sized object (3.6 cm wide) at 1 m is seen at all (the sim's rays
   may miss it).

## F. The brick-side stop, for Bluetooth (before D10)

**Why:** RFC-0025 §3.3: the deadman is a last-hop watchdog on the computer wired to the motors. Over
USB nxt-web on the workstation is wired to the brick and has its own 0.6 s watchdog (`web.py`
`WATCHDOG_SECONDS`) and stops the tracks when a client stops sending; over Bluetooth a lost link
means nxt-web cannot stop anything, so **the brick must stop by itself when commands stop**. The
question for D10: does it?

**What the source says (read, not run on the brick):**

- `programs/robotd.nxc` does: it stops the tracks when no drive command arrived for `DEADMAN_MS 500`
  (lines 72-75), sets the deadman flag, and plays a tone. It also ends when the dark grey button is
  pressed (the firmware resets the motors). So **while robotd-lite is the running program, a lost
  link stops the tracks within about 0.5 s on the brick's own clock.**
- Nothing else does. The brick's stock firmware has no deadman: a motor keeps its last power after a
  lost link or a crashed server (`robot.py` comment in `NxtRobot.__init__`;
  `hw_stop_on_connect.py`). The other programs in `programs/` (`first`, `chase`, `patrol`) are not
  checked for a timeout (not verified; their source is not read here). Direct drive mode
  (`drive_mode: "direct"` in Setup) uses motor commands from the PC and **has no brick-side stop**.

**What to check on the day (all not run):**

1. **robotd's timeout on the brick over Bluetooth.** Pair and bind Bluetooth (README step 3, `sudo
   rfcomm bind 0 <address>`). **Unplug USB** so the script's `["usb", "devfile"]` backends fall
   through to Bluetooth (`hw_deadman.py` tries USB first). Run `hw_deadman.py` (robot lifted). Pass
   is the same line, `DEADMAN PASS`, with a stop time in 0.4 to 0.9 s. Over Bluetooth the script's
   exchange takes longer; if it prints FAIL for a missing answer or a late stop, that is D10's
   finding.
2. **Kill the sender mid-drive** (this is the case that matters): over Bluetooth, drive from
   nxt-web, then `kill -9 <nxt-web's own pid>` (SIGKILL: no stop-on-exit path runs). Time the tracks
   by eye and by the brick's tone: they should stop within about 0.5 s and the tone (300 Hz) should
   sound. Lifted robot.
3. **Drop the link** instead: switch the host's Bluetooth off (or walk out of range) while the
   tracks run. Same expectation.
4. **After a drop, with robotd not running:** start a different program or switch to direct mode,
   drive, kill nxt-web: the tracks **keep running** on the stock firmware. Confirm so, lifted, and
   stop them with the brick's dark grey button. This shows why Bluetooth must refuse direct mode and
   other programs (a D10 decision: not decided here).
5. **Latency against the 0.5 s:** `hw_link_speed.py`'s median and max over Bluetooth. If a normal
   command's round trip is near 0.5 s, robotd's deadman will trip while the link is fine; its
   `DEADMAN_MS` is compiled into the program (change it in `robotd.nxc`, `make nxt-programs`,
   upload). D10 sets the number; do not change it today.
6. **The page's keep-alive:** the page resends a held drive every 200 ms (README); over Bluetooth
   one send can take as long as the median above. Record whether a held drive stutters.

Write the answer to 1 to 4 in G as "stops by itself: yes/no, after N s".

## G. Write down

| Item | Result |
| --- | --- |
| Scripts: 1 `hw_read_sensors` (readings), 2 `hw_link_speed` (median, max ms), 3 `hw_deadman` (PASS/FAIL, stop after s), 4 `hw_stop_on_sigterm`, 5 `hw_stop_on_connect` | |
| K15 steps 3 to 8, each pass or fail, with the answer's text for a refusal | |
| Speeds: m/s at 100 (3 runs), at 50; rad/s at +100/-100, at +50/-50 | |
| Sprocket `D` (3 runs and the mean), track width `W` (3 runs, the mean), the ruler's track-centre distance | |
| 15 cm stop: `dist` reported and the measured gap at power 25, 50, 100; backing away; forward flag off | |
| Ultrasonic: half-angle at 40 cm and 80 cm, mount height, forward offset, tilt, smallest reading | |
| F: robotd stops by itself over Bluetooth (yes/no, after s); kill -9 mid-drive; link drop; direct mode keeps running (yes/no) | |

Then: the two speeds into `apps/mission-control/robots.nxt/nxt-1.json`; `D` and `W` into nxt-web's
Setup; close K15 and K16 in `docs/wip/KNOWN-ISSUES.md`; the ultrasonic's numbers and the stop
distances to the sim's `WorldParams` (D9). Those edits are the implementer's, not the day's.

## Not verified

- Every command and expected output above is from reading the repo (`Makefile`, the `hw_*` scripts,
  `robotd.nxc`, `web.py`, `lock.py`, ADR-0013, `config.py`); none was run, and nothing touched the
  brick.
- Mission Control against `robots.nxt` (C step 8): the flags are `cli.py`'s; that the robot comes up
  online against a real nxt-web has never been tried (that is K15).
- Whether `/dev/rfcomm0` is bound to the brick now (the unit-test run printed
  `bluetooth=['/dev/rfcomm0']`, so the node exists; that it is this brick's, and paired, is not
  verified).
- Whether `build/robotd.rxe` in the tree matches `robotd.nxc`; that `nbc` in Docker still builds
  here.
- The sprocket's size, the track width, the sensor's cone, minimum and mount: nothing in the repo
  records them (that is the point of the day).
- The other brick programs' behaviour when commands stop (F).
- Over Bluetooth: any number. D10 measures them; this checklist only collects the first ones.
