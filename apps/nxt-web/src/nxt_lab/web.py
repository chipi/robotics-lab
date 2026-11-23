"""Web UI to drive the NXT, watch and record its sensors, and manage programs on the brick.

    uv run nxt-web            # real brick over USB, http://127.0.0.1:8000
    uv run nxt-web --fake     # no hardware; a simulated brick with made-up readings
    uv run nxt-web --sim --world scenes/apartment/scene.json   # no hardware; a simulated brick driving in a world
"""

import argparse
import collections
import json
import math
import signal
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from nxt_lab import config as config_mod
from nxt_lab import deadman, diag
from nxt_lab.config import SENSOR_TYPES, Config
from nxt_lab.lock import Lock, LockError, load_names
from nxt_lab.recorder import RUNS_DIR, Recorder
from nxt_lab.robot import LINK_BACKENDS, FakeRobot, NxtRobot, SimRobot
from nxt_lab.world import World, WorldParams

INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_bytes()

# The page resends the drive command every 200 ms while a button is held. If those stop
# (button released without a stop, tab closed, wifi dropped), the watchdog stops the motors.
WATCHDOG_SECONDS = 0.6
MAX_UPLOAD_BYTES = 256 * 1024
EVENTS_FILE = "events.jsonl"  # the simulated brick logs to events-fake.jsonl instead
# Commands that move the robot, start something that does, or change what is on the brick: they pass the exclusive
# lock (RFC-0017). Config, connect and the reads stay open. An upload carries the file as its body, so its session is
# the `session` query parameter; every other call has it in its JSON body.
LOCKED_PATHS = ("/api/drive", "/api/fire", "/api/program/start", "/api/program/stop", "/api/files/upload", "/api/files/delete")


class Controller:
    def __init__(self, config: Config, fake: bool, config_path: Path, link: str = "auto", miniview_data: Path | None = None,
                 takeover_names=(), world=None):
        self.config = config
        self.config_path = config_path
        self.fake = fake
        self.world = world                # a World: the simulated brick drives in it (--sim); fake is True with it
        self.link_pref = link
        self.robot = None
        self.error = None
        self.last_drive = 0.0
        self._lock = threading.Lock()
        self.recorder = Recorder(self, miniview_data=miniview_data)
        self.started = time.monotonic()
        self.connected_at = None
        self.connects = 0
        self.call_ms = collections.deque(maxlen=200)
        self.call_errors = 0
        self.last_call_error = None
        self.events = collections.deque(maxlen=500)
        self.event_seq = 0
        self._events_lock = threading.Lock()
        self._last_drive_logged = (0, 0)
        self.events_path = RUNS_DIR / ("events-sim.jsonl" if world else "events-fake.jsonl" if fake else EVENTS_FILE)
        self.lock = Lock(self._stop_motors, takeover_names=takeover_names, event=self.event)

    def _stop_motors(self) -> None:
        if self.robot is not None:
            self.call(lambda r: r.stop())
            self._last_drive_logged = (0, 0)

    def event(self, kind: str, ok: bool = True, **detail) -> None:
        """One line in the command log: shown in the UI, appended to runs/events.jsonl."""
        with self._events_lock:
            self.event_seq += 1
            entry = {"seq": self.event_seq, "at": datetime.now().isoformat(timespec="milliseconds"),
                     "kind": kind, "ok": ok, **detail}
            self.events.append(entry)
            self.recorder.log_event(entry)
            try:
                self.events_path.parent.mkdir(parents=True, exist_ok=True)
                with self.events_path.open("a") as f:
                    f.write(json.dumps(entry) + "\n")
            except OSError:
                pass

    def connect(self, link: str | None = None) -> None:
        """Connect if not connected. With a link ("auto", "usb", "bluetooth") different from the
        current one, stop the motors, close, and reconnect over that link."""
        with self._lock:
            if link is not None:
                if link not in LINK_BACKENDS:
                    raise ValueError(f"link must be one of {sorted(LINK_BACKENDS)}")
                self.link_pref = link
            robot = self.robot
            if robot is not None:
                wanted = {"auto": robot.link, "usb": "usb", "bluetooth": "bluetooth"}[self.link_pref]
                if robot.fake or wanted == robot.link:
                    return
                self.robot = None
                try:
                    robot.close()
                except Exception:
                    pass
            try:
                self.robot = (SimRobot(self.config, world=self.world) if self.world else FakeRobot(self.config)) if self.fake \
                    else NxtRobot(self.config, self.link_pref)
                self.error = None
                self.connected_at = time.monotonic()
                self.connects += 1
                self.event("connect", link=self.robot.link, detail=self.robot.link_detail, asked=self.link_pref)
                self.event("stop on connect", ok=not self.robot.running_on_connect,
                           were_running=self.robot.running_on_connect)
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                self.event("connect", ok=False, asked=self.link_pref, error=self.error)
                return
        self.ensure_deadman()

    def sync_deadman(self) -> None:
        """Tell the robot whether robotd-lite is the running program."""
        robot = self.robot
        if robot is not None:
            self.call(lambda r: r.set_deadman(self.recorder.program == deadman.PROGRAM))

    def ensure_deadman(self) -> None:
        """In deadman drive mode, keep robotd-lite running whenever no other program runs: after
        connecting, and after a program stops."""
        if self.robot is None or self.config.drive_mode != "deadman":
            self.sync_deadman()
            return
        try:
            program = self.call(lambda r: r.current_program())
            if program is None:
                if deadman.PROGRAM not in {f["name"] for f in self.call(lambda r: r.list_files())}:
                    self.event("deadman start", ok=False,
                               error=f"{deadman.PROGRAM} is not on the brick: make nxt-programs, "
                                     "then upload apps/nxt-web/build/robotd.rxe in Programs")
                else:
                    self.call(lambda r: r.start_program(deadman.PROGRAM))
                    program = deadman.PROGRAM
                    self.event("deadman start", program=program)
            self.recorder.program = program
            self.sync_deadman()
        except Exception as exc:
            self.event("deadman start", ok=False, error=f"{type(exc).__name__}: {exc}")

    def call(self, action):
        robot = self.robot
        if robot is None:
            raise RuntimeError("not connected")
        started = time.monotonic()
        try:
            result = action(robot)
            self.call_ms.append((time.monotonic() - started) * 1000)
            return result
        except (ValueError, FileNotFoundError):
            raise
        except Exception as exc:
            self.call_errors += 1
            self.last_call_error = f"{type(exc).__name__}: {exc}"
            # Link errors mean the brick was unplugged, switched off or out of range: drop it so
            # Connect can be retried.
            if not robot.fake and _is_link_error(exc):
                self.robot = None
                self.error = f"{type(exc).__name__}: {exc}"
                self.event("link lost", ok=False, link=robot.link, error=self.error)
            raise

    def link_test(self, n: int = 20) -> dict:
        times = []
        for _ in range(n):
            started = time.monotonic()
            self.call(lambda r: r.ping())
            times.append((time.monotonic() - started) * 1000)
        times.sort()
        return {"n": n, "median_ms": round(times[n // 2], 1), "min_ms": round(times[0], 1), "max_ms": round(times[-1], 1)}

    def diagnostics(self) -> dict:
        robot = self.robot
        calls = sorted(self.call_ms)
        now = time.monotonic()
        recent = [s for s in self.recorder.samples if s["t"] >= self.recorder.samples[-1]["t"] - 10] if self.recorder.samples else []
        rate = (len(recent) - 1) / (recent[-1]["t"] - recent[0]["t"]) if len(recent) > 1 and recent[-1]["t"] > recent[0]["t"] else None
        return {
            "connected": robot is not None,
            "link": robot.link if robot else None,
            "link_detail": robot.link_detail if robot else None,
            "link_pref": self.link_pref,
            "firmware": robot.firmware if robot else None,
            "connected_for_s": round(now - self.connected_at) if robot and self.connected_at else None,
            "connects": self.connects,
            "server_up_s": round(now - self.started),
            "error": self.error,
            "calls": {
                "n": len(calls),
                "median_ms": round(calls[len(calls) // 2], 1) if calls else None,
                "p90_ms": round(calls[int(len(calls) * 0.9)], 1) if calls else None,
                "max_ms": round(calls[-1], 1) if calls else None,
                "errors": self.call_errors,
                "last_error": self.last_call_error,
            },
            "samples_per_s": {"configured": self.config.sample_hz, "actual": round(rate, 2) if rate else None},
            "host": {"usb_nxt_present": diag.usb_present(), "bluetooth": diag.bluetooth()},
        }

    def status(self) -> dict:
        robot = self.robot
        rec = self.recorder.recording
        out = {
            "connected": robot is not None,
            "fake": self.fake,
            "error": self.error,
            "program": self.recorder.program,
            "recording": None if rec is None else {"name": rec["name"], "rows": rec["rows"], "miniview": self.recorder.run_status()},
        }
        if robot is not None:
            out.update(self.call(lambda r: r.info()))
            out.update(left=robot.left, right=robot.right, shots=getattr(robot, "shots", None))
            calls = sorted(self.call_ms)
            out.update(
                link=robot.link,
                link_detail=robot.link_detail,
                link_ms=round(calls[len(calls) // 2], 1) if calls else None,
            )
        out["deadman"] = {
            "mode": self.config.drive_mode,
            "running": self.recorder.program == deadman.PROGRAM,
            "state": robot.deadman_state if robot is not None else None,
        }
        return out

    def drive(self, left: int, right: int) -> None:
        program = self.recorder.program
        if program and program != deadman.PROGRAM:
            raise RuntimeError(f"program {program} is running on the brick; stop it first")
        if not program and self.config.drive_mode == "deadman":
            raise RuntimeError(f"the deadman program {deadman.PROGRAM} is not running on the brick: "
                               "start it in Programs (upload apps/nxt-web/build/robotd.rxe first if it is not "
                               "listed), or choose direct drive in Setup")
        self.last_drive = time.monotonic()
        self.call(lambda r: r.drive(left, right))
        # The page resends a held drive every 200 ms; log only changes, not every keepalive.
        if (left, right) != self._last_drive_logged:
            self._last_drive_logged = (left, right)
            self.event("drive", left=left, right=right)

    def save_config(self, data: dict) -> Config:
        new = Config.from_dict({**self.config.to_dict(), **data})
        self.recorder.stop()
        config_mod.save(new, self.config_path)
        self.config = new
        if self.robot is not None:
            self.call(lambda r: r.configure(new))
            self.ensure_deadman()
        return new

    def watchdog(self) -> None:
        while True:
            time.sleep(0.1)
            self.lock.tick()
            robot = self.robot
            if robot is None or (robot.left == 0 and robot.right == 0):
                continue
            if time.monotonic() - self.last_drive > WATCHDOG_SECONDS:
                try:
                    self.call(lambda r: r.stop())
                    self._last_drive_logged = (0, 0)
                    self.event("watchdog stop", detail=f"no drive command for {WATCHDOG_SECONDS} s")
                except Exception as exc:
                    self.event("watchdog stop", ok=False, error=f"{type(exc).__name__}: {exc}")


def _is_link_error(exc: Exception) -> bool:
    import usb.core

    return isinstance(exc, (usb.core.USBError, OSError)) and not isinstance(exc, FileNotFoundError)


def make_handler(controller: Controller):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            quiet = ("/api/drive", "/api/status", "/api/live", "/api/sim/truth")
            if not self.path.startswith(quiet):
                super().log_message(fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data) -> None:
            self._send(code, json.dumps(data).encode(), "application/json")

        def _attachment(self, name: str, data: bytes, ctype: str) -> None:
            self._send(200, data, ctype, {"Content-Disposition": f'attachment; filename="{name}"'})

        def _route(self):
            url = urllib.parse.urlsplit(self.path)
            return url.path, {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD_BYTES:
                raise ValueError(f"body too large ({length} bytes, limit {MAX_UPLOAD_BYTES})")
            return self.rfile.read(length)

        def _handle(self, fn) -> None:
            try:
                fn()
            except FileNotFoundError as exc:
                self._json(404, {"ok": False, "error": f"not found: {exc}"})
            except Exception as exc:
                self._json(409, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

        def do_GET(self):
            path, q = self._route()
            c = controller
            if path == "/":
                self._send(200, INDEX_HTML, "text/html; charset=utf-8")
            elif path == "/api/status":
                self._handle(lambda: self._json(200, c.status()))
            elif path in ("/api/live", "/api/events"):
                since = q.get("since", "0")
                if not since.isdigit():
                    self._json(400, {"ok": False, "error": f"since must be a whole number, not {since!r}"})
                elif path == "/api/live":
                    self._json(200, {"samples": c.recorder.since(int(since))})
                else:
                    self._json(200, {"events": [e for e in list(c.events) if e["seq"] > int(since)]})
            elif path == "/api/sim/truth":
                # The simulator host's truth reader (simhost, RFC-0021 3.1): read-only, so open without the control lock.
                # Only --sim has a truth; a fake or a real brick answers 404, never a made-up pose.
                truth = getattr(c.robot, "truth", None)
                if truth is None:
                    self._json(404, {"ok": False, "error": "no truth: this server is not running --sim"})
                else:
                    wall_ns, pose = truth()
                    self._json(200, {"wall_ns": wall_ns, "pose": list(pose)})
            elif path == "/api/lock":
                self._json(200, c.lock.who())
            elif path == "/api/config":
                self._json(200, {"config": c.config.to_dict(), "sensor_types": SENSOR_TYPES})
            elif path == "/api/runs":
                self._json(200, {"runs": c.recorder.list_runs()})
            elif path == "/api/runs/download":
                ctype = "application/octet-stream" if q.get("name", "").endswith(".mcap") else "text/csv"
                self._handle(lambda: self._attachment(q["name"], c.recorder.run_path(q["name"]).read_bytes(), ctype))
            elif path == "/api/files":
                self._handle(lambda: self._json(200, {"files": c.call(lambda r: r.list_files())}))
            elif path == "/api/files/download":
                self._handle(lambda: self._attachment(q["name"], c.call(lambda r: r.download(q["name"])), "application/octet-stream"))
            elif path == "/api/diagnostics":
                self._handle(lambda: self._json(200, c.diagnostics()))
            elif path == "/api/events/download":
                data = c.events_path.read_bytes() if c.events_path.exists() else b""
                self._attachment("events.jsonl", data, "application/x-ndjson")
            elif path == "/api/files/view":
                def view():
                    data = c.call(lambda r: r.download(q["name"]))
                    self._json(200, {"name": q["name"], "text": data.decode("ascii", errors="replace")})
                self._handle(view)
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            path, q = self._route()
            c = controller

            # Every command except drive goes into the command log (drive logs its own changes).
            kind = path.removeprefix("/api/").replace("/", " ")
            detail = {}

            def act():
                body = self._body()
                data = json.loads(body or b"{}") if path != "/api/files/upload" else None
                result = {"ok": True}
                if path == "/api/files/upload":
                    detail.update(name=q.get("name"), bytes=len(body))
                elif data:
                    detail.update({k: v for k, v in data.items() if k not in ("sensors", "session")})
                if path in LOCKED_PATHS:
                    c.lock.check(q.get("session") if data is None else data.get("session"), path)
                if path == "/api/lock":
                    result.update(lock_action(c.lock, data))
                elif path == "/api/connect":
                    c.connect(data.get("link"))
                    result["connected"] = c.robot is not None
                    if c.robot is None:
                        raise RuntimeError(c.error or "not connected")
                elif path == "/api/linktest":
                    result["linktest"] = c.link_test()
                    detail.update(result["linktest"])
                elif path == "/api/drive":
                    c.drive(int(data.get("left", 0)), int(data.get("right", 0)))
                elif path == "/api/stop":
                    c.lock.stop_from(data.get("client") or "unnamed client")
                    c.call(lambda r: r.stop())
                    c._last_drive_logged = (0, 0)
                elif path == "/api/fire":
                    if not c.config.shooter_enabled:
                        raise RuntimeError("the shooter is switched off (Setup → Shooter enabled); its balls are small enough for a dog to swallow")
                    # robotd-lite drives only the tracks, so the shooter may fire under it.
                    if c.recorder.program and c.recorder.program != deadman.PROGRAM:
                        raise RuntimeError("a program is running on the brick; stop it first")
                    c.call(lambda r: r.fire())
                elif path == "/api/record/start":
                    result["recording"] = c.recorder.start()["name"]
                elif path == "/api/record/stop":
                    done = c.recorder.stop()
                    result["recording"] = done and done["name"]
                elif path == "/api/config":
                    result["config"] = c.save_config(data).to_dict()
                elif path == "/api/files/upload":
                    c.call(lambda r: r.upload(q["name"], body))
                elif path == "/api/files/delete":
                    c.call(lambda r: r.delete(data["name"]))
                elif path == "/api/program/start":
                    c.call(lambda r: r.stop())
                    if c.recorder.program:
                        c.call(lambda r: r.stop_program())
                    c.call(lambda r: r.start_program(data["name"]))
                    c.recorder.program = data["name"]
                    c.sync_deadman()
                elif path == "/api/program/stop":
                    c.call(lambda r: r.stop_program())
                    c.recorder.program = None
                    c.sync_deadman()
                    c.call(lambda r: r.stop())
                    c.ensure_deadman()
                else:
                    self._json(404, {"error": "not found"})
                    return
                if path not in ("/api/drive", "/api/connect"):
                    c.event(kind, **detail)
                self._json(200, result)

            try:
                act()
            except FileNotFoundError as exc:
                if path not in ("/api/drive", "/api/connect"):
                    c.event(kind, ok=False, error=f"not found: {exc}", **detail)
                self._json(404, {"ok": False, "error": f"not found: {exc}"})
            except LockError as exc:
                if path not in ("/api/drive", "/api/connect"):
                    c.event(kind, ok=False, error=str(exc), lock=exc.code, **detail)
                self._json(409, {"ok": False, "error": str(exc), "lock": exc.code, **exc.data})
            except Exception as exc:
                if path not in ("/api/drive", "/api/connect"):
                    c.event(kind, ok=False, error=f"{type(exc).__name__}: {exc}", **detail)
                self._json(409, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    return Handler


def lock_action(lock: Lock, data: dict) -> dict:
    """POST /api/lock {action: acquire | release | takeover | keepalive, client, session}."""
    action = data.get("action")
    client = data.get("client")
    if action in ("acquire", "takeover") and not (isinstance(client, str) and client):
        raise ValueError("client (the name of the program asking) is needed")
    if action == "acquire":
        return lock.acquire(client)
    if action == "takeover":
        return lock.takeover(client)
    if action == "release":
        lock.release(data.get("session"))
        return {}
    if action == "keepalive":
        return lock.keepalive(data.get("session"))
    raise ValueError("action must be acquire, release, takeover or keepalive")


def _raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to reach it from a phone on the LAN")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--fake", action="store_true", help="simulated brick, nothing moves")
    parser.add_argument("--sim", action="store_true", help="simulated brick in a world (needs --world): it drives, hits walls, and its ultrasonic sees them")
    parser.add_argument("--world", type=Path, help="the scene for --sim, e.g. scenes/apartment/scene.json")
    parser.add_argument("--start", type=float, nargs=3, metavar=("X", "Y", "YAW_DEG"), default=(0.0, 0.0, 0.0),
                        help="the simulated robot's start pose: metres, metres, degrees counter-clockwise (default 0 0 0)")
    parser.add_argument("--sim-params", type=Path, help="JSON file overriding the world's parameters (nxt_lab.world.WorldParams): speeds, turn slip, the ultrasonic's cone")
    parser.add_argument("--config", type=Path, default=config_mod.CONFIG_PATH, help="port setup file")
    parser.add_argument("--miniview-data", type=Path, help="the lab data folder the recordings are written to as miniview runs (default: $OBSERVATORY_DATA, else miniview/ in this program's data folder)")
    parser.add_argument("--takeover-names", type=Path, help="file of client names (one per line) that may take the control lock from its holder; empty: nobody")
    parser.add_argument("--link", choices=sorted(LINK_BACKENDS), default="auto",
                        help="auto tries USB, then Bluetooth (/dev/rfcomm*)")
    args = parser.parse_args()
    if args.sim and (args.fake or not args.world):
        parser.error("--sim takes --world and is not combined with --fake")
    if (args.world or args.sim_params) and not args.sim:
        parser.error("--world and --sim-params only go with --sim")
    world = None
    if args.sim:
        params = WorldParams.from_dict(json.loads(args.sim_params.read_text())) if args.sim_params else None
        x, y, yaw_deg = args.start
        world = World.from_scene(args.world, params, (x, y, math.radians(yaw_deg)))

    controller = Controller(config_mod.load(args.config), fake=args.fake or args.sim, world=world, config_path=args.config, link=args.link, miniview_data=args.miniview_data,
                            takeover_names=load_names(args.takeover_names))
    controller.connect()
    threading.Thread(target=controller.watchdog, daemon=True).start()
    threading.Thread(target=controller.recorder.run_forever, daemon=True).start()

    # The NXT's stock firmware has no deadman: a motor keeps its last command after this process
    # dies. SIGTERM (kill, systemd, a test harness) must take the same stop-the-motors path as Ctrl-C.
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)

    server = ThreadingHTTPServer((args.host, args.port), make_handler(controller))
    robot = controller.robot
    via = f"{robot.link} ({robot.link_detail})" if robot else f"not connected: {controller.error}"
    print(f"{'SIM robot' if args.sim else 'FAKE robot' if args.fake else 'NXT'}: http://{args.host}:{args.port}  via {via}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.recorder.stop()
        if controller.robot is not None:
            controller.robot.close()
        print("stopped: motors idled", flush=True)


if __name__ == "__main__":
    main()
