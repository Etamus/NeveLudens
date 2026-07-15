import os
import sys
import time
import json
from pathlib import Path
from collections import OrderedDict

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageStat

from neveludens.game_env import GamepadEnv
from neveludens.shared import BUTTON_ACTION_TOKENS, PATH_REPO
from neveludens.inference_viz import create_viz, VideoRecorder
from neveludens.inference_client import ModelClient

import argparse
parser = argparse.ArgumentParser(description="VLM Inference")
parser.add_argument("--process", type=str, default="celeste.exe", help="Game to play")
parser.add_argument("--allow-menu", action="store_true", help="Allow menu actions (Disabled by default)")
parser.add_argument("--port", type=int, default=5555, help="Port for model server")
parser.add_argument("--screenshot-backend", choices=["auto", "dxcam", "pyautogui"], default="auto", help="Screenshot backend")
parser.add_argument("--no-special-init", action="store_true", help="Skip game-specific startup button macro")
parser.add_argument("--no-unstuck", action="store_true", help="Disable automatic unstuck actions")

args = parser.parse_args()

policy = ModelClient(port=args.port)
policy.reset()
policy_info = policy.info()
action_downsample_ratio = policy_info["action_downsample_ratio"]

CKPT_NAME = Path(policy_info["ckpt_path"]).stem
NO_MENU = not args.allow_menu
if NO_MENU:
    print("Menu actions blocked: START/BACK/GUIDE predictions will be ignored.")
else:
    print("WARNING: menu actions are allowed; the model may open pause/options menus.")

PATH_DEBUG = PATH_REPO / "debug"
PATH_DEBUG.mkdir(parents=True, exist_ok=True)

PATH_OUT = (PATH_REPO / "out" / CKPT_NAME).resolve()
PATH_OUT.mkdir(parents=True, exist_ok=True)

BUTTON_PRESS_THRES = 0.5
STUCK_FRAME_DIFF_THRES = 0.35
STUCK_FRAME_LIMIT = 12
UNSTUCK_COOLDOWN_STEPS = 8
UNSTUCK_ACTIONS_PER_TRIGGER = 10
UNSTUCK_DIRECTIONS = [
    (26000, 0),
    (-26000, 0),
    (0, -26000),
    (0, 26000),
    (22000, -18000),
    (-22000, 18000),
]

# Find in path_out the list of existing video files, named 0001.mp4, 0002.mp4, etc.
# If they exist, find the max number and set the next number to be max + 1
video_files = sorted(PATH_OUT.glob("*_DEBUG.mp4"))
if video_files:
    existing_numbers = [f.name.split("_")[0] for f in video_files]
    existing_numbers = [int(n) for n in existing_numbers if n.isdigit()]
    next_number = max(existing_numbers) + 1
else:
    next_number = 1

PATH_MP4_DEBUG = PATH_OUT / f"{next_number:04d}_DEBUG.mp4"
PATH_MP4_CLEAN = PATH_OUT / f"{next_number:04d}_CLEAN.mp4"
PATH_ACTIONS = PATH_OUT / f"{next_number:04d}_ACTIONS.json"

def preprocess_img(main_image):
    main_cv = cv2.cvtColor(np.array(main_image), cv2.COLOR_RGB2BGR)
    final_image = cv2.resize(main_cv, (256, 256), interpolation=cv2.INTER_AREA)
    return Image.fromarray(cv2.cvtColor(final_image, cv2.COLOR_BGR2RGB))


def frame_diff_score(current, previous):
    diff = ImageChops.difference(current.convert("L"), previous.convert("L"))
    return ImageStat.Stat(diff).mean[0]


def apply_unstuck_actions(env_actions, attempt):
    lx, ly = UNSTUCK_DIRECTIONS[attempt % len(UNSTUCK_DIRECTIONS)]
    rx, ry = UNSTUCK_DIRECTIONS[(attempt + 2) % len(UNSTUCK_DIRECTIONS)]
    forced_count = min(UNSTUCK_ACTIONS_PER_TRIGGER, len(env_actions))

    for action in env_actions[:forced_count]:
        action["AXIS_LEFTX"] = np.array([lx], dtype=np.long)
        action["AXIS_LEFTY"] = np.array([ly], dtype=np.long)
        action["AXIS_RIGHTX"] = np.array([rx], dtype=np.long)
        action["AXIS_RIGHTY"] = np.array([ry], dtype=np.long)
        action["_UNSTUCK"] = 1

    return forced_count, (lx, ly), (rx, ry)

zero_action = OrderedDict(
        [ 
            ("WEST", 0),
            ("SOUTH", 0),
            ("BACK", 0),
            ("DPAD_DOWN", 0),
            ("DPAD_LEFT", 0),
            ("DPAD_RIGHT", 0),
            ("DPAD_UP", 0),
            ("GUIDE", 0),
            ("AXIS_LEFTX", np.array([0], dtype=np.long)),
            ("AXIS_LEFTY", np.array([0], dtype=np.long)),
            ("LEFT_SHOULDER", 0),
            ("LEFT_TRIGGER", np.array([0], dtype=np.long)),
            ("AXIS_RIGHTX", np.array([0], dtype=np.long)),
            ("AXIS_RIGHTY", np.array([0], dtype=np.long)),
            ("LEFT_THUMB", 0),
            ("RIGHT_THUMB", 0),
            ("RIGHT_SHOULDER", 0),
            ("RIGHT_TRIGGER", np.array([0], dtype=np.long)),
            ("START", 0),
            ("EAST", 0),
            ("NORTH", 0),
        ]
    )

TOKEN_SET = BUTTON_ACTION_TOKENS

print("Model loaded, starting environment...")
for i in range(3):
    print(f"{3 - i}...")
    time.sleep(1)

try:
    env = GamepadEnv(
        game=args.process,
        game_speed=1.0,
        env_fps=60,
        async_mode=True,
        screenshot_backend=args.screenshot_backend,
    )
except ValueError as exc:
    print()
    print(f"Nao consegui encontrar o jogo: {exc}")
    print("Abra o jogo no Windows e use o nome exato do processo .exe.")
    sys.exit(1)
except Exception as exc:
    print()
    print(f"Falha ao iniciar o ambiente do jogo: {exc}")
    sys.exit(1)

# These games may require a menu/button nudge to initialize the controller.
if args.process.lower() in {"isaac-ng.exe", "cuphead.exe"} and not args.no_special_init:
    print(f"GamepadEnv ready for {args.process} at {env.env_fps} FPS")
    input("Press enter to create a virtual controller and start rollouts...")
    for i in range(3):
        print(f"{3 - i}...")
        time.sleep(1)

    def press(button):
        env.gamepad_emulator.press_button(button)
        env.gamepad_emulator.gamepad.update()
        time.sleep(0.05)
        env.gamepad_emulator.release_button(button)
        env.gamepad_emulator.gamepad.update()

    press("SOUTH")
    for k in range(5):
        press("EAST")
        time.sleep(0.3)
elif args.process.lower() in {"isaac-ng.exe", "cuphead.exe"}:
    print(f"Skipping special startup button macro for {args.process}.")

env.reset()
env.pause()


# Initial call to get state
obs, reward, terminated, truncated, info = env.step(action=zero_action)

frames = None
step_count = 0
previous_model_obs = None
still_frame_count = 0
last_unstuck_step = -UNSTUCK_COOLDOWN_STEPS
unstuck_attempt = 0

with VideoRecorder(str(PATH_MP4_DEBUG), fps=60, crf=32, preset="medium") as debug_recorder:
    with VideoRecorder(str(PATH_MP4_CLEAN), fps=60, crf=28, preset="medium") as clean_recorder:
        try:
            while True:
                obs = preprocess_img(obs)
                obs.save(PATH_DEBUG / f"{step_count:05d}.png")

                should_unstuck = False
                if not args.no_unstuck and previous_model_obs is not None:
                    motion = frame_diff_score(obs, previous_model_obs)
                    if motion <= STUCK_FRAME_DIFF_THRES:
                        still_frame_count += 1
                    else:
                        still_frame_count = 0

                    if (
                        still_frame_count >= STUCK_FRAME_LIMIT
                        and step_count - last_unstuck_step >= UNSTUCK_COOLDOWN_STEPS
                    ):
                        should_unstuck = True

                previous_model_obs = obs.copy()

                pred = policy.predict(obs)

                j_left, j_right, buttons = pred["j_left"], pred["j_right"], pred["buttons"]

                n = len(buttons)
                assert n == len(j_left) == len(j_right), "Mismatch in action lengths"


                env_actions = []

                for i in range(n):
                    move_action = zero_action.copy()

                    xl, yl = j_left[i]
                    xr, yr = j_right[i]
                    move_action["AXIS_LEFTX"] = np.array([int(xl * 32767)], dtype=np.long)
                    move_action["AXIS_LEFTY"] = np.array([int(yl * 32767)], dtype=np.long)
                    move_action["AXIS_RIGHTX"] = np.array([int(xr * 32767)], dtype=np.long)
                    move_action["AXIS_RIGHTY"] = np.array([int(yr * 32767)], dtype=np.long)
                    
                    button_vector = buttons[i]
                    assert len(button_vector) == len(TOKEN_SET), "Button vector length does not match token set length"

                    
                    for name, value in zip(TOKEN_SET, button_vector):
                        if "TRIGGER" in name:
                            move_action[name] =  np.array([value * 255], dtype=np.long)
                        else:
                            move_action[name] = 1 if value > BUTTON_PRESS_THRES else 0


                    env_actions.append(move_action)

                if should_unstuck:
                    forced_count, left_dir, right_dir = apply_unstuck_actions(env_actions, unstuck_attempt)
                    print(
                        "Image barely changed for "
                        f"{still_frame_count} model steps; forcing unstuck action "
                        f"#{unstuck_attempt + 1} on {forced_count} subactions "
                        f"(left={left_dir}, right={right_dir})"
                    )
                    last_unstuck_step = step_count
                    unstuck_attempt += 1
                    still_frame_count = 0

                print(f"Executing {len(env_actions)} actions, each action will be repeated {action_downsample_ratio} times")

                for i, a in enumerate(env_actions):
                    if NO_MENU:
                        blocked = [name for name in ("GUIDE", "START", "BACK") if a[name]]
                        if blocked:
                            print(f"Model predicted menu action(s) {blocked}, disabling them")
                        a["GUIDE"] = 0
                        a["START"] = 0
                        a["BACK"] = 0

                    for _ in range(action_downsample_ratio):
                        obs, reward, terminated, truncated, info = env.step(action=a)

                        # resize obs to 720p
                        obs_viz = np.array(obs).copy()
                        clean_viz = cv2.resize(obs_viz, (1920, 1080), interpolation=cv2.INTER_AREA)
                        debug_viz = create_viz(
                            cv2.resize(obs_viz, (1280, 720), interpolation=cv2.INTER_AREA), # 720p
                            i,
                            j_left,
                            j_right,
                            buttons,
                            token_set=TOKEN_SET
                        )
                        debug_recorder.add_frame(debug_viz)
                        clean_recorder.add_frame(clean_viz)

                # Append env_actions dictionnary to JSONL file
                with open(PATH_ACTIONS, "a") as f:
                    for i, a in enumerate(env_actions):
                        # convert numpy arrays to lists for JSON serialization
                        for k, v in a.items():
                            if isinstance(v, np.ndarray):
                                a[k] = v.tolist()
                        a["step"] = step_count
                        a["substep"] = i
                        json.dump(a, f)
                        f.write("\n")


                step_count += 1
        finally:
            env.unpause()
            env.close()
