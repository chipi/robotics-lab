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


class NxtRobot:
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
        with self._lock:
            self.config = config
            self._motors = {p: self._brick.get_motor(nxt.motor.Port[p]) for p in MOTOR_PORTS}
            self._sensors = {
                port: self._brick.get_sensor(nxt.sensor.Port[f"S{port}"], SENSOR_CLASSES[kind])
                for port, kind in config.sensors.items()
                if kind != "none"
            }

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
        self.drive(0, 0)

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
            with self._lock:
                for motor in self._motors.values():
                    motor.idle()
        finally:
            self._brick.close()


class FakeRobot:
    """Simulates the brick so the UI can be used with nothing plugged in. Values are made up."""

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
        self._files = {
            "demo.rxe": b"\x00" * 1200,
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

    def drive(self, left: int, right: int) -> None:
        self._advance()
        self.left, self.right = clamp(left), clamp(right)

    def stop(self) -> None:
        self.drive(0, 0)

    def fire(self) -> None:
        self.shots += 1
        self._tacho[self.config.shooter] += self.config.fire_degrees

    def _advance(self) -> None:
        now = time.monotonic()
        dt, self._last = now - self._last, now
        # Roughly 9 degrees/s per unit of power, about what an NXT motor does unloaded.
        self._tacho[self.config.left] += self.left * 9 * dt
        self._tacho[self.config.right] += self.right * 9 * dt

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
            elif kind == "ultrasonic":
                out[port] = {"value": int(60 + 40 * math.sin(t / 4))}
            elif kind == "color":
                c = generic.Color.DetectedColor(1 + int(t / 2) % 6)
                out[port] = {"value": c.value, "label": c.name.lower()}
        return out

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

    def current_program(self):
        return self._program

    def close(self) -> None:
        self.stop()
