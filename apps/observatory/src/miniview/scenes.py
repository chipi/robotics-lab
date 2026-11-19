"""Scenes: what is really there, in the world frame (CONTRACT.md)."""

import json
from pathlib import Path


def from_mujoco_layout(layout: Path, scene_id: str, name: str, stairs=(-0.40, 0.00, -1.40, -0.70)) -> dict:
    """The duck simulator's layout (sim/apartment_layout.json: geoms with type, pos, size, yaw,
    collides) as a scene. Floors are left out; cylinders become boxes with equal half sizes."""
    boxes = []
    for g in json.loads(layout.read_text())["geoms"]:
        if not g.get("collides") or str(g.get("name", "")).startswith("floor") or g.get("type") not in ("box", "cylinder"):
            continue
        hx, hy = (g["size"][0], g["size"][1]) if g["type"] == "box" else (g["size"][0], g["size"][0])
        hz = g["size"][2] if g["type"] == "box" else g["size"][1]
        boxes.append({"name": g.get("name", ""), "cx": g["pos"][0], "cy": g["pos"][1],
                      "z0": round(g["pos"][2] - hz, 4), "z1": round(g["pos"][2] + hz, 4),
                      "hx": hx, "hy": hy, "yaw": g.get("yaw", 0.0)})
    x0, x1, y0, y1 = stairs
    return {"id": scene_id, "name": name, "kind": "apartment", "frame": "world",
            "bounds": [-4.0, 4.0, -3.0, 3.0], "boxes": boxes,
            "hazards": [{"name": "stairs", "kind": "drop", "x0": x0, "x1": x1, "y0": y0, "y1": y1, "depth": 0.3}]}
