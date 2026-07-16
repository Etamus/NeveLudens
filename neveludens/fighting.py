from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from neveludens.memory import action_signature, action_value
from neveludens.perception import PerceptionState


ATTACK_BUTTONS = (
    "WEST",
    "SOUTH",
    "NORTH",
    "EAST",
    "LEFT_SHOULDER",
    "RIGHT_SHOULDER",
    "LEFT_TRIGGER",
    "RIGHT_TRIGGER",
)

ATTACK_CYCLE = (
    "WEST",
    "SOUTH",
    "NORTH",
    "EAST",
    "RIGHT_SHOULDER",
    "RIGHT_TRIGGER",
)


@dataclass(frozen=True)
class FightTuning:
    name: str
    move_strength: int
    move_window: int
    jump_interval: int
    attack_interval: int
    attack_window: int


@dataclass
class FightingDecision:
    reasons: list[str]
    changed_actions: int = 0


def _process_tuning(process_name: str) -> FightTuning:
    normalized = process_name.lower().replace("_", "").replace("-", "").replace(" ", "")
    if "streetfighter6" in normalized or normalized.startswith("sf6"):
        return FightTuning(
            name="street_fighter_6",
            move_strength=26000,
            move_window=10,
            jump_interval=5,
            attack_interval=3,
            attack_window=6,
        )

    return FightTuning(
        name="generic_fighting",
        move_strength=22000,
        move_window=8,
        jump_interval=7,
        attack_interval=4,
        attack_window=5,
    )


def _set_axis(action: dict, name: str, value: int) -> None:
    action[name] = np.array([int(value)], dtype=np.long)


def _set_trigger(action: dict, name: str, value: int) -> None:
    action[name] = np.array([int(max(0, min(255, value)))], dtype=np.long)


def _press_attack(action: dict, button: str) -> None:
    if "TRIGGER" in button:
        _set_trigger(action, button, 255)
    else:
        action[button] = 1


def _press_jump(action: dict) -> None:
    action["DPAD_UP"] = 1
    _set_axis(action, "AXIS_LEFTY", -24000)


def _set_horizontal(action: dict, direction: int, strength: int) -> None:
    _set_axis(action, "AXIS_LEFTX", direction * strength)
    action["DPAD_RIGHT"] = 1 if direction > 0 else 0
    action["DPAD_LEFT"] = 1 if direction < 0 else 0


def _clear_excess_attacks(action: dict, keep_button: str) -> bool:
    pressed = [button for button in ATTACK_BUTTONS if action_value(action, button) > 0]
    if len(pressed) <= 3:
        return False

    for button in ATTACK_BUTTONS:
        if "TRIGGER" in button:
            _set_trigger(action, button, 0)
        else:
            action[button] = 0
    _press_attack(action, keep_button)
    return True


def _attack_count(actions: list[dict]) -> int:
    return sum(1 for action in actions if any(action_value(action, button) > 0 for button in ATTACK_BUTTONS))


def _jump_count(actions: list[dict]) -> int:
    return sum(
        1
        for action in actions
        if action.get("DPAD_UP", 0) or action_value(action, "AXIS_LEFTY") < -16000
    )


def _movement_count(actions: list[dict]) -> int:
    return sum(
        1
        for action in actions
        if abs(action_value(action, "AXIS_LEFTX")) > 9000
        or action.get("DPAD_LEFT", 0)
        or action.get("DPAD_RIGHT", 0)
    )


class FightingAssist:
    """Opt-in movement and rhythm bias for fighting games.

    This intentionally avoids side detection, visual opponent tracking and
    high-level fighting logic. The base model still plays; this layer only
    pushes it to move, jump and attack more often.
    """

    def __init__(self, enabled: bool = False, process_name: str = "", agent_slot: str = "auto"):
        self.enabled = enabled
        self.tuning = _process_tuning(process_name)
        self.last_signature = None
        self.repeated_steps = 0
        self.last_jump_step = -999
        self.attack_index = 0
        self.move_bias = 1

    def apply(
        self,
        actions: list[dict],
        perception: PerceptionState,
        step: int,
        frame=None,
    ) -> FightingDecision:
        if not self.enabled or not actions:
            return FightingDecision([])

        reasons: list[str] = []
        changed = 0
        count = max(1, len(actions))
        movement_actions = _movement_count(actions)
        jump_actions = _jump_count(actions)
        attack_actions = _attack_count(actions)

        signature = action_signature(actions)
        if signature == self.last_signature:
            self.repeated_steps += 1
        else:
            self.repeated_steps = 0
        self.last_signature = signature

        if movement_actions < count * 0.45 or self.repeated_steps >= 3:
            changed += self._encourage_movement(actions, step)
            reasons.append("movement encouraged")
        else:
            boosted = self._boost_existing_movement(actions)
            if boosted:
                changed += boosted
                reasons.append("movement boosted")

        if jump_actions < count * 0.18 and step - self.last_jump_step >= self.tuning.jump_interval:
            changed += self._inject_jump(actions)
            self.last_jump_step = step
            reasons.append("jump encouraged")

        if attack_actions < count * 0.22 and step % self.tuning.attack_interval == 0:
            changed += self._inject_attack_rhythm(actions, step)
            reasons.append("attack rhythm encouraged")

        noise_changes = 0
        keep = ATTACK_CYCLE[self.attack_index % len(ATTACK_CYCLE)]
        for action in actions:
            if _clear_excess_attacks(action, keep):
                noise_changes += 1
        if noise_changes:
            changed += noise_changes
            reasons.append("attack noise reduced")

        if changed:
            self.attack_index += 1
            for action in actions[: min(8, len(actions))]:
                action["_FIGHTING"] = True

        return FightingDecision(reasons, changed)

    def _direction_for_step(self, step: int) -> int:
        phase = (step // self.tuning.move_window) % 2
        return self.move_bias if phase == 0 else -self.move_bias

    def _encourage_movement(self, actions: list[dict], step: int) -> int:
        direction = self._direction_for_step(step)
        changed = 0
        limit = min(len(actions), max(4, self.tuning.move_window))
        for action in actions[:limit]:
            current_x = action_value(action, "AXIS_LEFTX")
            if abs(current_x) < 12000 and not action.get("DPAD_LEFT", 0) and not action.get("DPAD_RIGHT", 0):
                _set_horizontal(action, direction, self.tuning.move_strength)
                changed += 1
        return changed

    def _boost_existing_movement(self, actions: list[dict]) -> int:
        changed = 0
        for action in actions:
            current_x = action_value(action, "AXIS_LEFTX")
            if 4000 < abs(current_x) < self.tuning.move_strength:
                direction = 1 if current_x > 0 else -1
                _set_axis(action, "AXIS_LEFTX", direction * self.tuning.move_strength)
                changed += 1
        return changed

    def _inject_jump(self, actions: list[dict]) -> int:
        changed = 0
        limit = min(len(actions), 3)
        for action in actions[:limit]:
            _press_jump(action)
            changed += 1
        return changed

    def _inject_attack_rhythm(self, actions: list[dict], step: int) -> int:
        changed = 0
        button = ATTACK_CYCLE[(self.attack_index + step) % len(ATTACK_CYCLE)]
        start = min(len(actions), 3)
        end = min(len(actions), start + self.tuning.attack_window)
        for action in actions[start:end]:
            _press_attack(action, button)
            changed += 1
        return changed
