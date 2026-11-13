"""Web UI to drive the NXT, watch and record its sensors, and manage programs on the brick.

    uv run nxt-web            # real brick over USB, http://127.0.0.1:8000
    uv run nxt-web --fake     # no hardware; a simulated brick with made-up readings
"""

import argparse
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from nxt_lab import config as config_mod
from nxt_lab.config import SENSOR_TYPES, Config
from nxt_lab.recorder import Recorder
from nxt_lab.robot import FakeRobot, NxtRobot

INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_bytes()

# The page resends the drive command every 200 ms while a button is held. If those stop
# (button released without a stop, tab closed, wifi dropped), the watchdog stops the motors.
WATCHDOG_SECONDS = 0.6
MAX_UPLOAD_BYTES = 256 * 1024


class Controller:
    def __init__(self, config: Config, fake: bool, config_path: Path):
        self.config = config
        self.config_path = config_path
        self.fake = fake
        self.robot = None
        self.error = None
        self.last_drive = 0.0
        self._lock = threading.Lock()
        self.recorder = Recorder(self)

    def connect(self) -> None:
        with self._lock:
            if self.robot is not None:
                return
            try:
                self.robot = FakeRobot(self.config) if self.fake else NxtRobot(self.config)
                self.error = None
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"

    def call(self, action):
        robot = self.robot
        if robot is None:
            raise RuntimeError("not connected")
        try:
            return action(robot)
        except (ValueError, FileNotFoundError):
            raise
        except Exception as exc:
            # USB errors mean the brick was unplugged or switched off: drop it so Connect can be retried.
            if not robot.fake and _is_link_error(exc):
                self.robot = None
                self.error = f"{type(exc).__name__}: {exc}"
            raise

    def status(self) -> dict:
        robot = self.robot
        rec = self.recorder.recording
        out = {
            "connected": robot is not None,
            "fake": self.fake,
            "error": self.error,
            "program": self.recorder.program,
            "recording": None if rec is None else {"name": rec["name"], "rows": rec["rows"]},
        }
        if robot is not None:
            out.update(self.call(lambda r: r.info()))
            out.update(left=robot.left, right=robot.right, shots=getattr(robot, "shots", None))
        return out

    def drive(self, left: int, right: int) -> None:
        if self.recorder.program:
            raise RuntimeError(f"program {self.recorder.program} is running on the brick; stop it first")
        self.last_drive = time.monotonic()
        self.call(lambda r: r.drive(left, right))

    def save_config(self, data: dict) -> Config:
        new = Config.from_dict({**self.config.to_dict(), **data})
        self.recorder.stop()
        config_mod.save(new, self.config_path)
        self.config = new
        if self.robot is not None:
            self.call(lambda r: r.configure(new))
        return new

    def watchdog(self) -> None:
        while True:
            time.sleep(0.1)
            robot = self.robot
            if robot is None or (robot.left == 0 and robot.right == 0):
                continue
            if time.monotonic() - self.last_drive > WATCHDOG_SECONDS:
                try:
                    self.call(lambda r: r.stop())
                except Exception:
                    pass


def _is_link_error(exc: Exception) -> bool:
    import usb.core

    return isinstance(exc, (usb.core.USBError, OSError)) and not isinstance(exc, FileNotFoundError)


def make_handler(controller: Controller):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            quiet = ("/api/drive", "/api/status", "/api/live")
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
            elif path == "/api/live":
                since = int(q.get("since", 0))
                self._json(200, {"samples": c.recorder.since(since)})
            elif path == "/api/config":
                self._json(200, {"config": c.config.to_dict(), "sensor_types": SENSOR_TYPES})
            elif path == "/api/runs":
                self._json(200, {"runs": c.recorder.list_runs()})
            elif path == "/api/runs/download":
                self._handle(lambda: self._attachment(q["name"], c.recorder.run_path(q["name"]).read_bytes(), "text/csv"))
            elif path == "/api/files":
                self._handle(lambda: self._json(200, {"files": c.call(lambda r: r.list_files())}))
            elif path == "/api/files/download":
                self._handle(lambda: self._attachment(q["name"], c.call(lambda r: r.download(q["name"])), "application/octet-stream"))
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

            def act():
                body = self._body()
                data = json.loads(body or b"{}") if path != "/api/files/upload" else None
                result = {"ok": True}
                if path == "/api/connect":
                    c.connect()
                elif path == "/api/drive":
                    c.drive(int(data.get("left", 0)), int(data.get("right", 0)))
                elif path == "/api/stop":
                    c.call(lambda r: r.stop())
                elif path == "/api/fire":
                    if c.recorder.program:
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
                    c.call(lambda r: r.start_program(data["name"]))
                    c.recorder.program = data["name"]
                elif path == "/api/program/stop":
                    c.call(lambda r: r.stop_program())
                    c.recorder.program = None
                    c.call(lambda r: r.stop())
                else:
                    self._json(404, {"error": "not found"})
                    return
                self._json(200, result)

            self._handle(act)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to reach it from a phone on the LAN")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--fake", action="store_true", help="simulated brick, nothing moves")
    parser.add_argument("--config", type=Path, default=config_mod.CONFIG_PATH, help="port setup file")
    args = parser.parse_args()

    controller = Controller(config_mod.load(args.config), fake=args.fake, config_path=args.config)
    controller.connect()
    threading.Thread(target=controller.watchdog, daemon=True).start()
    threading.Thread(target=controller.recorder.run_forever, daemon=True).start()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(controller))
    mode = "FAKE robot" if args.fake else "NXT over USB"
    print(f"{mode}: http://{args.host}:{args.port}  (connect: {controller.error or 'ok'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.recorder.stop()
        if controller.robot is not None:
            controller.robot.close()


if __name__ == "__main__":
    main()
