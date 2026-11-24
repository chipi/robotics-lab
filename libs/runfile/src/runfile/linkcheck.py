"""The link check (phase 5 item 4e unit E9): the one question `lab-link` and Mission Control both ask a robot's socket, so a forward's
liveness is judged the same way on both sides. Standard library only.

Why it asks, not only connects: when the robot's end of an ssh forward is gone, the local socket file stays and a connect still succeeds;
the connection is closed a moment later. Only a request that gets an answer (or an end of stream) tells a live socket from a dead one."""

import json
import socket
import stat
import time
from pathlib import Path

CHECK_TIMEOUT_S = 2.0        # one question to one socket

# what a dead end means for a forward (ssh) and for the gate (a process on this machine)
WORDS = {False: {"missing": "the forward is not up", "refused": "a stale socket file: ssh is gone",
                 "closed": "the forward is up but the robot's end is gone", "silent": "the link is silent"},
         True: {"missing": "the gate is not running", "refused": "a stale socket file: the gate has exited",
                "closed": "the gate hung up", "silent": "the gate is silent"}}


def check_socket(path, method: str, timeout_s: float = CHECK_TIMEOUT_S, gate: bool = False) -> tuple:
    """Ask one socket one read-only question: (True, "answered", ms) if any JSON object comes back (a result or an error is a live end),
    else (False, why, None). Each way to be dead names itself; `gate` words the dead ends for the gate's socket, not an ssh forward's."""
    words = WORDS[gate]
    p = Path(path)
    try:
        mode = p.stat().st_mode
    except FileNotFoundError:
        return False, f"no socket file {p} ({words['missing']})", None
    except OSError as exc:
        return False, f"{p}: {exc}", None
    if not stat.S_ISSOCK(mode):
        return False, f"{p} is not a socket", None
    t0 = time.monotonic()
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout_s)
    try:
        s.connect(str(p))
        s.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": method}) + "\n").encode())
        line = s.makefile("r").readline()
    except (ConnectionRefusedError, FileNotFoundError):
        return False, f"nothing listens ({words['refused']})", None
    except (ConnectionResetError, BrokenPipeError):         # the hang-up can land before or after the request: both are the same dead end
        return False, f"closed on {method} ({words['closed']})", None
    except (socket.timeout, TimeoutError):
        return False, f"no answer to {method} in {timeout_s:g} s ({words['silent']})", None
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}", None
    finally:
        s.close()
    if not line:
        return False, f"closed on {method} ({words['closed']})", None
    try:
        msg = json.loads(line)
    except ValueError:
        return False, f"answered {method} with something that is not JSON", None
    if not isinstance(msg, dict):
        return False, f"answered {method} with something that is not JSON-RPC", None
    return True, "answered", (time.monotonic() - t0) * 1000
