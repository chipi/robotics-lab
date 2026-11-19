"""A decision, for the log (ADR-0014): which rule fired, why, and the numbers it compared with its thresholds. Plugins and the
navigator both say what they decided this way."""


def decision(rule: str, reason: str, **values) -> dict:
    """A rule that fired, for the log (ADR-0014): which rule, why, and the numbers it compared with its thresholds."""
    return {"rule": rule, "reason": reason, "values": values}
