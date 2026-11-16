# RFC-0011 — Robots drawn as themselves: a link/joint description, moved by the recorded joints

**Status:** Accepted (2026-11-16, the operator)
**Builds on:** [ADR-0016](../adr/ADR-0016-joints-and-whole-truth-pose.md) (a run records the
joints and the truth's whole pose), [ADR-0007](../adr/ADR-0007-run-file-format-2.md) (format 2, Foxglove
channels), [ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md) (ROS terms and shapes),
[RFC-0009](RFC-0009-miniview.md) and [RFC-0010](RFC-0010-run-store-v2.md) (miniview, one API).
**Serves:** the video export (ADR-0017), the challenge course (RFC-0008: looking at a failure), the
robots to come (the NXT, the EV3, a third).

## 1. Why

A run now holds every joint angle and, in the simulator, the trunk's whole pose (ADR-0016). Every
view still draws the robot as a dot with a heading: miniview, Rerun and Foxglove alike. Looking at a
fall, a stall at a doorway or a gait means looking at the body: which leg, which joint, when. The
video export draws the body (its MuJoCo engine, 2026-11-16), but only there, and only for a robot
MuJoCo has a model of.

The operator: our own capability, in the shape ROS uses (a tree of links and joints, a transform per
link), with Rerun's way of doing it as the model, matching what we have, reused across everything.

## 2. How Rerun does it (checked in rerun-sdk 0.43.2, `rerun.urdf`)

- A robot is a **URDF**: links (rigid parts, each with its meshes) and joints (parent link, child
  link, type, axis, origin, limits).
- `UrdfTree.from_file_path` loads it; `log_urdf_to_recording` logs the geometry once and the fixed
  transforms to `/tf_static`.
- To animate, each joint's transform is computed from its value (`UrdfJoint.compute_transform(value)`:
  a rotation about the axis after the joint's origin, with a parent frame and a child frame) and
  logged as a `Transform3D` at its time. Rerun resolves the frame tree; the meshes follow.

Foxglove and Lichtblick (from general knowledge, not checked here) do the same from a URDF and
per-link `FrameTransform`s on `/tf`. Pollen ships the duck as MuJoCo XML only: no URDF was found
under `/work/pollen` (searched 2026-11-16).

## 3. Proposal

### 3.1 A robot description per robot, URDF

- Each robot has a description in the repo, `robots/<robot>/`: `robot.urdf` and its meshes (STL),
  and a `robot.json` (the joint names as the run's `joint_*` signals name them, the root link, a
  hash of the description). The video registry (`robots.json`) moves here.
- **The duck's is generated** from Pollen's MJCF by `robots/duck/from_mjcf.py`, through MuJoCo's
  compiled model (the body tree, each joint's axis and position, each visual geom's mesh, pose and
  colour), so it follows upstream and is rebuilt, not edited. The LEGO robots' are generated from
  LDraw models by `robots/ldraw/from_ldraw.py` (the LDraw parts library, `make robots-lego`), with a
  hand-written `kinematics.json` per robot that says which parts move with which joint (wheels and
  motor-driven parts as continuous joints). The EV3 Track3r and Spike3r come from the LDraw OMR's
  set 31313 files. The NXT Shooterbot's model is written by hand and is an approximation: its
  building instructions ship only inside the NXT software, so it is built from the 8547 User Guide's
  Quick Start model, with the sensors and the shooter placed by eye.
- Meshes are not copied into runs (the duck's are 23 MB): a run names its robot and the
  description's hash; the description is served by the service like a scene.

### 3.2 One forward kinematics, used everywhere

`miniview.kinematics`: a URDF and joint values to each link's pose in the robot's frame, the same
computation as `compute_transform` (origin, then the rotation about the axis), chained from the root.
With the trunk's pose (the truth's whole pose, or the belief and the IMU's tilt on a real robot, as
the video track already does) it places every link in the world.

| Where | Uses it for |
| --- | --- |
| The API | `GET /api/v1/robots/{robot}` (the description), `GET /runs/{key}/links?from=&to=` (link poses in a window, like `frames`) |
| miniview | a **Robot** layer in the 3D view: the meshes, placed per link; the outliner gets the link and joint tree; the inspector the joint angles at the playhead; each joint a lane in the timeline (they are signals already) |
| Rerun export | the URDF logged once, each joint's transform per sample: Rerun's own way |
| Foxglove export | the description and per-link `FrameTransform`s on `/tf`, in an exported copy |
| Video engines | link poses for Blender (meshes placed per link); MuJoCo keeps setting its own joints |

The live run file stays as it is (joints as signals): link transforms are derived on read and on
export, so runs stay small and an old run with joints gains a body when its robot gains a
description.

### 3.3 In the pages

- three.js draws the meshes (its STL loader is part of three.js, already a dependency); deck.gl
  draws the robot's footprint as today.
- The link/joint tree is a panel: select a joint, see its angle over time and its place in the tree;
  select a link, see it highlighted on the body.
- Shown at the playhead with the window the page has; scrubbing asks the API for link poses in
  windows, as it does for frames.
- **The Robot view** (the operator, 2026-11-16: "a basic robot body explorer"): the robot alone,
  centred, to orbit, zoom and pan. Click a part (a link): its name, the joint that moves it and the
  joint's limits, its meshes, its place in the tree; highlight, isolate or hide any part. Two poses:
  **as recorded** (the body at the playhead) and **by hand** (a slider per joint, within its
  limits). A robot with a description and no run can be explored too. *Placed by the operator
  after the prototype (`viewer/web/proto/`, 2026-11-16): not a view mode beside Top, 3D and Map,
  but the first kind of the right panel's **Explore** tab, beside Moment and Selection; parts are
  picked in the body or in the list of parts under it; technical names only. The left panel's
  link and joint tree is the **Body** section, joints grouped by chain with their angles (a
  show/hide switch). See [UXS-001](../uxs/UXS-001-miniview.md#the-left-panel-by-meaning-and-the-explore-view-operator-2026-11-16).*

### 3.4 Which robot, and where from (the operator: "we need to know what is in the sim and what we are looking at")

- **One registry**, `robots/<robot>/robot.json` beside its description: the description (the URDF),
  the **simulator model** when it has one (the duck: Pollen's MuJoCo model; the NXT: none yet), the
  **real robot's backend** (the duck's `robotd`, the NXT's `nxt-web`), its joint names. The video
  registry moves here. The simulator, the video engines, the exports, the API and the pages read it.
- **Every run says which robot and from where.** The robot is the key's first part already; the run
  record gains its **origin** (`sim` or `real`) and the description's hash, and a simulated run the
  model the simulator loaded. miniview's header shows it: "duck · simulated · challenge 3".
- **Choosing a robot:** a run's robot is the run's (shown, not chosen). The Robot view can open any
  robot of the registry, with or without a run. The render menu offers what the render service can
  draw; `GET /api/v1/robots` lists them all with what each has (a description, a simulator model,
  a backend).

## 4. Order

1. `kinematics` with tests (a two-link arm: known poses), and the duck's URDF from the MJCF, checked
   against MuJoCo itself: every link's pose from our FK equals MuJoCo's `xpos`/`xquat` for the same
   joint values.
2. The API (description, link windows) and the Rerun export, checked in Rerun (the duck moving).
3. The Robot layer in miniview's 3D view, the left panel by meaning (the Body section: the joints
   by chain), the joint lanes; the Explore tab with the robot's body (as recorded or by hand).
4. The Foxglove export; the Blender engine on link poses (ADR-0017).
5. The NXT's description; then the EV3's when it arrives. Done 2026-11-16 from LDraw: the NXT
   Shooterbot (an approximation), the EV3 Track3r and Spike3r.

## 5. Open questions

- The pages' FK: the API's link windows (one implementation, a request per window) or the same FK
  in JavaScript (no request when scrubbing, two implementations to keep equal, tested against each
  other). Posing by hand moves a slider many times a second, which a request per move cannot
  follow; the prototype did its FK in JavaScript.
- Mesh size in the pages: 23 MB for the duck. Decimated meshes for the pages, the full ones for
  videos?
- MJCF features URDF lacks (the duck's passive backlash joints, ball joints): kept at rest in the
  description, as now in the video.

## 6. Alternatives considered

- **MJCF as the description:** no conversion for the duck, but no viewer reads it (Rerun, Foxglove,
  three.js all read URDF or meshes), and the LEGO robots would need MJCF written by hand.
- **Link transforms in the run file** (FK at write time, Rerun and Foxglove see the body live): the
  run grows by a transform per link per sample (dozens of links at 20 Hz), and a run recorded before
  a description existed never gets a body.
- **glTF instead of URDF and STL:** one file with the tree and the meshes, well supported by
  three.js; but not what ROS tools, Rerun's URDF loader or Foxglove read.
