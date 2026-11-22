"""What the run format's tests share: a check that prints PASS or FAIL and counts the failures."""

import sys


class Checks:
    def __init__(self, label: str):
        self.label, self.failures = label, []

    def __call__(self, name, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
        if not cond:
            self.failures.append(name)

    def done(self):
        print(self.label, "FAIL " + ", ".join(self.failures) if self.failures else "PASS")
        sys.exit(1 if self.failures else 0)


def small_profile() -> dict:
    """A small valid profile of no real robot (a rover): for the tests of the profile's schema, its store and its versions."""
    return {
        "profile_version": 1, "id": "rover", "label": "A test rover", "kind": "rover",
        "factsheet": {"typeSpecification": {"seriesName": "Rover", "mobileRobotKinematics": "DIFFERENTIAL"},
                      "physicalParameters": {"maximumSpeed": 0.5, "maximumAngularSpeed": 2.0}},
        "control": {"deadman_s": 0.5, "lease_s": 20.0, "takeover": []},
        "footprint": {"radius_m": 0.1, "height_m": 0.2},
        "locomotion": {"cruise_mps": 0.3},
        "plugins": {"locomotion": "wheels@1"},
        "joints": {"names": ["left_wheel", "right_wheel"]},
        "subsystems": [{"name": "base", "what": "the motor board", "check": {"kind": "socket", "socket": "robot"}},
                       {"name": "camera", "check": {"kind": "none"}}],
        "variants": {"sim": {}, "real": {}},
    }
