# Mission Control (RFC-0014 §3.13) as an image, to run on any of the operator's machines.
#
#   docker build -f control/Dockerfile -t mission-control:local .     # from the repository root: it installs libs/runfile, libs/gate, libs/worldmodel and ../duck too
#   docker run --rm -p 127.0.0.1:8060:8060 -v $PWD/control/robots.example:/config/robots:ro -v mc-state:/state mission-control:local
#
# `make`'s control-up / control-down wrap control/compose.yml. Configuration (the robot files) and data (the SQLite store, the gates'
# logs) come in by volumes, the listen address and folders by MC_* variables; nothing is tied to a host. Robots are reached over the
# network, never through a device on this host. The API has no login by default: publish the port on loopback (as above) or on the
# tailnet's address, never on a public interface (RFC-0014 §3.9); `--require-tokens` adds per-client tokens.
#
# The versions are control/uv.lock's, installed with `uv sync --frozen`. The gate (RFC-0017) is a library (libs/gate) and the
# duck package depends on the run format: both are path sources in control/pyproject.toml, so the three folders sit side by side
# as they do in the repository, and the two are installed editable from there.

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY libs/runfile/pyproject.toml ./libs/runfile/pyproject.toml
COPY libs/runfile/src ./libs/runfile/src
COPY libs/gate/pyproject.toml ./libs/gate/pyproject.toml
COPY libs/gate/src ./libs/gate/src
COPY libs/worldmodel/pyproject.toml ./libs/worldmodel/pyproject.toml
COPY libs/worldmodel/src ./libs/worldmodel/src
COPY duck/pyproject.toml ./duck/pyproject.toml
COPY duck/src ./duck/src
COPY control/pyproject.toml control/uv.lock ./control/
COPY control/src ./control/src
RUN cd control && uv sync --frozen --no-dev \
 && mission-control serve --help >/dev/null

ENV MC_ROBOTS=/config/robots MC_STATE=/state MC_HOST=0.0.0.0 MC_PORT=8060 PYTHONUNBUFFERED=1
RUN mkdir -p /config/robots /state
VOLUME /state
EXPOSE 8060
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8060/api/v1/health', timeout=2)"
CMD ["mission-control", "serve"]
