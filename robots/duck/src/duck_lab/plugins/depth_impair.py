"""The simulated depth sensor's impairments (docs/wip/RESEARCH-R1-R2.md, R2): a stage on the frames the navigator reads, in the
simulator only. Pollen's simulator reports clean returns (noise only); the real sensor's are not. The defaults are NVIDIA's for
their Microduck avoidance task (isaac-sim/IsaacLab, branch exp/microduck, commit 802b8d5,
isaaclab_tasks/contrib/microduck_obstacle/sensors.py:27-78): a return nearer than 0.12 m is no return (`minimum_distance`, checked
before and after the error is added), an episode's bias U(-0.02, 0.02) m and scale U(0.98, 1.02), a zone's own bias U(-0.01, 0.01) m
for the episode, an invalid zone 3 % of zones per frame, a dropped frame 2 % of acquisitions, and a latency of 0 or 1 acquired
frames per episode. NVIDIA calls these priors, not measurements (sensors.py:55-78): a stress range until the real duck's own is
measured (R8). Not here: noise (the simulator has its own), floor validity far out, the floor-edge column, the mount's spread.

An episode is one stage: a run. Everything drawn for it (bias, scale, the zone biases, the latency) comes from the seed at
construction, the frames' own draws (invalid zones, drops) from the same generator after, so one seed and one stream of frames give one
output. Off, the stage hands every frame on as it is.

An invalid zone reads distance 0 with `invalid_status`, which is neither a return nor the sensor's "no target" (255): the navigator
reads a zone with no target below the floor line as a drop, and an impaired zone is not evidence of one. The plugin is told the status
(`Tof8x8.unknown_status`) and skips such a zone in the cliff check.
"""

import random
from collections import deque

SIM = "sim"
KEYS = ("enabled", "seed", "min_range_m", "bias_m", "scale", "zone_bias_m", "invalid_zone_p", "frame_dropout_p", "latency_frames_max",
        "invalid_status")


class DepthImpairment:
    def __init__(self, cfg: dict | None, valid=(5, 9), no_target: int = 255, range_m: float = 4.0, zones: int = 64):
        cfg = {k: v for k, v in (cfg or {}).items() if k in KEYS}
        self.cfg = cfg
        self.enabled = bool(cfg.get("enabled", False))
        self.valid, self.no_target, self.range_m, self.zones = set(valid), no_target, range_m, zones
        self.seed = int(cfg.get("seed", 0))
        self.invalid_status = int(cfg.get("invalid_status", 0))
        if self.enabled:
            if self.invalid_status in self.valid or self.invalid_status == no_target:
                raise ValueError(f"invalid_status {self.invalid_status}: not a return's status {sorted(self.valid)} and not "
                                 f"no-target {no_target}")
        self.min_range_m = float(cfg.get("min_range_m", 0.0))
        self.invalid_zone_p = float(cfg.get("invalid_zone_p", 0.0))
        self.frame_dropout_p = float(cfg.get("frame_dropout_p", 0.0))
        self._rng = random.Random(self.seed)
        r = self._rng
        bias, scale, zone = (float(cfg.get(k, 0.0)) for k in ("bias_m", "scale", "zone_bias_m"))
        self.episode = {"bias_m": r.uniform(-bias, bias), "scale": r.uniform(1.0 - scale, 1.0 + scale),
                        "zone_bias_m": [r.uniform(-zone, zone) for _ in range(zones)],
                        "latency_frames": r.randint(0, int(cfg.get("latency_frames_max", 0)))}
        self._queue = deque()
        self.frames = self.dropped = 0

    @classmethod
    def from_profile(cls, profile, override: dict | None = None) -> "DepthImpairment":
        """The stage the profile's `sensors.tof8x8.impairment` describes, over which a run's own settings (a dict) lay. Only the
        simulator's profile has the block; asking for it on any other environment is an error, not a quiet no-op."""
        t = profile.sensors.tof8x8
        block = t.get("impairment") or {}
        cfg = {**block, **(override or {})}
        if cfg.get("enabled") and profile.variant != SIM:
            raise ValueError(f"depth impairments are the simulator's: the {profile.variant!r} profile's frames are not impaired")
        return cls(cfg, valid=t.valid_status, no_target=t.no_target_status, range_m=t.range_m, zones=t.rows * t.cols)

    def _invalid(self, mm: list, status: list, i: int) -> None:
        mm[i], status[i] = 0, self.invalid_status

    def apply(self, frame: dict) -> dict | None:
        """The frame as the sensor would have delivered it, or None: nothing arrives now (dropped, or still on its way)."""
        if not self.enabled:
            return frame
        self.frames += 1
        r, ep = self._rng, self.episode
        if r.random() < self.frame_dropout_p:
            self.dropped += 1
            return None
        mm, status = list(frame["distance_mm"]), list(frame["status"])
        for i in range(len(mm)):
            if status[i] not in self.valid or mm[i] <= 0:
                continue
            m = mm[i] / 1000.0
            if m < self.min_range_m:
                self._invalid(mm, status, i)
                continue
            m = m * ep["scale"] + ep["bias_m"] + ep["zone_bias_m"][i]
            if m < self.min_range_m or m > self.range_m or r.random() < self.invalid_zone_p:
                self._invalid(mm, status, i)
            else:
                mm[i] = round(m * 1000)
        self._queue.append({**frame, "distance_mm": mm, "status": status})
        return self._queue.popleft() if len(self._queue) > ep["latency_frames"] else None

    def record(self) -> dict:
        """What a run says about it: the setting, the seed, the numbers in force, what was drawn for the episode, and what it did."""
        out = {"enabled": self.enabled, "seed": self.seed}
        if self.enabled:
            ep = self.episode
            out.update({k: self.cfg[k] for k in KEYS if k in self.cfg and k not in out})
            out["invalid_status"] = self.invalid_status
            out["episode"] = {"bias_m": round(ep["bias_m"], 5), "scale": round(ep["scale"], 5), "latency_frames": ep["latency_frames"]}
            out["frames"], out["dropped"] = self.frames, self.dropped
        return out
