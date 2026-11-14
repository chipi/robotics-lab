"""HARDWARE CHECK (no motors): read the colour sensor on port 3 and the ultrasonic on port 4.
Stop any running nxt-web first (one connection to the brick at a time)."""

import time

import nxt.locator
import nxt.sensor
import nxt.sensor.generic as g

with nxt.locator.find(backends=["usb", "devfile"]) as brick:
    us = brick.get_sensor(nxt.sensor.Port.S4, g.Ultrasonic)
    col = brick.get_sensor(nxt.sensor.Port.S3, g.Color)
    try:
        print("port 4 sensor info:", us.get_sensor_info())
    except Exception as exc:
        print("port 4 sensor info failed:", type(exc).__name__, exc)
    for i in range(5):
        try:
            d = us.get_distance()
        except Exception as exc:
            d = f"{type(exc).__name__}: {exc}"
        try:
            c = col.get_color().name
            refl = col.get_reflected_light(g.Type.COLOR_RED)
        except Exception as exc:
            c, refl = f"{type(exc).__name__}: {exc}", None
        print(f"{i}: ultrasonic {d} cm | colour {c} | red reflected {refl}")
        time.sleep(0.4)
    col.set_light_color(g.Type.COLOR_NONE)
