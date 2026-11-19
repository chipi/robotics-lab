"""Per-client tokens (RFC-0014 §3.9, step 7). In v1 the tailnet is the authentication and any client may name itself. When tokens are
required (`mission-control serve --require-tokens`), every call but STOP, the health check and the page's own files carries a token,
and the token names the client: the lease, the event stream and the goal run's record say who commanded, and a client cannot name
itself something else. A token can be revoked at any time and STOP stays open to everybody, revoked tokens included: a refused STOP
risks a collision (RFC-0017 §3.4).

A token is `mc_` and 32 characters of randomness. Only its SHA-256 is stored; the token is shown once, when it is made."""

import hashlib
import secrets
import time

from .errors import ApiError, conflict, invalid, not_found

PREFIX = "mc_"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Tokens:
    def __init__(self, store, wall=time.time):
        self.store, self._wall = store, wall

    def create(self, client) -> tuple:
        """(id, token): the token is not kept, only its hash."""
        if not isinstance(client, str) or not client.strip():
            raise invalid("client is the name this token speaks as: a non-empty string")
        token = PREFIX + secrets.token_urlsafe(24)
        tid = self.store.execute("INSERT INTO tokens (client, hash, created_at) VALUES (?,?,?)", (client.strip(), _hash(token), self._wall()))
        return tid, token

    def verify(self, token) -> str | None:
        """The client a token names, or None for a token that is not known or was revoked."""
        if not isinstance(token, str) or not token.startswith(PREFIX):
            return None
        row = self.store.one("SELECT client, revoked_at FROM tokens WHERE hash = ?", (_hash(token),))
        return row["client"] if row and row["revoked_at"] is None else None

    def list(self) -> list:
        return [{"id": r["id"], "client": r["client"], "created_at": r["created_at"], "revoked_at": r["revoked_at"]}
                for r in self.store.all("SELECT id, client, created_at, revoked_at FROM tokens ORDER BY id")]

    def revoke(self, tid) -> dict:
        row = self.store.one("SELECT * FROM tokens WHERE id = ?", (tid,)) if isinstance(tid, int) else None
        if row is None:
            raise not_found("token", tid)
        if row["revoked_at"] is not None:
            raise conflict("already_revoked", f"token {tid} was revoked already")
        self.store.execute("UPDATE tokens SET revoked_at = ? WHERE id = ?", (self._wall(), tid))
        return next(t for t in self.list() if t["id"] == tid)

    def active(self) -> int:
        return self.store.one("SELECT COUNT(*) AS n FROM tokens WHERE revoked_at IS NULL")["n"]


def unauthorized(message: str = "this call needs a token: Authorization: Bearer mc_... (or ?token= for the event stream)") -> ApiError:
    return ApiError(401, "unauthorized", message)
