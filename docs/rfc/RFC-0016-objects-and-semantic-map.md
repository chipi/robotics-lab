# RFC-0016 — Objects, landmarks and a semantic map: "this is the kitchen", "go to the fridge"

**Status:** Accepted, revision 3 (the operator, 2026-11-18: "let's fully implement this … at least
an MVP and a good starting point"); being built.
**Builds on:** [RFC-0002](RFC-0002-robot-brain.md) (the robot brain),
[RFC-0004](RFC-0004-perception-and-planning.md) (the world model: this is its object layer; a VLM
would be one more recogniser), [RFC-0013](RFC-0013-robot-eye.md) (the robot's eye),
[docs/wip/PRIOR-ART.md](../wip/PRIOR-ART.md) (semantic maps, scene graphs),
[docs/wip/EXPLORE-PROGRESS.md](../wip/EXPLORE-PROGRESS.md) (b7: trapped beside a landmark).

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
| Landmark value | 0-1: how distinctive and how well seen; a landmark at 0.7 or more | correcting position (later), naming places |
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
   `semantic` event when it changes; `semantic_map.json` at the end); an optional semantic layer in
   the cost map, off by default (`--object-costs`; §6, §5 question 2). Exploring in the apartment
   only; the challenge course is unchanged (no catalogue there).
5. Rooms: a `room` event when the room the duck believes it is in changes; the scoreboard compares
   it with the truth's room.
6. **Goals by object:** `duck-explore --find fridge` explores until a fridge is confirmed, then goes
   to stand in front of it; judged by the truth (the duck within 0.35 m of the fridge's outline,
   facing it within 45°).
7. The judge and the scoreboard count the six `lm_*` landmarks as obstacles: the depth sensor sees
   them, so in this world they are things the duck would hit.
8. **The inventory, "find all objects"** (`duck-explore --inventory`): explore, then say what is
   where (`inventory.json`: the confirmed objects by room, with sightings, confidence, recognisers
   and evidence); scored by recall, the scene's objects found by room.
9. **In the Observatory and the video:** the objects in the 3D scene, the camera's field of view and
   what it sees now in the eye view, the room and its votes in the thinking panel (records `objects`
   and `sighting`, ADR-0019; built on the `mission-control` branch).

### Revision 3: the site map, names, landmarks (the operator, 2026-11-18: "B yes", "C yes", "D yes")

**Sites and areas, not homes** (the operator: "there should be nothing hard-coded to a home … we
should support multiple terrains, and home is just one terrain being named"; "I'm okay that we adopt
terminology site and area"). A **site** is a named place robots work in, with a kind (apartment,
office, warehouse, garden, the simulated challenge course), its own frame and maps. An
**area** is a part of a site: a room is one kind of area (outdoors, a zone). The operator keeps a
library of sites and names their areas ("Home", and its rooms); the robot's area names (from the
objects' votes, "kitchen") are suggestions the operator can accept or rename (RFC-0014). A site's
kind may change the kinds' area hints (a fridge says kitchen in a home, break room in an office):
`kinds.json` keeps a general default, with optional hints per site kind.

- **A site's semantic map kept between runs.** A site has an id and a site frame. In the simulator
  every run starts at the dock, so a run's map frame is the site frame. Each run starts from the
  site's stored map, adds to it, and writes it back. Objects keep stable ids across runs: a run's
  object is matched to the stored one of the same kind by the same association rule (`ASSOC_M`,
  `UNIQUE_M` for unique kinds). At a real site the robot must first recognise where it is
  (correcting its position from landmarks), so that part comes later. Mission Control owns the
  stored map (RFC-0014); until it exists, a file per site.
- **Naming objects by hand.** An object can carry a label given by the operator ("my desk"), with
  `named_by` and `pinned` (a named object is not merged away or forgotten by a recogniser). `find`
  takes a kind, a label or an id.
- **Kind names and aliases.** Each kind lists aliases (a fridge is a "refrigerator" to COCO, a sofa
  a "couch"), so a goal or a detector's class finds the kind.
- **A landmark is an object whose landmark value is 0.7 or more** (the fridge, the bed, the toilet,
  the bathtub, the sofa, the vanity and the six markers). The Observatory colours them the same way.
- **The camera's record is `sighting`** (was `look`, which already meant the head's glance and the
  "looks before stepping").
- **Rooms have a name, not an extent.** The duck says which room it is in from the objects near it;
  where a room ends is not known yet, so "explore the kitchen" and "go to the kitchen" wait on room
  regions.
- **Results in the run file.** A find's outcome (including `not_found`, when the time or the
  frontiers run out first) and the inventory are recorded in the run, not only in side files, and an
  object's position is re-recorded as it moves (every 2 s when one moved more than 5 cm), not only
  when an object is new.

Glossary: **site** (a named place robots work in, of a kind, with its frame and maps; "Home" is
one), **area** (a part of a site; a room is one kind, named by its contents and by the operator),
**place** (a named point a goal can go to: an object or an area), **object** (anything in an area),
**kind** (what an object is, from `kinds.json`), **landmark** (an object with landmark value ≥ 0.7),
**sighting** (one camera look's recognised objects), **the Observatory** (the run viewer; its
package and command are still `miniview` until the rename).

### Recognisers, and a real site

Anything that recognises objects feeds the semantic map through one record, a `Detection`: a kind, a
disc relative to the duck, a height band, a range, a confidence, the recogniser's name, and evidence
(from a real camera: the frame's time and the box in the image, so an inventory can show the
picture). The simulated camera is one recogniser; a detector on real video (the duck's camera, or a
camera on the NXT's Raspberry Pi) is the next, with no change to the map.

For a real site nobody writes its objects down: the **kinds catalogue** (`kinds.json`, what a fridge
is) is shared by every site; the **site's objects** (which fridge, where) are the semantic map,
filled in by the robot while it explores and kept between runs. A detector trained on household
objects (the COCO set's classes include refrigerator, couch, bed, toilet, chair and TV — from
memory) or an open-vocabulary one (prompted with the catalogue's kind names) recognises the kinds;
anything it does not know is still an obstacle by its shape, and can be named later (in Mission
Control: "this is my desk"), which adds a kind or a label. What a real detector adds that the
simulated one lacks: false sightings, so an object expected in view and not seen must lose
confidence (not built yet).

## 4. Not in the first build

- Correcting position from landmarks (loop closure).
- A real camera, a rendered camera image or a detector network; doors as objects; moving objects.
- Rooms segmented from the map alone (rooms here come from objects; the map's segmentation stays the
  scoreboard's).
- Objects in Mission Control (goals by object there; RFC-0014 revision 2).
- ~~Forgetting an object expected in view and not seen~~ (built: see §6).
- The site map at a real site (it needs relocalisation first); area regions.

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
  - **Association**: kinds a site has one of are `unique` in the catalogue and merge across 1.5 m
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
- 2026-11-18, forgetting built. `SemanticMap.forget(pose, hfov, range, grid, t)` runs after each
  look's `integrate`: a confirmed object inside 0.8 of the field's half-angle and of the range, at
  least 0.3 m away and with no wall of mapd's grid between, that no detection matched, counts a miss
  and loses 15 % of its confidence. `FORGET_N` = 8 misses in a row and it is `gone` (kept in the map
  and the site's history, out of `find`, the votes and the costs; a `forget` event with a decision
  records it). A sighting resets the count; a gone object seen again is `back`, the same object. A
  pinned (operator-named) object is only flagged `missing`. `Site.merge` marks the stored
  counterpart of a run's gone object gone (missing, if named) and revives a gone one the run saw
  again. The constants are guesses for the simulated camera (hit chance 0.4 to 0.8): at its worst
  in-view range (0.8 of 3 m: hit chance 0.8·(1-0.5·0.8) = 0.48), eight misses in a row for an
  object that is there happen 0.52^8 = 0.5 % of the time.
