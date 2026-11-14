"""robotd-lite's mailbox protocol (programs/robotd.nxc, RFC-0003 §2.3): the PC side.

The brick program stops the tracks when no drive command arrives for 0.5 s, so a crashed server
or a dropped link stops the robot. These encode its commands and parse its answers."""

import time

PROGRAM = "robotd.rxe"
DEADMAN_S = 0.5
MIN_CM = 15
COMMAND_INBOX = 0   # MAILBOX1 on the brick
STATE_INBOX = 10    # its response mailbox 1
# The program's ports (programs/common.nxh); the service refuses deadman driving with others.
PORTS = {"left": "C", "right": "B"}
US_PORT = "4"

FLAG_DEADMAN = 1
FLAG_OBSTACLE = 2
FLAG_BAD = 4


def drive(seq: int, left: int, right: int, forward: bool) -> bytes:
    return f"D{seq % 10000:04d}{left + 100:03d}{right + 100:03d}{int(forward)}".encode()


def stop(seq: int) -> bytes:
    return f"S{seq % 10000:04d}".encode()


def query(seq: int) -> bytes:
    return f"Q{seq % 10000:04d}".encode()


def parse_state(message: bytes) -> dict:
    seq, left, right, dist, flags, ms = (int(x) for x in message.rstrip(b"\x00").decode().split(","))
    return {
        "seq": seq, "left": left, "right": right, "dist": dist, "ms": ms,
        "deadman_stop": bool(flags & FLAG_DEADMAN),
        "obstacle_stop": bool(flags & FLAG_OBSTACLE),
        "bad_command": bool(flags & FLAG_BAD),
    }


class FakeDeadman:
    """The brick program's behaviour, for the simulated brick and the tests."""

    def __init__(self):
        self.left = self.right = 0
        self.forward = False
        self.flags = 0
        self.dist = 255
        self.last_move = time.monotonic()
        self.started = time.monotonic()
        self.reply = None

    def tick(self) -> None:
        if (self.left or self.right) and time.monotonic() - self.last_move > DEADMAN_S:
            self.left = self.right = 0
            self.forward = False
            self.flags |= FLAG_DEADMAN
        if self.forward and self.dist < MIN_CM:
            self.left = self.right = 0
            self.forward = False
            self.flags |= FLAG_OBSTACLE

    def receive(self, message: bytes) -> None:
        text = message.decode()
        kind, seq = text[0], int(text[1:5])
        if kind == "D" and len(text) == 12:
            self.left, self.right = int(text[5:8]) - 100, int(text[8:11]) - 100
            self.forward = text[11] == "1"
            self.last_move = time.monotonic()
            self.flags = 0
        elif kind == "S":
            self.left = self.right = 0
            self.forward = False
            self.flags = 0
        elif kind != "Q":
            self.left = self.right = 0
            self.forward = False
            self.flags = FLAG_BAD
        self.tick()
        ms = int((time.monotonic() - self.started) * 1000)
        self.reply = f"{seq},{self.left},{self.right},{self.dist},{self.flags},{ms}".encode()
