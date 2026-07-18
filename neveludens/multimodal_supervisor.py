from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
import time
import warnings
from contextlib import contextmanager, redirect_stderr
from dataclasses import dataclass, field
from io import StringIO
from typing import Any

import numpy as np
from PIL import Image


QWEN35_4B_MODEL_ID = "Qwen/Qwen3.5-4B"

ALLOWED_INTENTS = {"explore", "follow_path", "interact", "fight", "retreat", "wait", "menu", "none"}
ALLOWED_DIRECTIONS = {"left", "right", "up", "down", "forward", "back", "none"}
ALLOWED_TARGETS = {
    "clear_path",
    "door",
    "route",
    "exit",
    "opening",
    "platform",
    "ledge",
    "ladder",
    "stairs",
    "gap",
    "pickup",
    "interactable",
    "objective_marker",
    "interaction_prompt",
    "enemy",
    "hazard",
    "menu_ui",
    "readable_text",
    "ceiling_or_floor",
    "unknown",
}

GENERIC_REASON_FRAGMENTS = (
    "check surroundings",
    "check area",
    "game world",
    "continue mission",
    "find objectives",
    "inspect environment",
)

DETAIL_TARGETS = {
    "interaction_prompt",
    "menu_ui",
    "readable_text",
    "pickup",
    "interactable",
    "objective_marker",
}

NAVIGATION_TARGETS = {
    "clear_path",
    "door",
    "route",
    "exit",
    "opening",
    "platform",
    "ledge",
    "ladder",
    "stairs",
    "gap",
    "objective_marker",
    "enemy",
    "hazard",
}

INTERACTION_TARGETS = {
    "interaction_prompt",
    "door",
    "pickup",
    "interactable",
    "objective_marker",
    "readable_text",
}

_SUBPROCESS_PATCHED = False
_SUBPROCESS_PATCH_LOCK = threading.Lock()


@dataclass
class MultimodalGuidance:
    intent: str = "none"
    direction: str = "none"
    visible_target: str = "unknown"
    confidence: float = 0.0
    duration_seconds: float = 2.0
    reason: str = ""
    created_at: float = field(default_factory=time.monotonic)
    captured_at: float = field(default_factory=time.monotonic)
    applied_count: int = 0
    logged_change: bool = False
    authority: str = "light"

    @property
    def expires_at(self) -> float:
        return self.created_at + self.duration_seconds

    def active(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.confidence > 0.0 and now <= self.expires_at


@dataclass
class _VisionTask:
    image: Image.Image
    process_name: str
    profile_name: str
    game_mode: str
    perception: dict[str, Any]
    memory: dict[str, Any]
    step: int
    created_at: float = field(default_factory=time.monotonic)


def _action_value(action: dict, name: str, default: int = 0) -> int:
    value = action.get(name, default)
    if isinstance(value, np.ndarray):
        return int(value[0])
    if isinstance(value, list):
        return int(value[0]) if value else default
    return int(value)


def _set_axis(action: dict, name: str, value: int) -> None:
    action[name] = np.array([int(value)], dtype=np.long)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _resize_for_vlm(image: Image.Image, max_side: int = 384) -> Image.Image:
    image = image.convert("RGB")
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image.copy()
    scale = max_side / float(longest)
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(size, Image.Resampling.BILINEAR)


def _sanitize_reason(reason: Any) -> str:
    text = " ".join(str(reason or "").split())[:120]
    lower = text.lower()
    if "hallway" in lower or "corridor" in lower:
        if "left" in lower:
            return "Corridor continues left."
        if "right" in lower:
            return "Corridor continues right."
        if "ahead" in lower or "forward" in lower or "down " in lower:
            return "Corridor continues ahead."
        return "Corridor visible."
    for prefix in (
        "player moves ",
        "player should move ",
        "player should ",
        "the player moves ",
        "the player should move ",
        "the player should ",
    ):
        if lower.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    text = text.replace("The player ", "").replace("the player ", "")
    text = text.replace("Player ", "").replace("player ", "")
    for word in ("character", "avatar", "should", "moves", "move"):
        text = text.replace(f"{word} ", "").replace(f"{word.capitalize()} ", "")
    return text[:120]


def _as_jsonable_perception(perception: Any) -> dict[str, Any]:
    fields = (
        "mean_luma",
        "contrast",
        "motion",
        "edge_density",
        "dark_ratio",
        "bright_ratio",
        "is_dark",
        "is_low_motion",
        "likely_loading",
        "likely_static_screen",
        "likely_menu_or_overlay",
    )
    result = {}
    for name in fields:
        if hasattr(perception, name):
            value = getattr(perception, name)
            if isinstance(value, float):
                value = round(value, 3)
            result[name] = value
    return result


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _patch_subprocess_text_decoding() -> None:
    """
    Some CUDA/driver probing helpers launch subprocesses in text mode. On PT-BR
    Windows those tools can emit bytes that are not valid UTF-8, producing a
    noisy background-thread traceback. Decode replacement is safer for probes.
    """
    global _SUBPROCESS_PATCHED
    with _SUBPROCESS_PATCH_LOCK:
        if _SUBPROCESS_PATCHED:
            return
        original_init = subprocess.Popen.__init__

        def patched_init(self, *args, **kwargs):
            text_mode = kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding") is not None
            if text_mode and kwargs.get("errors") is None:
                kwargs["errors"] = "replace"
            return original_init(self, *args, **kwargs)

        subprocess.Popen.__init__ = patched_init
        _SUBPROCESS_PATCHED = True


def _quiet_dependency_noise() -> None:
    os.environ.setdefault("TORCH_CPP_LOG_LEVEL", "ERROR")
    os.environ.setdefault("BITSANDBYTES_NOWELCOME", "1")
    logging.getLogger("torch").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message=".*triton not found.*")
    warnings.filterwarnings("ignore", message=".*torch_dtype.*deprecated.*")
    warnings.filterwarnings("ignore", message=".*use_fast.*deprecated.*")


@contextmanager
def _quiet_dependency_stderr():
    buffer = StringIO()
    with redirect_stderr(buffer):
        yield


def _normalize_guidance(data: dict[str, Any]) -> MultimodalGuidance | None:
    intent = str(data.get("intent", "none")).strip().lower()
    direction = str(data.get("direction", "none")).strip().lower()
    visible_target = str(data.get("visible_target", "unknown")).strip().lower()
    if intent not in ALLOWED_INTENTS:
        intent = "none"
    if direction not in ALLOWED_DIRECTIONS:
        direction = "none"
    if visible_target not in ALLOWED_TARGETS:
        visible_target = "unknown"

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    try:
        duration = float(data.get("duration_seconds", 2.0))
    except (TypeError, ValueError):
        duration = 2.0

    reason = _sanitize_reason(data.get("reason", ""))
    confidence = _clamp(confidence, 0.0, 1.0)
    duration = _clamp(duration, 1.5, 4.0)

    lower_reason = reason.lower()
    if any(fragment in lower_reason for fragment in GENERIC_REASON_FRAGMENTS):
        confidence = min(confidence, 0.35)

    if visible_target in {"unknown", "ceiling_or_floor"}:
        intent = "none"
        direction = "none"
        confidence = min(confidence, 0.25)

    if intent in {"explore", "follow_path"} and visible_target not in NAVIGATION_TARGETS:
        intent = "none"
        direction = "none"
        confidence = min(confidence, 0.35)

    if intent == "interact" and visible_target not in INTERACTION_TARGETS:
        intent = "none"
        direction = "none"
        confidence = min(confidence, 0.35)

    if intent == "menu" and visible_target != "menu_ui":
        intent = "none"
        direction = "none"
        confidence = min(confidence, 0.35)

    if intent == "none" and direction == "none":
        confidence = min(confidence, 0.2)

    authority = "light"
    if confidence >= 0.9 and direction != "none":
        authority = "command"
    elif confidence >= 0.84 and (
        intent in {"explore", "follow_path"} or visible_target in NAVIGATION_TARGETS
    ):
        authority = "strong"

    if authority == "command":
        duration = max(duration, 3.0)
    elif authority == "strong":
        duration = max(duration, 2.4)

    return MultimodalGuidance(
        intent=intent,
        direction=direction,
        visible_target=visible_target,
        confidence=confidence,
        duration_seconds=duration,
        reason=reason,
        authority=authority,
    )


class AsyncMultimodalSupervisor:
    """
    Optional Qwen3.5 4B supervisor.

    It never blocks the game loop. It reads occasional screenshots in a daemon
    thread and exposes the latest compact JSON guidance as a conservative action
    bias. When disabled, this class does not import or load any VLM dependency.
    """

    def __init__(
        self,
        enabled: bool,
        process_name: str,
        game_mode: str,
        model_id: str = QWEN35_4B_MODEL_ID,
        interval_seconds: float = 2.5,
        min_confidence: float = 0.82,
        guidance_hold_seconds: float = 1.5,
        max_apply_count: int = 24,
        max_task_age_seconds: float = 5.0,
    ):
        self.enabled = enabled
        self.process_name = process_name
        self.game_mode = game_mode
        self.model_id = model_id
        self.interval_seconds = interval_seconds
        self.min_confidence = min_confidence
        self.guidance_hold_seconds = guidance_hold_seconds
        self.max_apply_count = max_apply_count
        self.max_task_age_seconds = max_task_age_seconds
        self._queue: queue.Queue[_VisionTask | None] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._latest: MultimodalGuidance | None = None
        self._last_submit_at = 0.0
        self._model = None
        self._processor = None
        self._disabled_reason: str | None = None
        self._last_interact_at = 0.0
        self._last_accepted_at = 0.0
        self._detail_boost_until = 0.0
        self._closed = False
        self._thread: threading.Thread | None = None

        if self.enabled:
            self._thread = threading.Thread(target=self._worker, name="qwen35-vlm-supervisor", daemon=True)
            self._thread.start()

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    def _select_image_max_side(self, perception: dict[str, Any], now: float) -> int:
        if perception.get("likely_menu_or_overlay", False):
            return 512
        if now < self._detail_boost_until:
            return 512
        with self._lock:
            latest = self._latest
        if latest is not None and latest.active(now) and latest.visible_target in DETAIL_TARGETS:
            return 512
        return 384

    def submit(
        self,
        image: Image.Image,
        perception: Any,
        memory: dict[str, Any],
        profile_name: str,
        step: int,
    ) -> None:
        if not self.enabled or self._disabled_reason or self._closed:
            return

        now = time.monotonic()
        if now - self._last_submit_at < self.interval_seconds:
            return
        with self._lock:
            latest = self._latest
        if latest is not None and now - latest.created_at < self.guidance_hold_seconds:
            return
        perception_data = _as_jsonable_perception(perception)
        image_max_side = self._select_image_max_side(perception_data, now)
        task = _VisionTask(
            image=_resize_for_vlm(image, max_side=image_max_side),
            process_name=self.process_name,
            profile_name=profile_name,
            game_mode=self.game_mode,
            perception=perception_data,
            memory=dict(memory or {}),
            step=step,
        )

        try:
            self._queue.put_nowait(task)
            self._last_submit_at = now
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._queue.put_nowait(task)
                self._last_submit_at = now
            except queue.Full:
                pass

    def apply(self, actions: list[dict]) -> list[str]:
        if not self.enabled or not actions:
            return []

        with self._lock:
            guidance = self._latest

        if guidance is None or not guidance.active() or guidance.confidence < self.min_confidence:
            return []
        if guidance.applied_count >= self.max_apply_count:
            return []

        changed = 0
        reasons = []

        action_count = self._controlled_action_count(actions, guidance)
        lx, ly = self._direction_axis(guidance.direction, self._movement_strength(guidance))
        if lx or ly:
            changed += self._apply_movement_bias(
                actions,
                lx,
                ly,
                force=guidance.authority in {"strong", "command"},
                action_count=action_count,
            )

        if self._should_suppress_action_noise(guidance):
            changed += self._suppress_action_noise(
                actions,
                action_count=action_count,
                aggressive=guidance.authority == "command",
            )

        if self._should_camera_scan(guidance):
            changed += self._apply_camera_scan(actions, action_count=action_count)

        if self._should_press_interact(guidance):
            changed += self._apply_interact(actions)
        elif guidance.intent == "fight" and guidance.confidence >= 0.82:
            changed += self._apply_light_attack_bias(actions)

        if changed:
            guidance.applied_count += 1
            if not guidance.logged_change:
                guidance.logged_change = True
                source_age = max(0.0, time.monotonic() - guidance.captured_at)
                reasons.append(
                    "VLM aplicado "
                    f"{guidance.intent}/{guidance.direction}/{guidance.visible_target}/{guidance.authority} "
                    f"conf={guidance.confidence:.2f} idade={source_age:.1f}s "
                    f"alterou={changed}: {guidance.reason}"
                )
        return reasons

    def close(self) -> None:
        self._closed = True
        if self.enabled:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

    def _worker(self) -> None:
        try:
            self._ensure_loaded()
        except Exception as exc:
            self._disabled_reason = str(exc)
            print(f"Supervisor multimodal desativado: {exc}", flush=True)
            return

        while not self._closed:
            task = self._queue.get()
            if task is None:
                return
            try:
                guidance = self._infer(task)
                if guidance is not None:
                    task_age = time.monotonic() - task.created_at
                    if task_age > self.max_task_age_seconds:
                        guidance = None
                if guidance is None or guidance.confidence < self.min_confidence:
                    self._detail_boost_until = max(self._detail_boost_until, time.monotonic() + 8.0)
                if guidance is not None and self._accept_guidance(guidance, task):
                    with self._lock:
                        self._latest = guidance
                    self._last_accepted_at = time.monotonic()
            except Exception as exc:
                self._disabled_reason = str(exc)
                print(f"Supervisor multimodal desativado: {exc}", flush=True)

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._processor is not None:
            return

        os.environ.setdefault("BNB_CUDA_VERSION", "130")
        _patch_subprocess_text_decoding()
        _quiet_dependency_noise()

        with _quiet_dependency_stderr():
            import torch
            from transformers import AutoProcessor, BitsAndBytesConfig

            try:
                from transformers import AutoModelForImageTextToText as ModelClass
            except ImportError:
                try:
                    from transformers import AutoModelForVision2Seq as ModelClass
                except ImportError:
                    from transformers import AutoModelForCausalLM as ModelClass

        compute_dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float16
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=compute_dtype,
            bnb_4bit_use_double_quant=True,
        )

        with _quiet_dependency_stderr():
            self._processor = AutoProcessor.from_pretrained(
                self.model_id,
                trust_remote_code=True,
                use_fast=True,
            )
            self._model = ModelClass.from_pretrained(
                self.model_id,
                device_map="auto",
                quantization_config=quantization_config,
                torch_dtype=compute_dtype,
                trust_remote_code=True,
            )
        self._model.eval()

    def _infer(self, task: _VisionTask) -> MultimodalGuidance | None:
        with _quiet_dependency_stderr():
            import torch

        prompt = self._build_prompt(task)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a visual game supervisor. Return only compact JSON. "
                    "Do not explain. Do not use markdown. Do not reveal reasoning. "
                    "If the screenshot is ambiguous, choose intent none."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": task.image},
                    {"type": "text", "text": prompt},
                ],
            },
        ]

        try:
            text = self._processor.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            text = self._processor.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )

        with _quiet_dependency_stderr():
            try:
                inputs = self._processor(text=[text], images=[task.image], return_tensors="pt")
            except TypeError:
                inputs = self._processor(images=task.image, text=text, return_tensors="pt")

        device = next(self._model.parameters()).device
        inputs = {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}

        with torch.inference_mode():
            with _quiet_dependency_stderr():
                generated = self._model.generate(
                    **inputs,
                    max_new_tokens=80,
                    do_sample=False,
                    use_cache=True,
                )

        if "input_ids" in inputs:
            generated = generated[:, inputs["input_ids"].shape[1]:]
        output = self._processor.batch_decode(
            generated,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]
        data = _extract_json(output)
        if data is None:
            return None
        guidance = _normalize_guidance(data)
        if guidance is None:
            return None
        guidance.captured_at = task.created_at
        return guidance

    def _build_prompt(self, task: _VisionTask) -> str:
        payload = {
            "process": task.process_name,
            "profile": task.profile_name,
            "game_mode": task.game_mode,
            "perception": task.perception,
            "memory": task.memory,
            "step": task.step,
        }
        return (
            "Analyze this single game screenshot and choose one immediately actionable "
            "objective for a real-time controller agent in any game genre. Be strict: "
            "Return a controller instruction, not a narration. Never describe what "
            "the player will do. The reason must cite visible evidence only and must "
            "not contain the words player, character, avatar, should, moves, or move. "
            "If a target is not clearly visible, return none. Do not infer story, "
            "mission, room name, menu, or player state from weak evidence. Never output "
            "generic goals like check surroundings, check area, continue mission, or "
            "move through game world. Allowed intents: explore, follow_path, interact, "
            "fight, retreat, wait, menu, none. Allowed directions: left, right, up, "
            "down, forward, back, none. In 2D/side/top-down views prefer screen "
            "directions left/right/up/down; use forward/back only for 3D camera views "
            "where the left stick up/down moves into/out of the scene. Allowed "
            "visible_target: clear_path, route, exit, opening, platform, ledge, ladder, "
            "stairs, gap, door, pickup, interactable, objective_marker, "
            "interaction_prompt, enemy, hazard, menu_ui, readable_text, "
            "ceiling_or_floor, unknown. Use interact only when a prompt/text, pickup, "
            "menu item, or obvious interactable is clearly visible. Use menu only for a "
            "full menu UI. "
            "If the camera is mostly ceiling, floor, wall, blur, darkness, or clutter, "
            "return intent none, direction none, visible_target unknown or ceiling_or_floor, "
            "confidence <= 0.35. If Context.memory.advanced exists, use it only as "
            "short history: avoid repeating the last failed controller pattern, prefer "
            "a visibly different route when no_progress_steps is high, and do not invent "
            "targets that are not visible in the screenshot. Return exactly one JSON object with keys: intent, "
            "direction, visible_target, confidence, duration_seconds, reason. Keep reason "
            "under 10 words and cite only visible evidence. "
            f"Context: {json.dumps(payload, ensure_ascii=True)}"
        )

    def _accept_guidance(self, guidance: MultimodalGuidance, task: _VisionTask) -> bool:
        if guidance.confidence < self.min_confidence:
            return False
        if guidance.intent == "menu" and not task.perception.get("likely_menu_or_overlay", False):
            return False
        if guidance.intent == "interact" and guidance.visible_target == "readable_text" and guidance.direction in {"down", "up"}:
            return False
        if guidance.intent in {"explore", "follow_path"} and guidance.direction == "none":
            return False
        now = time.monotonic()
        return now - self._last_accepted_at >= self.guidance_hold_seconds

    def _movement_strength(self, guidance: MultimodalGuidance) -> int:
        if guidance.authority == "command":
            return 30000
        if guidance.authority == "strong":
            return 27500
        return 22000

    def _controlled_action_count(self, actions: list[dict], guidance: MultimodalGuidance) -> int:
        if guidance.authority in {"strong", "command"}:
            return len(actions)
        return min(10, len(actions))

    def _direction_axis(self, direction: str, strength: int) -> tuple[int, int]:
        if direction == "left":
            return -strength, 0
        if direction == "right":
            return strength, 0
        if direction in {"up", "forward"}:
            return 0, -strength
        if direction in {"down", "back"}:
            return 0, strength
        return 0, 0

    def _apply_movement_bias(
        self,
        actions: list[dict],
        lx: int,
        ly: int,
        force: bool = False,
        action_count: int | None = None,
    ) -> int:
        changed = 0
        limit = len(actions) if action_count is None else min(action_count, len(actions))
        for action in actions[:limit]:
            current_x = _action_value(action, "AXIS_LEFTX")
            current_y = _action_value(action, "AXIS_LEFTY")

            if force and lx and current_x != lx:
                _set_axis(action, "AXIS_LEFTX", lx)
                changed += 1
            elif lx and abs(current_x) < 10000:
                _set_axis(action, "AXIS_LEFTX", lx)
                changed += 1
            elif lx and current_x * lx > 0 and abs(current_x) < abs(lx):
                _set_axis(action, "AXIS_LEFTX", lx)
                changed += 1
            elif force and not lx and abs(current_x) > 8000:
                _set_axis(action, "AXIS_LEFTX", 0)
                changed += 1

            if force and ly and current_y != ly:
                _set_axis(action, "AXIS_LEFTY", ly)
                changed += 1
            elif ly and abs(current_y) < 10000:
                _set_axis(action, "AXIS_LEFTY", ly)
                changed += 1
            elif ly and current_y * ly > 0 and abs(current_y) < abs(ly):
                _set_axis(action, "AXIS_LEFTY", ly)
                changed += 1
            elif force and not ly and abs(current_y) > 8000:
                _set_axis(action, "AXIS_LEFTY", 0)
                changed += 1
        return changed

    def _should_suppress_action_noise(self, guidance: MultimodalGuidance) -> bool:
        if guidance.intent in {"explore", "follow_path"}:
            return guidance.direction != "none"
        if guidance.intent == "interact" and guidance.visible_target not in {"interaction_prompt", "readable_text", "menu_ui"}:
            return guidance.direction != "none"
        return False

    def _suppress_action_noise(
        self,
        actions: list[dict],
        action_count: int | None = None,
        aggressive: bool = False,
    ) -> int:
        changed = 0
        noisy_controls = [
            "WEST",
            "SOUTH",
            "EAST",
            "NORTH",
            "LEFT_SHOULDER",
            "RIGHT_SHOULDER",
            "LEFT_TRIGGER",
            "RIGHT_TRIGGER",
            "LEFT_THUMB",
            "RIGHT_THUMB",
        ]
        limit = len(actions) if action_count is None else min(action_count, len(actions))
        for action in actions[:limit]:
            for control in noisy_controls:
                if control not in action:
                    continue
                value = action[control]
                if isinstance(value, np.ndarray):
                    if int(value[0]) != 0:
                        action[control] = np.array([0], dtype=value.dtype)
                        changed += 1
                elif _action_value(action, control):
                    action[control] = 0
                    changed += 1
        return changed

    def _should_camera_scan(self, guidance: MultimodalGuidance) -> bool:
        if guidance.authority not in {"strong", "command"}:
            return False
        if guidance.applied_count < 2:
            return False
        if guidance.direction not in {"forward", "back"}:
            return False
        return guidance.visible_target in {"clear_path", "route", "exit", "opening", "door", "stairs"}

    def _apply_camera_scan(self, actions: list[dict], action_count: int | None = None) -> int:
        changed = 0
        limit = len(actions) if action_count is None else min(action_count, len(actions))
        sweep = 9500 if (int(time.monotonic() * 2) % 2 == 0) else -9500
        for action in actions[:limit]:
            current_x = _action_value(action, "AXIS_RIGHTX")
            current_y = _action_value(action, "AXIS_RIGHTY")
            if abs(current_x) < 7000:
                _set_axis(action, "AXIS_RIGHTX", sweep)
                changed += 1
            if abs(current_y) > 7000:
                _set_axis(action, "AXIS_RIGHTY", 0)
                changed += 1
        return changed

    def _should_press_interact(self, guidance: MultimodalGuidance) -> bool:
        if guidance.intent != "interact" or guidance.confidence < self.min_confidence:
            return False
        if guidance.visible_target in {"interaction_prompt", "readable_text", "menu_ui"}:
            return True
        return guidance.direction == "none" and guidance.visible_target in {
            "pickup",
            "interactable",
            "objective_marker",
        }

    def _apply_interact(self, actions: list[dict]) -> int:
        now = time.monotonic()
        if now - self._last_interact_at < 2.0:
            return 0
        self._last_interact_at = now
        changed = 0
        for action in actions[: min(3, len(actions))]:
            if not _action_value(action, "SOUTH"):
                action["SOUTH"] = 1
                changed += 1
        return changed

    def _apply_light_attack_bias(self, actions: list[dict]) -> int:
        changed = 0
        attack_buttons = ("WEST", "SOUTH", "EAST", "NORTH", "RIGHT_SHOULDER", "RIGHT_TRIGGER")
        for action in actions[: min(4, len(actions))]:
            if not any(_action_value(action, button) for button in attack_buttons):
                action["WEST"] = 1
                changed += 1
        return changed
