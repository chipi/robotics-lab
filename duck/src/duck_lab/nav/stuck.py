"""Stuck detection (RFC-0008 §7, the operator 2026-11-17: "the navigator must notice it is stuck — walking, the depth
ahead not changing — whatever the cause").

What a stuck walk looks like in the recordings (challenge 16's first build, ch16-s1 2026-11-17, at a 1.7 cm bar): the
duck commanded 0.3 m/s for 15 s, the belief advanced 1-2 cm a second (the truth 0.5 cm), until the stall rule
(15 s without getting closer) ended the leg. The view ahead was no help: its central range swung by hundreds of mm with
the head's bob. So the signal is the travel: over WINDOW_S of unbroken walking, the belief went less than MOVED_MAX_M,
where walking at 0.3 m/s goes ~0.39 m and a tight arc ~0.24 m.

Pure: StuckWatch.update(t, walking, xy) with the belief's position: the travel is the window's net displacement (summed
steps add the pose's 10 Hz jitter: several cm in 3 s standing still).
"""

import math
from collections import deque

WINDOW_S = 3.0        # unbroken walking watched
MOVED_MAX_M = 0.05    # less travel than this over the window is stuck
MIN_SAMPLES = 10      # samples in the window before a verdict


class StuckWatch:
    def __init__(self, window_s: float = WINDOW_S, moved_max_m: float = MOVED_MAX_M):
        self.window_s, self.moved_max_m = window_s, moved_max_m
        self.samples = deque()

    def reset(self) -> None:
        self.samples.clear()

    def update(self, t: float, walking: bool, xy: tuple) -> dict | None:
        """One sample: walking (a forward command), the belief's position. Returns the evidence when
        stuck ({"moved_m", "seconds"}), else None. Not walking clears the window: only unbroken walking counts."""
        if not walking:
            self.samples.clear()
            return None
        self.samples.append((t, xy))
        while self.samples and t - self.samples[0][0] > self.window_s:
            self.samples.popleft()
        if len(self.samples) < MIN_SAMPLES or t - self.samples[0][0] < self.window_s * 0.9:
            return None
        moved = math.dist(self.samples[-1][1], self.samples[0][1])
        if moved < self.moved_max_m:
            return {"moved_m": round(moved, 3), "seconds": round(t - self.samples[0][0], 2)}
        return None
