# robotics-lab

Robot projects, one folder each, and the docs around them. Every project is its own uv project
with its own `.venv`.

| Project | What |
| --- | --- |
| [nxt/](nxt/) | LEGO Mindstorms NXT 2.0 driven from our own Python code: web UI, NXC programs |

## Docs

The docs site lives in [`docs/`](docs/index.md) (MkDocs Material, same conventions as the
operator's other projects): `make docs-serve` to read it, `make docs-validate` before pushing.

- Start with [status and open decisions](docs/wip/STATUS.md).
- [Proposals (RFC)](docs/rfc/README.md): the NXT web UI, the robot brain, one robot interface,
  perception and planning, missions with flotilla and eval-harness.
- [In progress](docs/wip/README.md): ideas, Microduck notes, parts list.
- [History](docs/history/README.md).
