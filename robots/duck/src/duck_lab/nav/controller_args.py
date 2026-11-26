"""The navigator's own command-line options for the local controller (RFC-0025 section 3.7): `--local-controller learned --model PATH`,
which the runner hands on. The runner has its own copy of these (labrunner.remote); the navigator never imports the runner."""

from pathlib import Path


def add_args(ap) -> None:
    ap.add_argument("--local-controller", choices=("rules", "learned"), default=None,
                    help="rules (the profile's rules@1, the default) or learned (an ONNX model, with --model); the simulator only")
    ap.add_argument("--model", type=Path, metavar="PATH", default=None, help="the ONNX model of --local-controller learned")


def setting(args, ap) -> dict | None:
    """{"name": "learned", "model": path} for the options, None for the profile's own; a usage error (exit 2) for a model with no
    learned controller, a learned one with no model or one that is not a file, or for the real duck's variant."""
    if args.local_controller != "learned":
        if args.model is not None:
            ap.error("--model is the model of --local-controller learned")
        return None
    if args.model is None:
        ap.error("--local-controller learned needs --model PATH")
    if not args.model.is_file():
        ap.error(f"--model {args.model}: not a file")
    if getattr(args, "variant", "sim") == "real":
        ap.error("--local-controller learned is the simulator's for now: the real duck refuses it (RFC-0025 R8)")
    return {"name": "learned", "model": str(args.model)}
