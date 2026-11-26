# Mission Control (RFC-0014 §3.13) as an image, to run on any of the operator's machines.
#
#   docker build -f apps/mission-control/Dockerfile -t mission-control:local .     # from the repository root: it installs libs/runfile, libs/gate and libs/missions too
#   docker run --rm -p 127.0.0.1:8060:8060 -v $PWD/apps/mission-control/robots.example:/config/robots:ro -v mc-state:/state mission-control:local
#
# `make`'s control-up / control-down wrap apps/mission-control/compose.yml. Configuration (the robot files) and data (the SQLite store, the gates'
# logs) come in by volumes, the listen address and folders by MC_* variables; nothing is tied to a host. Robots are reached over the
# network, never through a device on this host. The API has no login by default: publish the port on loopback (as above) or on the
# tailnet's address, never on a public interface (RFC-0014 §3.9); `--require-tokens` adds per-client tokens.
#
# The versions are apps/mission-control/uv.lock's, installed with `uv sync --frozen --no-dev`. The gate (RFC-0017, libs/gate), mission planning (RFC-0030, libs/missions) and the run
# format (libs/runfile) are path sources in apps/mission-control/pyproject.toml, so the folders sit side by side as they do in the
# repository, and are installed editable from there. libs/web (the design tokens, three.js, the robot body) sits beside them, where api.py finds it. No robot's package is in the image (phase 5 step 1): a robot file that points at a
# robot's profile (`"robot": "duck"`) needs an installation file mounted (ROBOTICS_LAB_INSTALLATION) whose robots.<name>.registration
# names the robot's registration file, mounted with the profile beside it; the fake robot (robots.example) needs none.

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY libs/runfile/pyproject.toml ./libs/runfile/pyproject.toml
COPY libs/runfile/src ./libs/runfile/src
COPY libs/web ./libs/web
COPY libs/gate/pyproject.toml ./libs/gate/pyproject.toml
COPY libs/gate/src ./libs/gate/src
COPY libs/missions/pyproject.toml ./libs/missions/pyproject.toml
COPY libs/missions/src ./libs/missions/src
COPY apps/mission-control/pyproject.toml apps/mission-control/uv.lock ./apps/mission-control/
COPY apps/mission-control/src ./apps/mission-control/src
RUN cd apps/mission-control && uv sync --frozen --no-dev \
 && mission-control serve --help >/dev/null

ENV MC_ROBOTS=/config/robots MC_STATE=/state MC_HOST=0.0.0.0 MC_PORT=8060 PYTHONUNBUFFERED=1
RUN mkdir -p /config/robots /state
VOLUME /state
EXPOSE 8060
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8060/api/v1/health', timeout=2)"
CMD ["mission-control", "serve"]
