from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass

import numpy as np

from neveludens.memory import action_signature
from neveludens.perception import PerceptionState
from neveludens.profiles import GameProfile
from neveludens.skills import neutralize_action, set_axis


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


class LegacyAntiLoopMemory:
    """Exact pre-rework temporal state used by the original anti-loop."""

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


@dataclass
class LegacySkillDecision:
    name: str
    reason: str
    changed_actions: int


class LegacyWaitLoadingSkill:
    name = "wait_loading"

    def apply(self, actions, perception, memory, profile, step):
        if memory.loading_streak < profile.loading_wait_limit:
            return None
        for action in actions:
            neutralize_action(action)
            action["_SKILL"] = self.name
        reason = f"loading-like dark screen for {memory.loading_streak} steps"
        memory.mark_skill(self.name, step, reason)
        return LegacySkillDecision(self.name, reason, len(actions))


class LegacyUnstuckSkill:
    name = "unstuck"

    def apply(self, actions, perception, memory, profile, step):
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
        return LegacySkillDecision(self.name, reason, changed)


class LegacyBreakRepetitionSkill:
    name = "break_repetition"

    def apply(self, actions, perception, memory, profile, step):
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
        return LegacySkillDecision(self.name, reason, changed)


class LegacyAntiLoopSkills:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.skills = {
            "wait_loading": LegacyWaitLoadingSkill(),
            "unstuck": LegacyUnstuckSkill(),
            "break_repetition": LegacyBreakRepetitionSkill(),
        }

    def apply_first(self, actions, perception, memory, profile, step, calibration=None):
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
