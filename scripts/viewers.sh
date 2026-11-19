#!/usr/bin/env bash
# Both viewers on this machine, on loopback only, with every recorded run (ADR-0002).
#
#   scripts/viewers.sh up      # convert runs, start Lichtblick (Docker) and Rerun (web viewer)
#   scripts/viewers.sh down    # stop both (only what this script started)
#
# Runs: the format 2 runs of the lab data folder (MINIVIEW_DATA, default /work/robotics-lab/data:
# data/runs/<robot>/<scene>/<run>/run.mcap, the finished ones; the NXT's recordings are there, ADR-0013) and the duck's own
# robots/duck/runs/*.mcap. From another machine:
#   ssh -N -L 8090:127.0.0.1:8090 -L 9090:127.0.0.1:9090 -L 9876:127.0.0.1:9876 <this host>
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
view="$here/.viewers"
data="${MINIVIEW_DATA:-/work/robotics-lab/data}"
duck="$here/robots/duck/.venv/bin"
container=robotics-lichtblick
# pinned by digest, as in apps/observatory/tests/test_run_compat.py (how to bump it: ADR-0007 "Compatibility")
lichtblick_image=ghcr.io/lichtblick-suite/lichtblick@sha256:25333a8f57737c8c5866abf75670b8dcf2ed6c2cb5ce3d64f3c63f210a5177e9
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
    [ -x "$duck/duck-to-rerun" ] || { echo "run: cd robots/duck && uv sync" >&2; exit 2; }
    # The binary itself, not the Python launcher: the launcher starts it and exits, so its pid
    # would not be the server's.
    rerun_bin="$(ls "$here"/robots/duck/.venv/lib/python*/site-packages/rerun_cli/rerun 2>/dev/null | head -1)"
    [ -x "$rerun_bin" ] || { echo "no Rerun binary in robots/duck/.venv: cd robots/duck && uv sync" >&2; exit 2; }
    down >/dev/null
    rm -rf "$view/mcap" "$view/rrd"
    mkdir -p "$view/mcap" "$view/rrd"
    shopt -s nullglob
    v2_runs=("$data"/runs/*/*/*/run.mcap)
    duck_runs=("$here"/robots/duck/runs/*.mcap)
    [ $((${#v2_runs[@]} + ${#duck_runs[@]})) -gt 0 ] || { echo "no runs yet in $data/runs or robots/duck/runs: record one in nxt-web or with duck-record" >&2; exit 2; }
    # format 2 (ADR-0007): the protobuf channels decode in Rerun with its protobuf decoder; Lichtblick reads the file as it is
    for f in "${v2_runs[@]}"; do
        rel="${f#"$data"/runs/}"                      # robot/scene/run/run.mcap
        name="$(dirname "$rel" | tr / -)"             # robot-scene-run
        cp "$f" "$view/mcap/$name.mcap"
        "$rerun_bin" mcap convert -d protobuf --disable-raw-fallback "$f" -o "$view/rrd/$name.rrd" >/dev/null 2>&1 && echo "  $name.rrd"
    done
    for f in "${duck_runs[@]}"; do
        cp "$f" "$view/mcap/"
        "$duck/duck-to-rerun" "$f" -o "$view/rrd/$(basename "$f" .mcap).rrd" 2>/dev/null | sed 's|^|  |'
    done
    chmod -R a+rX "$view/mcap"
    # The brain's world model for the newest duck runs (VIEWER_RUNS, default 4): duck-world.
    for d in $(ls -1dt "$here"/robots/duck/runs/*/ 2>/dev/null | head -"${VIEWER_RUNS:-4}"); do
        [ -f "$d/ticks.jsonl" ] || continue
        "$duck/duck-world" "$d" -o "$view/rrd/world-$(basename "$d").rrd" 2>/dev/null | sed 's|^|  |'
    done

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
    echo "Rerun (timeline: 'recorded'; the world-* recordings: 'run'):"
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
