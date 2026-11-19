"""nav/cliff.py as the probes knew it, over the sensor plugin (plugins/tof8x8.py): a sensor that can be re-mounted with configure().

The module became the plugin's methods in RFC-0020 step 3 (the mount is instance state now, not module state). The probes read the
sensor by the old names (cliff.BEAMS, cliff.VALID, cliff.sensor_pose, cliff.configure(*mount)); this keeps them running unchanged:

    from cliff_shim import cliff
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from duck_lab.plugins.tof8x8 import Tof8x8, rotate  # noqa: E402
from duck_lab.profile import load as load_profile  # noqa: E402

CONSTANTS = {"BEAMS": "beams", "VALID": "valid", "LOOK_M": "look_m", "EXTRA_M": "extra_m", "COLS": "cols", "ROWS": "rows",
             "MIN_ZONES": "min_zones", "NO_TARGET": "no_target", "NO_TARGET_RANGE_M": "range_m", "CORRIDOR_DROP_M": "corridor_m",
             "FLOOR_MARGIN_M": "floor_margin_m", "FLOOR_MARGIN_PER_M": "floor_margin_per_m"}


class Cliff:
    rotate = staticmethod(rotate)

    def __init__(self, variant="sim"):
        self.profile = load_profile(variant)
        self.configure()

    def configure(self, pitch_offset_deg: float = 3.0, range_kind: str = "axial") -> None:
        """Mount the sensor as configure() did: the real duck's (3 deg, axial) unless told otherwise."""
        self.sensor = Tof8x8(self.profile, mount={"pitch_offset_deg": pitch_offset_deg, "range_kind": range_kind})

    def __getattr__(self, name):
        if name == "sensor":
            raise AttributeError(name)
        return getattr(self.sensor, CONSTANTS.get(name, name))


cliff = Cliff()
