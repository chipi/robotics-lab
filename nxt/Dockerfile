# The NXT web UI (nxt-web) as an image, to run on any Linux machine near the robot.
#
#   docker build -t robotics-lab/nxt-web nxt
#   docker run --rm -p 127.0.0.1:8000:8000 -v nxt-data:/data \
#     --device /dev/bus/usb robotics-lab/nxt-web                 # NXT over USB
#   docker run ... --device /dev/rfcomm0 robotics-lab/nxt-web     # NXT over Bluetooth (bound on the host)
#   docker run ... robotics-lab/nxt-web nxt-web --fake --host 0.0.0.0   # no robot
#
# `make nxt-image` / `make nxt-image-run` wrap these. The UI has no login: publish the port on
# 127.0.0.1 (as above) and reach it through an ssh tunnel, not on the open network.
#
# It runs as root inside the container: talking to the brick needs the USB or rfcomm device node,
# which the host's udev rule grants to the logged-in user, not to a container user.

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

RUN apt-get update \
 && apt-get install -y --no-install-recommends libusb-1.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && nxt-web --help >/dev/null

ENV NXT_LAB_DATA=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000

CMD ["nxt-web", "--host", "0.0.0.0", "--port", "8000"]
