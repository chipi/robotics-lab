# Mission Control (RFC-0014 §3.13) as an image, to run on any of the operator's machines.
#
#   docker build -f control/Dockerfile -t mission-control:local .     # from the repository root: it installs ../viewer and ../duck too
#   docker run --rm -p 127.0.0.1:8060:8060 -v $PWD/control/robots.example:/config/robots:ro -v mc-state:/state mission-control:local
#
# `make`'s control-up / control-down wrap control/compose.yml. Configuration (the robot files) and data (the SQLite store, the gates'
# logs) come in by volumes, the listen address and folders by MC_* variables; nothing is tied to a host. Robots are reached over the
# network, never through a device on this host. The API has no login: publish the port on loopback (as above) or on the tailnet's
# address, never on a public interface (RFC-0014 §3.9).
#
# The gate (RFC-0017) is a library in the duck package, and the duck package depends on the viewer package: pip does not read
# [tool.uv.sources], so they are installed first, from the paths, and mission-control finds them satisfied.

FROM python:3.12-slim

WORKDIR /app
COPY viewer/pyproject.toml ./viewer/pyproject.toml
COPY viewer/src ./viewer/src
COPY duck/pyproject.toml ./duck/pyproject.toml
COPY duck/src ./duck/src
COPY control/pyproject.toml ./control/pyproject.toml
COPY control/src ./control/src
RUN pip install --no-cache-dir ./viewer \
 && pip install --no-cache-dir ./duck \
 && pip install --no-cache-dir ./control \
 && mission-control serve --help >/dev/null

ENV MC_ROBOTS=/config/robots MC_STATE=/state MC_HOST=0.0.0.0 MC_PORT=8060 PYTHONUNBUFFERED=1
RUN mkdir -p /config/robots /state
VOLUME /state
EXPOSE 8060
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8060/api/v1/health', timeout=2)"
CMD ["mission-control", "serve"]
