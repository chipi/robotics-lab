"""What every runner command takes: where its run goes (the Observatory's data folder, the scene, the run's name) and which
robot it runs (RFC-0022). The same options as the navigator's own tools (duck_lab.nav.runlog.add_args)."""

from pathlib import Path

from labrunner.robots import add_robot_arg


def add_args(ap) -> None:
    ap.add_argument("--miniview-data", type=Path, default=None,
                    help="the lab's data folder: the run is written there (format 2) while it runs; default $OBSERVATORY_DATA")
    ap.add_argument("--scene", default="apartment", help="the run's scene (default apartment)")
    ap.add_argument("--run", help="the run's name (default: the output folder's name)")
    add_robot_arg(ap)
