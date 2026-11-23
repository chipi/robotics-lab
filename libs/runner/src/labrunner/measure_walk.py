"""How fast the duck walks against the speed it is asked, and what its odometry says of the distance (phase 5 item 4b unit B9;
RFC-0002 phase 5's first comparison: the commanded/measured speed gain; also the odometry scale a tape gives, REAL-DUCK.md section 4).
THIS ONE MOVES THE ROBOT, so it goes only through the gate, with a lease, and it refuses a robot that is not the simulator unless you say
`--real`:

    lab-measure-walk --speeds 0.2,0.3                                                  # the simulator: the host file's gate socket
    lab-measure-walk --real --interactive --gate ~/.cache/duck-real/duck-gate.sock     # the real duck, through lab-gate on lab-link's forward

Each leg: hold still 1 s, walk straight at the asked speed for --ramp-s (getting up to speed) and then --seconds (measured), hold still
1.5 s. Measured speed is the odometry's distance over its time in the measured part, divided by the asked speed: the gain. The odometry
distance of the WHOLE leg (the ramp and the stop included) is what a tape can be laid against: with --interactive the script waits for you to
put the duck on its start mark before each leg and asks for the tape distance after it; walked / believed is then the odometry scale
(the calibration card keeps that number). In the simulator the truth gives the same, no tape.

Safety, all of it the gate's and this script's, nothing of the robot's own:

- the lease: no lease, no motion. A robot someone else holds is refused before a command is sent; STOP from any client ends the lease
  and this script stops with "lease ended".
- speeds above 0.4 m/s are refused, and each leg is --seconds + --ramp-s + 2.5 s long: at 0.3 m/s and 4 s, about 1.8 m of floor in front
  of the duck, clear and flat, nothing it could drop from. A leg stops the robot first on any error and on Ctrl-C.
- not the simulator without `--real`: the simulator is a host file with a truth port and this gate's socket among its sockets. Anything
  else, the real duck's forward included, is refused with no connection made. Lowest speed first (profile `locomotion.slowest_mps`).
- not verified on the real duck: the real robotd's answer to a second connection beside this one, and its deadman (0.5 s) if the link
  drops mid-leg: the script's own stop would not get through."""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import threading
import time
from pathlib import Path

import simhost

from labrunner.rpc import LeaseLost, Rpc

MAX_SPEED_MPS = 0.4
TICK_S = 0.1                 # one robot.move per tick: the robot's deadman is 0.5 s, so a missed tick or two is not a stop
SETTLE_S, STOP_S = 1.0, 1.5
CLIENT = "lab-measure-walk"


class Refused(SystemExit):
    """The script will not run, said in one line; nothing was sent to any robot."""


def is_simulator(gate: Path, host) -> bool:
    """True only for a host that has a truth (a simulator) and whose own sockets include this gate: the one case run without --real."""
    return host is not None and getattr(host, "truth_port", None) is not None and \
        Path(gate) in {Path(v) for v in host.sockets.values()}


def parse_speeds(text: str) -> list:
    speeds = [float(x) for x in text.split(",") if x.strip()]
    if not speeds or any(s <= 0 for s in speeds):
        raise Refused(f"--speeds {text!r}: forward speeds in m/s, e.g. 0.2,0.3")
    if any(s > MAX_SPEED_MPS for s in speeds):
        raise Refused(f"--speeds {text!r}: above {MAX_SPEED_MPS} m/s is refused (the walking policy is trained for less)")
    return speeds


def check_target(gate: Path, host, real: bool) -> None:
    """The refusal that comes before any connection: a robot that is not the simulator, without --real."""
    if not real and not is_simulator(gate, host):
        raise Refused(f"{gate} is not the simulator's gate (no simulator host file names it): this moves a robot, so it needs --real. "
                      f"Real duck: floor clear for 2 m ahead, nothing to drop from, someone with a hand on STOP")


def check_free(holder) -> None:
    """`holder` is gate.who's: None is a free robot."""
    if holder is not None:
        raise Refused(f"the robot is held by {holder}: not taking it from them")


def window(a: dict, b: dict, key: str) -> float | None:
    """Speed between two samples by one source (`odom` or `truth`), in m/s over that source's own clock; None when it has no reading."""
    if a.get(key) is None or b.get(key) is None or b.get(f"{key}_t", 0) <= a.get(f"{key}_t", 0):
        return None
    return math.dist(a[key][:2], b[key][:2]) / (b[f"{key}_t"] - a[f"{key}_t"])


def leg_metrics(asked: float, s0: dict, w0: dict, w1: dict, s1: dict, tape_m: float | None) -> dict:
    """One leg's numbers from the four samples: the whole leg's start and end (s0, s1) and the measured window's (w0, w1)."""
    out = {"asked_mps": asked, "window_s": round(w1["odom_t"] - w0["odom_t"], 2)}
    for key in ("odom", "truth"):
        v = window(w0, w1, key)
        if v is not None:
            out[f"{key}_mps"] = round(v, 3)
            out[f"{key}_gain"] = round(v / asked, 3)
        if s0.get(key) is not None and s1.get(key) is not None:
            out[f"{key}_leg_m"] = round(math.dist(s0[key][:2], s1[key][:2]), 3)
    if tape_m is not None:
        out["tape_leg_m"] = tape_m
        if out.get("odom_leg_m"):
            out["odom_scale_by_tape"] = round(tape_m / out["odom_leg_m"], 3)
    if "truth_leg_m" in out and out.get("odom_leg_m"):
        out["odom_scale_by_truth"] = round(out["truth_leg_m"] / out["odom_leg_m"], 3)
    return out


def hold(move, sleep, seconds: float, vx: float) -> None:
    for _ in range(max(1, round(seconds / TICK_S))):
        move(vx)
        sleep(TICK_S)


def walk(move, sample, sleep, speeds: list, seconds: float, ramp_s: float, ask=None, tell=print) -> list:
    """The legs, in order. move(vx) sends one forward robot.move; sample() is {odom, odom_t, truth?, truth_t?}; ask(prompt) -> str is the
    operator at the keyboard (--interactive), else None. Always ends with a stop, whatever happens in between."""
    legs = []
    try:
        for asked in speeds:
            if ask:
                ask(f"put the duck on its start mark, clear floor ahead, hand near STOP; Enter to walk at {asked} m/s for "
                    f"{ramp_s + seconds:g} s: ")
            hold(move, sleep, SETTLE_S, 0.0)
            s0 = sample()
            hold(move, sleep, ramp_s, asked)
            w0 = sample()
            hold(move, sleep, seconds, asked)
            w1 = sample()
            hold(move, sleep, STOP_S, 0.0)
            s1 = sample()
            tape = None
            if ask:
                text = ask("tape: distance from the start mark to where it stopped, metres (Enter to skip): ").strip()
                tape = float(text) if text else None
            legs.append(leg_metrics(asked, s0, w0, w1, s1, tape))
            tell(f"leg {asked} m/s: " + json.dumps(legs[-1]))
    finally:
        try:
            move(0.0)
        except (LeaseLost, RuntimeError, OSError):
            pass                                  # the lease is gone: the gate already stopped the robot, or the link is down
    return legs


def table(result: dict) -> str:
    lines = [f"walk speed against the asked speed  variant={result['variant']}  {result['seconds']} s measured after a {result['ramp_s']} s ramp",
             f"{'asked':>6}{'odom m/s':>10}{'gain':>7}{'truth m/s':>11}{'gain':>7}{'odom leg m':>12}{'truth leg m':>13}{'tape m':>8}{'scale':>7}"]
    for l in result["legs"]:
        g = lambda k, d=3: "-" if l.get(k) is None else f"{l[k]:.{d}f}"
        scale = l.get("odom_scale_by_tape", l.get("odom_scale_by_truth"))
        lines.append(f"{l['asked_mps']:>6.2f}{g('odom_mps'):>10}{g('odom_gain'):>7}{g('truth_mps'):>11}{g('truth_gain'):>7}"
                     f"{g('odom_leg_m'):>12}{g('truth_leg_m'):>13}{g('tape_leg_m', 2):>8}{'-' if scale is None else f'{scale:.3f}':>7}")
    lines.append("gain = measured / asked speed; scale = walked (tape, else truth) / believed distance over the whole leg")
    return "\n".join(lines)


class State:
    """The robot's odometry from robot.subscribe on its own connection (an open method: no lease needed, the gate relays it)."""

    def __init__(self, gate: Path, hz: int = 20):
        self.latest = None
        self._sock = socket.socket(socket.AF_UNIX)
        self._sock.settimeout(1.0)
        self._sock.connect(str(gate))
        self._f = self._sock.makefile("rw")
        for i, (method, params) in enumerate((("hello", {"client": CLIENT + "-state"}), ("robot.subscribe", {"hz": hz}))):
            self._f.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}) + "\n")
        self._f.flush()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                line = self._f.readline()
            except (TimeoutError, socket.timeout):
                continue
            except (OSError, ValueError):
                return
            if not line:
                return
            msg = json.loads(line)
            if msg.get("method") == "robot.state":
                self.latest = msg["params"]

    def wait(self, seconds: float = 3.0) -> None:
        end = time.monotonic() + seconds
        while self.latest is None and time.monotonic() < end:
            time.sleep(0.02)
        if self.latest is None:
            raise SystemExit("robotd sent no state in 3 s: no odometry to measure (is the link up: lab-link check?)")

    def close(self) -> None:
        self._stop.set()
        self._sock.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gate", type=Path, help="the gate's socket (default: the simulator host file's)")
    ap.add_argument("--real", action="store_true", help="the robot is not the simulator: required for the real duck, nothing else")
    ap.add_argument("--speeds", default="0.2,0.3", help="forward m/s, one leg each, comma separated (default 0.2,0.3)")
    ap.add_argument("--seconds", type=float, default=4.0, help="the measured part of a leg")
    ap.add_argument("--ramp-s", type=float, default=1.5, help="walking before the measured part, getting up to speed")
    ap.add_argument("--interactive", action="store_true", help="wait for the operator before each leg and ask for the tape distance after it")
    ap.add_argument("--json", action="store_true", help="print JSON, for the profile's `measured` notes, instead of the table")
    a = ap.parse_args(argv)
    speeds = parse_speeds(a.speeds)
    try:
        host = simhost.load()
    except simhost.HostError:
        host = None
    gate = a.gate or (host.sockets["gate"] if host is not None else None)
    if gate is None:
        raise Refused("no --gate and no simulator host file: say which gate's socket to walk through")
    if not Path(gate).exists():
        raise Refused(f"no socket {gate}: start lab-gate (and lab-link for the real duck) first")
    check_target(gate, host, a.real)
    rpc = Rpc(gate, client=CLIENT)
    try:
        check_free(rpc.call("gate.who").get("holder"))
    except SystemExit:
        rpc.close()
        raise
    variant = "simulator" if is_simulator(gate, host) else "real"
    body = None
    if variant == "simulator":
        from simhost.truth import Body
        body = Body(host.truth_port)
    state = State(gate)
    try:
        state.wait()
        rpc.call("gate.acquire")

        def sample() -> dict:
            st = state.latest
            s = {"odom": st["odom"]["position"][:2], "odom_t": st["t_ns"] / 1e9}
            if body is not None:
                pose, _, _, sim_time = body.read()
                s["truth"], s["truth_t"] = pose[:2], sim_time
            return s

        try:
            legs = walk(lambda vx: rpc.call("robot.move", {"vx": vx, "vy": 0.0, "vyaw": 0.0}), sample, time.sleep, speeds, a.seconds,
                        a.ramp_s, ask=input if a.interactive else None, tell=lambda m: print(m, file=sys.stderr))
        except LeaseLost as exc:
            raise SystemExit(f"lease ended ({exc.code}: {exc.reason or exc}): the robot was stopped by the gate") from None
        finally:
            for end in (lambda: rpc.call("gate.release"), state.close, rpc.close):
                try:
                    end()
                except (LeaseLost, RuntimeError, OSError):
                    pass
    finally:
        if body is not None:
            body.close()
    result = {"kind": "walk_speed", "variant": variant, "seconds": a.seconds, "ramp_s": a.ramp_s, "legs": legs}
    print(json.dumps(result, indent=1) if a.json else table(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
