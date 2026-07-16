from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from neveludens.memory import TemporalMemory, action_value
from neveludens.perception import PerceptionState
from neveludens.profiles import GameProfile


UNSTUCK_DIRECTIONS = [
    (26000, 0),
    (-26000, 0),
    (0, -26000),
    (0, 26000),
    (22000, -18000),
    (-22000, 18000),
]

REPETITION_BREAK_DIRECTIONS = [
    (0, -24000),
    (24000, 0),
    (0, 24000),
    (-24000, 0),
]

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
    ) -> SkillDecision | None:
        if memory.low_motion_streak < profile.low_motion_limit:
            return None
        if not memory.can_use_skill(self.name, step, profile.unstuck_cooldown_steps):
            return None

        attempt = memory.skill_counts.get(self.name, 0)
        lx, ly = UNSTUCK_DIRECTIONS[attempt % len(UNSTUCK_DIRECTIONS)]
        rx, ry = UNSTUCK_DIRECTIONS[(attempt + 2) % len(UNSTUCK_DIRECTIONS)]
        changed = min(profile.unstuck_actions, len(actions))

        for action in actions[:changed]:
            set_axis(action, "AXIS_LEFTX", lx)
            set_axis(action, "AXIS_LEFTY", ly)
            set_axis(action, "AXIS_RIGHTX", rx)
            set_axis(action, "AXIS_RIGHTY", ry)
            action["_SKILL"] = self.name

        reason = f"low visual motion for {memory.low_motion_streak} steps"
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
    ) -> SkillDecision | None:
        if memory.repeated_action_streak < profile.repeated_action_limit:
            return None
        if not memory.can_use_skill(self.name, step, profile.repetition_cooldown_steps):
            return None

        attempt = memory.skill_counts.get(self.name, 0)
        lx, ly = REPETITION_BREAK_DIRECTIONS[attempt % len(REPETITION_BREAK_DIRECTIONS)]
        changed = min(max(4, profile.unstuck_actions // 2), len(actions))

        for action in actions[:changed]:
            set_axis(action, "AXIS_LEFTX", lx)
            set_axis(action, "AXIS_LEFTY", ly)
            action["SOUTH"] = 0
            action["WEST"] = 0
            action["_SKILL"] = self.name

        reason = f"same action signature for {memory.repeated_action_streak} steps"
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
    ) -> SkillDecision | None:
        if not self.enabled:
            return None

        for name in profile.skill_names:
            skill = self.skills.get(name)
            if skill is None:
                continue
            decision = skill.apply(actions, perception, memory, profile, step)
            if decision is not None:
                return decision
        return None
