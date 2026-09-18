from __future__ import annotations

import json
import os
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from neveludens.shared import BUTTON_ACTION_TOKENS


class FlyVisualEncoder:
    """Convert arbitrary game frames into retina and visual-circuit drives."""

    def __init__(self, brain):
        self.brain = brain
        self.previous_gray: np.ndarray | None = None
        self.previous_target_area = 0.0
        self.static_frames = 0
        self.cells = {
            channel: {side: brain.cells(types, side) for side in "LR"}
            for channel, types in {
                "chase": ["LC10a"],
                "loom": ["LPLC2"],
                "threat": ["LC4"],
                "small": ["LPLC1"],
            }.items()
        }

    @staticmethod
    def _prepare(image) -> tuple[np.ndarray, np.ndarray]:
        rgb = np.asarray(image.convert("RGB") if hasattr(image, "convert") else image)
        if rgb.ndim != 3 or rgb.shape[2] < 3:
            raise ValueError("MaleCNS expected an RGB game frame")
        rgb = cv2.resize(rgb[:, :, :3], (160, 120), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
        return rgb, cv2.GaussianBlur(gray, (5, 5), 0)

    def encode(self, image) -> tuple[np.ndarray, list[tuple[np.ndarray, float]], dict]:
        rgb, gray = self._prepare(image)
        height, width = gray.shape
        usable = gray[int(height * 0.08) : int(height * 0.92)]

        if self.previous_gray is None:
            motion = np.zeros_like(gray)
        else:
            motion = cv2.absdiff(gray, self.previous_gray)
        self.previous_gray = gray

        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        edges = np.clip(cv2.magnitude(gx, gy), 0.0, 1.0)
        saturation = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1].astype(np.float32) / 255.0
        salience = np.clip(motion * 2.8 + edges * 0.28 + saturation * 0.12, 0.0, 1.0)
        salience[: int(height * 0.08)] *= 0.15
        salience[int(height * 0.92) :] *= 0.15

        motion_energy = float(np.mean(motion[int(height * 0.08) : int(height * 0.92)]))
        scene_change = float(np.mean(motion))
        self.static_frames = self.static_frames + 1 if scene_change < 0.012 else 0

        threshold = max(0.16, float(np.percentile(salience, 88)))
        mask = (salience >= threshold).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)

        candidates = []
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area < 18 or area > width * height * 0.48:
                continue
            cx, cy = centroids[label]
            region = labels == label
            score = float(np.mean(salience[region])) * np.sqrt(area)
            score *= 1.0 - min(0.45, abs(cy / height - 0.55) * 0.55)
            candidates.append((score, float(cx), float(cy), area))

        target = max(candidates, default=None)
        target_visible = bool(target is not None and (motion_energy > 0.008 or target[0] > 3.4))
        target_x = 0.0
        target_y = 0.0
        target_area = 0.0
        if target_visible:
            _, cx, cy, area = target
            target_x = float(np.clip((cx / max(1, width - 1)) * 2.0 - 1.0, -1.0, 1.0))
            target_y = float(np.clip((cy / max(1, height - 1)) * 2.0 - 1.0, -1.0, 1.0))
            target_area = float(area / (width * height))

        growth = max(0.0, target_area - self.previous_target_area)
        self.previous_target_area = target_area if target_visible else self.previous_target_area * 0.75
        center_motion = float(np.mean(motion[:, width // 3 : width * 2 // 3]))
        threat = float(np.clip(center_motion * 7.0 + growth * 12.0, 0.0, 1.0))
        looming = float(np.clip(growth * 20.0 + center_motion * 2.0, 0.0, 1.0))

        # MaleCNS photoreceptors receive a compact horizontal panorama. Direct
        # projection-neuron stimulation below carries motion past the graded
        # lamina cells that a point-neuron model cannot reproduce faithfully.
        panorama = 1.0 - np.mean(usable, axis=0)
        panorama = np.clip((panorama - panorama.min()) / (np.ptp(panorama) + 1e-6), 0.0, 1.0)
        columns = np.clip(((self.brain.azimuth + 1.0) * 0.5 * (width - 1)).astype(np.int32), 0, width - 1)
        eye_drive = (panorama[columns] * 0.28).astype(np.float32)

        left_energy = float(np.mean(salience[:, : width // 2]))
        right_energy = float(np.mean(salience[:, width // 2 :]))
        if target_visible:
            side = "L" if target_x < 0 else "R"
        else:
            side = "L" if left_energy > right_energy else "R"

        injections: list[tuple[np.ndarray, float]] = []
        if target_visible:
            chase = float(np.clip(0.48 + target_area * 2.5 + motion_energy * 2.0, 0.0, 0.82))
            injections.append((self.cells["chase"][side], chase))
        elif max(left_energy, right_energy) > 0.12:
            injections.append((self.cells["chase"][side], 0.30))
        if looming > 0.04:
            injections.append((self.cells["loom"][side], min(0.82, 0.30 + looming * 0.55)))
        if threat > 0.10:
            injections.append((self.cells["threat"][side], min(0.86, 0.25 + threat * 0.62)))
        if target_visible and target_area < 0.025 and motion_energy > 0.012:
            injections.append((self.cells["small"][side], 0.46))

        features = {
            "target_visible": target_visible,
            "target_x": target_x,
            "target_y": target_y,
            "target_area": target_area,
            "motion": motion_energy,
            "threat": threat,
            "looming": looming,
            "static_frames": self.static_frames,
            "left_energy": left_energy,
            "right_energy": right_energy,
        }
        return eye_drive, injections, features


class FlyMotorDecoder:
    """Read identified descending neurons and produce bounded gamepad actions."""

    def __init__(self, brain, horizon: int = 6):
        self.brain = brain
        self.horizon = horizon
        self.groups = {
            "steer_l": brain.cells(["DNa02"], "L"),
            "steer_r": brain.cells(["DNa02"], "R"),
            "jump": brain.cells(["DNp01"]),
            "forward": brain.cells(["DNg100"]),
            "backward": brain.cells(["MDN"]),
            "attack": brain.cells(["DNg11"]),
            "secondary": brain.cells(["pIP10"]),
        }
        self.trace = {name: 0.0 for name in self.groups}
        self.previous_x = 0.0
        self.previous_y = -0.45
        self.previous_camera_x = 0.0
        self.previous_camera_y = 0.0
        self.jump_cooldown = 0
        self.attack_cooldown = 0
        self.decision = 0

    def observe_spikes(self, fired: np.ndarray) -> None:
        fired = np.asarray(fired)
        for name, indices in self.groups.items():
            hits = int(np.isin(fired, indices, assume_unique=False).sum())
            density = hits / max(1, len(indices))
            self.trace[name] = self.trace[name] * 0.72 + density

    def actions(self, features: dict) -> tuple[dict, dict]:
        self.decision += 1
        self.jump_cooldown = max(0, self.jump_cooldown - 1)
        self.attack_cooldown = max(0, self.attack_cooldown - 1)

        signed_steer = self.trace["steer_r"] - self.trace["steer_l"]
        neural_x = float(np.tanh(signed_steer * 2.2))
        if abs(neural_x) < 0.12 and features["target_visible"]:
            neural_x = float(np.clip(features["target_x"] * 0.48, -0.48, 0.48))
        elif abs(neural_x) < 0.08 and not features["target_visible"]:
            sensory_bias = features["right_energy"] - features["left_energy"]
            neural_x = float(np.clip(sensory_bias * 1.8, -0.35, 0.35))

        forward_signal = self.trace["forward"]
        backward_signal = self.trace["backward"]
        if backward_signal > forward_signal + 0.42:
            neural_y = 0.62
        elif features["target_visible"] or forward_signal > 0.12:
            neural_y = -0.78
        else:
            neural_y = -0.52

        stuck_escape = features["static_frames"] >= 8
        if stuck_escape:
            phase = (self.decision // 3) % 2
            neural_x = -0.82 if phase == 0 else 0.82
            neural_y = -0.76

        target_close = features["target_visible"] and features["target_area"] > 0.018
        jump = self.jump_cooldown == 0 and (
            self.trace["jump"] > 0.36 or features["looming"] > 0.35 or stuck_escape
        )
        attack = self.attack_cooldown == 0 and target_close and (
            self.trace["attack"] > 0.16 or features["threat"] > 0.22
        )
        secondary = self.attack_cooldown == 0 and target_close and self.trace["secondary"] > 0.30
        if jump:
            self.jump_cooldown = 5
        if attack or secondary:
            self.attack_cooldown = 3

        target_x = float(np.clip(neural_x, -1.0, 1.0))
        target_y = float(np.clip(neural_y, -1.0, 1.0))
        camera_x = 0.0
        camera_y = 0.0
        if features["target_visible"]:
            horizontal_error = float(features["target_x"])
            vertical_error = float(features.get("target_y", 0.0))
            if abs(horizontal_error) > 0.16:
                camera_x = float(
                    np.clip(np.sign(horizontal_error) * (abs(horizontal_error) - 0.16) * 0.72, -0.58, 0.58)
                )
            if abs(vertical_error) > 0.22:
                camera_y = float(
                    np.clip(np.sign(vertical_error) * (abs(vertical_error) - 0.22) * 0.52, -0.38, 0.38)
                )
        elif features["static_frames"] >= 12:
            # Brief low-speed sweeps expose new visual stimuli without spinning continuously.
            camera_x = -0.26 if (self.decision // 4) % 2 == 0 else 0.26

        camera_x_requested = abs(camera_x) > 0.0
        camera_y_requested = abs(camera_y) > 0.0
        old_camera_x = self.previous_camera_x
        old_camera_y = self.previous_camera_y
        camera_blend = 0.42 if features["target_visible"] else 0.28
        camera_x = old_camera_x * (1.0 - camera_blend) + camera_x * camera_blend
        camera_y = old_camera_y * (1.0 - camera_blend) + camera_y * camera_blend
        if camera_x_requested and 0.0 < abs(camera_x) < 0.28:
            camera_x = float(np.copysign(0.28, camera_x))
        if camera_y_requested and 0.0 < abs(camera_y) < 0.24:
            camera_y = float(np.copysign(0.24, camera_y))
        if abs(camera_x) < 0.025:
            camera_x = 0.0
        if abs(camera_y) < 0.025:
            camera_y = 0.0

        j_left = np.zeros((self.horizon, 2), dtype=np.float32)
        j_right = np.zeros((self.horizon, 2), dtype=np.float32)
        buttons = np.zeros((self.horizon, len(BUTTON_ACTION_TOKENS)), dtype=np.float32)
        button_index = {name: idx for idx, name in enumerate(BUTTON_ACTION_TOKENS)}

        for step in range(self.horizon):
            blend = min(1.0, (step + 1) / 3.0)
            j_left[step, 0] = self.previous_x * (1.0 - blend) + target_x * blend
            j_left[step, 1] = self.previous_y * (1.0 - blend) + target_y * blend
            j_right[step, 0] = old_camera_x * (1.0 - blend) + camera_x * blend
            j_right[step, 1] = old_camera_y * (1.0 - blend) + camera_y * blend
        if jump:
            buttons[:2, button_index["SOUTH"]] = 1.0
        if attack:
            buttons[1:3, button_index["WEST"]] = 1.0
        if secondary:
            buttons[2:4, button_index["EAST"]] = 1.0

        self.previous_x, self.previous_y = target_x, target_y
        self.previous_camera_x, self.previous_camera_y = camera_x, camera_y
        state = {
            "steering": target_x,
            "forward": -target_y,
            "camera_x": camera_x,
            "camera_y": camera_y,
            "jump": jump,
            "attack": attack or secondary,
            "stuck_escape": stuck_escape,
            "traces": {key: round(value, 4) for key, value in self.trace.items()},
        }
        return {"j_left": j_left, "j_right": j_right, "buttons": buttons}, state


class MaleCNSPolicy:
    """MaleCNS v1.0 game policy with a generic visual/motor interface."""

    MODEL_ID = "malecns:v1.0"
    def __init__(self, data_dir: Path, telemetry_path: Path | None = None, device: str = "cpu"):
        from flybrain import FlyBrain

        self.data_dir = Path(data_dir)
        self.telemetry_path = Path(telemetry_path) if telemetry_path else None
        self.brain = FlyBrain(
            data=self.data_dir,
            device=device,
            sensory_input=False,
            refractory=0.004,
        )
        self.encoder = FlyVisualEncoder(self.brain)
        self.decoder = FlyMotorDecoder(self.brain)
        self.decision = 0
        self.recent_fired: deque[np.ndarray] = deque(maxlen=4)
        self._layout_bounds = self._position_bounds()
        self._write_layout()
        # Trigger Numba compilation before accepting the first frame.
        self.brain.step()

    def reset(self) -> None:
        self.brain.reset(64)
        self.encoder = FlyVisualEncoder(self.brain)
        self.decoder = FlyMotorDecoder(self.brain)
        self.decision = 0
        self.recent_fired.clear()

    def info(self) -> dict:
        return {
            "engine": "flybrain",
            "model_id": self.MODEL_ID,
            "ckpt_path": "malecns_v1",
            "action_downsample_ratio": 1,
            "neurons": int(self.brain.n),
            "connections": 25_582_938,
            "device": self.brain.device,
        }

    def predict(self, image) -> dict:
        started = time.perf_counter()
        eye_drive, injections, features = self.encoder.encode(image)
        fired_union = []
        for _ in range(4):
            fired = np.asarray(self.brain.step(eye_drive=eye_drive, inject=injections), dtype=np.int64)
            self.decoder.observe_spikes(fired)
            fired_union.append(fired)
            self.recent_fired.append(fired)
        actions, motor = self.decoder.actions(features)
        self.decision += 1
        self._write_telemetry(fired_union, features, motor, (time.perf_counter() - started) * 1000.0)
        return actions

    def _position_bounds(self) -> tuple[np.ndarray, np.ndarray]:
        positions = np.asarray(self.brain.positions, dtype=np.float64)
        valid = np.isfinite(positions).all(axis=1)
        selected = self._project_positions(positions[valid])
        return np.percentile(selected, 1, axis=0), np.percentile(selected, 99, axis=0)

    def _normalized_positions(self, indices: np.ndarray) -> np.ndarray:
        positions = self._project_positions(np.asarray(self.brain.positions[indices], dtype=np.float64))
        lower, upper = self._layout_bounds
        return (positions - lower) / np.maximum(upper - lower, 1.0)

    @staticmethod
    def _project_positions(positions: np.ndarray) -> np.ndarray:
        # Dorsal soma projection: EM X/Y preserves the recognizable bilateral
        # brain silhouette while keeping the central nervous system visible.
        return positions[:, [0, 1]]

    def _inside_layout(self, indices: np.ndarray) -> np.ndarray:
        projected = self._project_positions(
            np.asarray(self.brain.positions[indices], dtype=np.float64)
        )
        lower, upper = self._layout_bounds
        return np.logical_and(projected >= lower, projected <= upper).all(axis=1)

    @staticmethod
    def _sample_activity_levels(
        indices: np.ndarray,
        spike_counts: np.ndarray,
        limit: int = 320,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Keep a balanced sample of weak, medium and peak activity."""
        if len(indices) <= limit:
            return indices, spike_counts
        levels = np.unique(spike_counts)
        quota = max(1, limit // max(1, len(levels)))
        selected = []
        for level in levels:
            group = np.flatnonzero(spike_counts == level)
            if len(group) > quota:
                group = group[np.linspace(0, len(group) - 1, quota, dtype=np.int64)]
            selected.extend(group.tolist())
        selected = np.asarray(selected[:limit], dtype=np.int64)
        return indices[selected], spike_counts[selected]

    def _write_layout(self) -> None:
        if self.telemetry_path is None or self.brain.positions is None:
            return
        positions = np.asarray(self.brain.positions)
        valid_indices = np.flatnonzero(np.isfinite(positions).all(axis=1))
        valid_indices = valid_indices[self._inside_layout(valid_indices)]
        sample_count = min(3200, len(valid_indices))
        random = np.random.default_rng(2026)
        sample = np.sort(random.choice(valid_indices, size=sample_count, replace=False))
        normalized = self._normalized_positions(sample)
        span = self._layout_bounds[1] - self._layout_bounds[0]
        layout = {
            "model": self.MODEL_ID,
            "neurons": int(self.brain.n),
            "projection": "anatomical-dorsal-soma",
            "aspect_ratio": round(float(span[0] / max(span[1], 1.0)), 4),
            "points": [[round(float(x), 4), round(float(1.0 - y), 4)] for x, y in normalized],
        }
        self._atomic_json(self.telemetry_path.with_name("flybrain_layout.json"), layout)

    def _write_telemetry(self, fired_batches, features: dict, motor: dict, latency_ms: float) -> None:
        if self.telemetry_path is None or self.decision % 2:
            return
        all_fired = np.concatenate(fired_batches) if fired_batches else np.empty(0, np.int64)
        fired, spike_counts = np.unique(all_fired, return_counts=True)
        if self.brain.positions is not None and len(fired):
            position_mask = np.isfinite(self.brain.positions[fired]).all(axis=1)
            valid = fired[position_mask]
            valid_counts = spike_counts[position_mask]
            inside = self._inside_layout(valid)
            valid = valid[inside]
            valid_counts = valid_counts[inside]
            valid, valid_counts = self._sample_activity_levels(valid, valid_counts)
            normalized = self._normalized_positions(valid) if len(valid) else np.empty((0, 2))
            active = [
                [round(float(x), 4), round(float(1.0 - y), 4), round(float(count / 4.0), 3)]
                for (x, y), count in zip(normalized, valid_counts)
            ]
        else:
            active = []
        payload = {
            "model": self.MODEL_ID,
            "decision": self.decision,
            "timestamp": time.time(),
            "active_count": int(len(fired)),
            "active": active,
            "features": features,
            "motor": motor,
            "latency_ms": round(latency_ms, 2),
        }
        self._atomic_json(self.telemetry_path, payload)

    @staticmethod
    def _atomic_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, default=MaleCNSPolicy._json_value),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    @staticmethod
    def _json_value(value):
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, Path):
            return str(value)
        raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")
