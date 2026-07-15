from __future__ import annotations

from collections import deque
from dataclasses import asdict

import numpy as np

from neveludens.perception import PerceptionState


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
        self.last_action_signature = None
        self.last_skill_step: dict[str, int] = {}
        self.skill_counts: dict[str, int] = {}

    def update_perception(self, perception: PerceptionState) -> None:
        self.frames.append(asdict(perception))

        self.low_motion_streak = self.low_motion_streak + 1 if perception.is_low_motion else 0
        self.dark_streak = self.dark_streak + 1 if perception.is_dark else 0
        self.loading_streak = self.loading_streak + 1 if perception.likely_loading else 0
        self.static_streak = self.static_streak + 1 if perception.likely_static_screen else 0
        self.menu_like_streak = self.menu_like_streak + 1 if perception.likely_menu_or_overlay else 0

    def update_actions(self, actions: list[dict]) -> tuple:
        signature = action_signature(actions)
        self.action_signatures.append(signature)

        if signature == self.last_action_signature:
            self.repeated_action_streak += 1
        else:
            self.repeated_action_streak = 0
        self.last_action_signature = signature
        return signature

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
            "skill_counts": dict(self.skill_counts),
        }
