# The NXT web UI (nxt-web) as an image, to run on any Linux machine near the robot.
#
#   docker build -f apps/nxt-web/Dockerfile -t robotics-lab/nxt-web .     # from the repository root: it installs libs/runfile too
#   docker run --rm -p 127.0.0.1:8000:8000 -v nxt-data:/data -v /work/robotics-lab/data:/observatory -e OBSERVATORY_DATA=/observatory \
#     --device /dev/bus/usb robotics-lab/nxt-web                 # NXT over USB
#   docker run ... --device /dev/rfcomm0 robotics-lab/nxt-web     # NXT over Bluetooth (bound on the host)
#   docker run ... robotics-lab/nxt-web nxt-web --fake --host 0.0.0.0   # no robot
#
# Recordings are also written as Observatory runs (ADR-0013) into $OBSERVATORY_DATA, which `make nxt-image-run` mounts from the
# host's lab data folder; without it they go to /data/miniview, in the nxt-data volume.
# `make nxt-image` / `make nxt-image-run` wrap these. The UI has no login: publish the port on
# 127.0.0.1 (as above) and reach it through an ssh tunnel, not on the open network.
#
# It runs as root inside the container: talking to the brick needs the USB or rfcomm device node,
# which the host's udev rule grants to the logged-in user, not to a container user. What it writes
# into a mounted OBSERVATORY_DATA goes to NXT_DATA_OWNER (uid:gid), which `make nxt-image-run` sets to
# the host user; without it those files are root's.

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

RUN apt-get update \
 && apt-get install -y --no-install-recommends libusb-1.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# pip does not read [tool.uv.sources]: install the run format (libs/runfile) first, then nxt-web finds `runfile` satisfied
COPY libs/runfile/pyproject.toml ./libs/runfile/pyproject.toml
COPY libs/runfile/src ./libs/runfile/src
COPY apps/nxt-web/pyproject.toml apps/nxt-web/README.md ./apps/nxt-web/
COPY apps/nxt-web/src ./apps/nxt-web/src
RUN pip install --no-cache-dir ./libs/runfile \
 && pip install --no-cache-dir ./apps/nxt-web \
 && nxt-web --help >/dev/null

ENV NXT_LAB_DATA=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000

CMD ["nxt-web", "--host", "0.0.0.0", "--port", "8000"]
