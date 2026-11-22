"""The navigator contract's names (libs/runner/CONTRACT.md): its version, its methods, a goal's states. The duck's payload and
its navigator API answer by them; the runner and Mission Control check what a navigator answers against them."""

CONTRACT = "1.0"

# A goal's states: `idle` before the first goal, `running`, then one end. Each end's meaning is in CONTRACT.md.
ENDS = ("reached", "done", "refused", "not_found", "timeout", "stalled", "stopped_by_guardrail", "cancelled", "interrupted",
        "failed")
STATES = ("idle", "running") + ENDS
SUCCESS = ("reached", "done")
# the ends a stop asked from outside gives (goal.break, goal.cancel); a navigator's stop event is named by them
STOPS = ("stopped_by_guardrail", "cancelled")

GOAL_METHODS = ("hello", "goal.start", "goal.status", "goal.cancel", "goal.break")
# what each kind of navigator answers besides the goal methods, and nothing else
PAYLOAD_METHODS = GOAL_METHODS + ("localise", "stop")
API_METHODS = GOAL_METHODS + ("map", "state", "objects", "inventory")


class ContractError(ValueError):
    """A navigator answered outside the contract: another major version, or a state the contract does not have."""


def major(version: str) -> int:
    return int(str(version).split(".", 1)[0])


def check_hello(hello: dict) -> dict:
    """`hello`'s answer, when its contract is one this side knows (the same major version), else ContractError naming both."""
    theirs = hello.get("contract")
    if theirs is None:
        raise ContractError(f"the navigator {hello.get('name')!r} names no contract version; this side speaks {CONTRACT}")
    if major(theirs) != major(CONTRACT):
        raise ContractError(f"the navigator {hello.get('name')!r} speaks contract {theirs}; this side speaks {CONTRACT}")
    return hello


def stop_before(why) -> str:
    """What a stop a run recorded as `aborted` (before contract 1.0) is named now, by its recorded reason: a cancel's reason
    says "cancelled ..." (Mission Control's, the runner's); every other was a guardrail's (the truth guard, an invariant, a
    goal's guardrail: the 9 in the Observatory's index on 2026-11-22 are all of these)."""
    return "cancelled" if str(why or "").strip().lower().startswith("cancel") else "stopped_by_guardrail"


def check_state(state) -> str:
    if state not in STATES:
        raise ContractError(f"the navigator answered state {state!r}, which contract {CONTRACT} does not have")
    return state
