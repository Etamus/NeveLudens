from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GameProfile:
    name: str
    process_names: tuple[str, ...] = ()
    genre: str = "generic"
    blocked_buttons: tuple[str, ...] = ("GUIDE", "START", "BACK")
    left_deadzone: int = 900
    right_deadzone: int = 1200
    trigger_deadzone: int = 10
    right_stick_from_buttons: bool = False
    low_motion_limit: int = 12
    repeated_action_limit: int = 10
    loading_wait_limit: int = 6
    unstuck_cooldown_steps: int = 8
    repetition_cooldown_steps: int = 8
    unstuck_actions: int = 10
    skill_names: tuple[str, ...] = ("wait_loading", "unstuck", "break_repetition")
    notes: tuple[str, ...] = field(default_factory=tuple)


DEFAULT_PROFILE = GameProfile(
    name="generic",
    genre="generic",
)

PROFILES = [
    GameProfile(
        name="isaac",
        process_names=("isaac-ng.exe",),
        genre="top_down_shooter",
        right_stick_from_buttons=True,
        low_motion_limit=10,
        repeated_action_limit=8,
        unstuck_actions=12,
        notes=("top-down movement and right-stick shooting",),
    ),
    GameProfile(
        name="cuphead",
        process_names=("cuphead.exe",),
        genre="platformer",
        low_motion_limit=14,
        repeated_action_limit=12,
        unstuck_actions=8,
        notes=("platformer-style recovery timing",),
    ),
    GameProfile(
        name="celeste",
        process_names=("celeste.exe",),
        genre="platformer",
        low_motion_limit=14,
        repeated_action_limit=12,
        unstuck_actions=8,
    ),
    GameProfile(
        name="action_rpg",
        process_names=("granblue_fantasy_relink.exe",),
        genre="action_rpg",
        low_motion_limit=16,
        repeated_action_limit=12,
        unstuck_actions=8,
    ),
]


def get_profile(process_name: str) -> GameProfile:
    normalized = process_name.lower()
    for profile in PROFILES:
        if normalized in profile.process_names:
            return profile
    return DEFAULT_PROFILE
