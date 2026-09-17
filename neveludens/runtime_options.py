from __future__ import annotations


MEMORY_MODES = ("disabled", "temporary", "persistent")
MEMORY_MODE_LABELS = {
    "disabled": "Padrão",
    "temporary": "Temporário",
    "persistent": "Persistente",
}


def resolve_memory_mode(
    selected: str | None,
    *,
    legacy_advanced_memory: bool = False,
    legacy_smart_recovery: bool = True,
) -> str:
    """Resolve the unified mode while accepting legacy command-line flags."""
    if selected is not None:
        if selected not in MEMORY_MODES:
            raise ValueError(f"Invalid memory mode: {selected}")
        return selected
    if legacy_advanced_memory:
        return "persistent"
    if legacy_smart_recovery:
        return "temporary"
    return "disabled"


def memory_mode_flags(mode: str) -> tuple[bool, bool]:
    """Return (recovery_enabled, persistent_memory_enabled)."""
    if mode not in MEMORY_MODES:
        raise ValueError(f"Invalid memory mode: {mode}")
    return mode != "disabled", mode == "persistent"


def memory_mode_label(mode: str) -> str:
    if mode not in MEMORY_MODE_LABELS:
        raise ValueError(f"Invalid memory mode: {mode}")
    return MEMORY_MODE_LABELS[mode]
