from __future__ import annotations

import unittest

import numpy as np

from neveludens.control_calibration import AutomaticControlCalibration
from neveludens.legacy_anti_loop import LegacyAntiLoopMemory, LegacyAntiLoopSkills
from neveludens.memory import TemporalMemory
from neveludens.perception import PerceptionState
from neveludens.profiles import DEFAULT_PROFILE
from neveludens.runtime_options import memory_mode_flags, resolve_memory_mode
from neveludens.skills import SkillLibrary
from neveludens.supervisor import ObjectiveSupervisor


def perception(*, motion: float) -> PerceptionState:
    return PerceptionState(
        step=0,
        mean_luma=80.0,
        contrast=20.0,
        motion=motion,
        edge_density=8.0,
        dark_ratio=0.0,
        bright_ratio=0.0,
        is_dark=False,
        is_low_motion=motion <= 0.35,
        likely_loading=False,
        likely_static_screen=motion <= 0.35,
        likely_menu_or_overlay=False,
    )


def actions(x: int = 0, y: int = 0, count: int = 8) -> list[dict]:
    return [
        {
            "AXIS_LEFTX": np.array([x], dtype=np.int64),
            "AXIS_LEFTY": np.array([y], dtype=np.int64),
            "AXIS_RIGHTX": np.array([7000], dtype=np.int64),
            "AXIS_RIGHTY": np.array([0], dtype=np.int64),
            "SOUTH": 1,
        }
        for _ in range(count)
    ]


class TemporalRecoveryTests(unittest.TestCase):
    def test_static_screen_without_movement_does_not_look_stuck(self):
        memory = TemporalMemory()
        for _ in range(8):
            memory.record_executed_actions(actions())
            memory.update_perception(perception(motion=0.0))
        self.assertEqual(memory.movement_failure_streak, 0)

    def test_opposite_movements_are_not_treated_as_one_failed_direction(self):
        memory = TemporalMemory()
        alternating = actions(x=24000, count=4) + actions(x=-24000, count=4)
        memory.record_executed_actions(alternating)
        memory.update_perception(perception(motion=0.0))
        self.assertEqual(memory.movement_failure_streak, 0)
        self.assertIsNone(memory.last_failed_direction)

    def test_failed_movement_triggers_conservative_escape(self):
        memory = TemporalMemory()
        for _ in range(DEFAULT_PROFILE.failed_movement_limit):
            memory.record_executed_actions(actions(x=24000))
            memory.update_perception(perception(motion=0.0))

        output = actions(x=24000)
        decision = SkillLibrary().apply_first(
            output,
            perception(motion=0.0),
            memory,
            DEFAULT_PROFILE,
            step=10,
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.name, "unstuck")
        self.assertEqual(output[0]["SOUTH"], 1)
        self.assertEqual(int(output[0]["AXIS_RIGHTX"][0]), 7000)
        self.assertNotEqual(int(output[0]["AXIS_LEFTX"][0]), 24000)

    def test_visual_result_resets_failed_movement(self):
        memory = TemporalMemory()
        memory.record_executed_actions(actions(x=24000))
        memory.update_perception(perception(motion=0.0))
        memory.record_executed_actions(actions(x=24000))
        memory.update_perception(perception(motion=4.0))
        self.assertEqual(memory.movement_failure_streak, 0)
        self.assertTrue(memory.last_movement_had_result)


class CalibrationTests(unittest.TestCase):
    def test_calibration_waits_for_repeated_evidence(self):
        calibration = AutomaticControlCalibration(enabled=True)
        untouched = actions(x=9000)
        self.assertEqual(calibration.apply(untouched), 0)

        for _ in range(3):
            calibration.record_executed_actions(actions(x=9000))
            calibration.observe(perception(motion=0.0))
        for _ in range(3):
            calibration.record_executed_actions(actions(x=24000))
            calibration.observe(perception(motion=4.0))

        calibrated = actions(x=9000)
        self.assertGreater(calibration.apply(calibrated), 0)
        self.assertEqual(int(calibrated[0]["AXIS_LEFTX"][0]), 18000)


class MemoryModeTests(unittest.TestCase):
    def test_modes_map_to_expected_layers(self):
        self.assertEqual(memory_mode_flags("disabled"), (False, False))
        self.assertEqual(memory_mode_flags("temporary"), (True, False))
        self.assertEqual(memory_mode_flags("persistent"), (True, True))

    def test_legacy_settings_are_migrated(self):
        self.assertEqual(resolve_memory_mode(None), "temporary")
        self.assertEqual(
            resolve_memory_mode(None, legacy_advanced_memory=True),
            "persistent",
        )
        self.assertEqual(
            resolve_memory_mode(None, legacy_smart_recovery=False),
            "disabled",
        )

    def test_temporary_uses_the_original_anti_loop(self):
        supervisor = ObjectiveSupervisor(
            process_name="example.exe",
            allow_menu=False,
            enable_recovery=True,
            legacy_anti_loop=True,
        )
        self.assertIsInstance(supervisor.memory, LegacyAntiLoopMemory)
        self.assertIsInstance(supervisor.skills, LegacyAntiLoopSkills)

        supervisor.memory.low_motion_streak = DEFAULT_PROFILE.low_motion_limit
        output = actions(x=24000, count=12)
        decision = supervisor.skills.apply_first(
            output,
            perception(motion=0.0),
            supervisor.memory,
            DEFAULT_PROFILE,
            step=10,
        )
        self.assertEqual(decision.name, "unstuck")
        self.assertEqual(int(output[0]["AXIS_LEFTX"][0]), 26000)
        self.assertEqual(int(output[0]["AXIS_LEFTY"][0]), 0)
        self.assertEqual(int(output[0]["AXIS_RIGHTX"][0]), 0)
        self.assertEqual(int(output[0]["AXIS_RIGHTY"][0]), -26000)

    def test_persistent_keeps_the_reworked_recovery(self):
        supervisor = ObjectiveSupervisor(
            process_name="example.exe",
            allow_menu=False,
            enable_recovery=True,
            legacy_anti_loop=False,
        )
        self.assertIsInstance(supervisor.memory, TemporalMemory)
        self.assertIsInstance(supervisor.skills, SkillLibrary)


if __name__ == "__main__":
    unittest.main()
