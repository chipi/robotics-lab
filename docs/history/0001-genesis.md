# 0001 — Genesis

**Dates:** 2026-11-13 to 2026-11-14
**Operator:** Marko Dragoljevic
**Agent:** Claude Code (Opus 5.5), the robotics-lab session
**Outcome:** the NXT is driven, recorded and programmed from our own software over USB and
Bluetooth; the Microduck's simulator, arena and DGX training stack exist; the robot brain is
designed as RFC-0002 to RFC-0005.

## How it started

The operator wanted to play with robotics: a LEGO Mindstorms NXT 2.0 from about 15 years ago,
and a Hugging Face "duck" on its way — the Microduck. First project: get the NXT moving with their
own software. Several robot projects would live in one repo, one folder each.

## What was built

- **`nxt/`:** a uv project on nxt-python; a web UI ([RFC-0001](../rfc/RFC-0001-nxt-web-ui.md));
  NXC programs compiled by Debian's `nbc` in Docker (the operator chose Docker over an AUR
  install); dog games (chase, patrol).
- **The NXT on the robot (2026-11-14):** ports identified by turning each motor (A shooter, B
  right, C left) and confirmed by the box labels; sensors read (colour 3, ultrasonic 4); driving,
  recording and an on-brick program over USB, then Bluetooth paired and used.
- **Microduck:** official repos cloned in `/work/pollen/`; the arena and the simulated duck run on
  the workstation; Rust installed per user.
- **DGX:** the homelab session added a `robotics` GPU mode and ran a first measured training run;
  robot-brain model aliases went live on LiteLLM (open-weight models, the operator's choice).
- **Docs:** this docs site, five RFCs, notes in `wip/`.

## What the operator decided

- One folder per robot project; Docker for the NXC compiler; the NXT over USB first, Bluetooth as
  a start for wireless, an ESP32 bridge for house-level range later.
- The robot brain: build it for the duck first, phase 0 approved; models open-weight and runnable
  on the DGX, budget "whatever we need".
- The direction for eval-harness and flotilla: the combined mission loop, with shadow meaning
  "run the plan on the simulated duck".
- Align every robot on one JSON-RPC interface; where the NXT's lives is decided later.

## What was learned

- **The NXT has no deadman.** Our own smoke test drove the real robot twice: once leaving the
  tracks running after its server was killed, once hanging the live server over Bluetooth. Both
  fixed at the cause that was ours; the on-brick deadman is the remaining fix
  ([RFC-0003](../rfc/RFC-0003-robot-interface.md)).
- **Read facts from the hardware, not from photos.** The firmware is 1.28; it had been read as 1.31
  from a photo of the brick's screen.
- **Press coverage was wrong about the duck's sensor** (it is an 8×8 time-of-flight sensor, not
  LiDAR); the upstream repos were the source to trust.

## Where things were left

See [Status and open decisions](../wip/STATUS.md).
