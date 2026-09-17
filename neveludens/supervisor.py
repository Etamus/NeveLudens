from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from neveludens.control_calibration import AutomaticControlCalibration
from neveludens.memory import TemporalMemory
from neveludens.perception import PerceptionAnalyzer, PerceptionState
from neveludens.profiles import GameProfile, get_profile
from neveludens.skills import (
    SkillLibrary,
    apply_deadzone,
    block_buttons,
    map_right_stick_buttons,
)


@dataclass
class SupervisorDecision:
    step: int
    profile: str
    objective: str
    skill: str | None
    reasons: list[str]
    perception: PerceptionState
    memory: dict


class ObjectiveSupervisor:
    def __init__(
        self,
        process_name: str,
        allow_menu: bool,
        enable_recovery: bool = True,
        enable_skills: bool = True,
        enable_control_calibration: bool = False,
        log_path: Path | None = None,
    ):
        self.enable_recovery = enable_recovery
        self.profile: GameProfile = get_profile(process_name)
        self.allow_menu = allow_menu
        self.perception = PerceptionAnalyzer()
        self.memory = TemporalMemory() if enable_recovery else None
        self.calibration = AutomaticControlCalibration(enabled=enable_control_calibration)
        self.skills = SkillLibrary(enabled=enable_skills and enable_recovery)
        self.log_path = log_path
        self.latest_perception: PerceptionState | None = None
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def observe(self, image: Image.Image, step: int) -> PerceptionState:
        state = self.perception.analyze(image, step)
        self.calibration.observe(state)
        if self.memory is not None:
            self.memory.update_perception(state)
        self.latest_perception = state
        return state

    def process_actions(self, actions: list[dict], step: int) -> SupervisorDecision:
        if self.latest_perception is None:
            raise RuntimeError("Supervisor.observe must be called before process_actions.")

        reasons = []
        objective = "follow_model"

        if not self.allow_menu:
            blocked = block_buttons(actions, self.profile.blocked_buttons)
            if blocked:
                reasons.append(f"blocked menu buttons: {', '.join(blocked)}")

        if self.profile.right_stick_from_buttons:
            changed = map_right_stick_buttons(actions)
            if changed:
                reasons.append(f"mapped right-stick button tokens on {changed} actions")

        apply_deadzone(actions, self.profile)
        calibrated_actions = self.calibration.apply(actions)
        if calibrated_actions:
            reasons.append(f"control calibration strengthened {calibrated_actions} movement axes")

        skill_decision = None
        if self.memory is not None:
            skill_decision = self.skills.apply_first(
                actions,
                self.latest_perception,
                self.memory,
                self.profile,
                step,
                self.calibration,
            )
        skill_name = None
        if skill_decision is not None:
            skill_name = skill_decision.name
            objective = skill_decision.name
            reasons.append(f"{skill_decision.name}: {skill_decision.reason}")

        memory_snapshot = {}
        if self.memory is not None:
            self.memory.update_actions(actions)
            memory_snapshot = self.memory.snapshot()
        calibration_snapshot = self.calibration.snapshot()
        if calibration_snapshot:
            memory_snapshot["control_calibration"] = calibration_snapshot

        decision = SupervisorDecision(
            step=step,
            profile=self.profile.name,
            objective=objective,
            skill=skill_name,
            reasons=reasons,
            perception=self.latest_perception,
            memory=memory_snapshot,
        )
        self._log(decision)
        return decision

    def record_executed_actions(self, actions: list[dict]) -> None:
        """Record only the final action slice that was sent to the controller."""
        if self.memory is not None:
            self.memory.record_executed_actions(actions)
        self.calibration.record_executed_actions(actions)

    def _log(self, decision: SupervisorDecision) -> None:
        if self.log_path is None:
            return

        row = {
            "step": decision.step,
            "profile": decision.profile,
            "objective": decision.objective,
            "skill": decision.skill,
            "reasons": decision.reasons,
            "perception": asdict(decision.perception),
            "memory": decision.memory,
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            json.dump(row, f)
            f.write("\n")
