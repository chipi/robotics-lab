"""The duck's side of the navigator contract (libs/runner/CONTRACT.md): a goal's end from what its navigator did, one rule for
the payload and the navigator API, and the goal's time and budget as the contract's goal shape gives them."""

from runfile.navcontract import CONTRACT

DEFAULT_POINT_S = 60.0
DEFAULT_MINUTES = 5.0


def hello(name: str, version: str, kinds, camera: bool, **more) -> dict:
    return {"name": name, "version": version, "contract": CONTRACT, "kinds": list(kinds), "camera": camera, **more}


def within_s(spec: dict, default: float = DEFAULT_POINT_S) -> float:
    return float(((spec.get("conditions") or {}).get("done_when") or {}).get("within_s") or default)


def minutes(spec: dict, default: float = DEFAULT_MINUTES) -> float:
    """The budget's minutes, cut to `done_when.within_s` when that is shorter."""
    budget = float((spec.get("budget") or {}).get("minutes") or default)
    within = ((spec.get("conditions") or {}).get("done_when") or {}).get("within_s")
    return min(budget, float(within) / 60.0) if within else budget


def of_go_to(out: dict) -> tuple:
    """(state, reason) of a point goal from Navigator.go_to's answer; a stop asked from outside comes back as its end
    (Navigator.stop_goal), which `settle` confirms."""
    status = out.get("status")
    if status == "reached":
        return "reached", None
    if status in ("refused", "stalled", "stopped_by_guardrail", "cancelled"):
        return status, out.get("why")
    if status == "timeout":
        return "timeout", f"the time limit of {out.get('time_s')} s was spent before it was reached"
    return "failed", out.get("why") or str(status)


def of_lease(exc) -> tuple:
    """(state, reason) when the robot was taken from the navigator (duck_lab.nav.client.LeaseLost)."""
    reason = exc.reason or ""
    if reason.startswith("taken_over_by"):
        return "interrupted", f"the robot was {reason.replace('_', ' ')}"
    if reason.startswith("stopped_by"):
        return "cancelled", reason.replace("_", " ")
    return "interrupted", f"the lease ended: {reason or exc.code}"


def settle(state: str, reason, broken: dict | None, cancelled: str | None) -> tuple:
    """The end once what was asked from outside is put in: a broken guardrail, else a cancel, over what the navigator did;
    neither over the robot being taken (interrupted), and a guardrail not over a STOP (a lease stopped_by: cancelled)."""
    if state == "interrupted":
        return state, reason
    if broken and state != "cancelled":
        return "stopped_by_guardrail", broken["detail"]
    if cancelled:
        return "cancelled", cancelled
    return state, reason
