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

from duck_lab.challenge.runner import Remote

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


code = "import sys, duck_lab.payload; print(sorted(m for m in sys.modules if m.split('.')[0] in ('simhost',)))"
out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
check("importing the payload loads no host library (simhost: the host file, the reset, the truth sampler)",
      out.returncode == 0 and out.stdout.strip() == "[]", (out.returncode, out.stdout, out.stderr[-300:]))

from duck_lab.challenge.runner import event  # noqa: E402

e = event("goal", "goal n 3", n=3, kind="box", text="kept")
check("a runner's event keeps a row's own `kind` and `text` fields as data (challenge 21's goal rows name a place kind)",
      e["kind"] == "goal" and e["text"] == "goal n 3" and e["raw"] == {"n": 3, "kind": "box", "text": "kept"}, e)

if sys.platform.startswith("linux"):
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
    try:
        for _ in range(50):
            if accepted:
                break
            time.sleep(0.1)
        fake = types.SimpleNamespace(proc=child)
        n = Remote.truth_connections(fake, port)
        m = Remote.truth_connections(fake, other.getsockname()[1])
        check("the counter sees a process's connection to the port (1), and none to another (0)", n == 1 and m == 0, (n, m))
        me = types.SimpleNamespace(proc=types.SimpleNamespace(pid=999_999_999))
        check("a process that is gone is not counted as clean: None (not measured)",
              Remote.truth_connections(me, port) is None)
    finally:
        child.kill()
        child.wait()
        srv.close()
        other.close()
else:
    print("NOT RUN the connection counter (no /proc on this platform: a run records it as not measured)")

print()
print("FAIL: " + ", ".join(failures) if failures else "all passed")
raise SystemExit(1 if failures else 0)
