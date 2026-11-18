# robotics-lab

Robot projects, one folder each, and the docs around them. Every project is its own uv project
with its own `.venv`.

| Project | What |
| --- | --- |
| [nxt/](nxt/) | LEGO Mindstorms NXT 2.0 driven from our own Python code: web UI, NXC programs |
| [duck/](duck/) | Pollen's Microduck in simulation: the navigator, exploration, probes, recording |
| [viewer/](viewer/) | miniview: runs as MCAP, an API with live runs, the workbench pages (`make viewer-up`) |
| [control/](control/) | Mission Control (RFC-0014): robots, goals, sites and areas behind one API, against a fake robot so far (`make test-control`, `make control-run`; [CONTRACT.md](control/CONTRACT.md)) |

## Checks and CI

The same make targets run on the workstation and in CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)),
so a red job reproduces locally with the target it names:

| Target | What |
| --- | --- |
| `make ci-fast` | lint, then every project's unit tests: `test-unit` (nxt), `test-duck`, `test-viewer` |
| `make test-viewer-pages` | miniview's two pages in headless Chromium (`MINIVIEW_CHROMIUM`, else Playwright's) |
| `make test-integration` | the NXT web UI image (built from the repo root) answers with a simulated brick and records a miniview run |
| `make test-viewer-image` | miniview's image runs with the data mounted read only and its index on its own volume, serves a run, and cannot write the data |
| `make test-run-compat` | a run opens fully in Rerun (`mcap check`, `mcap convert`), in Lichtblick (its image, headless: topics, start date, the topics draw) and in miniview; guards ADR-0007's compatibility |
| `make perf-viewer` | not in CI: replays a real run at 20 Hz through the writer with both pages open and prints latency, bytes per page and lock hold time |
| `make nxt-programs` | every NXC program compiles for the brick |
| `make ci` | all of the above and the docs (`docs-lint`, `docs-build`) |

## Docs

The docs site lives in [`docs/`](docs/index.md) (MkDocs Material, same conventions as the
operator's other projects): `make docs-serve` to read it, `make docs-validate` before pushing.

- Start with [status and open decisions](docs/wip/STATUS.md).
- [Proposals (RFC)](docs/rfc/README.md): the NXT web UI, the robot brain, one robot interface,
  perception and planning, missions with flotilla and eval-harness.
- [In progress](docs/wip/README.md): ideas, Microduck notes, parts list.
- [History](docs/history/README.md).
