from __future__ import annotations

import json

import numpy as np
from PIL import Image, ImageDraw

from neveludens.flybrain_policy import FlyMotorDecoder, FlyVisualEncoder, MaleCNSPolicy
from neveludens.shared import BUTTON_ACTION_TOKENS
from scripts.launcher import CHECKPOINT, MODEL_CHOICES, server_matches


class FakeBrain:
    def __init__(self):
        self.azimuth = np.linspace(-1.0, 1.0, 96, dtype=np.float32)
        self._ids = {}
        self._next = 1

    def cells(self, types, side=None):
        key = (tuple(types), side)
        if key not in self._ids:
            count = 4 if types[0] in {"LC10a", "LPLC2", "LC4", "LPLC1"} else 1
            self._ids[key] = np.arange(self._next, self._next + count, dtype=np.int64)
            self._next += count
        return self._ids[key]


def frame_with_object(x: int) -> Image.Image:
    image = Image.new("RGB", (256, 256), (32, 34, 37))
    draw = ImageDraw.Draw(image)
    draw.rectangle((x - 14, 82, x + 14, 184), fill=(232, 232, 232))
    return image


def test_visual_encoder_tracks_a_moving_salient_region():
    brain = FakeBrain()
    encoder = FlyVisualEncoder(brain)
    encoder.encode(frame_with_object(125))
    eye_drive, injections, features = encoder.encode(frame_with_object(194))

    assert eye_drive.shape == brain.azimuth.shape
    assert np.all((eye_drive >= 0.0) & (eye_drive <= 1.0))
    assert features["target_visible"]
    assert features["target_x"] > 0.0
    assert injections


def test_motor_decoder_emits_bounded_actions_without_menu_buttons():
    brain = FakeBrain()
    decoder = FlyMotorDecoder(brain, horizon=6)
    decoder.observe_spikes(brain.cells(["DNa02"], "R"))
    actions, state = decoder.actions(
        {
            "target_visible": True,
            "target_x": 0.7,
            "target_y": -0.5,
            "target_area": 0.04,
            "motion": 0.05,
            "threat": 0.3,
            "looming": 0.0,
            "static_frames": 0,
            "left_energy": 0.05,
            "right_energy": 0.25,
        }
    )

    assert actions["j_left"].shape == (6, 2)
    assert actions["j_right"].shape == (6, 2)
    assert actions["buttons"].shape == (6, len(BUTTON_ACTION_TOKENS))
    assert np.max(np.abs(actions["j_left"])) <= 1.0
    assert actions["j_left"][-1, 0] > 0.0
    assert actions["j_left"][-1, 1] < 0.0
    assert actions["j_right"][-1, 0] >= 0.28
    assert actions["j_right"][-1, 1] <= -0.24
    for name in ("START", "BACK", "GUIDE"):
        assert not actions["buttons"][:, BUTTON_ACTION_TOKENS.index(name)].any()
    assert state["steering"] > 0.0
    assert state["camera_x"] > 0.0
    assert state["camera_y"] < 0.0


def test_telemetry_serializes_numpy_scalars(tmp_path):
    telemetry_path = tmp_path / "telemetry.json"
    MaleCNSPolicy._atomic_json(
        telemetry_path,
        {
            "visible": np.bool_(True),
            "confidence": np.float32(0.75),
            "indices": np.array([1, 2], dtype=np.int64),
        },
    )

    assert json.loads(telemetry_path.read_text(encoding="utf-8")) == {
        "visible": True,
        "confidence": 0.75,
        "indices": [1, 2],
    }


def test_activity_sample_preserves_every_intensity_level():
    indices = np.arange(800, dtype=np.int64)
    counts = np.repeat(np.arange(1, 5, dtype=np.int64), 200)

    sampled_indices, sampled_counts = MaleCNSPolicy._sample_activity_levels(
        indices,
        counts,
        limit=320,
    )

    assert len(sampled_indices) == 320
    assert {int(value) for value in sampled_counts} == {1, 2, 3, 4}
    assert all(np.count_nonzero(sampled_counts == level) == 80 for level in range(1, 5))


def test_only_default_and_malecns_models_are_exposed():
    assert set(MODEL_CHOICES) == {"default", "malecns"}
    assert MODEL_CHOICES["default"]["engine"] == "nitrogen"
    assert MODEL_CHOICES["malecns"]["engine"] == "flybrain"
    assert server_matches(
        {"model_id": "malecns:v1.0", "ckpt_path": "malecns_v1"},
        MODEL_CHOICES["malecns"]["path"],
        MODEL_CHOICES["malecns"],
    )
    assert server_matches(
        {"ckpt_path": str(CHECKPOINT)},
        CHECKPOINT,
        MODEL_CHOICES["default"],
    )
