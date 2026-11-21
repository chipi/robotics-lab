"""The payload and the truth (RFC-0021 step 2): the navigator's process is handed no route to the simulator's truth. Static:
importing the payload loads neither the host library nor anything that names the host. Live, the runner counts the
payload process's connections to the truth's port (runner.Remote.truth_connections); here that counter is shown to count
a real connection (a process connected to a port is 1, another port 0), so a 0 from it in a run means something. No
simulator. Run: cd robots/duck && uv run python tests/test_payload.py"""

import socket
import subprocess
import sys
import threading
import time
import types

from labrunner.remote import Remote

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


for module, what in (("duck_lab.payload", "the payload"), ("duck_lab.nav.server", "Mission Control's navigator API (RFC-0021 step 6)")):
    code = f"import sys, {module}; print(sorted(m for m in sys.modules if m.split('.')[0] in ('simhost', 'labrunner')))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    check(f"importing {what} loads no host library (simhost: the host file, the reset, the truth sampler) and no runner (labrunner, RFC-0022)",
          out.returncode == 0 and out.stdout.strip() == "[]", (out.returncode, out.stdout, out.stderr[-300:]))

import inspect  # noqa: E402

from duck_lab.nav import run as nav_run  # noqa: E402

check("the navigator cannot be handed the truth: no `body` among its arguments, no truth reader in its module, and "
      "host_links gives sockets only (RFC-0021 step 6)",
      "body" not in inspect.signature(nav_run.Navigator).parameters and not hasattr(nav_run, "Body")
      and "truth" not in inspect.signature(nav_run.host_links).parameters,
      list(inspect.signature(nav_run.Navigator).parameters))

import ast  # noqa: E402
from pathlib import Path  # noqa: E402

# Every Navigator(...) in the package and its tools names only arguments the navigator takes (2026-11-21: `body` was removed
# and the navigator API still passed it; no unit test starts a goal there, only the live run found it).
known = set(inspect.signature(nav_run.Navigator).parameters)
root = Path(nav_run.__file__).resolve().parents[3]          # robots/duck
bad = []
for f in list((root / "src").rglob("*.py")) + list((root / "sim").rglob("*.py")) + list((root / "payloads").rglob("*.py")):
    for node in ast.walk(ast.parse(f.read_text(), str(f))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "Navigator":
            bad += [f"{f.relative_to(root)}:{node.lineno} {k.arg}" for k in node.keywords if k.arg and k.arg not in known]
check("every call of the navigator names only the arguments it takes", not bad, bad)

from labrunner.remote import event  # noqa: E402

e = event("goal", "goal n 3", n=3, kind="box", text="kept")
check("a runner's event keeps a row's own `kind` and `text` fields as data (challenge 21's goal rows name a place kind)",
      e["kind"] == "goal" and e["text"] == "goal n 3" and e["raw"] == {"n": 3, "kind": "box", "text": "kept"}, e)

import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

from labrunner import remote as runner  # noqa: E402

srv = socket.socket()
srv.bind(("127.0.0.1", 0))
srv.listen()
port = srv.getsockname()[1]
other = socket.socket()
other.bind(("127.0.0.1", 0))
other.listen()
accepted = []
threading.Thread(target=lambda: accepted.append(srv.accept()), daemon=True).start()
child = subprocess.Popen([sys.executable, "-c",
                          f"import socket, time; s = socket.create_connection(('127.0.0.1', {port})); time.sleep(30)"])
ways = []
if Path("/proc").exists():
    ways.append((Path("/proc"), "/proc"))
if shutil.which("lsof"):
    ways.append((Path("/nonexistent/proc"), "lsof (no /proc, as on macOS)"))
try:
    for _ in range(50):
        if accepted:
            break
        time.sleep(0.1)
    for proc, way in ways:
        runner.PROC = proc
        fake = types.SimpleNamespace(proc=child)
        n = Remote.truth_connections(fake, port)
        m = Remote.truth_connections(fake, other.getsockname()[1])
        check(f"{way}: the counter sees a process's connection to the port (1), and none to another (0)", n == 1 and m == 0,
              (n, m))
        me = types.SimpleNamespace(proc=types.SimpleNamespace(pid=999_999_999))
        check(f"{way}: a process that is gone is not counted as clean: None (not measured)",
              Remote.truth_connections(me, port) is None)
    if not ways:
        print("NOT RUN the connection counter (no /proc and no lsof: a run records it as not measured)")
finally:
    runner.PROC = Path("/proc")
    child.kill()
    child.wait()
    srv.close()
    other.close()

from duck_lab.nav import explore_run  # noqa: E402
from labrunner import explore_score  # noqa: E402

check("the runner reads the explorer's end events by the names the explorer writes (one copy each side, RFC-0022)",
      explore_run.ENDS == explore_score.ENDS, (explore_run.ENDS, explore_score.ENDS))

print()
print("FAIL: " + ", ".join(failures) if failures else "all passed")
raise SystemExit(1 if failures else 0)
