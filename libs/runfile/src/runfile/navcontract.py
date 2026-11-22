"""The navigator contract's names (libs/runner/CONTRACT.md): its version, its methods, a goal's states. The duck's payload and
its navigator API answer by them; the runner and Mission Control check what a navigator answers against them."""

CONTRACT = "1.0"

# A goal's states: `idle` before the first goal, `running`, then one end. Each end's meaning is in CONTRACT.md.
ENDS = ("reached", "done", "refused", "not_found", "timeout", "stalled", "stopped_by_guardrail", "cancelled", "interrupted",
        "failed")
STATES = ("idle", "running") + ENDS
SUCCESS = ("reached", "done")

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


def check_state(state) -> str:
    if state not in STATES:
        raise ContractError(f"the navigator answered state {state!r}, which contract {CONTRACT} does not have")
    return state
