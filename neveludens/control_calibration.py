from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from neveludens.memory import movement_summary
from neveludens.perception import PerceptionState


AXIS_LIMIT = 32767
STRONG_INPUT = 18000
WEAK_INPUT = 13000
CALIBRATED_FLOOR = 18000


@dataclass
class DirectionStats:
    attempts: int = 0
    successes: int = 0
    failures: int = 0

    @property
    def score(self) -> float:
        if self.attempts == 0:
            return 0.5
        return (self.successes + 1.0) / (self.attempts + 2.0)


class AutomaticControlCalibration:
    """Conservative passive calibration based on action-to-image response."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.pending: dict | None = None
        self.direction_stats = {
            name: DirectionStats() for name in ("left", "right", "up", "down")
        }
        self.axis_samples = {
            "horizontal": {"weak_failures": 0, "strong_successes": 0},
            "vertical": {"weak_failures": 0, "strong_successes": 0},
        }
        self.horizontal_floor = 0
        self.vertical_floor = 0

    def observe(self, perception: PerceptionState) -> None:
        if not self.enabled or not self.pending or not self.pending.get("expected"):
            self.pending = None
            return

        pending = self.pending
        self.pending = None
        if perception.likely_loading or perception.likely_menu_or_overlay:
            return

        direction = pending.get("direction")
        if direction not in self.direction_stats:
            return

        had_result = not perception.is_low_motion
        stats = self.direction_stats[direction]
        stats.attempts += 1
        if had_result:
            stats.successes += 1
        else:
            stats.failures += 1

        axis = "horizontal" if direction in {"left", "right"} else "vertical"
        magnitude = int(pending.get("magnitude", 0))
        samples = self.axis_samples[axis]
        if magnitude <= WEAK_INPUT and not had_result:
            samples["weak_failures"] += 1
        elif magnitude >= STRONG_INPUT and had_result:
            samples["strong_successes"] += 1

        if samples["weak_failures"] >= 3 and samples["strong_successes"] >= 3:
            if axis == "horizontal":
                self.horizontal_floor = CALIBRATED_FLOOR
            else:
                self.vertical_floor = CALIBRATED_FLOOR

    def apply(self, actions: list[dict]) -> int:
        if not self.enabled:
            return 0

        changed = 0
        for action in actions:
            for axis, floor in (
                ("AXIS_LEFTX", self.horizontal_floor),
                ("AXIS_LEFTY", self.vertical_floor),
            ):
                if floor <= 0:
                    continue
                raw = action.get(axis, 0)
                value = int(raw[0]) if isinstance(raw, (np.ndarray, list)) else int(raw)
                if 0 < abs(value) < floor:
                    action[axis] = np.array(
                        [min(AXIS_LIMIT, floor) if value > 0 else -min(AXIS_LIMIT, floor)],
                        dtype=np.int64,
                    )
                    changed += 1
        return changed

    def record_executed_actions(self, actions: list[dict]) -> None:
        if self.enabled:
            self.pending = movement_summary(actions)

    def ranked_escape_directions(self, failed_direction: str | None) -> list[str]:
        directions = list(self.direction_stats)
        directions.sort(
            key=lambda name: (
                name == failed_direction,
                -self.direction_stats[name].score,
                -self.direction_stats[name].attempts,
            )
        )
        return directions

    def snapshot(self) -> dict:
        if not self.enabled:
            return {}
        return {
            "horizontal_floor": self.horizontal_floor,
            "vertical_floor": self.vertical_floor,
            "directions": {
                name: {
                    "attempts": stats.attempts,
                    "successes": stats.successes,
                    "failures": stats.failures,
                    "score": round(stats.score, 3),
                }
                for name, stats in self.direction_stats.items()
            },
        }
