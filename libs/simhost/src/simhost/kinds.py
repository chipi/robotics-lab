"""The host kinds: per kind, how its host file is read, how it is reset, what its truth reader is, and which sensor kinds it
simulates. Three functions and a tuple; nothing more is generalised (docs/wip/NXT-D0.md §1: two kinds do not yet show what a
base class would hold, and RFC-0028 writes the contract from what these two have in common)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from simhost import host as H
from simhost import nxt, simulator
from simhost.truth import Body


@dataclass(frozen=True)
class Kind:
    parse: Callable          # (dict, source path) -> the kind's host
    reset: Callable          # (host, scene) -> None, when the simulator stands at the start (scene optional where it has a default)
    down: Callable           # (host, scene) -> None
    truth: Callable          # (host) -> a reader with read() -> (pose, z, quat, sim_time) and close()
    simulates: tuple         # sensor kinds the simulator makes readings for (RFC-0025 §3.9); recorded, not yet enforced


KINDS = {
    "pollen-duck-sim": Kind(H.parse_duck, simulator.reset, simulator.down, lambda host: Body(host.truth_port),
                            ("tof8x8", "camera")),
    "nxt-kinematic-sim": Kind(H.parse_nxt, nxt.reset, nxt.down, nxt.Truth, ("range",)),
}


def reset(host, *scene) -> None:
    """The host's simulator at its start. `scene` is the kind's own (the duck's: a scene name or path, default
    apartment_backlash; the NXT's: a scene.json path, default the host's)."""
    KINDS[host.kind].reset(host, *scene)


def down(host, *scene) -> None:
    KINDS[host.kind].down(host, *scene)
