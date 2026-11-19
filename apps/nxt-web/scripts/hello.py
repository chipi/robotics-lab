"""Find the NXT (USB, or Bluetooth via /dev/rfcomm*), print its name and battery, optionally turn one motor.

    uv run scripts/hello.py                      # info only, nothing moves
    uv run scripts/hello.py --motor A            # turn motor A 180 degrees at power 30
"""

import argparse

import nxt.locator
import nxt.motor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motor", choices=["A", "B", "C"])
    parser.add_argument("--degrees", type=int, default=180)
    parser.add_argument("--power", type=int, default=30, help="-100..100, negative = reverse")
    args = parser.parse_args()

    with nxt.locator.find(backends=["usb", "devfile"]) as brick:
        name, address, _, free_flash = brick.get_device_info()
        print(f"brick: {name}  address: {address}  free flash: {free_flash} bytes")
        print(f"battery: {brick.get_battery_level()} mV")

        if args.motor:
            motor = brick.get_motor(nxt.motor.Port[args.motor])
            before = motor.get_tacho().tacho_count
            motor.turn(args.power, args.degrees)
            after = motor.get_tacho().tacho_count
            print(f"motor {args.motor}: tacho {before} -> {after}")


if __name__ == "__main__":
    main()
