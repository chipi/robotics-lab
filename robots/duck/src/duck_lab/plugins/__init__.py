"""A robot's capability plugins, loaded by the names its profile gives (RFC-0020 §4, RFC-0018's adapters-by-name).

    plugins.load(profile)      -> {"locomotion": DuckWalk(profile), "range_sensing": Tof8x8(profile), ...}

The profile's `plugins` block maps each interface to `name@version`; `REGISTRY` maps those to this package's classes. A name or a
version this package does not have is an error naming it (a profile that asks for `duck-walk@2` is not the duck of this checkout).
Plugins are Python classes only (RFC-0020 §7, question 3); a process boundary is for a robot driven by another runtime.
"""

from duck_lab.plugins.duck_walk import DuckWalk
from duck_lab.plugins.duck_head import DuckHead
from duck_lab.plugins.mapd import Mapd
from duck_lab.plugins.tof8x8 import Tof8x8
from duck_lab.plugins.interfaces import Localisation, LocalController, Locomotion, Looking, RangeSensing
from duck_lab.plugins.rules import Rules

RULES = "rules@1"
REGISTRY = {"duck-walk@1": DuckWalk, "tof8x8@1": Tof8x8, "mapd@1": Mapd, "duck-head@1": DuckHead, "rules@1": Rules}
INTERFACES = {"locomotion": Locomotion, "range_sensing": RangeSensing, "localisation": Localisation, "looking": Looking,
              "local_controller": LocalController}


def load(profile) -> dict:
    """One instance of each interface's plugin the profile names, built from the profile (no I/O: sockets are opened by the
    navigator when it binds them)."""
    out = {}
    for interface, spec in profile.plugins.data.items():
        cls = REGISTRY.get(spec)
        if cls is None:
            raise LookupError(f"plugins.{interface}: no plugin {spec!r} (this package has {sorted(REGISTRY)})")
        plugin = cls(profile)
        if not isinstance(plugin, INTERFACES[interface]):
            raise TypeError(f"plugins.{interface}: {spec} is not a {INTERFACES[interface].__name__}")
        out[interface] = plugin
    return out


def local_controller(profile, setting: dict | None = None, tick_s: float = 0.1):
    """The run's local controller: the profile's (`rules@1` when it names none), or the override `{"name": "learned", "model": path}`
    (the simulator only; `learned` is imported here, so a run with no model never loads onnxruntime)."""
    if setting and setting.get("name", "rules") != "rules":
        if setting["name"] != "learned":
            raise LookupError(f"no local controller {setting['name']!r} (the overrides are rules and learned)")
        from duck_lab.plugins.learned import Learned
        return Learned(profile, setting["model"], tick_s)
    spec = profile.plugins.data.get("local_controller", "rules@1")
    cls = REGISTRY.get(spec)
    if cls is None or not isinstance(cls(profile), LocalController):
        raise LookupError(f"plugins.local_controller: no plugin {spec!r} (this package has {sorted(REGISTRY)})")
    return cls(profile)
