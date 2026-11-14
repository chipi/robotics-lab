"""What this computer can see of the NXT on each link, independent of the current connection."""

import glob
import re
import shutil
import subprocess
from pathlib import Path

LEGO_VENDOR = "0694"


def usb_present() -> bool:
    return any(p.read_text().strip() == LEGO_VENDOR for p in Path("/sys/bus/usb/devices").glob("*/idVendor"))


def _run(cmd: list[str]) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def bluetooth() -> dict:
    """rfcomm bindings (`rfcomm` prints e.g. "rfcomm0: 00:16:53:0F:4C:2A channel 1 connected"),
    and for each bound address whether BlueZ has it paired and connected."""
    devices = sorted(glob.glob("/dev/rfcomm*"))
    bindings = []
    for line in _run(["rfcomm"]).splitlines():
        m = re.match(r"(rfcomm\d+): ([0-9A-F:]{17}) channel (\d+) (\S+)", line.strip())
        if not m:
            continue
        dev, addr, channel, state = m.groups()
        info = _run(["bluetoothctl", "info", addr])
        bindings.append({
            "device": f"/dev/{dev}",
            "address": addr,
            "channel": int(channel),
            "rfcomm_state": state,
            "name": _field(info, "Name"),
            "paired": _field(info, "Paired") == "yes",
            "connected": _field(info, "Connected") == "yes",
        })
    return {"devices": devices, "bindings": bindings, "rfcomm_tool": bool(shutil.which("rfcomm"))}


def _field(text: str, name: str):
    m = re.search(rf"^\s*{name}: (.*)$", text, re.M)
    return m.group(1).strip() if m else None
