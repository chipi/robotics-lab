"""The simulated depth sensor's impairments (docs/wip/RESEARCH-R1-R2.md, R2; no simulator). Run: cd robots/duck && uv run python tests/test_depth_impair.py

Off unless a run turns it on, and only ever in the simulator. Seeded: one seed, one run. Each impairment's statistics over many
frames, the invalid zone's status (not 255, so never a drop), the dropped frame and the one frame of latency.
"""

import math
import statistics
import sys

from duck_lab.plugins.depth_impair import DepthImpairment
from duck_lab.plugins.tof8x8 import Tof8x8, rotate
from duck_lab.profile import load

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


SIM, REAL = load("sim"), load("real")
BLOCK = SIM.sensors.tof8x8.impairment.data
QUIET = {"enabled": True, "seed": 1, "bias_m": 0.0, "scale": 0.0, "zone_bias_m": 0.0, "invalid_zone_p": 0.0,
         "frame_dropout_p": 0.0, "latency_frames_max": 0}


def imp(**over) -> DepthImpairment:
    return DepthImpairment.from_profile(SIM, {**QUIET, **over})


def flat(mm=1000, n=64, status=5, seq=0):
    return {"rows": 8, "cols": 8, "distance_mm": [mm] * n, "status": [status] * n, "t_ns": 1_000 * seq, "seq": seq}


# ---- off by default, and never on the real duck ---------------------------------------------------------------------------
off = DepthImpairment.from_profile(SIM)
f0 = flat()
check("the simulator's profile ships it off", BLOCK["enabled"] is False, BLOCK)
check("off: the frame is passed on as it is", off.apply(f0) is f0 and not off.enabled)
check("off: the record says so", off.record()["enabled"] is False, off.record())
check("a sensor built from the simulator's profile has it off", Tof8x8(SIM).impairment.enabled is False)
check("the real duck's profile has no impairment block at all", REAL.sensors.tof8x8.get("impairment") is None)
check("the real duck's sensor has it off", Tof8x8(REAL).impairment.enabled is False)
try:
    DepthImpairment.from_profile(REAL, {"enabled": True, "seed": 1})
    refused = False
except ValueError as e:
    refused = "simulator" in str(e)
check("asking for it on the real duck's frames is refused, naming the simulator", refused)
check("the real duck's sensor never impairs a frame", Tof8x8(REAL).impairment.apply(f0) is f0)

# ---- the defaults are NVIDIA's (sensors.py of isaaclab_tasks.contrib.microduck_obstacle at 802b8d5) ------------------------
for k, v in {"min_range_m": 0.12, "bias_m": 0.02, "scale": 0.02, "zone_bias_m": 0.01, "invalid_zone_p": 0.03,
             "frame_dropout_p": 0.02, "latency_frames_max": 1}.items():
    check(f"the profile's {k} is NVIDIA's {v}", BLOCK[k] == v, BLOCK.get(k))

# ---- minimum range ---------------------------------------------------------------------------------------------------------
m = imp(min_range_m=0.12).apply({**flat(), "distance_mm": [50, 119, 120, 121, 300, 1000, 3990, 4010] + [500] * 56})
st, dm = m["status"], m["distance_mm"]
check("a return under 0.12 m is invalid: status the plugin does not read as a return, distance 0",
      st[0] == st[1] == imp().invalid_status and dm[0] == dm[1] == 0, (st[:3], dm[:3]))
check("0.12 m and over stays a return", st[2:7] == [5] * 5 and dm[2:7] == [120, 121, 300, 1000, 3990], (st[2:7], dm[2:7]))
check("beyond the sensor's range after the impairment: invalid too", st[7] == imp().invalid_status and dm[7] == 0, (st[7], dm[7]))
nt = imp(min_range_m=0.12).apply({**flat(), "distance_mm": [0] * 64, "status": [255] * 64})
check("a zone with no target (255) is left as the simulator said it", nt["status"] == [255] * 64 and nt["distance_mm"] == [0] * 64)

# ---- per-episode bias, scale, per-zone bias: many episodes, a fixed seed ----------------------------------------------------
N = 2000
bias = [imp(seed=s, bias_m=0.02).episode["bias_m"] for s in range(N)]
check("episode bias: uniform in +-2 cm (within the range)", min(bias) >= -0.02 and max(bias) <= 0.02 and max(bias) > 0.019 and min(bias) < -0.019,
      (min(bias), max(bias)))
check("episode bias: mean 0 and the std of a uniform (0.0115 m)", abs(statistics.fmean(bias)) < 0.001 and abs(statistics.pstdev(bias) - 0.02 / math.sqrt(3)) < 0.0008,
      (statistics.fmean(bias), statistics.pstdev(bias)))
scale = [imp(seed=s, scale=0.02).episode["scale"] for s in range(N)]
check("episode scale: uniform in 0.98 to 1.02, mean 1", min(scale) >= 0.98 and max(scale) <= 1.02 and abs(statistics.fmean(scale) - 1.0) < 0.001,
      (min(scale), max(scale), statistics.fmean(scale)))
zb = [b for s in range(200) for b in imp(seed=s, zone_bias_m=0.01).episode["zone_bias_m"]]
check("per-zone bias: 64 numbers an episode, uniform in +-1 cm, mean 0", len(zb) == 200 * 64 and min(zb) >= -0.01 and max(zb) <= 0.01
      and abs(statistics.fmean(zb)) < 0.0003 and abs(statistics.pstdev(zb) - 0.01 / math.sqrt(3)) < 0.0004, (len(zb), statistics.fmean(zb), statistics.pstdev(zb)))
same_ep = imp(seed=3, bias_m=0.02, scale=0.02, zone_bias_m=0.01)
a, b = same_ep.apply(flat(2000, seq=1)), same_ep.apply(flat(2000, seq=2))
check("within an episode the bias is one: two frames of the same scene read alike", a["distance_mm"] == b["distance_mm"])
check("an episode's zones differ from each other (per-zone bias)", len(set(a["distance_mm"])) > 8, len(set(a["distance_mm"])))
e = same_ep.episode
want = [round((2.0 * e["scale"] + e["bias_m"] + e["zone_bias_m"][i]) * 1000) for i in range(64)]
check("the reading is range x scale + bias + zone bias, in whole mm", a["distance_mm"] == want, (a["distance_mm"][:3], want[:3]))
check("the input frame is not written to", flat(2000)["distance_mm"] == [2000] * 64 and same_ep.apply(f0)["distance_mm"] is not f0["distance_mm"])

# ---- random invalid zones: 3 % per zone per frame, with a status that is neither a return nor 255 ------------------------
iz = imp(seed=5, invalid_zone_p=0.03)
frames = [iz.apply(flat(1000, seq=i)) for i in range(2000)]
bad = sum(1 for fr in frames for s in fr["status"] if s != 5)
rate = bad / (2000 * 64)
check("invalid zones: 3 % of zones (0.027 to 0.033)", 0.027 < rate < 0.033, rate)
check("an invalid zone has distance 0 and the invalid status, never 255 and never a return's",
      all(d == 0 and s == iz.invalid_status for fr in frames for d, s in zip(fr["distance_mm"], fr["status"]) if s != 5)
      and iz.invalid_status not in (255, *SIM.sensors.tof8x8.valid_status), iz.invalid_status)
per_zone = [sum(1 for fr in frames if fr["status"][z] != 5) / 2000 for z in range(64)]
check("each zone is hit about alike (no zone favoured)", max(per_zone) < 0.055 and min(per_zone) > 0.012, (min(per_zone), max(per_zone)))

# ---- dropped frames: 2 % of acquisitions never arrive -----------------------------------------------------------------------
dr = imp(seed=7, frame_dropout_p=0.02)
out = [dr.apply(flat(1000, seq=i)) for i in range(20000)]
lost = sum(1 for o in out if o is None) / 20000
check("dropped frames: 2 % (0.017 to 0.023)", 0.017 < lost < 0.023, lost)
check("a frame that arrives is the one acquired: its seq and time are its own", all(o["seq"] == i and o["t_ns"] == 1_000 * i for i, o in enumerate(out) if o))
check("the record counts what was dropped", dr.record()["dropped"] == sum(1 for o in out if o is None), dr.record())

# ---- latency: a frame arrives one acquisition late ---------------------------------------------------------------------------
ls =[imp(seed=s, latency_frames_max=1).episode["latency_frames"] for s in range(N)]
check("latency is 0 or 1 frames an episode, about half each", set(ls) == {0, 1} and 0.45 < statistics.fmean(ls) < 0.55, statistics.fmean(ls))
one = next(imp(seed=s, latency_frames_max=1) for s in range(50) if imp(seed=s, latency_frames_max=1).episode["latency_frames"] == 1)
got = [one.apply(flat(1000, seq=i)) for i in range(4)]
check("one frame of latency: nothing yet for the first, then each frame the one before it", got[0] is None and [g["seq"] for g in got[1:]] == [0, 1, 2],
      [g and g["seq"] for g in got])
check("the late frame keeps its own time (the navigator pairs it with the older state, so its age shows)", got[1]["t_ns"] == 0 and got[3]["t_ns"] == 2_000)
zero = next(imp(seed=s, latency_frames_max=1) for s in range(50) if imp(seed=s, latency_frames_max=1).episode["latency_frames"] == 0)
check("no latency this episode: each frame at once", [zero.apply(flat(1000, seq=i))["seq"] for i in range(3)] == [0, 1, 2])
both = imp(seed=9, frame_dropout_p=0.5, latency_frames_max=0)
seen = [o["seq"] for o in (both.apply(flat(1000, seq=i)) for i in range(40)) if o]
check("a dropped frame is skipped: the seqs that arrive have gaps, in order", len(seen) < 40 and seen == sorted(seen) and len(set(seen)) == len(seen), seen)
late_drop = next(imp(seed=s, frame_dropout_p=0.4, latency_frames_max=1) for s in range(50)
                 if imp(seed=s, latency_frames_max=1).episode["latency_frames"] == 1)
acquired = [late_drop.apply(flat(1000, seq=i)) for i in range(200)]
arrived = [o["seq"] for o in acquired if o]
check("with latency, a dropped acquisition is never delivered; the others come in order, each one acquisition behind",
      arrived == sorted(arrived) and len(set(arrived)) == len(arrived) and len(arrived) < 199 and arrived[0] >= 0
      and all(o is None for o in acquired[:1]), (len(arrived), arrived[:8]))

# ---- deterministic: one seed, one run --------------------------------------------------------------------------------------
def run(seed):
    i = DepthImpairment.from_profile(SIM, {"enabled": True, "seed": seed})
    return [i.apply(flat(500 + 17 * k, seq=k)) for k in range(300)], i.record()


r1, r2, r3 = run(11), run(11), run(12)
check("the same seed gives the same frames and the same record", r1 == r2)
check("another seed gives other frames", r1[0] != r3[0])
check("the record names the setting and the seed it ran with", r1[1]["enabled"] is True and r1[1]["seed"] == 11 and r1[1]["min_range_m"] == 0.12
      and r1[1]["invalid_status"] == imp().invalid_status and "episode" in r1[1], r1[1])

# ---- an impaired invalid zone never creates a drop point -----------------------------------------------------------------------
def stance(pitch_deg=25.0, height=0.118):
    p = math.radians(pitch_deg) / 2
    return {"imu": {"quat": [1.0, 0.0, 0.0, 0.0]}, "odom": {"position": [0.0, 0.0, height], "yaw": 0.0},
            "frames": {"tof": {"pos": [0.08, 0.0, 0.11], "quat": [math.cos(p), 0.0, math.sin(p), 0.0]}}}


def floor_frame(sensor, st):
    height, q = sensor.sensor_pose(st)
    dist = []
    for beam in sensor.beams:
        d = rotate(q, beam)
        dist.append(2000 if d[2] >= -0.01 else int(-height / d[2] * 1000))
    return {"rows": 8, "cols": 8, "distance_mm": dist, "status": [5] * 64}


sensor, st0 = Tof8x8(SIM), stance()
floor = floor_frame(sensor, st0)
check("flat floor, unimpaired: no drop point (the baseline)", sensor.drop_points(floor, st0) == [])
blank = {**floor, "distance_mm": [0] * 64, "status": [255] * 64}
check("the same frame with 255 on every zone: drop points (255 below the floor line is a drop, so an impairment must not use it)",
      len(sensor.drop_points(blank, st0)) > 0)
allbad = imp(invalid_zone_p=1.0).apply(floor)
check("every zone invalid by the impairment: its status is not 255", set(allbad["status"]) == {sensor.impairment.invalid_status}, set(allbad["status"]))
check("every zone invalid by the impairment: no drop point", sensor.drop_points(allbad, st0) == [] and sensor.drop_ahead(allbad, st0) is None)
check("every zone invalid by the impairment: no hole drawn below the floor either", [p for p in sensor.depth_points(allbad, st0) if p[3] == "below"] == [])
near = imp(min_range_m=5.0).apply(floor)
check("every return under the minimum range: no drop point", set(near["status"]) == {sensor.impairment.invalid_status} and sensor.drop_points(near, st0) == [])
worst = 0
for s in range(300):
    fr = DepthImpairment.from_profile(SIM, {"enabled": True, "seed": s, "invalid_zone_p": 0.3, "frame_dropout_p": 0.0, "latency_frames_max": 0}).apply(floor)
    worst += len(sensor.drop_points(fr, st0))
check("300 impaired floor frames (30 % of zones invalid, NVIDIA's bias and scale): not one drop point", worst == 0, worst)
for pitch in (0.0, 10.0, 25.0, 40.0):
    stp = stance(pitch)
    ff = floor_frame(sensor, stp)
    n = sum(len(sensor.drop_points(DepthImpairment.from_profile(SIM, {"enabled": True, "seed": s, "invalid_zone_p": 0.3, "frame_dropout_p": 0.0,
                                                                      "latency_frames_max": 0}).apply(ff), stp)) for s in range(100))
    check(f"head pitched {pitch:.0f} deg: still not one drop point over 100 impaired frames", n == 0, n)
real_sensor = Tof8x8(REAL)
check("the real duck's sensor reads an unknown status as before (a zone without a return is a drop): its behaviour is unchanged",
      len(real_sensor.drop_points({**floor, "distance_mm": [0] * 64, "status": [13] * 64}, st0)) > 0)
check("a real drop is still a drop beside impaired zones",
      len(sensor.drop_points(imp(invalid_zone_p=0.05).apply({**floor, "distance_mm": [d + 500 if i % 8 in (3, 4) else d for i, d in enumerate(floor["distance_mm"])]}), st0)) > 0)

print("DEPTH IMPAIR", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
