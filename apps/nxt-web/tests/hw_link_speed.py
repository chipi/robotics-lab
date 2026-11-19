"""HARDWARE CHECK (no motors): talk to the NXT over Bluetooth only (/dev/rfcomm0): info, battery,
and the time per command. Stop any running nxt-web first (one connection to the brick at a time)."""

import time

import nxt.locator
import nxt.motor

t0 = time.monotonic()
with nxt.locator.find(backends=["devfile"]) as brick:
    print(f"connected via {brick._sock} in {time.monotonic() - t0:.2f} s")
    name, address, _, free = brick.get_device_info()
    print(f"brick {name} {address}, free flash {free}, battery {brick.get_battery_level()} mV")
    times = []
    for _ in range(20):
        t = time.monotonic()
        brick.get_output_state(nxt.motor.Port.B)
        times.append((time.monotonic() - t) * 1000)
    times.sort()
    print(f"20 reads of one motor's state: median {times[10]:.0f} ms, min {times[0]:.0f} ms, max {times[-1]:.0f} ms")
