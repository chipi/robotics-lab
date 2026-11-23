"""The last minute's alarms per robot, kept from the event bus (RFC-0023 D5), so a page opened after an alarm still knows it: the robot's view
carries the worst alarm overall and the worst one per joint, each with its time."""

import threading

WINDOW_S = 60
SEVERITIES = ["info", "minor", "major", "critical"]


def _rank(entry: dict) -> int:
    s = entry["anomaly"].get("severity")
    return SEVERITIES.index(s) if s in SEVERITIES else -1


class RecentAlarms:
    def __init__(self, wall):
        self._wall = wall
        self._by_robot: dict = {}
        self._lock = threading.Lock()

    def on_event(self, event: dict) -> None:
        if event.get("kind") != "anomaly" or not event.get("robot"):
            return
        entry = {"at": event["t"], "goal_run": event.get("goal_run"), "watch": event.get("watch"), "anomaly": event.get("anomaly") or {}}
        with self._lock:
            kept = self._by_robot.setdefault(event["robot"], [])
            kept.append(entry)
            self._prune(kept)

    def _prune(self, kept: list) -> None:
        cut = self._wall() - WINDOW_S
        kept[:] = [e for e in kept if e["at"] >= cut]

    def view(self, robot: str) -> dict:
        with self._lock:
            kept = self._by_robot.get(robot, [])
            self._prune(kept)
            entries = list(kept)
        worst, joints = None, {}
        for e in entries:
            if worst is None or _rank(e) >= _rank(worst):
                worst = e
            joint = (e["anomaly"].get("values") or {}).get("joint")
            if isinstance(joint, str) and (joint not in joints or _rank(e) >= _rank(joints[joint])):
                joints[joint] = e
        return {"window_s": WINDOW_S, "worst": worst, "joints": joints}
