from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from neveludens.memory import TemporalMemory, action_value
from neveludens.perception import PerceptionState
from neveludens.profiles import GameProfile
from neveludens.control_calibration import AutomaticControlCalibration


DIRECTION_AXES = {
    "right": (25000, 0),
    "left": (-25000, 0),
    "up": (0, -25000),
    "down": (0, 25000),
}


def choose_escape_direction(
    memory: TemporalMemory,
    calibration: AutomaticControlCalibration | None,
    attempt: int,
) -> tuple[str, int, int]:
    failed = memory.last_failed_direction
    if calibration is not None and calibration.enabled:
        candidates = calibration.ranked_escape_directions(failed)
    else:
        alternatives = {
            "right": ["up", "down", "left"],
            "left": ["up", "down", "right"],
            "up": ["left", "right", "down"],
            "down": ["left", "right", "up"],
        }
        candidates = alternatives.get(failed, ["right", "left", "up", "down"])
    direction = candidates[attempt % len(candidates)]
    return direction, *DIRECTION_AXES[direction]

@dataclass
class SkillDecision:
    name: str
    reason: str
    changed_actions: int


def set_axis(action: dict, name: str, value: int) -> None:
    action[name] = np.array([int(value)], dtype=np.long)


def neutralize_action(action: dict) -> None:
    for name in ("AXIS_LEFTX", "AXIS_LEFTY", "AXIS_RIGHTX", "AXIS_RIGHTY"):
        set_axis(action, name, 0)
    for name in ("LEFT_TRIGGER", "RIGHT_TRIGGER"):
        set_axis(action, name, 0)
    for key in list(action.keys()):
        if key.startswith("_"):
            continue
        if key not in {"AXIS_LEFTX", "AXIS_LEFTY", "AXIS_RIGHTX", "AXIS_RIGHTY", "LEFT_TRIGGER", "RIGHT_TRIGGER"}:
            action[key] = 0


def block_buttons(actions: list[dict], buttons: tuple[str, ...]) -> list[str]:
    blocked = []
    for action in actions:
        for button in buttons:
            if action.get(button, 0):
                blocked.append(button)
            action[button] = 0
    return sorted(set(blocked))


def apply_deadzone(actions: list[dict], profile: GameProfile) -> None:
    axis_thresholds = {
        "AXIS_LEFTX": profile.left_deadzone,
        "AXIS_LEFTY": profile.left_deadzone,
        "AXIS_RIGHTX": profile.right_deadzone,
        "AXIS_RIGHTY": profile.right_deadzone,
        "LEFT_TRIGGER": profile.trigger_deadzone,
        "RIGHT_TRIGGER": profile.trigger_deadzone,
    }
    for action in actions:
        for axis, threshold in axis_thresholds.items():
            value = action_value(action, axis)
            if abs(value) < threshold:
                set_axis(action, axis, 0)


def map_right_stick_buttons(actions: list[dict]) -> int:
    changed = 0
    for action in actions:
        x = 0
        y = 0
        if action.get("RIGHT_LEFT", 0):
            x -= 32767
        if action.get("RIGHT_RIGHT", 0):
            x += 32767
        if action.get("RIGHT_UP", 0):
            y -= 32767
        if action.get("RIGHT_BOTTOM", 0):
            y += 32767
        if x or y:
            set_axis(action, "AXIS_RIGHTX", x)
            set_axis(action, "AXIS_RIGHTY", y)
            changed += 1
    return changed


class WaitLoadingSkill:
    name = "wait_loading"

    def apply(
        self,
        actions: list[dict],
        perception: PerceptionState,
        memory: TemporalMemory,
        profile: GameProfile,
        step: int,
        calibration: AutomaticControlCalibration | None = None,
    ) -> SkillDecision | None:
        if memory.loading_streak < profile.loading_wait_limit:
            return None

        for action in actions:
            neutralize_action(action)
            action["_SKILL"] = self.name

        reason = f"loading-like dark screen for {memory.loading_streak} steps"
        memory.mark_skill(self.name, step, reason)
        return SkillDecision(self.name, reason, len(actions))


class UnstuckSkill:
    name = "unstuck"

    def apply(
        self,
        actions: list[dict],
        perception: PerceptionState,
        memory: TemporalMemory,
        profile: GameProfile,
        step: int,
        calibration: AutomaticControlCalibration | None = None,
    ) -> SkillDecision | None:
        if memory.movement_failure_streak < profile.failed_movement_limit:
            return None
        if not memory.can_use_skill(self.name, step, profile.unstuck_cooldown_steps):
            return None

        attempt = memory.skill_counts.get(self.name, 0)
        direction, lx, ly = choose_escape_direction(memory, calibration, attempt)
        changed = min(max(4, profile.unstuck_actions // 2), len(actions))

        for action in actions[:changed]:
            set_axis(action, "AXIS_LEFTX", lx)
            set_axis(action, "AXIS_LEFTY", ly)
            action["_SKILL"] = self.name

        reason = (
            f"movement had no visual result for {memory.movement_failure_streak} steps; "
            f"trying {direction}"
        )
        memory.mark_skill(self.name, step, reason)
        return SkillDecision(self.name, reason, changed)


class BreakRepetitionSkill:
    name = "break_repetition"

    def apply(
        self,
        actions: list[dict],
        perception: PerceptionState,
        memory: TemporalMemory,
        profile: GameProfile,
        step: int,
        calibration: AutomaticControlCalibration | None = None,
    ) -> SkillDecision | None:
        if memory.repeated_movement_streak < profile.repeated_action_limit:
            return None
        if memory.movement_failure_streak < 2:
            return None
        if not memory.can_use_skill(self.name, step, profile.repetition_cooldown_steps):
            return None

        attempt = memory.skill_counts.get(self.name, 0)
        direction, lx, ly = choose_escape_direction(memory, calibration, attempt + 1)
        changed = min(max(4, profile.unstuck_actions // 2), len(actions))

        for action in actions[:changed]:
            set_axis(action, "AXIS_LEFTX", lx)
            set_axis(action, "AXIS_LEFTY", ly)
            action["_SKILL"] = self.name

        reason = (
            f"repeated failed movement for {memory.repeated_movement_streak} steps; "
            f"trying {direction}"
        )
        memory.mark_skill(self.name, step, reason)
        return SkillDecision(self.name, reason, changed)


class SkillLibrary:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.skills = {
            "wait_loading": WaitLoadingSkill(),
            "unstuck": UnstuckSkill(),
            "break_repetition": BreakRepetitionSkill(),
        }

    def apply_first(
        self,
        actions: list[dict],
        perception: PerceptionState,
        memory: TemporalMemory,
        profile: GameProfile,
        step: int,
        calibration: AutomaticControlCalibration | None = None,
    ) -> SkillDecision | None:
        if not self.enabled:
            return None

        for name in profile.skill_names:
            skill = self.skills.get(name)
            if skill is None:
                continue
            decision = skill.apply(actions, perception, memory, profile, step, calibration)
            if decision is not None:
                return decision
        return None
