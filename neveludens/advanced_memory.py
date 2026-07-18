from __future__ import annotations

import json
import re
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from neveludens.memory import action_signature, action_value
from neveludens.perception import PerceptionState
from neveludens.shared import PATH_REPO


@dataclass
class AdvancedMemoryDecision:
    reasons: list[str]
    changed_actions: int = 0


def _safe_process_name(process_name: str) -> str:
    name = process_name.strip().lower() or "unknown"
    name = re.sub(r"[^a-z0-9_.-]+", "_", name)
    return name[:80] or "unknown"


def _average_hash(image: Image.Image, size: int = 16) -> str:
    sample = image.convert("L").resize((size, size), Image.Resampling.BILINEAR)
    pixels = list(sample.getdata())
    average = sum(pixels) / max(1, len(pixels))
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= average)
    return f"{value:0{(size * size) // 4}x}"


def _hamming(left: str, right: str) -> int:
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 9999


def _signature_key(actions: list[dict]) -> str:
    return json.dumps(list(action_signature(actions)), ensure_ascii=True, separators=(",", ":"))


def _set_axis(action: dict, name: str, value: int) -> None:
    action[name] = np.array([int(value)], dtype=np.long)


def _movement_level(actions: list[dict]) -> float:
    if not actions:
        return 0.0
    moving = 0
    for action in actions:
        if (
            abs(action_value(action, "AXIS_LEFTX")) > 9000
            or abs(action_value(action, "AXIS_LEFTY")) > 9000
            or action.get("DPAD_LEFT", 0)
            or action.get("DPAD_RIGHT", 0)
            or action.get("DPAD_UP", 0)
            or action.get("DPAD_DOWN", 0)
        ):
            moving += 1
    return moving / max(1, len(actions))


class AdvancedGameMemory:
    """Opt-in memory that records places, outcomes and compact VLM context.

    This class is deliberately isolated from the default TemporalMemory path.
    Nothing is loaded, saved or applied unless the caller explicitly enables it.
    """

    RECOVERY_DIRECTIONS = (
        (26000, 0),
        (-26000, 0),
        (0, -26000),
        (0, 26000),
        (22000, -16000),
        (-22000, -16000),
        (22000, 16000),
        (-22000, 16000),
    )

    def __init__(
        self,
        process_name: str,
        enabled: bool = False,
        memory_dir: Path | None = None,
        max_recent_steps: int = 96,
        max_places: int = 500,
        autosave_steps: int = 30,
    ):
        self.enabled = enabled
        self.process_name = process_name
        self.safe_name = _safe_process_name(process_name)
        self.memory_dir = memory_dir or (PATH_REPO / "memories")
        self.path = self.memory_dir / f"{self.safe_name}.json"
        self.max_places = max_places
        self.autosave_steps = autosave_steps

        self.recent_frames = deque(maxlen=max_recent_steps)
        self.recent_places = deque(maxlen=max_recent_steps)
        self.recent_actions = deque(maxlen=max_recent_steps)
        self.events = deque(maxlen=80)

        self.current_place_id: int | None = None
        self.current_hash = ""
        self.current_place_streak = 0
        self.duplicate_streak = 0
        self.no_progress_streak = 0
        self.revisit_streak = 0
        self.pending_action: dict[str, Any] | None = None
        self.last_outcome: dict[str, Any] | None = None
        self.last_recovery_step = -9999
        self.recovery_count = 0
        self._dirty = False
        self._closed = False

        self.data = self._load() if self.enabled else self._empty_data()
        if self.enabled:
            self.data["session_count"] = int(self.data.get("session_count", 0)) + 1
            self._dirty = True

    def _empty_data(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "process": self.process_name,
            "session_count": 0,
            "places": [],
            "transitions": {},
            "action_results": {},
        }

    def _load(self) -> dict[str, Any]:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return self._empty_data()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty_data()
        if not isinstance(data, dict):
            return self._empty_data()
        data.setdefault("schema_version", 1)
        data.setdefault("process", self.process_name)
        data.setdefault("session_count", 0)
        data.setdefault("places", [])
        data.setdefault("transitions", {})
        data.setdefault("action_results", {})
        return data

    def observe(self, image: Image.Image, perception: PerceptionState, step: int) -> dict[str, Any]:
        if not self.enabled:
            return {}

        frame_hash = _average_hash(image)
        previous_place = self.current_place_id
        place = self._find_or_create_place(frame_hash, perception, step)
        place_id = int(place["id"])
        self.current_hash = frame_hash
        self.current_place_id = place_id

        if previous_place == place_id:
            self.current_place_streak += 1
        else:
            self.current_place_streak = 0

        duplicate_recent = any(_hamming(frame_hash, item["hash"]) <= 6 for item in self.recent_frames)
        self.duplicate_streak = self.duplicate_streak + 1 if duplicate_recent else 0

        recent_place_hits = sum(1 for recent_id in self.recent_places if recent_id == place_id)
        if previous_place is not None and previous_place != place_id and recent_place_hits >= 2:
            self.revisit_streak += 1
        elif previous_place != place_id:
            self.revisit_streak = 0

        if self.pending_action is not None:
            self._record_pending_result(place_id, perception, step)

        self.recent_frames.append(
            {
                "step": step,
                "hash": frame_hash,
                "place_id": place_id,
                "motion": round(float(perception.motion), 3),
            }
        )
        self.recent_places.append(place_id)

        if self.autosave_steps > 0 and step > 0 and step % self.autosave_steps == 0:
            self.save()

        return self.snapshot()

    def process_actions(
        self,
        actions: list[dict],
        perception: PerceptionState,
        step: int,
    ) -> AdvancedMemoryDecision:
        if not self.enabled or not actions:
            return AdvancedMemoryDecision([])

        reasons = []
        changed = 0
        recovery = self._apply_conservative_recovery(actions, perception, step)
        if recovery.changed_actions:
            changed += recovery.changed_actions
            reasons.extend(recovery.reasons)

        signature = _signature_key(actions)
        self.recent_actions.append({"step": step, "signature": signature})
        self.pending_action = {
            "step": step,
            "signature": signature,
            "place_id": self.current_place_id,
        }
        return AdvancedMemoryDecision(reasons, changed)

    def snapshot(self) -> dict[str, Any]:
        if not self.enabled:
            return {}
        place = self._place_by_id(self.current_place_id)
        return {
            "enabled": True,
            "current_place_id": self.current_place_id,
            "current_place_streak": self.current_place_streak,
            "duplicate_streak": self.duplicate_streak,
            "no_progress_streak": self.no_progress_streak,
            "revisit_streak": self.revisit_streak,
            "known_places": len(self.data.get("places", [])),
            "last_outcome": self.last_outcome or {},
            "current_place": self._compact_place(place),
            "recent_repeated_places": self._recent_repeated_places(),
            "likely_loop": self._likely_loop(),
        }

    def vlm_summary(self) -> dict[str, Any]:
        if not self.enabled:
            return {}

        snapshot = self.snapshot()
        place = snapshot.get("current_place", {})
        avoid_repeating = self.no_progress_streak >= 4 or self.duplicate_streak >= 6
        repeated_places = snapshot.get("recent_repeated_places", [])
        notes = []
        if avoid_repeating:
            notes.append("recent actions produced little visual progress")
        if repeated_places:
            notes.append("current area resembles recently visited places")
        if self.last_outcome and not self.last_outcome.get("progress", False):
            notes.append("last controller pattern did not change the scene")
        if not notes:
            notes.append("no strong loop evidence")

        return {
            "advanced_memory": True,
            "current_place_id": self.current_place_id,
            "place_visits": place.get("visits", 0),
            "same_place_steps": self.current_place_streak,
            "duplicate_frame_steps": self.duplicate_streak,
            "no_progress_steps": self.no_progress_streak,
            "recent_repeated_places": repeated_places[:6],
            "avoid_repeating_last_action": avoid_repeating,
            "last_outcome": self.last_outcome or {},
            "instruction_hint": "; ".join(notes[:3]),
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.save()

    def save(self) -> None:
        if not self.enabled or not self._dirty:
            return
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._trim_data()
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)
        self._dirty = False

    def _find_or_create_place(
        self,
        frame_hash: str,
        perception: PerceptionState,
        step: int,
    ) -> dict[str, Any]:
        places = self.data.setdefault("places", [])
        best_place = None
        best_distance = 9999
        for place in places:
            distance = _hamming(frame_hash, str(place.get("hash", "")))
            if distance < best_distance:
                best_distance = distance
                best_place = place

        if best_place is not None and (best_distance <= 28 or len(places) >= self.max_places):
            place = best_place
        else:
            place = {
                "id": self._next_place_id(),
                "hash": frame_hash,
                "visits": 0,
                "first_step": step,
                "last_step": step,
                "mean_luma": round(float(perception.mean_luma), 2),
                "failed_attempts": 0,
                "successful_exits": 0,
            }
            places.append(place)

        place["visits"] = int(place.get("visits", 0)) + 1
        place["last_step"] = step
        if best_distance <= 10:
            place["hash"] = frame_hash
        self._dirty = True
        return place

    def _next_place_id(self) -> int:
        places = self.data.get("places", [])
        if not places:
            return 1
        return max(int(place.get("id", 0)) for place in places) + 1

    def _place_by_id(self, place_id: int | None) -> dict[str, Any] | None:
        if place_id is None:
            return None
        for place in self.data.get("places", []):
            if int(place.get("id", -1)) == int(place_id):
                return place
        return None

    def _record_pending_result(self, new_place_id: int, perception: PerceptionState, step: int) -> None:
        pending = self.pending_action
        self.pending_action = None
        if pending is None:
            return

        old_place_id = pending.get("place_id")
        signature = str(pending.get("signature", ""))
        place_changed = old_place_id is not None and int(old_place_id) != int(new_place_id)
        visual_progress = float(perception.motion) >= 1.2 and not perception.likely_static_screen
        progress = bool(place_changed or visual_progress)

        if progress:
            self.no_progress_streak = 0
        else:
            self.no_progress_streak += 1

        results = self.data.setdefault("action_results", {})
        result = results.setdefault(
            signature,
            {"attempts": 0, "progress": 0, "no_progress": 0, "last_step": 0},
        )
        result["attempts"] = int(result.get("attempts", 0)) + 1
        result["progress"] = int(result.get("progress", 0)) + int(progress)
        result["no_progress"] = int(result.get("no_progress", 0)) + int(not progress)
        result["last_step"] = step

        if old_place_id is not None:
            transition_key = f"{old_place_id}->{new_place_id}"
            transitions = self.data.setdefault("transitions", {})
            transition = transitions.setdefault(
                transition_key,
                {"count": 0, "last_step": 0, "progress": False},
            )
            transition["count"] = int(transition.get("count", 0)) + 1
            transition["last_step"] = step
            transition["progress"] = bool(place_changed)

            old_place = self._place_by_id(int(old_place_id))
            if old_place is not None:
                if place_changed:
                    old_place["successful_exits"] = int(old_place.get("successful_exits", 0)) + 1
                elif not progress:
                    old_place["failed_attempts"] = int(old_place.get("failed_attempts", 0)) + 1

        self.last_outcome = {
            "from_place": old_place_id,
            "to_place": new_place_id,
            "progress": progress,
            "place_changed": place_changed,
            "motion": round(float(perception.motion), 3),
            "step": step,
        }
        self._dirty = True

    def _apply_conservative_recovery(
        self,
        actions: list[dict],
        perception: PerceptionState,
        step: int,
    ) -> AdvancedMemoryDecision:
        if perception.likely_loading or perception.likely_menu_or_overlay:
            return AdvancedMemoryDecision([])
        if step - self.last_recovery_step < 18:
            return AdvancedMemoryDecision([])

        trigger = None
        if self.no_progress_streak >= 8:
            trigger = f"{self.no_progress_streak} passos sem progresso visual"
        elif self.duplicate_streak >= 12:
            trigger = f"{self.duplicate_streak} frames parecidos recentes"
        elif self.current_place_streak >= 24 and self.revisit_streak >= 2:
            trigger = "area atual repetida no historico recente"

        if trigger is None:
            return AdvancedMemoryDecision([])

        movement = _movement_level(actions)
        if movement >= 0.65 and self.no_progress_streak < 12:
            return AdvancedMemoryDecision([])

        lx, ly = self.RECOVERY_DIRECTIONS[self.recovery_count % len(self.RECOVERY_DIRECTIONS)]
        changed = 0
        limit = min(6, len(actions))
        for action in actions[:limit]:
            _set_axis(action, "AXIS_LEFTX", lx)
            _set_axis(action, "AXIS_LEFTY", ly)
            action["_ADVANCED_MEMORY"] = True
            changed += 1

        self.recovery_count += 1
        self.last_recovery_step = step
        self.events.append({"step": step, "type": "recovery", "reason": trigger})
        self._dirty = True
        return AdvancedMemoryDecision([f"memoria avancada: rota alternativa apos {trigger}"], changed)

    def _compact_place(self, place: dict[str, Any] | None) -> dict[str, Any]:
        if not place:
            return {}
        return {
            "id": place.get("id"),
            "visits": int(place.get("visits", 0)),
            "failed_attempts": int(place.get("failed_attempts", 0)),
            "successful_exits": int(place.get("successful_exits", 0)),
        }

    def _recent_repeated_places(self) -> list[int]:
        counts = Counter(self.recent_places)
        repeated = [place_id for place_id, count in counts.items() if count >= 3]
        return sorted(repeated, key=lambda place_id: (-counts[place_id], place_id))

    def _likely_loop(self) -> bool:
        return (
            self.no_progress_streak >= 6
            or self.duplicate_streak >= 10
            or (self.current_place_streak >= 18 and self.revisit_streak >= 2)
        )

    def _trim_data(self) -> None:
        places = self.data.get("places", [])
        if len(places) > self.max_places:
            places.sort(key=lambda item: (int(item.get("visits", 0)), int(item.get("last_step", 0))))
            self.data["places"] = places[-self.max_places :]

        action_results = self.data.get("action_results", {})
        if len(action_results) > 600:
            ordered = sorted(
                action_results.items(),
                key=lambda item: int(item[1].get("last_step", 0)),
            )
            self.data["action_results"] = dict(ordered[-600:])

        transitions = self.data.get("transitions", {})
        if len(transitions) > 1000:
            ordered = sorted(
                transitions.items(),
                key=lambda item: int(item[1].get("last_step", 0)),
            )
            self.data["transitions"] = dict(ordered[-1000:])
