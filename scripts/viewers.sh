#!/usr/bin/env bash
# Both viewers on this machine, on loopback only, with every recorded run (ADR-0002).
#
#   scripts/viewers.sh up      # convert runs, start Lichtblick (Docker) and Rerun (web viewer)
#   scripts/viewers.sh down    # stop both (only what this script started)
#
# Runs: nxt/runs/*.mcap and duck/runs/*.mcap. From another machine:
#   ssh -N -L 8090:127.0.0.1:8090 -L 9090:127.0.0.1:9090 -L 9876:127.0.0.1:9876 <this host>
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
view="$here/.viewers"
duck="$here/duck/.venv/bin"
container=robotics-lichtblick
lichtblick_image=ghcr.io/lichtblick-suite/lichtblick:latest
LICHTBLICK_PORT="${LICHTBLICK_PORT:-8090}"
RERUN_PORT="${RERUN_PORT:-9090}"
RERUN_GRPC_PORT="${RERUN_GRPC_PORT:-9876}"

down() {
    docker stop "$container" >/dev/null 2>&1 && echo "stopped Lichtblick" || echo "Lichtblick was not running"
    if [ -f "$view/rerun.pid" ]; then
        pid="$(cat "$view/rerun.pid")"
        if ps -o args= -p "$pid" 2>/dev/null | grep -q "rerun"; then
            kill "$pid" && echo "stopped Rerun ($pid)"
        else
            echo "Rerun was not running"
        fi
        rm -f "$view/rerun.pid"
    else
        echo "Rerun was not running"
    fi
}

up() {
    [ -x "$duck/duck-to-rerun" ] || { echo "run: cd duck && uv sync" >&2; exit 2; }
    # The binary itself, not the Python launcher: the launcher starts it and exits, so its pid
    # would not be the server's.
    rerun_bin="$(ls "$here"/duck/.venv/lib/python*/site-packages/rerun_cli/rerun 2>/dev/null | head -1)"
    [ -x "$rerun_bin" ] || { echo "no Rerun binary in duck/.venv: cd duck && uv sync" >&2; exit 2; }
    down >/dev/null
    rm -rf "$view/mcap" "$view/rrd"
    mkdir -p "$view/mcap" "$view/rrd"
    shopt -s nullglob
    runs=("$here"/nxt/runs/*.mcap "$here"/duck/runs/*.mcap)
    [ ${#runs[@]} -gt 0 ] || { echo "no runs yet: record one in nxt-web or with duck-record" >&2; exit 2; }
    for f in "${runs[@]}"; do
        cp "$f" "$view/mcap/"
        "$duck/duck-to-rerun" "$f" -o "$view/rrd/$(basename "$f" .mcap).rrd" 2>/dev/null | sed 's|^|  |'
    done
    chmod -R a+rX "$view/mcap"

    docker run -d --rm --name "$container" -p "127.0.0.1:$LICHTBLICK_PORT:8080" \
        -v "$view/mcap:/src/runs:ro" "$lichtblick_image" >/dev/null
    nohup "$rerun_bin" "$view"/rrd/*.rrd --web-viewer --bind 127.0.0.1 \
        --web-viewer-port "$RERUN_PORT" --port "$RERUN_GRPC_PORT" >"$view/rerun.log" 2>&1 &
    echo $! >"$view/rerun.pid"
    sleep 3
    if ! kill -0 "$(cat "$view/rerun.pid")" 2>/dev/null; then
        echo "Rerun did not start:" >&2
        grep -E "WARN|ERROR" "$view/rerun.log" | tail -3 >&2
        rm -f "$view/rerun.pid"
        exit 1
    fi

    echo
    echo "Rerun (timeline: choose 'recorded'):"
    echo "  http://localhost:$RERUN_PORT/?url=rerun%2Bhttp%3A%2F%2Flocalhost%3A$RERUN_GRPC_PORT%2Fproxy"
    echo "Lichtblick (3D panel: display frame 'world'):"
    for f in "$view"/mcap/*.mcap; do
        echo "  http://localhost:$LICHTBLICK_PORT/?ds=remote-file&ds.url=http://localhost:$LICHTBLICK_PORT/runs/$(basename "$f")"
    done
}

case "${1:-}" in
    up) up ;;
    down) down ;;
    *) echo "usage: $0 up|down" >&2; exit 2 ;;
esac
