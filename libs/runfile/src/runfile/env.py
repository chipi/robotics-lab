"""The lab's environment variables: OBSERVATORY_<NAME>, with the MINIVIEW_<NAME> of before the rename (RFC-0018) as a
fallback. The first one that is set and not empty wins, so the new name beats the old when both are present."""

import os

PREFIXES = ("OBSERVATORY_", "MINIVIEW_")


def get(name: str, default=None):
    for prefix in PREFIXES:
        v = os.environ.get(prefix + name)
        if v:
            return v
    return default
