"""The old `duck-*` names of the runner's commands, for one release (RFC-0022 §4): each says its new name, then runs it."""

import importlib
import sys

NEW = {"duck-challenge": ("lab-challenge", "labrunner.challenge"), "duck-eval": ("lab-eval", "labrunner.evaluate"),
       "duck-explore": ("lab-explore", "labrunner.explore_run"), "duck-go": ("lab-go", "labrunner.go"),
       "duck-nav-server": ("lab-nav-server", "labrunner.navapi"), "duck-gate": ("lab-gate", "labrunner.gate"),
       "duck-rooms": ("lab-rooms", "labrunner.rooms")}


def _run(old: str) -> None:
    new, module = NEW[old]
    print(f"{old} is now {new} (RFC-0022); the old name works for one release", file=sys.stderr, flush=True)
    importlib.import_module(module).main()


def duck_challenge() -> None:
    _run("duck-challenge")


def duck_eval() -> None:
    _run("duck-eval")


def duck_explore() -> None:
    _run("duck-explore")


def duck_go() -> None:
    _run("duck-go")


def duck_nav_server() -> None:
    _run("duck-nav-server")


def duck_gate() -> None:
    _run("duck-gate")


def duck_rooms() -> None:
    _run("duck-rooms")
