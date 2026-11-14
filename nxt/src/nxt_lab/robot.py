"""Robot backends: the real NXT over USB, and a fake that needs no hardware."""

import math
import random
import re
import threading
import time

import nxt.error
import nxt.locator
import nxt.motor
import nxt.sensor
import nxt.sensor.generic as generic

from nxt_lab import deadman
from nxt_lab.config import MOTOR_PORTS, Config

SENSOR_CLASSES = {
    "touch": generic.Touch,
    "light": generic.Light,
    "sound": generic.Sound,
    "color": generic.Color,
    "ultrasonic": generic.Ultrasonic,
}

# NXT file names: up to 15 characters, a dot, and an extension of up to 3.
NXT_NAME = re.compile(r"^[A-Za-z0-9_\-]{1,15}\.[A-Za-z0-9]{1,3}$")


def clamp(power: int) -> int:
    return max(-100, min(100, int(power)))


def check_name(name: str) -> str:
    if not NXT_NAME.match(name):
        raise ValueError(f"{name!r} is not a valid NXT file name (up to 15 letters/digits/_/-, then .ext)")
    return name


def read_sensor(kind: str, sensor) -> dict:
    if kind == "touch":
        return {"value": int(sensor.is_pressed())}
    if kind == "light":
        return {"value": sensor.get_lightness()}
    if kind == "sound":
        return {"value": sensor.get_loudness()}
    if kind == "ultrasonic":
        return {"value": sensor.get_distance()}
    if kind == "color":
        color = sensor.get_color()
        return {"value": color.value, "label": color.name.lower()}
    raise ValueError(kind)


# Which nxt-python backends each link choice tries. "devfile" is Bluetooth through /dev/rfcomm*.
LINK_BACKENDS = {"auto": ["usb", "devfile"], "usb": ["usb"], "bluetooth": ["devfile"]}


def deadman_ports_problem(config: Config) -> str | None:
    """Why robotd-lite cannot drive this setup, or None."""
    if (config.left, config.right) != (deadman.PORTS["left"], deadman.PORTS["right"]):
        return (f"the deadman program drives left {deadman.PORTS['left']} and right {deadman.PORTS['right']}; "
                f"Setup has left {config.left} and right {config.right}")
    return None


def deadman_powers(config: Config, left: int, right: int) -> tuple:
    """Port powers and the forward flag for robotd-lite, with Setup's inversions applied."""
    left, right = clamp(left), clamp(right)
    sign_l = -1 if config.invert_left else 1
    sign_r = -1 if config.invert_right else 1
    return sign_l * left, sign_r * right, left + right > 0


class DeadmanMixin:
    """Driving through robotd-lite while it runs (RFC-0003 §2.3-2.4). `deadman` is set by the
    controller from the running program; `_exchange` sends one command and returns its answer."""

    deadman = False
    deadman_state = None
    _seq = 0

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) % 10000
        return self._seq

    def _deadman_drive(self, left: int, right: int) -> None:
        problem = deadman_ports_problem(self.config)
        if problem:
            raise RuntimeError(problem)
        port_l, port_r, forward = deadman_powers(self.config, left, right)
        self.deadman_state = self._exchange(deadman.drive(self._next_seq(), port_l, port_r, forward))
        self.left, self.right = clamp(left), clamp(right)

    def _deadman_stop(self) -> None:
        try:
            self.deadman_state = self._exchange(deadman.stop(self._next_seq()))
        finally:
            self.left = self.right = 0

    def deadman_query(self) -> dict | None:
        self.deadman_state = self._exchange(deadman.query(self._next_seq()))
        return self.deadman_state


class NxtRobot(DeadmanMixin):
    fake = False

    def __init__(self, config: Config, link: str = "auto"):
        self._lock = threading.RLock()
        self._brick = nxt.locator.find(backends=LINK_BACKENDS[link])
        self.link = self._brick._sock.type
        self.link_detail = str(self._brick._sock)
        protocol, firmware = self._brick.get_firmware_version()
        self.firmware = f"{firmware[0]}.{firmware[1]:02d} (protocol {protocol[0]}.{protocol[1]})"
        self.left = 0
        self.right = 0
        self.configure(config)
        # The brick has no deadman: after a lost link or a crashed server its motors keep their last
        # power, while a fresh connection believes them stopped. Stop everything on connect.
        self.running_on_connect = self.idle_all()

    def idle_all(self) -> list:
        """Idle every motor; return the ports that still had power."""
        running = []
        with self._lock:
            for port, motor in self._motors.items():
                if self._brick.get_output_state(nxt.motor.Port[port])[1] != 0:
                    running.append(port)
                motor.idle()
        return running

    def configure(self, config: Config) -> None:
        # Under robotd-lite the program owns the ultrasonic port (an I2C sensor: two masters would
        # collide); its distance comes from the program's answers instead.
        with self._lock:
            self.config = config
            self._motors = {p: self._brick.get_motor(nxt.motor.Port[p]) for p in MOTOR_PORTS}
            self._sensors = {
                port: self._brick.get_sensor(nxt.sensor.Port[f"S{port}"], SENSOR_CLASSES[kind])
                for port, kind in config.sensors.items()
                if kind != "none" and not (self.deadman and port == deadman.US_PORT)
            }

    def set_deadman(self, on: bool) -> None:
        """Called when robotd-lite starts or stops. Starting a program resets the brick's sensor
        modes, so the sensors are set up again either way."""
        if on == self.deadman:
            return
        self.deadman = on
        self.deadman_state = None
        self.configure(self.config)

    def _exchange(self, message: bytes) -> dict | None:
        """One command to robotd-lite, and its answer. The program answers within one loop
        (about 20-40 ms); if the answer is not there yet the command still counts."""
        seq = int(message[1:5])
        with self._lock:
            self._brick.message_write(deadman.COMMAND_INBOX, message)
            waits = 0
            while waits < 4:
                try:
                    _, reply = self._brick.message_read(deadman.STATE_INBOX, 0, True)
                except nxt.error.EmptyMailboxError:
                    waits += 1
                    time.sleep(0.015)
                    continue
                state = deadman.parse_state(reply)
                if state["seq"] == seq:
                    return state
                # A late answer to an earlier command: drop it and read on.
        return None

    def info(self) -> dict:
        with self._lock:
            name, _, _, free_flash = self._brick.get_device_info()
            battery = self._brick.get_battery_level()
        return {"name": name, "battery_mv": battery, "free_flash": free_flash}

    def ping(self) -> None:
        """One cheap read-only round trip, for timing the link."""
        with self._lock:
            self._brick.get_output_state(nxt.motor.Port.A)

    def drive(self, left: int, right: int) -> None:
        if self.deadman:
            self._deadman_drive(left, right)
            return
        left, right = clamp(left), clamp(right)
        sign_l = -1 if self.config.invert_left else 1
        sign_r = -1 if self.config.invert_right else 1
        with self._lock:
            for port, power in ((self.config.left, sign_l * left), (self.config.right, sign_r * right)):
                if power == 0:
                    self._motors[port].brake()
                else:
                    self._motors[port].run(power)
        self.left, self.right = left, right

    def stop(self) -> None:
        if not self.deadman:
            self.drive(0, 0)
            return
        # Belt and braces: the program's stop, then the motors directly, even if the first failed.
        try:
            self._deadman_stop()
        finally:
            with self._lock:
                for port in (self.config.left, self.config.right):
                    self._motors[port].brake()

    def fire(self) -> None:
        with self._lock:
            self._motors[self.config.shooter].turn(self.config.fire_power, self.config.fire_degrees)

    def read_tachos(self) -> dict:
        with self._lock:
            return {p: m.get_tacho().tacho_count for p, m in self._motors.items()}

    def read_sensors(self) -> dict:
        out = {}
        with self._lock:
            for port, sensor in self._sensors.items():
                try:
                    out[port] = read_sensor(self.config.sensors[port], sensor)
                except Exception as exc:
                    out[port] = {"value": None, "error": f"{type(exc).__name__}: {exc}"}
        if self.deadman and self.config.sensors.get(deadman.US_PORT) == "ultrasonic":
            state = self.deadman_query()
            out[deadman.US_PORT] = {"value": state["dist"]} if state else {"value": None, "error": "no answer from robotd"}
        return out

    def list_files(self) -> list:
        with self._lock:
            return [{"name": n, "size": s} for n, s in self._brick.find_files("*.*")]

    def upload(self, name: str, data: bytes) -> None:
        check_name(name)
        with self._lock:
            try:
                self._brick.file_delete(name)
            except nxt.error.FileNotFoundError:
                pass
            with self._brick.open_file(name, "wb", len(data)) as f:
                f.write(data)

    def download(self, name: str) -> bytes:
        check_name(name)
        with self._lock:
            with self._brick.open_file(name, "rb") as f:
                return f.read()

    def delete(self, name: str) -> None:
        check_name(name)
        with self._lock:
            self._brick.file_delete(name)

    def start_program(self, name: str) -> None:
        check_name(name)
        with self._lock:
            self._brick.start_program(name)

    def stop_program(self) -> None:
        with self._lock:
            try:
                self._brick.stop_program()
            except nxt.error.NoActiveProgramError:
                pass

    def current_program(self):
        with self._lock:
            try:
                return self._brick.get_current_program_name()
            except nxt.error.NoActiveProgramError:
                return None

    def close(self) -> None:
        try:
            # robotd-lite would otherwise keep its last command until its own deadman fires.
            if self.deadman:
                try:
                    self._deadman_stop()
                except Exception:
                    pass
            with self._lock:
                for motor in self._motors.values():
                    motor.idle()
        finally:
            self._brick.close()


class FakeRobot(DeadmanMixin):
    """Simulates the brick so the UI can be used with nothing plugged in. Values are made up.
    robotd.rxe is on its flash; started, it behaves like the real program (deadman.FakeDeadman)."""

    fake = True
    link = "fake"
    link_detail = "simulated brick"
    firmware = "simulated"

    def __init__(self, config: Config, link: str = "auto"):
        self.left = 0
        self.right = 0
        self.shots = 0
        self._tacho = {p: 0.0 for p in MOTOR_PORTS}
        self._last = time.monotonic()
        self._brick_program = None
        self._files = {
            "demo.rxe": b"\x00" * 1200,
            deadman.PROGRAM: b"\x00" * 3522,
            "runlog.txt": b"t,light,dist\n" + b"".join(
                f"{i * 100},{40 + int(10 * math.sin(i / 5))},{max(5, 80 - i)}\n".encode() for i in range(60)
            ),
        }
        self._program = None
        self.running_on_connect = []
        self.configure(config)

    def configure(self, config: Config) -> None:
        self.config = config

    def info(self) -> dict:
        used = sum(len(d) for d in self._files.values())
        return {"name": "fake", "battery_mv": 7800, "free_flash": 100_000 - used}

    def ping(self) -> None:
        pass

    def set_deadman(self, on: bool) -> None:
        if on == self.deadman:
            return
        self.deadman = on
        self.deadman_state = None
        self._brick_program = deadman.FakeDeadman() if on else None

    def _exchange(self, message: bytes) -> dict:
        self._brick_program.dist = self._fake_distance()
        self._brick_program.receive(message)
        return deadman.parse_state(self._brick_program.reply)

    def drive(self, left: int, right: int) -> None:
        self._advance()
        if self.deadman:
            self._deadman_drive(left, right)
        else:
            self.left, self.right = clamp(left), clamp(right)

    def stop(self) -> None:
        self._advance()
        if self.deadman:
            self._deadman_stop()
        self.left = self.right = 0

    def fire(self) -> None:
        self.shots += 1
        self._tacho[self.config.shooter] += self.config.fire_degrees

    def _advance(self) -> None:
        now = time.monotonic()
        dt, self._last = now - self._last, now
        left, right = self.left, self.right
        if self._brick_program is not None:
            # The motors follow the simulated program, with its own deadman; like the real brick,
            # that does not change what the server last commanded (self.left, self.right).
            self._brick_program.dist = self._fake_distance()
            self._brick_program.tick()
            left, right = self._brick_program.left, self._brick_program.right
        # Roughly 9 degrees/s per unit of power, about what an NXT motor does unloaded.
        self._tacho[self.config.left] += left * 9 * dt
        self._tacho[self.config.right] += right * 9 * dt

    def read_tachos(self) -> dict:
        self._advance()
        return {p: int(v) for p, v in self._tacho.items()}

    def read_sensors(self) -> dict:
        t = time.monotonic()
        out = {}
        for port, kind in self.config.sensors.items():
            if kind == "touch":
                out[port] = {"value": int(math.sin(t / 3) > 0.8)}
            elif kind == "light":
                out[port] = {"value": int(45 + 15 * math.sin(t) + random.uniform(-2, 2))}
            elif kind == "sound":
                out[port] = {"value": int(abs(random.gauss(10, 8)))}
            elif kind == "ultrasonic" and self.deadman and port == deadman.US_PORT:
                out[port] = {"value": self.deadman_query()["dist"]}
            elif kind == "ultrasonic":
                out[port] = {"value": self._fake_distance()}
            elif kind == "color":
                c = generic.Color.DetectedColor(1 + int(t / 2) % 6)
                out[port] = {"value": c.value, "label": c.name.lower()}
        return out

    @staticmethod
    def _fake_distance() -> int:
        return int(60 + 40 * math.sin(time.monotonic() / 4))

    def list_files(self) -> list:
        return [{"name": n, "size": len(d)} for n, d in self._files.items()]

    def upload(self, name: str, data: bytes) -> None:
        self._files[check_name(name)] = data

    def download(self, name: str) -> bytes:
        if check_name(name) not in self._files:
            raise FileNotFoundError(name)
        return self._files[name]

    def delete(self, name: str) -> None:
        if self._files.pop(check_name(name), None) is None:
            raise FileNotFoundError(name)

    def start_program(self, name: str) -> None:
        if check_name(name) not in self._files:
            raise FileNotFoundError(name)
        self._program = name

    def stop_program(self) -> None:
        self._program = None
        self.left = self.right = 0

    def current_program(self):
        return self._program

    def close(self) -> None:
        self.stop()
