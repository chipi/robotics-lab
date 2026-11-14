# nxt — LEGO Mindstorms NXT 2.0

Drives an NXT brick (stock LEGO firmware) from Python using
[nxt-python](https://github.com/schodet/nxt-python) over USB.

## One-time setup

1. USB permission (Linux). Install the udev rule, then unplug and replug the brick:

   ```sh
   sudo cp 70-lego-nxt.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules
   ```

2. Python env (already done if `.venv/` exists): `uv sync`

3. Bluetooth instead of USB (optional). Needs `rfcomm` (Arch: `bluez-deprecated-tools`).
   On the brick: Bluetooth → On, and Visibility → Visible. Then pair once (the NXT's default
   PIN is `1234`; confirm it on the brick too) and bind the serial port:

   ```sh
   bluetoothctl            # then: scan on / pair 00:16:53:0F:4C:2A / trust 00:16:53:0F:4C:2A
   sudo rfcomm bind 0 00:16:53:0F:4C:2A
   ```

   The code tries USB first, then any `/dev/rfcomm*`. The udev rule above also lets the
   logged-in user open `/dev/rfcomm*`. A bind does not survive a reboot.

## Run

Plug the brick in by USB and switch it on, then:

```sh
uv run scripts/hello.py              # name + battery, nothing moves
uv run scripts/hello.py --motor A    # turn motor A 180 degrees at low power
```

## Web UI

```sh
make nxt-web                       # real brick, http://127.0.0.1:8000 (from the repo root)
make nxt-web NXT_LINK=bluetooth    # or usb / auto; NXT_HOST, NXT_PORT too
make nxt-web-fake                  # simulated brick with made-up readings, nothing moves
uv run nxt-web --help              # the same, from nxt/
```

**Anywhere, in Docker** (`nxt/Dockerfile`; config and recordings in the `nxt-web-data` volume):

```sh
make nxt-image                     # build robotics-lab/nxt-web:dev
make nxt-image-run                 # run it with this machine's USB and /dev/rfcomm* devices
```

The image runs as root inside the container, because it needs the robot's device nodes, and
publishes the port on `127.0.0.1` only: the UI has no login, so reach it through an ssh tunnel.
On another machine, that machine needs the udev rule, and for Bluetooth the pairing and
`rfcomm bind`, as below.

Tabs (also reachable as `#drive`, `#sensors`, `#programs`, `#setup` in the URL):

- **Drive** — hold a direction (or arrows / WASD) to drive, let go to stop; space fires.
  The page resends the drive command every 200 ms while held, and the server stops the
  motors if those stop arriving for 0.6 s (tab closed, connection lost).
- **Sensors & log** — live readings and chart of sensors, motor power and tacho counts.
  *Start recording* writes every sample to `runs/run-<date>-<time>.csv`, and the samples plus the
  command log to `runs/run-<date>-<time>.mcap` for Foxglove, Lichtblick or Rerun (not committed).
  Saved runs can be plotted again or downloaded.
- **Programs** — files on the brick: upload (e.g. a compiled `.rxe`), run, stop, view
  or plot text/CSV files a program wrote, download, delete. While a program runs, the
  PC stops reading sensors (reading can change a sensor's mode under the program) and
  driving from the UI is disabled; tacho counts are still logged.
- **Setup** — which motor port is left / right / shooter, inverting a side, what sensor
  is on each port (NXT analog sensors cannot be auto-detected), samples per second.
  Saved to `config.json`.

**STOP ALL** in the header brakes the drive motors and stops any running program.

`--host 0.0.0.0` makes it reachable from other devices on the LAN (the firewall may
still block the port).

## Programs that run on the brick (NXC)

Programs are written in [NXC](https://bricxcc.sourceforge.net/nbc/) (C-like) under
`programs/` and compiled by the `nbc` compiler in Docker (`toolchain/Dockerfile`, Debian's
`nbc` package; nothing is installed on the host). The image is built on first use.

```sh
scripts/nxc.sh programs/first.nxc     # -> build/first.rxe
```

Then upload and run `build/first.rxe` from the web UI's Programs tab. Compile errors
name the file as `build/<name>.nxc` (an nbc quirk); the line numbers are right.

## Working without a cable

- **Programs on the brick** (`first`, `chase`, `patrol`) need no link while they run: upload,
  unplug, start them from the brick's menu (My Files → Software files), reconnect later to read
  their CSV log. The link is only for uploading before and reading the log after.
- **Live control from the PC** (the UI's drive pad, live charts, recording) needs a link the whole
  time: USB, or PC Bluetooth (`/dev/rfcomm0`; about one room of range). Measured on 2026-11-14:
  about 41 ms per command over Bluetooth with nothing else running; set the sample rate to 2/s
  for Bluetooth (5/s is fine on USB).
- **Drive through the deadman program** (Setup → Drive through: deadman, the default). It needs
  `robotd.rxe` on the brick: `make nxt-programs`, then upload `nxt/build/robotd.rxe` in Programs;
  Connect starts it. In direct mode, if the link drops, the motors keep their last command.

## The robot as checked (2026-11-14)

Shooterbot build. Motors: A shooter, B right track, C left track; positive power drives both
tracks forward. Sensors: colour on 3, ultrasonic on 4 (reports type "Sonar"); 1 and 2 free.
Brick: stock firmware 1.28 (protocol 1.124), Bluetooth address `00:16:53:0F:4C:2A`, about
55–59 KB free flash.

## Known issues

- **The deadman program is not yet checked on the real brick.** Stock firmware keeps a motor's
  last command; `robotd.rxe` (RFC-0003 §2.3) stops the tracks 0.5 s after commands stop, and
  passes against the simulated brick. Until `hw_deadman.py` passes on the brick, treat a dropped
  link as leaving the motors running. In direct mode that is always so.
- **Only one program at a time may talk to the brick.** A second connection on the same
  `/dev/rfcomm0` (or USB) scrambles replies; on 2026-11-14 it hung the running `nxt-web`, whose
  Bluetooth reads have no timeout. Stop `nxt-web` before running scripts against the brick.
- **"Command time" in the diagnostics includes waiting for other commands** (live sampling shares
  the link), so it reads higher than one command alone: over Bluetooth about 170–190 ms median
  while sampling, against 41 ms measured with nothing else running.
