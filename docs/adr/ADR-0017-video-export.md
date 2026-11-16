# ADR-0017 — A run as a video, with any rendering engine and the robot's own model

**Status:** Accepted (2026-11-16, the operator)
**Date:** 2026-11-16
**Context documents:** [ADR-0016](ADR-0016-joints-and-whole-truth-pose.md) (joints and the whole
truth pose), [RFC-0011](../rfc/RFC-0011-robot-models.md) (robot descriptions),
[ADR-0012](ADR-0012-docker-read-only-data.md) (the service's data is read-only)

## Context

The operator: a video of what happened in a run, the robot drawn with its own model, the rendering
engine chosen per export (MuJoCo first, then Blender), robot-generic (the duck is one robot of
several), and the same for a run from the field, at home, as for a simulated one.

## Decision

### A track, then an engine

- `miniview video <run> --engine mujoco -o out.mp4` (`--fps`, `--size`, `--from`, `--to`). The run
  becomes a **track**: at each frame's time, the trunk's position and orientation and each joint's
  angle, interpolated between samples (positions linearly, orientations by normalised lerp). It is
  handed, with the run's scene and the robot's model, to an **engine** that draws it.
- **Where the robot was:** the truth when the run has it (with its whole pose, ADR-0016), in the
  world frame. A run from the field has no truth: then the belief on the robot's own map, the tilt
  from the IMU's signals with the belief's heading, at the robot's standing height, in the map frame.
- **The room:** the run's scene (boxes, and drops drawn dark on the floor) in the world frame; with
  the belief, the robot's last map grid (its occupied cells as low blocks), the only picture of a
  room there is in the field.
- **The robot:** `miniview/video/robots.json` names, per robot and engine, the model and the Python
  that runs the engine (MuJoCo's, Blender's: not miniview's). The duck's MuJoCo model is Pollen's
  (`robot_allcollisions_backlash.xml`, its 86 visual meshes and colours). It moves to the robot
  descriptions of RFC-0011 when they exist.
- **Engines** are scripts in `miniview/video/engines/`, each given one job file. The MuJoCo engine
  poses the model per frame (the free joint, each named joint; the rest at the home keyframe),
  renders off-screen (EGL), the camera following the trunk from behind and above, the room's boxes
  see-through so they never hide the robot, and writes the video (mediapy, ffmpeg).

### Checked (2026-11-16)

Challenge 1, seed 7 (a run with joints and the whole truth pose): 888 frames at 30 fps, 960×540,
rendered in 6 s; 14 of the duck's 15 joints move the model (the model has no mouth joint); the duck
is drawn as Pollen's model, walking. Field runs (belief and map) are built but not yet checked on a
run from a real robot.

### The UI trigger (the operator: "trigger it from miniview")

The use (the operator): after a run in the simulator, open it in miniview and make a video of how it
went.

**Rendering is a separate system; miniview is aware of it** (the operator, 2026-11-16). The engines
need what the simulator's machine has (MuJoCo, the robot's model) and miniview's image has not; they
are not built into miniview.

- **The render service** (`miniview render-serve`, on the machine with the engines; `make
  render-up`): `GET /engines` (which engines and robots it can render, each with why not when it
  cannot), `POST /jobs` (a run's key, engine, span, size), `GET /jobs/{id}` (progress, then the
  file). It reads the runs from the same data folder, read-only; it writes videos to its own
  folder (the state folder's `videos/`). One job at a time.
- **miniview knows of it:** its address is in miniview's settings (`MINIVIEW_RENDER`, e.g.
  `http://127.0.0.1:8071`). miniview's API passes through: `GET /api/v1/render` (the render
  service's engines, or that there is none and why), `POST /api/v1/runs/{key}/video`, `GET
  /api/v1/videos/{id}`. miniview's own data stays read-only (ADR-0012); it writes nothing.
- **In the pages:** the run's menu has **Export video** (engine, span, size), offered only when the
  render service answers and can render that run's robot, with the reason when it cannot; the job's
  progress, then the video, playable and downloadable in the page.
- **The command line stays:** `miniview video` and `make video RUN=… [ENGINE=…]` render without the
  service, the same code.
- **Engines plug in:** an engine is a script given one job file, run by its own runtime. Blender is
  the next one (the operator: "anticipate we can plug Blender in"): `blender --background --python
  blender_engine.py -- job.json`, the meshes placed per link from RFC-0011's link poses. The render
  service lists every engine it finds runnable; miniview offers what it lists.
- **Blender, in use (2026-11-16):** Blender's official build in the user's home (`~/opt/blender`,
  the registry's default; `VIDEO_BLENDER` overrides it), not a system package: the distribution's
  package needed a system upgrade it did not get (it would not start). Run with
  `--python-exit-code 1` so a script that fails is a failed job (Blender exits 0 otherwise), and a
  job that wrote no video fails too. The duck's 2 s at 1280x720: about 30 s, EEVEE, Blender 5.2.4.

## Consequences

- **Positive:** any run with joints, simulated or from the field, becomes a video of the robot as it
  moved; a robot gains videos by naming its model; engines are swappable.
- **Negative:** an engine needs its own Python and library on the machine that renders.
- **Neutral:** a run without joints still renders, with the model at its home pose.

## Alternatives considered

- **Recording the video during the run** (MuJoCo's own viewer): only for simulated runs, one camera,
  decided before the run.
- **A screen recording of miniview's 3D view:** no robot model, the browser's resolution.
