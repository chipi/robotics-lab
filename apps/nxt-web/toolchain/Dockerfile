# NXC/NBC compiler for the LEGO NXT, from Debian's own package. Only compiles; uploading
# to the brick is done by nxt-python on the host, so the container needs no USB access.
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
RUN apt-get update \
 && apt-get install -y --no-install-recommends nbc=1.2.1.r4+dfsg-14 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
ENTRYPOINT ["nbc"]
