"""The navigator's own run in format 2 and the replay check (ADR-0014): a depth frame paired with the state nearest its time,
derived once (FrameView) and logged with everything a replay needs; the IMU and the navigator's values as signals; a decision
on the event of the rule that fired; an evaluation's goals as segments, a navigator that is no longer the current one dropped;
a failing writer costing the run, never the navigator; `duck-replay` finding the log complete, and finding it incomplete when
what the navigator derived is not what its inputs give. No simulator.
Run: cd duck && uv run python tests/test_replay.py"""

import collections
import contextlib
import io
import json
import math
import sys
import tempfile
from pathlib import Path

from miniview.mcapio import Follower

from duck_lab import replay
from duck_lab.nav import cliff
from duck_lab.nav.cliff import BEAMS, rotate, sensor_pose
from duck_lab.nav.frames import Localizer
from duck_lab.nav.run import FrameView, Navigator, decision, load_tof
from duck_lab.nav.runlog import RunLog, SIGNALS

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def robot_state(t_ns, pitch_deg=25.0, height=0.118, trunk_pitch=0.0, x=0.0):
    p = math.radians(pitch_deg) / 2
    h = math.radians(trunk_pitch) / 2
    return {"t_ns": t_ns, "odom": {"position": [x, 0.0, height], "yaw": 0.0},
            "imu": {"quat": [math.cos(h), 0.0, math.sin(h), 0.0], "gyro": [0.0, 0.5, 0.0]},
            "frames": {"tof": {"pos": [0.08, 0.0, 0.11], "quat": [math.cos(p), 0.0, math.sin(p), 0.0]}}}


def frame_for(st, t_ns, seq, floor_until_m=None, drop_m=0.3):
    """The frame the sensor would send over flat floor, the floor dropping by drop_m beyond floor_until_m."""
    height, q = sensor_pose(st)
    dist = []
    for beam in BEAMS:
        d = rotate(q, beam)
        if d[2] >= -0.01:
            dist.append(2000)
            continue
        t = -height / d[2]
        if floor_until_m is not None and t * math.hypot(d[0], d[1]) > floor_until_m:
            t = -(height + drop_m) / d[2]
        dist.append(int(t * beam[0] * 1000))
    return {"seq": seq, "t_ns": t_ns, "rows": 8, "cols": 8, "distance_mm": dist, "status": [5] * 64}


def navigator(runlog=None):
    """A Navigator with its sockets left out: what the stream threads call, and what they need."""
    nav = Navigator.__new__(Navigator)
    nav.scale, nav.loc = 1.0, Localizer()
    nav.loc.map_from_odom = (1.2345678901, 2.3456789012, 0.1234567890)     # not round numbers: the pose a frame was placed with is kept as it was
    nav._t0, nav.runlog, nav._sid = __import__("time").monotonic(), runlog, runlog.new_session() if runlog else None
    nav._states, nav._fv, nav.sense, nav._logging_failed = collections.deque(maxlen=40), None, {}, False
    nav.tof = type("Tof", (), {"nearest_mm": 410})()
    nav.floor_seen = set()
    return nav


MS = 1_000_000
with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)

    # ---- the pairing: the state nearest the frame's time, the newest for a frame with no time ------------------------
    nav = navigator()
    for k in range(5):
        nav._on_state(robot_state(1_000_000_000 + k * 50 * MS))
    st, dt = nav._pair(1_000_000_000 + 120 * MS)
    check("a frame is paired with the state nearest its time (states at 0, 50, 100, 150, 200 ms; the frame at 120 ms: the 100 ms one)",
          st["t_ns"] == 1_000_000_000 + 100 * MS and abs(dt - (-20.0)) < 1e-9, (st["t_ns"], dt))
    st, dt = nav._pair(1_000_000_000 + 130 * MS)
    check("... and the 150 ms one when that is nearer, the difference positive (the state after the frame)", st["t_ns"] == 1_000_000_000 + 150 * MS and abs(dt - 20.0) < 1e-9, dt)
    check("a frame with no time is paired with the newest state, with no difference to say",
          nav._pair(0) == (nav._states[-1][1], None) and navigator()._pair(5) == (None, None))

    # ---- a frame, derived once ---------------------------------------------------------------------------------------
    s0 = robot_state(1_000_000_000 + 100 * MS)
    fr = frame_for(s0, 1_000_000_000 + 120 * MS, 7, floor_until_m=0.45)
    fv = FrameView(fr, s0, -20.0, (1.0, 2.0, 0.0))
    check("the drop ahead is in the frame's drop points; the points are in map metres, rounded", fv.ok and fv.drops and fv.points
          and all(round(v, 3) == v for q in fv.points for v in q[:3]) and min(d[2] for d in fv.drops) < 0.6, (len(fv.drops), fv.points[:1]))
    pl = fv.payload()
    check("its record carries the raw frame, both times, the paired state's replay fields, the pose and what was derived",
          pl["distance_mm"] == fr["distance_mm"] and pl["frame_t_ns"] == fr["t_ns"] and pl["state_t_ns"] == s0["t_ns"] and pl["pair_dt_ms"] == -20.0
          and pl["seq"] == 7 and pl["state"]["odom_z"] == 0.118 and pl["pose"] == [1.0, 2.0, 0.0]
          and pl["derived"]["points"] == fv.points and len(pl["derived"]["drop_points"]) == len(fv.drops), sorted(pl))
    check("a state without what the cliff check needs gives a frame that is logged but not derived",
          not FrameView(fr, {"t_ns": 1}, None, None).ok and "state" not in FrameView(fr, {"t_ns": 1}, None, None).payload())

    # ---- a run written by the navigator's own threads and loop -------------------------------------------------------
    rl = RunLog(data, "apartment", "explore99", "exploration", None)
    nav = navigator(rl)
    nav.tof.nearest_mm = 380
    nav.sense = {"room_m": 0.2, "turning": 1}
    for k in range(10):
        nav._on_state(robot_state(1_000_000_000 + k * 50 * MS, trunk_pitch=2.0 * k, x=0.01 * k))
    frames_in = []
    for k in range(6):
        f = frame_for(robot_state(0), 1_000_000_000 + (60 + 70 * k) * MS, 100 + k, floor_until_m=0.4 if k >= 2 else None)
        nav._on_frame(f)
        frames_in.append(nav._fv)
    nav.runlog.row(nav._sid, {"t": 0.05, "pose": [1.0, 2.0, 0.0], "truth": [0.0, 0.0, 0.0], "vx": 0.2, "vyaw": 0.0, "depth": frames_in[-1].points})
    nav.runlog.row(nav._sid, {"t": 0.1, "event": "cliff_stop", "drop_m": 0.4, "pose": [1.0, 2.0, 0.0],
                              "decision": decision("cliff_stop", "a drop ahead seen in 3 frames in a row", drop_m=0.4, stop_m=0.6, streak=3)})
    nav.runlog.row(nav._sid, {"t": 0.2, "pose": [1.1, 2.0, 0.0], "truth": [0.1, 0.0, 0.0], "vx": 0.2, "vyaw": 0.0, "depth": frames_in[0].points})
    path = rl.finish()
    recs = Follower(path.parent, keep_raw=True).poll()
    kinds = [k for _, k, _ in recs]
    run_rec = recs[0][2]
    check("the run is key duck/apartment/explore99, declares the IMU and decision signals, and is compacted when finished",
          run_rec["key"] == "duck/apartment/explore99" and [s["name"] for s in run_rec["signals"]] == [s["name"] for s in SIGNALS]
          and path.name == "run.mcap" and not (path.parent / "run.live.mcap").exists() and kinds[-1] == "end", kinds[:3])
    check("every frame the sensor sent is a depth_frame record, in order", kinds.count("depth_frame") == 6
          and [p["seq"] for _, k, p in recs if k == "depth_frame"] == list(range(100, 106)))
    sig = [p["values"] for _, k, p in recs if k == "signals"]
    check("a signals record per state sample with the IMU values and the navigator's, nothing absent written as zero",
          len(sig) == 10 and {"pitch_deg", "roll_deg", "pitch_rate_dps", "qw", "qx", "qy", "qz", "nearest_mm", "room_m", "turning"} <= set(sig[-1])
          and "block_m" not in sig[0] and abs(sig[-1]["pitch_rate_dps"] - math.degrees(0.5)) < 1e-9 and abs(sig[-1]["pitch_deg"] - 18.0) < 1e-6
          and sig[-1]["nearest_mm"] == 380.0 and sig[-1]["turning"] == 1.0, sig[-1])
    ev = next(p for _, k, p in recs if k == "event")
    check("the event of the rule that fired carries its decision", ev["kind"] == "cliff_stop" and ev["decision"]["rule"] == "cliff_stop"
          and ev["decision"]["values"]["streak"] == 3, ev)
    check("an epoch from the first pose and truth, one (an exploration's goals do not reset the simulator)", kinds.count("epoch") == 1)
    ts = [t for t, _, _ in recs]
    check("run time only grows across the three threads' records", all(b >= a for a, b in zip(ts, ts[1:])), [x for x in ts if x < 0][:3])

    # ---- the replay finds the log complete ---------------------------------------------------------------------------
    rep = replay.replay(recs)
    check("replay: every frame re-derived from its raw frame and its paired state equals what was logged, and every tick's depth is a frame's",
          replay.verdict(rep) and rep["replayed"] == 6 and not rep["diffs"] and rep["ticks_untraced"] == 0 and rep["ticks_with_depth"] == 2,
          (len(rep["diffs"]), rep["ticks_untraced"]))
    check("replay: the drop in the later frames is in what was replayed (the check is not vacuous)", rep["drop_frames"] >= 3 and rep["points"] > 100, (rep["drop_frames"], rep["points"]))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        argv, sys.argv = sys.argv, ["duck-replay", str(path.parent)]
        try:
            replay.main()
            code = 0
        except SystemExit as e:
            code = e.code
        finally:
            sys.argv = argv
    check("duck-replay <run folder> prints the report and exits 0 with REPLAY PASS", code == 0 and "REPLAY PASS" in buf.getvalue(), buf.getvalue()[-120:])

    # ---- ... and finds it incomplete when what was derived is not what the inputs give --------------------------------
    def tampered(edit):
        out = []
        for t, k, p in recs:
            p = json.loads(json.dumps(p))
            if k == "depth_frame" and p["seq"] == 103:
                edit(p)
            out.append((t, k, p))
        return replay.replay(out)

    t1 = tampered(lambda p: p["derived"]["points"][0].__setitem__(0, p["derived"]["points"][0][0] + 0.01))
    t2 = tampered(lambda p: p["distance_mm"].__setitem__(10, p["distance_mm"][10] + 300))
    t3 = tampered(lambda p: p["state"]["quat"].__setitem__(2, 0.05))
    t4 = tampered(lambda p: p.pop("block_m", None) or p["derived"].__setitem__("block_m", 0.1))
    check("a point that moved, a distance that changed, a state that differs and a blocking distance that was not there are each a difference",
          all(not replay.verdict(r) and r["diffs"] for r in (t1, t2, t3, t4)), [len(r["diffs"]) for r in (t1, t2, t3, t4)])
    t5 = replay.replay([(t, k, dict(p, depth=[[9.0, 9.0, 0.0, "f"]]) if k == "tick" and p.get("depth") else p) for t, k, p in recs])
    check("a tick whose depth is not any frame's points is found", not replay.verdict(t5) and t5["ticks_untraced"] == 2, t5["ticks_untraced"])
    check("a run with no depth frames is not a pass", not replay.verdict(replay.replay([r for r in recs if r[1] != "depth_frame"])))

    # ---- an evaluation: a goal is a segment, the navigator before the current one is dropped -------------------------
    ev_rl = RunLog(data, "apartment", "phase1x", "go-to evaluation", None, evaluation=True)
    sid1 = ev_rl.new_session()
    ev_rl.row(sid1, {"t": 1.0, "pose": [0.0, 0.0, 0.0], "truth": [0.0, 0.0, 0.0], "vx": 0.2, "vyaw": 0.0})
    ev_rl.frame(sid1, 1.5, {"rows": 8, "cols": 8, "distance_mm": [100] * 64, "status": [5] * 64, "frame_t_ns": 5})
    ev_rl.row(sid1, {"t": 2.0, "event": "reached", "goal": [1.0, 0.0], "pose": [0.5, 0.0, 0.0]})
    ev_rl.frame(sid1, 2.1, {"rows": 8, "cols": 8, "distance_mm": [111] * 64, "status": [5] * 64, "frame_t_ns": 6})   # a leftover of goal 1's streams
    ev_rl.signals(sid1, 2.1, {"pitch_deg": 1.0})                                                                       # ... and one of its states
    sid2 = ev_rl.new_session()
    ev_rl.frame(sid2, 0.1, {"rows": 8, "cols": 8, "distance_mm": [222] * 64, "status": [5] * 64, "frame_t_ns": 7})
    ev_rl.row(sid1, {"t": 2.2, "pose": [0.0, 0.0, 0.0], "truth": [0.0, 0.0, 0.0]})                                    # a stale navigator's row
    ev_rl.row(sid2, {"t": 0.5, "pose": [0.0, 0.0, 0.0], "truth": [0.0, 0.0, 0.0], "vx": 0.2, "vyaw": 0.0})
    ev_rl.row(sid2, {"t": 1.0, "event": "refused", "goal": [2.0, 0.0], "pose": [0.0, 0.0, 0.0]})
    p2 = ev_rl.finish()
    r2 = Follower(p2.parent, keep_raw=True).poll()
    segs = [p for _, k, p in r2 if k == "segment"]
    dfs = [p["distance_mm"][0] for _, k, p in r2 if k == "depth_frame"]
    check("an evaluation's goals are segments with the goal and the outcome, and each goal has its epoch",
          [(s["goal"], s["outcome"]) for s in segs] == [([1.0, 0.0], "reached"), ([2.0, 0.0], "refused")]
          and [k for _, k, _ in r2].count("epoch") == 2, segs)
    check("what goal 1's streams still sent after it ended, and the stale navigator's row, are dropped; goal 2's first frame is kept",
          dfs == [100, 222] and not any(p["values"].get("pitch_deg") == 1.0 for _, k, p in r2 if k == "signals"), dfs)
    t_ = [t for t, _, _ in r2]
    check("the second goal's clock starts after the first's end, not before", all(b >= a for a, b in zip(t_, t_[1:])) and segs[1]["t_start"] > segs[0]["t_end"],
          (segs[0]["t_end"], segs[1]["t_start"]))

    # ---- a writer that fails costs the run, never the navigator -------------------------------------------------------
    bad = RunLog(data, "apartment", "broken1", "exploration", None)
    nav = navigator(bad)
    bad._rec.add = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        nav._on_state(robot_state(1_000_000_000))
        nav._on_frame(frame_for(robot_state(0), 1_000_000_000, 1))
        nav.runlog.row(nav._sid, {"t": 0.1, "pose": [0.0, 0.0, 0.0]})
    check("a write that fails is said once and the navigator's own threads carry on", bad.error and "disk full" in bad.error
          and err.getvalue().count("not written any more") == 1 and nav._fv is not None, err.getvalue())

    # ---- the sensor's mounting: the robot's calibration, recorded with the run, applied by the replay --------------------
    check("load_tof: the simulator's sensor, as calibration/sim.json measured it (2.5 deg, along the ray)",
          load_tof("sim") == {"pitch_offset_deg": 2.5, "range_kind": "radial"}, load_tof("sim"))
    check("load_tof: no robot is the real duck's mounting (cliff.py's defaults)",
          load_tof(None) == {"pitch_offset_deg": 3.0, "range_kind": "axial"}, load_tof(None))
    # A navigator applies its robot's mounting when it starts (its sockets stubbed: no simulator here).
    from duck_lab.nav import run as nav_run
    real = {k: getattr(nav_run, k) for k in ("Rpc", "StateStream", "TofStream", "Body")}
    for k in real:
        setattr(nav_run, k, lambda *a, **kw: type("Stub", (), {})())
    try:
        Navigator(calibration="sim", truth=False)
        sim_applied = (cliff.PITCH_OFFSET_RAD, cliff.RANGE) == (math.radians(2.5), "radial")
        Navigator(calibration=None, truth=False)
        default_applied = (cliff.PITCH_OFFSET_RAD, cliff.RANGE) == (math.radians(3.0), "axial")
    finally:
        for k, v in real.items():
            setattr(nav_run, k, v)
    check("a navigator configures the cliff check with its robot's mounting when it starts (and the real duck's without one)",
          sim_applied and default_applied, (sim_applied, default_applied))
    cal_rl = RunLog(data, "apartment", "calib1", "exploration", None)
    cal_sid = cal_rl.new_session()
    cal_rl.row(cal_sid, {"t": 0.0, "event": "calibration", "tof": load_tof("sim"), "odom_scale": 0.91})
    cal_rl.row(cal_sid, {"t": 0.5, "pose": [0.0, 0.0, 0.0]})
    cal_recs = Follower(cal_rl.finish().parent, keep_raw=True).poll()
    check("the run's calibration event is read back as the mounting it was recorded with",
          replay.calibration_of(cal_recs) == load_tof("sim"), replay.calibration_of(cal_recs))
    check("a run from before the event existed: the real duck's mounting", replay.calibration_of(recs) == load_tof(None))
    replay.replay(cal_recs + [r for r in recs if r[1] == "depth_frame"])
    sim_set = (cliff.PITCH_OFFSET_RAD, cliff.RANGE) == (math.radians(2.5), "radial")
    replay.replay(recs)
    check("the replay applies each run's own mounting, and puts the default back for a run without one",
          sim_set and (cliff.PITCH_OFFSET_RAD, cliff.RANGE) == (math.radians(3.0), "axial"), (cliff.PITCH_OFFSET_RAD, cliff.RANGE))

    # ---- a run that exists is not overwritten -----------------------------------------------------------------------
    try:
        RunLog(data, "apartment", "explore99", "exploration", None)
        refused = False
    except Exception as e:  # noqa: BLE001
        refused = "already exists" in str(e)
    check("a run that exists is refused, not overwritten", refused)

print("REPLAY-LOG", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
