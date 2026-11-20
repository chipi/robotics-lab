"""The four interfaces a robot's plugins implement (RFC-0020 §4). The navigator decides; the plugins only answer.

A robot's profile names one implementation of each (`plugins`: `duck-walk@1`, `tof8x8@1`, `mapd@1`, `duck-head@1`), loaded by name
(`duck_lab.plugins.load`). A plugin is built from the profile and holds the robot's numbers as instance state, so two robots
can run in one process. Hazard memory (edges, drops, suspected drops, what the floor showed) is the navigator's, not a plugin's:
a plugin is handed the hazards it must judge a motion against and returns classified frames, never remembers them.

Checked by `isinstance` (the classes are runtime-checkable Protocols): tests/test_plugins.py holds the duck's four to them, and a
robot that cannot look (`capable = False`) to what the navigator then does.
"""

from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class Locomotion(Protocol):
    """A wanted motion in, the robot's commands out; where it may turn."""

    name: str
    version: int
    pivot_vx: float            # the forward speed a turn on the spot is sent with, against the robot's own creep

    def bind(self, robot) -> None:
        """The channel commands go over (a robot RPC with `call(method, params)`)."""

    def command(self, vx: float, vyaw: float) -> None:
        """Send one motion to the robot."""

    def stop(self) -> None:
        """Send a zero motion (the deadman wants one every tick; every stop ends with one)."""

    def drive(self, err: float, yaw: float, now: float, st, near: bool, pivot_ok: bool, close: bool):
        """The motion (a Twist) that takes a robot whose heading is `err` off the lookahead, walking or turning, from the
        follower's state `st` (the part of following a path that is the robot's own: the kick, the slowest walk, the creep)."""

    def can_pivot(self, room_m: float, xy: tuple, drops: list, edges: list) -> bool:
        """Is there room to turn on the spot here: clear of obstacles and of the drops and measured edges."""

    def tight_pivot_ok(self, room_m: float, xy: tuple, drops: list, edges: list, now: float) -> bool:
        """No room for the usual turn: may it pivot anyway, once for this spot, while the room lasts."""

    def arc_clear(self, costs, pose: tuple, turn: float, nearest_mm, drops: list, edges: list, suspected: list) -> bool:
        """Is the floor a turn while walking sweeps clear (turn > 0 to the left)."""


@runtime_checkable
class RangeSensing(Protocol):
    """The robot's sensor: frames in, obstacles, floor and drops out."""

    name: str
    version: int
    on_frame: Callable | None      # called with each frame as it arrives (the navigator derives and logs it)

    def open(self, path) -> None:
        """Start reading the sensor's stream."""

    def derive(self, frame: dict, state: dict | None, dt_ms: float | None, pose: tuple | None):
        """A frame, the robot state it was paired with and the pose of that state, as what the navigator makes of it: points in
        the map frame, drop points, how far ahead an obstacle sits in the corridor (a perception, derived once)."""

    def nearest_mm(self) -> float | None:
        """The nearest valid return straight ahead, None when there is none."""

    def close(self) -> None:
        """Stop reading."""


@runtime_checkable
class Localisation(Protocol):
    """Where the robot is, the map it has, and how sure."""

    name: str
    version: int

    def bind(self, rpc) -> None:
        """The channel the source answers on."""

    def pose(self) -> tuple | None:
        """The belief's pose (x, y, yaw) on the map, None before it has one."""

    def fix(self, record, frames_on: bool = True, fault=None, t0: float = 0.0) -> bool:
        """Ask the source for a fix and apply it (the gate holds a jump too large to believe); what it says about itself it says
        through `record`. False when there was none."""

    def grid(self, frames_on: bool = True, fault=None, fault_grid: bool = False, t0: float = 0.0) -> dict:
        """The map as a grid dict (res_m, origin, width, height, cells), in the belief's frame and the robot's true metres."""

    def needs_stationary(self) -> bool:
        """Does the source map only when the robot stands still (so the navigator stops to let it)."""

    def settle(self, hold: Callable, survey_timeout_s: float, tick_s: float) -> bool:
        """Stand still (`hold()` each tick) until the source is mapping this stop. True when it was."""

    def on_odom(self, t_ns: int, odom_pose: tuple) -> None:
        """Every odometry sample (the robot's own, unscaled)."""

    def commanded(self, vx: float, vyaw: float = 0.0) -> None:
        """The motion now commanded: a source whose odometry error depends on speed corrects the steps that follow by it."""

    def to_map(self, odom_pose: tuple) -> tuple | None:
        """An odometry pose on the map, at the odometry's own instant."""

    def frame_delta(self) -> tuple | None:
        """The belief's frame against the source's own: how far a held jump or a correction has moved it."""

    def nudge(self, dx: float, dy: float) -> tuple:
        """Move the belief by a correction (landmarks); returns the step taken."""


@runtime_checkable
class Looking(Protocol):
    """Looking at a spot the sensor cannot see from where the robot stands."""

    name: str
    version: int
    capable: bool       # a robot that cannot look leaves a spot unseen, not blocked

    def bind(self, robot) -> None:
        """The channel the look's commands go over."""

    def look_at(self, target: tuple, pose: tuple, hold: Callable, view: Callable, tick_s: float = 0.1) -> dict:
        """Aim at a floor spot (map metres) from a pose and collect what the sensor then sees, holding the robot still with
        `hold()` each tick; `view()` is the newest frame as a perception. Returns the classified frames, or {"failed": why}
        when the robot could not look."""

    def settled(self) -> bool:
        """Is the view steady (the head has stopped moving)."""

    def restore(self, hold: Callable, view: Callable, tick_s: float = 0.1) -> None:
        """Give the head back its walking command."""
