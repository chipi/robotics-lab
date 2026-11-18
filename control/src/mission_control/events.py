"""The live stream (RFC-0014 §3.2.2): every event gets a sequence number, so a client that dropped asks
for what it missed. A ring of the latest events is kept in memory; the durable record of a goal run
is in the store, not here."""

import threading
import time

RING = 5000


class EventBus:
    def __init__(self, wall=time.time, size: int = RING):
        self._wall = wall
        self._size = size
        self._events: list = []
        self._seq = 0
        self._cond = threading.Condition()

    @property
    def seq(self) -> int:
        with self._cond:
            return self._seq

    def emit(self, kind: str, robot: str | None = None, **data) -> dict:
        with self._cond:
            self._seq += 1
            event = {"seq": self._seq, "t": round(self._wall(), 3), "kind": kind, "robot": robot, **data}
            self._events.append(event)
            if len(self._events) > self._size:
                del self._events[: len(self._events) - self._size]
            self._cond.notify_all()
            return event

    def since(self, seq: int, limit: int = 1000) -> tuple:
        """(events after `seq`, gap). `gap` is true when the ring no longer holds everything after it."""
        with self._cond:
            if not self._events:
                return [], seq < self._seq
            gap = self._events[0]["seq"] > seq + 1
            return [e for e in self._events if e["seq"] > seq][:limit], gap

    def wait(self, seq: int, timeout: float) -> bool:
        """Block until an event after `seq` exists or the timeout passes."""
        with self._cond:
            return self._cond.wait_for(lambda: self._seq > seq, timeout)

    def wake(self) -> None:
        """Let waiting streams look at their stop flag."""
        with self._cond:
            self._cond.notify_all()
