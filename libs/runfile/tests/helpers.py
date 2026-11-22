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
