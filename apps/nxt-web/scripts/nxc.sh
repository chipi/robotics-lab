#!/usr/bin/env bash
# Compile an NXC program to a .rxe the NXT can run, using the nbc compiler in Docker.
#
#   scripts/nxc.sh programs/first.nxc          # -> build/first.rxe
#
# Upload and run it from the web UI (Programs tab), or: uv run nxt-push build/first.rxe
set -euo pipefail

IMAGE=nxt-lab-nbc:1
here="$(cd "$(dirname "$0")/.." && pwd)"

if [ $# -ne 1 ] || [ ! -f "$1" ]; then
  echo "usage: $0 path/to/program.nxc" >&2
  exit 2
fi
src="$(realpath "$1")"
case "$src" in
  "$here"/*) ;;
  *) echo "program must be inside $here" >&2; exit 2 ;;
esac

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build -t "$IMAGE" "$here/toolchain"
fi

name="$(basename "$src" .nxc)"
mkdir -p "$here/build"
docker run --rm -u "$(id -u):$(id -g)" -v "$here:/src" -w /src "$IMAGE" \
  -Z2 -sm- -I="$(dirname "${src#"$here"/}")" -O="build/$name.rxe" "${src#"$here"/}"
echo "built build/$name.rxe ($(stat -c %s "$here/build/$name.rxe") bytes)"
