# LEGO robots from LDraw

`from_ldraw.py` turns an LDraw model and a hand-written `kinematics.json` into a robot description
(`robot.urdf` and STL meshes per link and colour, RFC-0011). Run `make robots-lego`; it needs the LDraw
parts library in `~/opt/ldraw/ldraw` (ldraw.org's `complete.zip`) or `LDRAW_DIR`. Meshes are generated,
not committed.

| Robot | Model | Source | Licence |
|---|---|---|---|
| `ev3-track3r` | `31313-1_Track3r.mpd` | LDraw OMR, set 31313, by Philippe Hurbain (Philo) | CCAL 2.0 (CC BY 2.0) |
| `ev3-spike3r` | `31313-1_Spike3r.mpd` | LDraw OMR, set 31313, by Philippe Hurbain (Philo) | CCAL 2.0 (CC BY 2.0) |
| `nxt-shooterbot` | `shooterbot.ldr` | written in this repo, an approximation from the 8547 User Guide's Quick Start model; its tread subfiles are copied from the Track3r file above | CCAL 2.0 (the copied parts) |

The OMR files are unchanged; their author and licence lines are in their headers. The LDraw parts
library itself (CCAL 2.0) is not in the repo.

Which parts move with which joint is set in each robot's `kinematics.json`; several assignments are
judgements from geometry, not from the instructions (the selector format is in `from_ldraw.py`'s
docstring).
