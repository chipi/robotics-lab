# PRD-001: miniview (now the Observatory) — seeing what a robot believed, against what happened

> Now the Observatory (RFC-0018, built 2026-11-19): the product, package and command were renamed;
> this text keeps the names of its time.

- **Status**: Proposed (2026-11-15) — for the operator's review
- **Authors**: Marko Dragoljevic
- **Related UX spec**: [UXS-001](../uxs/UXS-001-miniview.md) (the two faces: the page and the commands)
- **Related RFCs**: [RFC-0009](../rfc/RFC-0009-miniview.md) (architecture),
  [RFC-0008](../rfc/RFC-0008-challenge-course.md) (the challenge course it serves),
  [RFC-0007](../rfc/RFC-0007-platform.md) (the platform it is part of)
- **Related ADRs**: [ADR-0002](../adr/ADR-0002-viewers-rerun-and-lichtblick.md) (Rerun and Lichtblick)

## Summary

A robot run is reviewed by looking: where the robot thought it was, what it thought was around it,
what it planned, and what was really there. Rerun and Lichtblick do this well for a person at a
screen; an agent (the session that builds the navigator, a reviewer) cannot drive them — their views
are one canvas, with nothing to ask and nothing to read back. **miniview** gives the same answers to
both: a page for the operator, and commands that return pictures and text for an agent, from one
run format and one way of drawing it, for any robot.

## Background & Context

Phase 2 of the robot brain went one difficulty per trial for a weekend; twice the cause was guessed
from numbers and was wrong, and pictures settled it ([PHASE2-RESULTS](../wip/PHASE2-RESULTS.md),
[the review](../wip/REVIEW-2026-11-15-navigator.md)). The challenge course (RFC-0008) multiplies runs:
twenty challenges, ten runs each. A first `miniview` exists (top and 3D frames, layers, a filmstrip,
`duck_lab/miniview.py`); this document is what it should become.

## Goals

1. **Answer "what happened at this moment, and why"** for one run: belief and truth, the world model
   (map, remembered obstacles and drops), what the sensors saw, the plan, the rule that acted.
2. **Answer "how did the runs in this scene go"** — a scene is the place (the apartment, a
   challenge's scene, a real room), and runs belong to it (operator, 2026-11-15): verdicts, pass
   rates, invariant breaks,
   each linked to the run and the moment.
3. **Two faces, one truth**: what the page shows, a command returns, with the same picture.
4. **Any robot**: the duck first, the NXT next, from one run format with an adapter per robot.
5. **Cheap for an agent**: small pictures, short text, stable outputs, nothing to install at run time.

## Non-Goals

- Replacing Rerun or Lichtblick for free 3D exploration, point clouds at scale, or live streams.
  (The Explore tab's robot body, RFC-0011, is one robot's model to orbit and pick parts from, not a
  free 3D scene.)
- ~~Live viewing of a running robot (later; the format allows it).~~ *Now in scope* (ADR-0005,
  RFC-0010): a run being
  written is followed by record and shown live, with Follow live as a mode. Free 3D exploration of
  live streams stays with
  Rerun and Lichtblick.
- Editing runs or annotating them (the logbook of RFC-0007 may).
- ~~A server or a database: files in, files out.~~ *A small service exists* (RFC-0009 "Running in
  Docker", ADR-0005, ADR-0012):
  one process serving the pages and the API, with a SQLite index of its own derived from the run
  files. The runs stay files; the
  service reads them and cannot change them (the data is mounted read only).

## Personas

- **The operator** reviews runs in a browser, often away from the machine: wants the failure moment
  in one click and to see it, not read logs.
- **The building agent** (the session improving the navigator) asks narrow questions many times a
  run: a picture at t, the state at t, the events, what changed.
- **A reviewing agent** (the Fable advisor) checks claims against runs: needs the same commands and
  numbers it can quote.

## User Stories

- As the operator, I open the viewer, pick a run from the list (or switch runs from the picker),
  drag the timebar, and every panel follows.
- As the operator, I open a run's page, see the timeline with its events, click the cliff stop, and
  see the world model and the truth at that moment in 3D, with the frames before it underneath.
- As the operator, I load a scene, see what is really there and its runs, failures first, each opening
  at its failure.
- As the building agent, I list a run's events, then ask for a picture of the seconds before the
  first refusal, with only the layers I name.
- As the building agent, I ask for the state at t as JSON — belief, truth, their difference,
  clearance to the nearest real obstacle and drop, the rule that acted — instead of reading ticks.
- As a reviewing agent, I ask which runs in a scene broke an invariant and when.
- As the operator, I draw several runs of the same scene together (repeats; before and after a fix).
- As the operator, I open a run's robot in the Explore tab, turn its body around, click a part to
  see what moves it and where it hangs, and pose it as recorded at t or by hand (2026-11-16).
- As the operator, I find a stream by what it means for the robot (World, Body, Senses, Mind), with
  the joints by leg and head, and keep closed what I do not need (2026-11-16).

## Functional Requirements

### FR1: One run format

Records in time order: robot poses (belief, truth where a simulator gives it), world snapshots (map
grid, remembered obstacles, hazards such as drops), perception (sensor returns with a kind, raw
frames), the plan, decisions (rule, reason) and events; plus the run's metadata (robot, footprint,
scene, start). Adapters bring in the duck's navigator log now and MCAP (`nxt-web`) next.

### FR2: The agent's face

Commands, each with a picture (PNG) and/or JSON: events; a frame at t (top or 3D, layers, camera);
a filmstrip; the state at t; a raw sensor frame at t; scenes and their runs. Same inputs, same
outputs.

### FR3: The operator's face

A viewer page served by `make viewers`: the list of runs to choose from and a run picker; a
timebar that every panel follows; 2D by default from the top, any side or all three at once, and
3D; the coordinate system always visible; a data view with only the robot's own data in its own
frame; layers, the state panel, the
filmstrip; scenes to load and runs within them, several runs drawn together. (Scenes, choosing
runs, the timebar, 2D first: operator, 2026-11-15.) The left panel grouped by meaning in sections
that collapse; an Explore tab on the right whose first kind is the robot's body (operator,
2026-11-16; UXS-001).

### FR4: Truth and numbers beside the picture

Belief–truth error and clearance to real obstacles and drops over time, as charts on the page and
numbers in the commands, with the invariants of RFC-0008 marked where they broke.

## Success Criteria

- For the next ten failures of the challenge course, the cause is found from miniview without a
  new trial (today: one trial per cause).
- The operator reviews a scene's runs from the page alone, on the phone included.
- A new robot needs an adapter only.

## Related Documents

[RFC-0009](../rfc/RFC-0009-miniview.md), [UXS-001](../uxs/UXS-001-miniview.md),
[RFC-0008](../rfc/RFC-0008-challenge-course.md), [RFC-0007](../rfc/RFC-0007-platform.md).
