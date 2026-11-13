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
uv run nxt-web            # real brick, http://127.0.0.1:8000
uv run nxt-web --fake     # simulated brick with made-up readings, nothing moves
```

Tabs (also reachable as `#drive`, `#sensors`, `#programs`, `#setup` in the URL):

- **Drive** — hold a direction (or arrows / WASD) to drive, let go to stop; space fires.
  The page resends the drive command every 200 ms while held, and the server stops the
  motors if those stop arriving for 0.6 s (tab closed, connection lost).
- **Sensors & log** — live readings and chart of sensors, motor power and tacho counts.
  *Start recording* writes every sample to `runs/run-<date>-<time>.csv` (not committed).
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
