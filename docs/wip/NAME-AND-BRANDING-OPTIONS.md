# Name and branding: options for the operator, 2026-11-26

The MVP 1 close-out (the operator, 2026-11-23): "decide on a new name for the repository and on
the project's branding". This page gives the options and a recommendation; the decision is the
operator's. Nothing is renamed until it is made.

## What a name has to cover

- **Robot-neutral.** RFC-0022 took "duck" out of the platform's names; the duck, the NXT and the
  Burger (MVP 2) are peers. A duck pun would undo that.
- **The parts it holds:** Mission Control (operate robots and missions), the Observatory (watch
  and analyse runs), the challenge course and its scenario sets, the simulators, the robots'
  brains, and now training (RFC-0031). Satellites: chipi/microduck-nav (public), robotics-evals
  (private).
- **Next to the operator's other projects:** Orrery, Recce, flotilla, Close Listening. Short,
  evocative, one or two words.

## What a rename costs

Measured at main 5b63534:

- **GitHub:** the repository rename redirects old clone and web URLs; the Pages site moves from
  `https://chipi.github.io/robotics-lab/` to the new name (the old one does not redirect).
- **In the code:** 325 references to `robotics-lab`, `robotics_lab` or `ROBOTICS_LAB` in Python,
  TOML, JSON, YAML and the Makefile, among them `ROBOTICS_LAB_INSTALLATION` and the entry-point
  group `robotics_lab.robots`. These do **not** need to change for a rename: the recommendation
  keeps them, as RFC-0022 kept old command names working.
- **Outside the repository:** `/work/robotics-lab/` worktrees, the homelab's stack (`prepare.sh`,
  ROBOTICS_* variables), robotics-evals' and microduck-nav's docs that name the repository, the
  MCP server names. A list is made before the rename, not guessed now.

## Options

| | Name | Says | For | Against |
| --- | --- | --- | --- | --- |
| A | **robotics-lab** (keep) | What it is | No cost; every link stays | Generic; not a name, a description |
| B | **Hangar** | Where the robots live, are prepared and launched from, under Mission Control and watched by the Observatory | One word like Orrery and Recce; robot-neutral; sits with Mission Control and flotilla; `chipi/hangar` is free | Says little about learning and evaluation |
| C | **Proving Ground** | Where machines are tested before they go out | Names what the lab does now: challenges, scenario sets, simulator first, the real robot last | Two words; reads military; slug `proving-ground` |
| D | **Paddock** | Where racing machines are prepared between runs | Warm, robot-neutral, short | Less tied to Mission Control and the Observatory's space vocabulary |

**Recommendation: B, Hangar**, as the repository and the product's name: "Hangar: a home robotics
lab". Mission Control and the Observatory keep their names as its two apps. Internal identifiers
(`robotics_lab.*`, `ROBOTICS_LAB_*`, the Python packages) stay, as RFC-0022 kept the old commands;
renaming them is a separate decision with its own cost. If the space vocabulary should carry
through, C is the alternative that best names the testing work.

## Branding: what it would include

The look and feel closed for MVP 1 (review round 4, all A), so branding is the name and its
marks, not a new design:

1. **The wordmark** in the existing tokens (`libs/web`, `brand.js` names the apps): the name set
   in the UI's typeface, on the shell's top bar beside "Mission Control" and "Observatory".
2. **An icon** for the browser tab and the GitHub social preview, from the same tokens.
3. **The GitHub page:** a one-line description, topics, the Pages URL as homepage, and the README's
   screenshot (the docs close-out item proposes the text).
4. **The docs site's title** (`site_name` in `mkdocs.yml`) and the README's first line.

## Questions for the operator

1. The name: A, B, C, D or another?
2. Internal identifiers: keep (recommended) or rename with it?
3. Branding scope: items 1-4 as above, or more (a logo by a designer, a landing page)?

## Not covered

No trademark or wider name search was made; only `chipi/<name>` was checked on GitHub (free for
B, C, D). The outside-repository list is not made. No wordmark or icon is drawn.
