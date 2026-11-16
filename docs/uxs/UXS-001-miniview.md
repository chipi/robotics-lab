# UXS-001: miniview — scenes, runs, and the commands

- **Status**: Proposed (2026-11-15) — for the operator's review; shaped by the operator's asks the
  same day (scenes, choosing runs, the timebar, 2D first, sides and three-view, the coordinate
  system, the data view)
- **Authors**: Marko Dragoljevic
- **Related PRDs**: [PRD-001](../prd/PRD-001-miniview.md)
- **Related RFCs**: [RFC-0009](../rfc/RFC-0009-miniview.md) (architecture)
- **Implementation paths**: today `duck/src/duck_lab/miniview.py`; RFC-0009 moves it

## Summary

Two faces over the same things: a page modelled on Rerun's layout for the operator, and commands for
an agent. What you open is a **scene** — the place, with what is really there — and its **runs**:
the robot's attempts in it. Every view on the page names the command that draws it, and every
command's picture is the page's picture.

## Principles

- **Agent first, human friendly.** Anything the page shows is a command; anything a command answers
  the page shows. No view exists in one face only.
- **The scene is what you load; runs belong to it.** A run is always seen in its place, unless you
  ask for its data alone.
- **Truth beside belief, always.** Where the scene knows what is really there, it is drawn and
  measured next to what the robot believed; the difference is the point.
- **The moment is the unit.** Every view is "at t"; the timebar moves t; events are the way to
  find it.
- **The coordinate system is never hidden.** Every view says where zero is, which way the axes go,
  and in which frame.
- **Quiet by default.** Layers are on or off by name; routine records (a kept plan) are not events.
- **Same picture, any size.** A view reads at 900 px on a screen and 180 px in a filmstrip.

## Scope

**In scope:** the scenes list, a scene, a run in its scene, several runs in one scene, a run's data
alone, the commands. **Non-goals:** live view, editing, annotations, free 3D exploration of large
point clouds (Rerun does that).

## Scenes and runs

A **scene** is a place: the simulated apartment, a challenge's small generated scene, later a real
room as a recorded map. It holds what is really there (walls, furniture, hazards such as stairs), its
origin and frame, and — for a challenge — the mission and the invariants. A **run** is one attempt by
one robot in one scene: its records, its verdict.

**The scenes page** (where the viewer opens): every scene found, newest activity first, filterable by
kind (apartment, challenge, real) and robot; each row with its name, its runs, and for a challenge its
pass rate. A **scene picker** in the head switches scenes from anywhere; the URL names the scene and
the run, so a link opens exactly that.

**A scene's page**: the scene drawn alone (its geometry, its hazards, the coordinate system), and its
runs as a list beside it — time, robot, length, verdict, closest clearance, the invariants broken —
failures first for a challenge. Choosing a run opens it in the scene; choosing several draws their
tracks together over the scene (repeats of a challenge, before and after a fix), each in its own
shade, with one timebar per run or aligned at a chosen event. The head shows the pass rate and how
often each invariant broke.

## A run in its scene (Rerun's layout, in miniature)

- **Left — layers**, Rerun's entity tree flattened: scene (truth), coordinate system, map, memory,
  hazards, depth, raw frame, plan, belief, truth, events. A checkbox each; the URL keeps the choice.
- **Centre — the view**: **2D by default, from the top**; the side to look from is a choice — top,
  front, back, left, right — or **all three at once** (top, front and side, the engineering
  three-view); a switch to 3D (orbit with the mouse; dollhouse cutaway) and back. 2D pans and zooms;
  a "follow the robot" toggle in every view; the robot at its real size, belief blue, truth green.
- **Right — the moment**: t; belief, truth and their difference; clearance to the nearest real
  obstacle and hazard; the last decision (rule and reason); the raw sensor frame as a small image
  (8×8 depth, coloured by kind).
- **Bottom — the timebar**: the run's length, event markers coloured by kind (stop, refusal, hazard,
  recovery, end), a cursor to drag or click; **everything on the page follows the cursor** — the
  view, the moment, the raw frame, the filmstrip, the charts' marker — with no lag that shows
  (frames are prepared, not computed while dragging); play at 1×/4×. Under it the filmstrip of the
  seconds before t; under that two thin charts — belief–truth error and clearance — with invariant
  breaks in red.
- **Head**: scene and run pickers, robot, verdict; "this view as a command" (copies the CLI line).
- **Keys**: space play/pause, ← → a tick, `e`/`E` next/previous event, `2`/`3` 2D/3D, `v` next side,
  `a` all three, `f` follow, `s` scene picker, `r` run picker.

### The left panel: streams, and how they connect (operator, 2026-11-15)

What the session used to wire up in code becomes seven controls, modelled on Rerun's blueprint and
entity tree (comparison: the "miniview and Rerun" page):

1. **Streams tree** — every stream the run holds, grouped by source (Scene, Robot (belief), Truth,
   Sensors with depth by kind as children, World model, Plan, Events), each with an eye to show or
   hide it; hiding a group hides its children. *Grouped by meaning since 2026-11-16 (World, Body,
   Senses, Mind, Other values; [below](#the-left-panel-by-meaning-and-the-explore-view-operator-2026-11-16)).*
2. **Badges** — on each stream: its frame (world, map, robot), how many records and how often, or
   **missing** with the reason (a run without tilt, a real robot without truth).
3. **Time mode** per stream — at t (the latest at or before t), the last N seconds, or everything up
   to t; tracks default to everything up to t, depth to at t.
4. **View frame** — world (the scene and truth beside belief) or the robot's map frame (the data view).
5. **Relations** — belief ↔ truth: a line between the two robots and their distance; depth ↔ pose:
   the pose each depth frame was placed with (shown as unavailable until the run logs frame times).
6. **Per-view visibility** — in the three-view, T, F and S pips per stream turn it off in one view only.
7. **Selection** — a click on a point, a robot or a map cell shows its values in the right panel
   (stream, kind, position, height, tick).

Every control maps to a call of the page's script API (`viewer/CONTRACT.md`), which the commands use.

### The coordinate system

Every view draws its frame plainly: the origin marked; the axes as arrows in the robotics colours
(x red, y green, z blue), labelled; a metre grid with numbered lines along the edges; the frame's
name in a corner (world, map, odom); in 3D a small axis gizmo that turns with the camera. A side view
shows heights the same way: the floor at z = 0, below-floor returns visibly under it.

## A run's data alone

A tab beside the run, like the first Rerun tests: **only the robot's own data in its own frame** —
odometry and map poses and their tracks, the sensor returns, its map, its plans — with no scene, no
truth and no world transform. It answers "what does the data say" before "how does it compare"; it is
also all a real robot's run has when no map of the room exists. Same timebar, same views, same
coordinate system, its frame named (odom or map).

## The commands

`miniview <command> <scene-or-run> [options]`; pictures are PNG (SVG with `--svg`), answers JSON with
`--json`, short text otherwise.

| Command | Answers |
| --- | --- |
| `scenes` | the scenes found, with their runs and pass rates |
| `scene SCENE` | a picture of the scene alone, and its runs as a table |
| `runs SCENE` | the scene's runs: verdicts, numbers, invariant breaks, each run's worst moment |
| `events RUN` | what happened, when (one line each; `--kinds` to filter) |
| `frame RUN --at T` | a picture of the moment (options below) |
| `film RUN --at T --span S --n N` | the moment with N frames before it underneath |
| `state RUN --at T` | belief, truth, error, clearances, the last decision, the sensor summary |
| `sensor RUN --at T` | the raw depth frame as an image and numbers |
| `tracks SCENE RUN...` | several runs' tracks over the scene, optionally aligned `--at-event KIND` |

`frame` and `film` take `--view` (top, front, back, left, right, three, 3d), `--data-only`,
`--layers`, `--around` (metres around the robot), `--az` and `--el` (the 3D camera).

Outputs are stable (same inputs, same bytes), small (a picture under ~200 KB), and every picture's
caption carries the scene, the run, t and the last event, so a picture quoted out of context still
says what it is.

## The whole page (operator, 2026-11-15)

Approved from the mockup `viewer/web/mockup/index.html` (explore12 at 78.96 s; its picture does not
follow the time controls). It replaces the flat left list of v0.2 and is modelled on Blender, Maya,
Unreal, Unity, Rerun and Foxglove:

- **Top bar** (36 px): scene and run as popover lists (verdict and length in the run list), the
  layout (Top, Three, 3D) and the frame (World, Map) as segmented controls, a status chip, keys `?`.
- **Left, Streams** — an outliner: 22 px rows, carets, a type icon in the data colour, the frame
  once per group as a dim suffix, an eye in a fixed column at the right edge (a group's eye shows
  all, some or none; hiding a group dims its children without changing them). Count, rate and id on
  hover only. Missing streams are dimmed with a warning icon, and one filter hides them. Search
  with `/`. **Belief and Truth are grouped under Robot** (decision D3). *The grouping is replaced by
  the sections World, Body, Senses, Mind and Other values (operator, 2026-11-16; [below](#the-left-panel-by-meaning-and-the-explore-view-operator-2026-11-16));
  the outliner's rows, eyes, badges and search stay.*
- **Left, under the outliner — the selected stream's properties** (decision D2): a header (name, id,
  frame, records and rate), then collapsible sections Time (At t, Window, Up to t; window length as
  a drag field), Display (visible, views T F S 3D, colour, size), Source (read-only), Relations.
- **Right — the inspector**, read-only: Moment (time, tick, belief, truth, error, command, depth
  frame, plan and map, last event with previous and next) and Selection (a picked point's values).
  Label left, value right in mono, unit dim, copy on hover; "copy JSON" per section. A third tab,
  **Explore**, was added on 2026-11-16 ([below](#the-left-panel-by-meaning-and-the-explore-view-operator-2026-11-16)).
- **Viewport**: a header with the frame and orientation, an overlays menu (coordinate system,
  relations), fit; axis gizmo, cursor readout, legend, a 1 m scale bar.
- **Bottom — the timeline**: transport, time and tick fields, speed, loop, an event-kind filter; a
  ruler with the recorded span; event markers by kind (triangles for stops and refusals); the
  selected stream's window as a band. **Data rows, one per stream, are on by default, with a switch
  to the compact timeline without them** (decision D4).
- **Status bar** (22 px): key hints, scene and run.

## The left panel by meaning, and the Explore view (operator, 2026-11-16)

Prototyped in `viewer/web/proto/` (round 1: a run of challenge 3 with the duck's joints and
Pollen's meshes; the main view unchanged) after the duck's runs gained joints (ADR-0016) and robots
their description (RFC-0011). The operator's answers:

**The left panel** groups the streams by what they mean for the robot, not by where they come from:

- **Run** (the header): the robot, the scene, where the run came from (simulated or real), its
  length and verdict.
- **World**: what was really there: the scene's geometry and hazards, the truth's pose and track
  (simulator only).
- **Body**: what the robot is: its 3D model (its parts), and its joints grouped by kinematic chain
  (left leg, right leg, head), the chains read from the robot's joint tree.
- **Senses**: what it perceived: depth by kind, the raw frame, the IMU.
- **Mind**: what it believed and decided: belief and its track, the map grid, remembered obstacles
  and drops, the plan, decisions and events.
- **Other values**: the navigator's own signals that belong to none of the above.

Rules:

- **Every section collapses**, and they are **not all open by default**; each viewer's open and
  closed sections are remembered on their machine. Which section, if any, opens on a first visit is
  open (the prototype opened Body).
- **The joints show their angle at t**, with **a switch to show or hide the angles** (on the Body
  section's header).
- **Names are the robot's technical names** (`left_knee`, `neck_pitch`, `head_roll_link`), not
  friendly ones, for now.
- **The same sections order the timeline's data rows and the Moment tab's values**, so a joint is in
  Body everywhere (else the duck's 14 joints are 14 more flat rows in each).
- The outliner's rows, eyes, badges, missing-stream dimming and search are those of the whole page
  above.

**Explore** is a third tab of the right panel, beside Moment and Selection: a detail view for
looking closely at one thing. A picker says what is explored; its first kind is **the robot's
body**. Other kinds (a depth frame, the map) come later in the same place. The tab can take more
room ("Expand").

- **The body in 3D**: the robot's meshes placed by its joint tree (RFC-0011's forward kinematics);
  drag to orbit, scroll to zoom. **Posed as recorded at t** (it follows the timeline) **or by
  hand**, with a slider per joint grouped by chain.
- **Parts are clickable**, in the 3D view or in the list of parts under it (the link tree). A picked
  part is highlighted and its **details** shown: what moves it (its joint, the joint's type and
  limits) or what it is fixed to, what it hangs from and what it carries, its meshes, and where it is
  relative to the trunk now. Mass and inertia are not shown: the description has none
  (`robots/duck/robot.urdf` has no `<inertial>`).
- **Isolate, hide, show all**, and **focus** on the picked part.
- A robot can be explored with no run open (the registry, RFC-0011 §3.4); then it is posed by hand
  only.

This places RFC-0011's Robot view as the Explore tab's first kind, not as a view mode beside Top, 3D
and Map.

## The robot's eye, what it decided, and the watch page (RFC-0013 prototype, operator 2026-11-16)

Prototype for review, on the three.js page only.

- **Two more views** in the layout switch, beside Top, Three and 3D, both in the world frame:
  **Eye**, a camera at the depth sensor's pose at the playhead (recorded with the depth frame; for a
  run without it, estimated from the trunk's pose and a nominal mount, and the HUD says which),
  darkened outside the sensor's 45 degree cone; and **Chase**, behind and above the robot,
  following it.
- **The eye's HUD** (over the Eye view): pace (the tick's command), what the newest event decided
  (its rule and reason), the numbers that decision compared, this frame's returns by kind and the
  8 x 8 distances. Only recorded values or values computed from them. An **alert** above them says
  what the navigator did that RFC-0012 calls attention: STOPPED for a cliff stop, LOOKING while
  the head looks at a suspected drop (its bearing and distance), LOOKED after it (what it saw, where
  the edge is); held 4 s. It shows what the robot did, never what a rule would have done.
- **Gaps** (stream `world.gaps`, in the World model group): the unknown cells of the map in force within
  0.45 m of the plan in force, tinted orange with a hatch; the other unknown cells as a faint fog.
  **Real hazards over the model** (an overlay, off by default) draws the scene's hazards again as a
  dashed outline over everything, so what is there and not in the model reads.
- **Decided**, a fourth tab of the right panel: the run's events with their rule, reason and values,
  the one at or before the playhead marked, a click seeks; stops and the judge's invariant and verdict
  are emphasised.
- **Watch** (`/watch/<robot>/<scene>/<run|latest>`): one run for watching: the eye with the top view
  inset, the decisions beside it, a timeline with the events marked; it follows a live run. A link on
  each page opens the other at the same moment.

## Theme

**Dark and light from the start** (decision D1, operator 2026-11-15): one set of colour tokens with
both values; the page follows the system and has a switch; dark is designed first. Colours carry
meaning and
are the same everywhere: belief blue, truth green, plan amber, obstacles orange, hazards magenta,
floor returns green, obstacle returns red, overhead blue, below-floor magenta, mapd's occupied grey;
the axes x red, y green, z blue.
