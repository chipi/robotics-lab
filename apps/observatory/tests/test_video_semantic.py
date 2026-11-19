"""The semantic map in the video export (RFC-0016, ADR-0019), with no MuJoCo and no rendering: the track a run becomes (objects through the
run's epoch into the world the video renders, each frame's current sighting with its detections placed from the robot's pose, the HUD's
SEES / ROOM / OBJECTS entries), the job the engine is given, what an old run gets (nothing), and the overlay's own geometry (the HUD's
lines, the eye inset's pinhole projection, the top inset's pixels, the camera's wedge). Drawing on an image needs Pillow, which is the
engine's Python's, not Observatory's: that part runs in the robot's MuJoCo Python when the machine has it, and says NOT RUN when it has not.
Run: cd apps/observatory && uv run python tests/test_video_semantic.py"""

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from helpers import Checks, make_run, tick
from runfile import keys
from observatory import video

ENGINES = Path(video.__file__).resolve().parent / "engines"
sys.path.insert(0, str(ENGINES))
import overlay  # noqa: E402

check = Checks("VIDEO SEMANTIC")
PY = video.python_of(video.ROBOTS["duck"]["mujoco"])           # the machine's MuJoCo Python, read before a test points the export at a stand-in
EPOCH = [0.5, -0.2, 0.3]
FRIDGE = {"id": "fridge_1", "kind": "fridge", "x": 1.5, "y": 0.5, "confirmed": True, "landmark": 1.0, "parts": [[1.5, 0.5, 0.3, 0.25, 0.4, 0.0, 1.7]]}
CABINET = {"id": "cabinet_1", "kind": "cabinet", "x": 0.5, "y": -0.5, "confirmed": False, "landmark": 0.5, "parts": [[0.5, -0.5, 0.25, 0.25, 0.0, 0.0, 0.6]]}
SEEN = {"kind": "fridge", "x": 1.0, "y": 0.4, "radius": 0.4, "z0": 0.0, "z1": 1.7, "range_m": 1.08, "confidence": 0.8, "source": "sim_camera"}
SIGHTING_POSE = [0.5, 0.1, 0.2]


def compose(a, b):
    c, s = math.cos(a[2]), math.sin(a[2])
    return [a[0] + c * b[0] - s * b[1], a[1] + s * b[0] + c * b[1], a[2] + b[2]]


def records(truth=True, semantic=True):
    out = [(0.0, "epoch", {"map_to_world": EPOCH})]
    for k in range(30):
        b = [0.05 * k, 0.01 * k, 0.2]
        out.append(tick(round(1.0 + 0.1 * k, 3), b[0], belief=b, truth=compose(EPOCH, b) if truth else None, cmd=[0.3, 0.0], depth=[]))
    if semantic:
        out += [(1.5, "objects", {"objects": [CABINET], "changes": [["new", "cabinet_1"]]}),
                (2.0, "objects", {"objects": [CABINET, FRIDGE], "changes": [["confirmed", "fridge_1"]]}),
                (2.0, "sighting", {"pose": SIGHTING_POSE, "hfov_deg": 60.0, "range_m": 3.0, "seen": [SEEN]}),
                (2.5, "sighting", {"pose": [0.6, 0.12, 0.2], "hfov_deg": 60.0, "range_m": 3.0, "seen": []}),
                (2.6, "event", {"kind": "room", "text": "room kitchen", "notable": False, "t_src": 2.6, "raw": {}, "room": "kitchen",
                                "votes": {"office": 0.1, "kitchen": 0.4}, "decision": {"rule": "room", "reason": "x", "values": {}}}),
                (1.2, "event", {"kind": "tight_pivot", "text": "tight_pivot", "notable": True, "t_src": 1.2, "raw": {},
                                "decision": {"rule": "tight_pivot", "reason": "no clear floor", "values": {"room_m": 0.156}}})]
    return sorted(out, key=lambda r: r[0]) + [(3.95, "end", {"verdict": "reached"})]


def frame_at(tr, t):
    return min(tr["frames"], key=lambda f: abs(f["t"] - t))


def near(a, b, tol=1e-3):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    make_run(data, "duck/room/v1", records())
    make_run(data, "duck/room/old", records(semantic=False))
    make_run(data, "duck/room/field", records(truth=False))
    d = lambda name: keys.run_dir(data, keys.make_key("duck", "room", name))  # noqa: E731

    # ---- the track: geometry through the epoch, the sighting, the HUD ------------------------------------------------------
    tr = video.track(d("v1"), fps=10, hud=True, semantic=True)
    snaps = tr["semantic"]["objects"]
    x, y, yaw = compose(EPOCH, [1.5, 0.5, 0.4])
    check("the objects are snapshots in the world frame the video renders: the fridge's part through the epoch (position and heading), its size and heights as they are",
          [s["t"] for s in snaps] == [1.5, 2.0] and near(snaps[1]["items"][1]["parts"][0][:2], [x, y], 1e-3) and abs(snaps[1]["items"][1]["parts"][0][4] - yaw) < 1e-3
          and snaps[1]["items"][1]["parts"][0][2:4] == [0.3, 0.25] and snaps[1]["items"][1]["parts"][0][5:] == [0.0, 1.7] and snaps[1]["items"][1]["confirmed"], snaps[1])
    f = frame_at(tr, 2.05)
    check("a frame at 2.05 s: the second snapshot, the sighting at 2.0 s", f["obj_i"] == 1 and f["sighting"] is not None and f["sighting"]["hfov_deg"] == 60.0 and f["sighting"]["range_m"] == 3.0, f["sighting"])
    check("the sighting's pose is the belief's, through the epoch (the camera's wedge is drawn where the objects are)", near(f["sighting"]["pose"], compose(EPOCH, SIGHTING_POSE), 1e-3), f["sighting"]["pose"])
    # the detection is placed from the robot's pose in the frame (the truth's), as the simulated camera saw it, not from the belief
    w_, x_, y_, z_ = f["quat"]
    tyaw = math.atan2(2 * (w_ * z_ + x_ * y_), 1 - 2 * (y_ * y_ + z_ * z_))
    want = compose([f["pos"][0], f["pos"][1], tyaw], [SEEN["x"], SEEN["y"], 0.0])
    check("a detection is placed from the robot's own pose in the frame: its position plus the relative x (ahead) and y (left) turned by its heading",
          near(f["sighting"]["seen"][0]["world"], want[:2], 1e-3) and f["sighting"]["seen"][0]["rel"] == [1.0, 0.4] and f["sighting"]["seen"][0]["kind"] == "fridge", f["sighting"]["seen"])
    h = f["hud"]
    check("the HUD at 2.05 s: sees the fridge (range, confidence), no room told yet, 1 of 2 objects confirmed",
          h["sees"] == [{"kind": "fridge", "range_m": 1.08, "confidence": 0.8}] and h["room"] is None and h["objects"] == {"confirmed": 1, "total": 2}, h)
    h = frame_at(tr, 1.1)["hud"]
    check("before anything: no sighting yet, no room, no objects (the keys are there, the lines say so)", h["sees"] is None and h["room"] is None and h["objects"] == {"confirmed": 0, "total": 0}
          and frame_at(tr, 1.1)["obj_i"] is None and frame_at(tr, 1.1)["sighting"] is None, h)
    h = frame_at(tr, 2.9)["hud"]
    check("at 2.9 s: the 2.5 s sighting saw nothing, the room is told with its votes",
          h["sees"] == [] and h["room"] == {"name": "kitchen", "votes": {"office": 0.1, "kitchen": 0.4}}, h)
    check("... and a sighting older than a second is not current", frame_at(tr, 3.8)["sighting"] is None and frame_at(tr, 3.8)["hud"]["sees"] == [])
    check("the room is not what the robot is doing: the HUD's DOING stays the pivot", frame_at(tr, 2.9)["hud"]["doing"]["rule"] == "tight_pivot", frame_at(tr, 2.9)["hud"]["doing"])

    # ---- a run from before, a run from the field ----------------------------------------------------------------------------
    old = video.track(d("old"), fps=10, hud=True, semantic=True)
    check("a run with no semantic map gets none of it: no semantic part, no obj_i or sighting on a frame, no sees, room or objects in the HUD",
          "semantic" not in old and all("obj_i" not in f and "sighting" not in f and not {"sees", "room", "objects"} & set(f["hud"]) for f in old["frames"]), old["frames"][0])
    plain = video.track(d("v1"), fps=10, hud=True)
    check("without semantic=True nothing is added either, and the room is not a decision",
          "semantic" not in plain and all("sighting" not in f for f in plain["frames"]) and plain["frames"][-1]["hud"]["doing"]["rule"] == "tight_pivot")
    fld = video.track(d("field"), fps=10, semantic=True)
    check("a run with no truth is drawn in the map frame: the objects are where the robot put them, no epoch",
          fld["frame"] == "map" and fld["semantic"]["objects"][1]["items"][1]["parts"][0][:2] == [1.5, 0.5] and near(frame_at(fld, 2.05)["sighting"]["pose"], SIGHTING_POSE), fld["semantic"]["objects"][1])

    # ---- export hands the engine the job with it, only when an inset wants it ----------------------------------------------------
    dump = Path(tmp) / "dump_engine.py"
    dump.write_text("import json, sys\njob = json.load(open(sys.argv[1]))\nopen(job['out'], 'w').write(json.dumps({'insets': job['insets'], 'semantic': 'semantic' in job['track'], "
                    "'sighting': any(f.get('sighting') for f in job['track']['frames']), 'hud': any('sees' in f.get('hud', {}) for f in job['track']['frames'])}))\n")
    os.environ["VIDEO_MUJOCO_SCRIPT"], os.environ["VIDEO_MUJOCO_PYTHON"] = str(dump), sys.executable
    got = {}
    for name, insets in (("all", ("eye", "top", "hud")), ("none", ())):
        out = video.export(data, "duck/room/v1", "mujoco", Path(tmp) / f"{name}.json", fps=5, insets=insets)
        got[name] = json.loads(out.read_text())
    check("the job carries the semantic part, the sightings and the HUD's entries for the insets; a plain export carries none",
          got["all"] == {"insets": ["eye", "top", "hud"], "semantic": True, "sighting": True, "hud": True} and got["none"] == {"insets": [], "semantic": False, "sighting": False, "hud": False}, got)

# ---- the overlay's geometry (pure) ---------------------------------------------------------------------------------------------------
lines = overlay.hud_lines({"t": 2.0, "sees": [{"kind": "fridge", "range_m": 1.08, "confidence": 0.8}, {"kind": "shelf", "range_m": 2.5, "confidence": 0.5}],
                           "room": {"name": "kitchen", "votes": {"office": 0.1, "kitchen": 0.4}}, "objects": {"confirmed": 3, "total": 5}}, 60)
text = [t for t, _ in lines]
check("the HUD's lines from a sighting, a room and the objects: SEES with each kind, range and confidence; ROOM with its votes, strongest first; OBJECTS confirmed and not yet",
      text == ["SEES  fridge 1.1 m 80% · shelf 2.5 m 50%", "ROOM  kitchen (kitchen 0.40 · office 0.10)", "OBJECTS 3 confirmed · 2 not yet"], text)
check("a sighting that saw nothing, no sighting yet, an unnamed room, no room told",
      [t for t, _ in overlay.hud_lines({"sees": [], "room": {"name": None, "votes": {}}, "objects": {"confirmed": 0, "total": 0}}, 60)][:2] == ["SEES  nothing in view", "ROOM  unnamed"]
      and overlay.hud_lines({"sees": None, "room": None}, 60)[0][0] == "SEES  no sighting yet" and overlay.hud_lines({"sees": None, "room": None}, 60)[1][0] == "ROOM  not told yet")
check("a HUD with none of the three (a run with no semantic map) adds no lines", overlay.hud_lines({"t": 1.0, "cmd": [0.3, 0.0]}, 60) == [])
long = overlay.hud_lines({"sees": [{"kind": f"kind{i}", "range_m": 1.0, "confidence": 0.5} for i in range(8)]}, 40)
check("a long SEES list wraps to two lines at most, the second ends with an ellipsis", len([t for t, _ in long if t.startswith(("SEES", "      "))]) == 2 and long[1][0].endswith("…"), long)

pos, fwd = (0.0, 0.0, 0.1), (1.0, 0.0, 0.0)
pr = overlay.eye_projector(pos, fwd, 200, 90.0)
check("a point straight ahead is the image's centre; at 45 degrees (fov 90) it is on the edge; left of the axis is left in the image, above it is up",
      near(pr((2.0, 0.0, 0.1))[:2], [100, 100], 1e-6) and near(pr((2.0, 2.0, 0.1))[:2], [0, 100], 1e-6) and pr((2.0, -1.0, 0.1))[0] > 100 and pr((2.0, 0.0, 0.6))[1] < 100,
      (pr((2.0, 0.0, 0.1)), pr((2.0, 2.0, 0.1))))
check("a point behind the camera does not project; a camera looking straight up has no projector", pr((-1.0, 0.0, 0.1)) is None and overlay.eye_projector(pos, (0, 0, 1), 200, 90) is None)
tilt = overlay.eye_projector(pos, (math.cos(0.5), 0.0, -math.sin(0.5)), 200, 60.0)                # looking down 0.5 rad
check("looking down, the floor just ahead is below the centre and the far floor above it", tilt((0.1, 0.0, 0.0))[1] > 100 and tilt((2.0, 0.0, 0.0))[1] < 100)
box = overlay.seen_box(pr, {"world": [2.0, 0.0], "radius": 0.2, "z0": 0.0, "z1": 1.0})
check("a detection is the box its footprint and heights cover in the image: wider than it is far off-axis, taller than its heights, in front of the camera",
      box is not None and box[0] < 100 < box[2] and box[1] < 100 - 1 and box[3] > 100 and box[4] > 1.7, box)
check("a detection with a corner behind the camera has no box", overlay.seen_box(pr, {"world": [0.1, 0.0], "radius": 0.3, "z0": 0.0, "z1": 1.0}) is None)
px = overlay.top_to_px(300, (1.0, 2.0, 0.0), 4.0, 45.0)
half = 4.0 * math.tan(math.radians(22.5))
check("the top inset: the look-at point is the centre, +y is up the image, +x right, and the visible half-width is distance x tan(fov/2)",
      near(px(1.0, 2.0), [150, 150], 1e-6) and px(1.0, 3.0)[1] < 150 and px(2.0, 2.0)[0] > 150 and near(px(1.0 + half, 2.0), [300, 150], 1e-6), px(1.0, 2.0))
wd = overlay.wedge([1.0, 1.0, math.pi / 2], 60.0, 3.0, 6)
check("the camera's wedge: its apex at the pose, an arc at the range spanning the field of view, centred on the heading",
      wd[0] == (1.0, 1.0) and len(wd) == 8 and all(abs(math.dist(wd[0], p) - 3.0) < 1e-9 for p in wd[1:]) and abs((wd[1][0] - 1.0) / 3 - math.cos(math.pi / 2 - math.radians(30))) < 1e-9 and abs(wd[4][0] - 1.0) < 1e-9, wd)
check("an object's colour: a landmark (0.7 or more, confirmed or not), a confirmed one, an unconfirmed one", overlay.object_rgb({"landmark": 1.0, "confirmed": False}) == overlay.LANDMARK_RGB
      and overlay.object_rgb({"landmark": 0.7, "confirmed": False}) == overlay.LANDMARK_RGB and overlay.object_rgb({"landmark": 0.69, "confirmed": False}) == overlay.UNCONFIRMED_RGB
      and overlay.object_rgb({"landmark": 0.5, "confirmed": True}) == overlay.CONFIRMED_RGB and overlay.object_rgb({"landmark": 0.5}) == overlay.UNCONFIRMED_RGB)

# ---- drawing on an image: the engine's Python has Pillow ---------------------------------------------------------------------------------------

PROBE = f'''
import json, sys
sys.path.insert(0, {str(ENGINES)!r})
import overlay
from PIL import Image
img = Image.new("RGB", (200, 200), (0, 0, 0))
pr = overlay.eye_projector((0.0, 0.0, 0.1), (1.0, 0.0, 0.0), 200, 90.0)
sighting = {{"seen": [{{"kind": "fridge", "confidence": 0.8, "world": [2.0, 0.0], "radius": 0.2, "z0": 0.0, "z1": 1.0}},
                 {{"kind": "behind", "world": [-2.0, 0.0], "radius": 0.2}}]}}
labels = overlay.draw_eye(img, sighting, pr, None)
x0, y0, x1, y1 = (int(round(v)) for v in overlay.seen_box(pr, sighting["seen"][0])[:4])
top = Image.new("RGB", (300, 300), (0, 0, 0))
px = overlay.top_to_px(300, (0.0, 0.0, 0.0), 4.0, 45.0)
snap = {{"items": [{{"id": "f", "kind": "fridge", "confirmed": True, "landmark": 0.0, "parts": [[0.0, 0.0, 0.4, 0.4, 0.0, 0.0, 1.0]]}}]}}
overlay.draw_top(top, snap, {{"pose": [-1.0, -1.0, 0.0], "hfov_deg": 60.0, "range_m": 2.0}}, px, None)
foot, wedge = top.getpixel((150, 150)), top.getpixel(tuple(int(v) for v in px(0.5, -1.0)))
print(json.dumps({{"labels": labels, "edge": list(img.getpixel((x0, (y0 + y1) // 2))), "inside": list(img.getpixel((100, 100))),
                  "footprint_green": foot[1] > foot[0] and foot[1] > foot[2] and foot[1] > 40, "wedge_blue": wedge[2] > wedge[0] and wedge[2] > 10,
                  "corner": list(top.getpixel((5, 5)))}}))
'''
if Path(PY).is_file():
    r = subprocess.run([PY, "-c", PROBE], capture_output=True, text=True)
    try:
        res = json.loads(r.stdout)
    except ValueError:
        res = None
    check("drawing (in the engine's Python): the eye's box is outlined in the detection colour with its label, its inside untouched, the detection behind the camera left out",
          res is not None and res["labels"] == ["fridge 80%"] and res["edge"] == list(overlay.SEEN_RGB) and res["inside"] == [0, 0, 0], (r.stderr or r.stdout)[-300:])
    check("... the top inset: the footprint filled with the confirmed colour, the wedge tinted blue, the rest of the image untouched",
          res is not None and res["footprint_green"] and res["wedge_blue"] and res["corner"] == [0, 0, 0], res)
else:
    print(f"NOT RUN drawing on an image: no MuJoCo Python at {PY} (set VIDEO_MUJOCO_PYTHON)")

check.done()
