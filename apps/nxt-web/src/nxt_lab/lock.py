"""The exclusive control lock of nxt-web (RFC-0017 step 4): one driver at a time, the same rules as
the duck's gate (robotgate) over HTTP. nxt-web is the only process on the brick's link, so the
lock lives here and every client of ours (the page, Mission Control's adapter) passes it.

HTTP has no connection to tie a lease to, so a lease is tied to a *session*: a random id that
`acquire` returns and the holder sends with every motion command. A new acquire is a new session,
so a client that comes back late is refused, as a reconnect would be on the duck. A holder that
vanishes frees the robot when its lease runs out (there is no disconnect to react to).

No lease, no motion: a command that moves the robot (or starts or changes what does) needs the holder's session, and
while nobody holds the lock it is refused with `no_lease`, so a client takes the lock first. STOP is accepted from
anyone and ends the lease."""

import secrets
import threading
import time
from collections import OrderedDict
from pathlib import Path

LEASE_SECONDS = 20.0  # RFC-0017 §3.3: 10 to 30 s; the 0.6 s watchdog and the deadman are the safety stop
REMEMBERED_ENDS = 64  # sessions whose lease ended, kept to refuse them with the reason


class LockError(Exception):
    def __init__(self, code: str, message: str, **data):
        super().__init__(message)
        self.code = code
        self.data = data


def load_names(path: Path | None) -> frozenset:
    """The takeover list: one client name per line, blank lines and # comments skipped."""
    if path is None:
        return frozenset()
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return frozenset()
    names = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return frozenset(n for n in names if n)


class Lock:
    """`stop` stops the motors and is called first at every end of a lease. `event(kind, **detail)`
    is the command log."""

    def __init__(self, stop, *, clock=time.monotonic, wall=time.time, lease_s: float = LEASE_SECONDS,
                 takeover_names=(), event=None):
        self._stop = stop
        self._clock = clock
        self._wall = wall
        self.lease_s = lease_s
        self.takeover_names = frozenset(takeover_names)
        self._event = event or (lambda kind, **detail: None)
        self._mutex = threading.RLock()
        self._lease_id = 0
        self._session = None
        self._client = None
        self._since = 0.0
        self._renewed = 0.0
        self._ended: OrderedDict = OrderedDict()

    def acquire(self, client: str) -> dict:
        with self._mutex:
            self.tick()
            if self._session is not None:
                raise self._held()
            return self._grant(client)

    def takeover(self, client: str) -> dict:
        with self._mutex:
            self.tick()
            if client not in self.takeover_names:
                raise LockError("not_allowed", f"{client} is not on the takeover list")
            if self._session is not None:
                self._end(f"taken_over_by {client}", "lock taken over", by=client)
            return self._grant(client)

    def release(self, session: str | None) -> None:
        with self._mutex:
            self.tick()
            if session is None or session != self._session:
                raise LockError("not_holder", "this session does not hold the lock")
            self._end("released", "lock released")

    def stop_from(self, client: str) -> None:
        """STOP from anyone: it ends the lease and latches (the holder's next command is refused).
        The caller stops the motors itself, held or not."""
        with self._mutex:
            self.tick()
            if self._session is not None:
                self._end(f"stopped_by {client}", "lock ended by stop", by=client)

    def check(self, session: str | None, what: str = "motion") -> None:
        """Called before every command that moves the robot. Renews the holder's lease."""
        with self._mutex:
            self.tick()
            if session is not None and session == self._session:
                self._renewed = self._clock()
                return
            if session is not None:
                reason = self._ended.get(session)
                if reason is not None:
                    raise LockError("lease_ended", f"your lease ended: {reason}; acquire again", reason=reason)
                raise LockError("no_lease", "unknown session: acquire the lock first")
            if self._session is not None:
                raise self._held()
            raise LockError("no_lease", "no lease: take the control lock first (POST /api/lock, action acquire); STOP stays open")

    def keepalive(self, session: str | None) -> dict:
        self.check(session, "keepalive")
        if session is None:
            raise LockError("no_lease", "keepalive needs the holder's session")
        return {"lease_id": self._lease_id, "expires_in_s": self.lease_s}

    def tick(self) -> None:
        with self._mutex:
            if self._session is not None and self._clock() - self._renewed > self.lease_s:
                self._end("expired", f"no command for {self.lease_s:g} s")

    def who(self) -> dict:
        with self._mutex:
            self.tick()
            if self._session is None:
                return {"holder": None, "lease_id": self._lease_id}
            return {"holder": self._client, "since": self._since, "lease_id": self._lease_id,
                    "expires_in_s": round(max(0.0, self.lease_s - (self._clock() - self._renewed)), 3)}

    def _grant(self, client: str) -> dict:
        self._lease_id += 1
        self._session = secrets.token_hex(8)
        self._client = client
        self._since = self._wall()
        self._renewed = self._clock()
        self._event("lock acquired", client=client, lease_id=self._lease_id)
        return {"session": self._session, "lease_id": self._lease_id, "expires_in_s": self.lease_s}

    def _end(self, reason: str, text: str, **extra) -> None:
        """Every end of a lease stops the motors first, then frees the robot."""
        try:
            self._stop()
        except Exception as exc:
            self._event("lock stop", ok=False, error=f"{type(exc).__name__}: {exc}")
        self._ended[self._session] = reason
        while len(self._ended) > REMEMBERED_ENDS:
            self._ended.popitem(last=False)
        self._event(text, client=self._client, lease_id=self._lease_id, reason=reason, **extra)
        self._session = None
        self._client = None

    def _held(self) -> LockError:
        return LockError("held", f"driven by {self._client} since {time.strftime('%H:%M', time.localtime(self._since))}",
                         holder=self._client, since=self._since)
