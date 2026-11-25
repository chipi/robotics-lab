"""The Observatory's page-test boot helper, for Mission Control's page tests: one implementation, not a copy. A page test runs in the
Observatory's environment (the Makefile's test-control-page), whose tests/ folder is not on its path; this puts it there."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "observatory" / "tests"))

from helpers import boot  # noqa: E402,F401
