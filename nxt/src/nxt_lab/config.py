"""Port setup, saved as JSON next to the project so the web UI can edit it."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"

SENSOR_TYPES = ("none", "touch", "light", "sound", "color", "ultrasonic")
MOTOR_PORTS = ("A", "B", "C")
SENSOR_PORTS = ("1", "2", "3", "4")


@dataclass
class Config:
    # Unverified on the real robot: the Shooterbot instructions put the tracks on B/C and the shooter on A.
    left: str = "B"
    right: str = "C"
    shooter: str = "A"
    invert_left: bool = False
    invert_right: bool = False
    fire_power: int = 75
    fire_degrees: int = 360
    sensors: dict = field(default_factory=lambda: {p: "none" for p in SENSOR_PORTS})
    sample_hz: float = 5.0

    def validate(self) -> None:
        roles = (self.left, self.right, self.shooter)
        if any(p not in MOTOR_PORTS for p in roles):
            raise ValueError(f"motor ports must be one of {MOTOR_PORTS}")
        if len(set(roles)) != 3:
            raise ValueError("left, right and shooter must be different ports")
        if set(self.sensors) != set(SENSOR_PORTS):
            raise ValueError(f"sensors must list ports {SENSOR_PORTS}")
        for port, kind in self.sensors.items():
            if kind not in SENSOR_TYPES:
                raise ValueError(f"sensor {port}: {kind!r} is not one of {SENSOR_TYPES}")
        if not 1 <= self.fire_power <= 100:
            raise ValueError("fire_power must be 1..100")
        if not 0.5 <= self.sample_hz <= 20:
            raise ValueError("sample_hz must be 0.5..20")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        config = cls(**known)
        config.sensors = {str(k): v for k, v in config.sensors.items()}
        config.fire_power = int(config.fire_power)
        config.fire_degrees = int(config.fire_degrees)
        config.sample_hz = float(config.sample_hz)
        config.validate()
        return config


def load(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    return Config.from_dict(json.loads(path.read_text()))


def save(config: Config, path: Path = CONFIG_PATH) -> None:
    config.validate()
    path.write_text(json.dumps(config.to_dict(), indent=2) + "\n")
