# RFC-0016 — Objects, landmarks and a semantic map: "this is the kitchen", "go to the fridge"

**Status:** Accepted, revision 2 (the operator, 2026-11-18: "let's fully implement this … at least
an MVP and a good starting point"); being built.
**Builds on:** [RFC-0002](RFC-0002-robot-brain.md) (the robot brain),
[RFC-0013](RFC-0013-robot-eye.md) (the robot's eye), [docs/wip/PRIOR-ART.md](../wip/PRIOR-ART.md)
(semantic maps, scene graphs), [docs/wip/EXPLORE-PROGRESS.md](../wip/EXPLORE-PROGRESS.md) (b7:
trapped beside a landmark).

## 1. Why

Exploring batch b7 ended all three runs trapped beside `lm_office`, a landmark pillar the
simulator's depth sensor sees but the duck walks through (Pollen's scene: "visual only, for loop
closure"). That opened the question of what a landmark is to the duck. The operator's goals behind
it: rooms named by what is in them ("recognise the fridge: this is the kitchen"), goals given as
things ("go to the fridge"), and later a real camera (on the NXT's Raspberry Pi, or the duck's own)
doing image recognition.

## 2. The model

**Everything in a room is an object.** Furniture says what a thing is; a landmark is a role a thing
plays (distinctive, staying put, recognisable again). A fridge is both; a chair is furniture and a
poor landmark; a picture on a wall is a landmark and no obstacle. An object has independent
properties:

| Property | Values | Used for |
| --- | --- | --- |
| Shape and height | parts (boxes in plan, each with a bottom and a top) | moving: avoid, walk over, pass under |
| Traversal (from shape) | over (≤ walk-over height), under (bottom above the head), around | the cost map |
| Permanence | fixed, movable, moving | how long the map trusts it |
| Landmark value | 0-1: how distinctive and how well seen | correcting position (later), naming places |
| Kind and room hints | "fridge" → kitchen 0.95 | rooms by their contents; goals by name |

Kinds and their defaults live in one catalogue (`duck/src/duck_lab/world_model/kinds.json`), not in
code.

**The semantic map** is the object layer over the occupancy grid (the field's term; larger systems
call it a 3D scene graph: building → rooms → objects). It holds tracked objects in the map frame:
each detection is associated with a known object of the same kind nearby or starts a new one; an
object is
**confirmed** after several detections. From it: the room the duck is in (votes of the confirmed
objects near it, by their kinds' room hints), an object by kind or name, and where to stand to reach
one.

**How the duck behaves.** Moving: an object counts only by its shape — whatever the duck could hit
is avoided, whether or not it is a landmark. Knowing where it is: a re-seen landmark could correct
drift (not in the first build). The mission: rooms named, goals by object.

## 3. The first build (MVP)

1. `world_model/objects.py`: the kinds catalogue, `Object` and its parts, traversal from height.
2. `world_model/semantic_map.py`: association, confirmation, `room_at`, `find`, `approach`; JSON in
   and out.
3. **A simulated camera** (`nav/sim_camera.py`), the stand-in for image recognition until a real one
   exists: from the simulator's layout, the objects within the head camera's field of view (60° by
   default) and range (3 m), not hidden behind a wall, each detected with a probability and placed
   with noise (range, bearing). Fidelity is a setting (`calibration/sim.json` "camera"). It reads
   the simulator's scene and the duck's true pose — the one place the brain's inputs come from the
   truth, on purpose and only through this sensor model; its detections are relative to the duck and
   placed on the map with the duck's belief, as a real camera's would be.
4. The navigator and the explorer: the camera every 0.5 s, the semantic map updated and recorded (a
   `semantic` event when it changes; `semantic_map.json` at the end); confirmed objects' blocking
   parts join the cost map as obstacle points (a semantic layer). Exploring in the apartment only;
   the challenge course is unchanged (no catalogue there).
5. Rooms: a `room` event when the room the duck believes it is in changes; the scoreboard compares
   it with the truth's room.
6. **Goals by object:** `duck-find fridge` explores until a fridge is confirmed, then goes to stand
   in front of it; judged by the truth (the duck within 0.35 m of the fridge's outline, facing it
   within 45°).
7. The judge and the scoreboard count the six `lm_*` landmarks as obstacles: the depth sensor sees
   them, so in this world they are things the duck would hit.

## 4. Not in the first build

- Correcting position from landmarks (loop closure).
- A real camera, a rendered camera image or a detector network; doors as objects; moving objects.
- Rooms segmented from the map alone (rooms here come from objects; the map's segmentation stays the
  scoreboard's).
- Objects in Mission Control and the Observatory (the `semantic` events are recorded so they can be
  drawn later).

## 5. Open questions

1. The simulated camera reads the truth. Its fidelity settings (field of view, range, detection
   probability, noise) are guesses until a real camera is measured.
2. Whether confirmed objects in the cost map change the exploring results enough to keep them
   (measured by a batch with and without).

## 6. Discussion

- 2026-11-18, the operator: "everything is object, some objects are landmark … the semantic map …
  recognise the fridge tells the duck this is the kitchen … then I can give goals, go to the
  fridge."
- 2026-11-18, the advisor's review (taken, revision 2 as built):
  - **The semantic cost layer is off by default** (`--object-costs`). The depth sensor already sees
    what the camera would add; a drifted copy of an object beside its fresh points would close
    passages, and its points feed "no room to turn" (b7's trap). Kept for the comparison in §5.
  - **A detection is a kind, a disc relative to the duck, a height band and a range**, no name and
    no world coordinate (a test checks it). The simulated camera moved to `nav/sim_camera.py`,
    beside the truth (`Body`), out of the brain's `world_model` package; `Body` serialises its
    socket (the record, the truth guard and the camera read it from three threads).
  - **Association**: kinds a home has one of are `unique` in the catalogue and merge across 1.5 m
    (the fridge seen again after drift is the same fridge); positions follow recent detections.
  - **Rooms**: objects within 1.2 m, weighted 1/(1+d)², and not behind a wall of the duck's own map
    vote; a new room only after it leads three looks in a row; none named while no object near says
    anything. Scored per tick away from doorways (0.3 m), the unnamed time apart.
  - **Where to stand** must leave room to turn there (`PIVOT_OBSTACLE_M`); a turn then faces the
    object.
  - **The judge** counts the `lm_*` landmarks; phase 1's goal set is drawn without them, as before.
    Batches b1-b7 re-scored with it: contacts b1 0→4, b5 2→5, b6 0→3, b7 0→3 (grazes of 7.5-8 cm in
    tight pivots beside `lm_office`, its points remembered on its outline).
  - Not taken yet: an object missed in view losing confidence (the simulated camera has no false
    positives); a two-leg approach along the face's normal (the turn does the facing).
