from __future__ import annotations

from collections import deque
from dataclasses import asdict

import numpy as np

from neveludens.perception import PerceptionState


MOVEMENT_INTENT_THRESHOLD = 6000


def movement_summary(actions: list[dict]) -> dict:
    """Summarize left-stick movement that will actually reach the game."""
    if not actions:
        return {"expected": False, "direction": None, "magnitude": 0, "active_fraction": 0.0}

    xs = [action_value(action, "AXIS_LEFTX") for action in actions]
    ys = [action_value(action, "AXIS_LEFTY") for action in actions]
    active = [
        max(abs(x), abs(y)) >= MOVEMENT_INTENT_THRESHOLD
        for x, y in zip(xs, ys)
    ]
    active_count = sum(active)
    if active_count == 0:
        return {"expected": False, "direction": None, "magnitude": 0, "active_fraction": 0.0}

    active_x = [x for x, enabled in zip(xs, active) if enabled]
    active_y = [y for y, enabled in zip(ys, active) if enabled]
    mean_x = int(sum(active_x) / len(active_x))
    mean_y = int(sum(active_y) / len(active_y))
    magnitude = int(
        sum(max(abs(x), abs(y)) for x, y in zip(active_x, active_y)) / len(active_x)
    )
    net_magnitude = max(abs(mean_x), abs(mean_y))
    coherent_direction = net_magnitude >= magnitude * 0.4
    if abs(mean_x) >= abs(mean_y):
        direction = "right" if mean_x >= 0 else "left"
    else:
        direction = "down" if mean_y >= 0 else "up"

    return {
        "expected": active_count >= max(1, len(actions) // 3) and coherent_direction,
        "direction": direction if coherent_direction else None,
        "magnitude": magnitude,
        "active_fraction": active_count / len(actions),
    }


def action_value(action: dict, name: str, default: int = 0) -> int:
    value = action.get(name, default)
    if isinstance(value, np.ndarray):
        return int(value[0])
    if isinstance(value, list):
        return int(value[0]) if value else default
    return int(value)


def action_signature(actions: list[dict]) -> tuple:
    if not actions:
        return ("empty",)

    pressed = {}
    axis_totals = {
        "AXIS_LEFTX": 0,
        "AXIS_LEFTY": 0,
        "AXIS_RIGHTX": 0,
        "AXIS_RIGHTY": 0,
    }

    button_names = [
        "WEST",
        "SOUTH",
        "EAST",
        "NORTH",
        "DPAD_UP",
        "DPAD_DOWN",
        "DPAD_LEFT",
        "DPAD_RIGHT",
        "LEFT_SHOULDER",
        "RIGHT_SHOULDER",
        "START",
        "BACK",
    ]

    for action in actions:
        for button in button_names:
            pressed[button] = pressed.get(button, 0) + int(bool(action.get(button, 0)))
        for axis in axis_totals:
            axis_totals[axis] += action_value(action, axis)

    count = max(1, len(actions))
    axis_bins = tuple(round((axis_totals[axis] / count) / 6000) for axis in axis_totals)
    button_bins = tuple(sorted(name for name, value in pressed.items() if value >= count * 0.4))
    return axis_bins + button_bins


class TemporalMemory:
    def __init__(self, max_steps: int = 240):
        self.frames = deque(maxlen=max_steps)
        self.action_signatures = deque(maxlen=max_steps)
        self.events = deque(maxlen=200)
        self.low_motion_streak = 0
        self.dark_streak = 0
        self.loading_streak = 0
        self.static_streak = 0
        self.menu_like_streak = 0
        self.repeated_action_streak = 0
        self.repeated_movement_streak = 0
        self.movement_attempt_streak = 0
        self.movement_failure_streak = 0
        self.movement_success_streak = 0
        self.last_movement_direction = None
        self.last_failed_direction = None
        self.last_movement_had_result = None
        self.pending_movement = None
        self.last_action_signature = None
        self.last_movement_signature = None
        self.last_skill_step: dict[str, int] = {}
        self.skill_counts: dict[str, int] = {}

    def update_perception(self, perception: PerceptionState) -> None:
        self.frames.append(asdict(perception))

        self.low_motion_streak = self.low_motion_streak + 1 if perception.is_low_motion else 0
        self.dark_streak = self.dark_streak + 1 if perception.is_dark else 0
        self.loading_streak = self.loading_streak + 1 if perception.likely_loading else 0
        self.static_streak = self.static_streak + 1 if perception.likely_static_screen else 0
        self.menu_like_streak = self.menu_like_streak + 1 if perception.likely_menu_or_overlay else 0

        pending = self.pending_movement
        self.pending_movement = None
        if not pending or not pending.get("expected"):
            self.movement_attempt_streak = 0
            self.movement_failure_streak = max(0, self.movement_failure_streak - 1)
            self.last_movement_had_result = None
            return

        self.last_movement_direction = pending.get("direction")
        if perception.likely_loading or perception.likely_menu_or_overlay:
            self.last_movement_had_result = None
            return

        self.movement_attempt_streak += 1
        movement_had_result = not perception.is_low_motion
        self.last_movement_had_result = movement_had_result
        if movement_had_result:
            self.movement_success_streak += 1
            self.movement_failure_streak = 0
        else:
            self.movement_success_streak = 0
            self.movement_failure_streak += 1
            self.last_failed_direction = pending.get("direction")

    def update_actions(self, actions: list[dict]) -> tuple:
        signature = action_signature(actions)
        self.action_signatures.append(signature)

        if signature == self.last_action_signature:
            self.repeated_action_streak += 1
        else:
            self.repeated_action_streak = 0
        self.last_action_signature = signature

        movement = movement_summary(actions)
        movement_signature = movement.get("direction") if movement.get("expected") else None
        if movement_signature is not None and movement_signature == self.last_movement_signature:
            self.repeated_movement_streak += 1
        elif movement_signature is not None:
            self.repeated_movement_streak = 0
        else:
            self.repeated_movement_streak = 0
        self.last_movement_signature = movement_signature
        return signature

    def record_executed_actions(self, actions: list[dict]) -> dict:
        self.pending_movement = movement_summary(actions)
        return dict(self.pending_movement)

    def can_use_skill(self, name: str, step: int, cooldown_steps: int) -> bool:
        return step - self.last_skill_step.get(name, -cooldown_steps) >= cooldown_steps

    def mark_skill(self, name: str, step: int, reason: str) -> None:
        self.last_skill_step[name] = step
        self.skill_counts[name] = self.skill_counts.get(name, 0) + 1
        self.events.append({"step": step, "type": "skill", "name": name, "reason": reason})

    def add_event(self, step: int, kind: str, message: str) -> None:
        self.events.append({"step": step, "type": kind, "message": message})

    def snapshot(self) -> dict:
        return {
            "low_motion_streak": self.low_motion_streak,
            "dark_streak": self.dark_streak,
            "loading_streak": self.loading_streak,
            "static_streak": self.static_streak,
            "menu_like_streak": self.menu_like_streak,
            "repeated_action_streak": self.repeated_action_streak,
            "repeated_movement_streak": self.repeated_movement_streak,
            "movement_attempt_streak": self.movement_attempt_streak,
            "movement_failure_streak": self.movement_failure_streak,
            "movement_success_streak": self.movement_success_streak,
            "last_movement_direction": self.last_movement_direction,
            "last_failed_direction": self.last_failed_direction,
            "last_movement_had_result": self.last_movement_had_result,
            "skill_counts": dict(self.skill_counts),
        }
