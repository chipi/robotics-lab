"""HARDWARE CHECK — moves the robot: runs both tracks at power 25 for about 1 s. Lift the robot.
Stop any running nxt-web first (one connection to the brick at a time).

Uploads nxt/build/robotd.rxe (make nxt-programs), starts it, drives through its mailbox, then
stops sending — the way a crashed server or a dropped link would — and reads the motors directly.
Pass = the tracks ran while commands came, and robotd stopped them by itself 0.5-0.9 s after the
last one, with its deadman flag set (RFC-0003 §2.3). Leaves robotd.rxe on the brick, stopped.

Not checked here: the obstacle stop (it needs something in front of the sensor)."""

import time
from pathlib import Path

import nxt.error
import nxt.locator
import nxt.motor

from nxt_lab import deadman

RXE = Path(__file__).resolve().parents[1] / "build" / deadman.PROGRAM


def exchange(brick, message):
    brick.message_write(deadman.COMMAND_INBOX, message)
    for _ in range(6):
        try:
            return deadman.parse_state(brick.message_read(deadman.STATE_INBOX, 0, True)[1])
        except nxt.error.EmptyMailboxError:
            time.sleep(0.015)
    return None


def powers(brick):
    return {p.name: brick.get_output_state(p)[1] for p in (nxt.motor.Port.B, nxt.motor.Port.C)}


data = RXE.read_bytes()
with nxt.locator.find(backends=["usb", "devfile"]) as brick:
    try:
        brick.stop_program()
    except nxt.error.NoActiveProgramError:
        pass
    try:
        brick.file_delete(deadman.PROGRAM)
    except nxt.error.FileNotFoundError:
        pass
    with brick.open_file(deadman.PROGRAM, "wb", len(data)) as f:
        f.write(data)
    print(f"uploaded {deadman.PROGRAM} ({len(data)} bytes)")
    brick.start_program(deadman.PROGRAM)
    time.sleep(0.8)
    print("running:", brick.get_current_program_name())

    # fwd=0: the lifted robot's sensor may see the table, which would trigger the obstacle stop.
    answers = []
    for seq in range(1, 6):
        answers.append(exchange(brick, deadman.drive(seq, 25, 25, False)))
        time.sleep(0.2)
    running = powers(brick)
    last_command = time.monotonic()
    print("answers:", answers[-2:])
    print("powers while commands came:", running)

    stopped_after = None
    while time.monotonic() - last_command < 1.5:
        if all(v == 0 for v in powers(brick).values()):
            stopped_after = time.monotonic() - last_command
            break
        time.sleep(0.03)
    state = exchange(brick, deadman.query(99))
    print("stopped after:", None if stopped_after is None else f"{stopped_after:.2f} s", "| state:", state)

    exchange(brick, deadman.stop(100))
    brick.stop_program()
    for p in (nxt.motor.Port.B, nxt.motor.Port.C):
        brick.get_motor(p).idle()

ok = (all(a is not None for a in answers) and running == {"B": 25, "C": 25}
      and stopped_after is not None and 0.4 <= stopped_after <= 0.9
      and state is not None and state["deadman_stop"])
print("DEADMAN", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
