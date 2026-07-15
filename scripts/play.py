import os
import sys
import time
import json
from pathlib import Path
from collections import OrderedDict

import cv2
import numpy as np
from PIL import Image

from neveludens.game_env import GamepadEnv
from neveludens.shared import BUTTON_ACTION_TOKENS, PATH_REPO
from neveludens.inference_viz import create_viz, VideoRecorder
from neveludens.inference_client import ModelClient
from neveludens.supervisor import ObjectiveSupervisor

import argparse
parser = argparse.ArgumentParser(description="VLM Inference")
parser.add_argument("--process", type=str, default="celeste.exe", help="Game to play")
parser.add_argument("--allow-menu", action="store_true", help="Allow menu actions (kept for compatibility)")
parser.add_argument("--block-menu", action="store_true", help="Block START/BACK/GUIDE menu actions")
parser.add_argument("--port", type=int, default=5555, help="Port for model server")
parser.add_argument("--screenshot-backend", choices=["auto", "dxcam", "pyautogui"], default="auto", help="Screenshot backend")
parser.add_argument("--no-special-init", action="store_true", help="Skip game-specific startup button macro")
parser.add_argument("--no-unstuck", action="store_true", help="Disable supervisor recovery skills")

args = parser.parse_args()
menu_allowed = not args.block_menu

policy = ModelClient(port=args.port)
policy.reset()
policy_info = policy.info()
action_downsample_ratio = policy_info["action_downsample_ratio"]

CKPT_NAME = Path(policy_info["ckpt_path"]).stem
if not menu_allowed:
    print("Ações de menu bloqueadas: previsões START/BACK/GUIDE serão ignoradas.")
else:
    print("Ações de menu liberadas: previsões START/BACK/GUIDE podem chegar ao jogo.")

PATH_DEBUG = PATH_REPO / "debug"
PATH_DEBUG.mkdir(parents=True, exist_ok=True)

PATH_OUT = (PATH_REPO / "out" / CKPT_NAME).resolve()
PATH_OUT.mkdir(parents=True, exist_ok=True)

BUTTON_PRESS_THRES = 0.5

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
PATH_SUPERVISOR = PATH_OUT / f"{next_number:04d}_SUPERVISOR.json"

supervisor = ObjectiveSupervisor(
    process_name=args.process,
    allow_menu=menu_allowed,
    enable_skills=not args.no_unstuck,
    log_path=PATH_SUPERVISOR,
)
print(f"Supervisor profile: {supervisor.profile.name} ({supervisor.profile.genre})")
if args.no_unstuck:
    print("Skills de recuperação do supervisor desativadas.")

def preprocess_img(main_image):
    main_cv = cv2.cvtColor(np.array(main_image), cv2.COLOR_RGB2BGR)
    final_image = cv2.resize(main_cv, (256, 256), interpolation=cv2.INTER_AREA)
    return Image.fromarray(cv2.cvtColor(final_image, cv2.COLOR_BGR2RGB))

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
    print(f"Não consegui encontrar o jogo: {exc}")
    print("Abra o jogo no Windows e use o nome exato do processo .exe.")
    sys.exit(1)
except Exception as exc:
    print()
    print(f"Falha ao iniciar o ambiente do jogo: {exc}")
    sys.exit(1)

# These games may require a menu/button nudge to initialize the controller.
if args.process.lower() in {"isaac-ng.exe", "cuphead.exe"} and not args.no_special_init:
    print(f"GamepadEnv ready for {args.process} at {env.env_fps} FPS")
    print("Executando macro automática de inicialização para este jogo...")
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

with VideoRecorder(str(PATH_MP4_DEBUG), fps=60, crf=32, preset="medium") as debug_recorder:
    with VideoRecorder(str(PATH_MP4_CLEAN), fps=60, crf=28, preset="medium") as clean_recorder:
        try:
            while True:
                obs = preprocess_img(obs)
                obs.save(PATH_DEBUG / f"{step_count:05d}.png")
                supervisor.observe(obs, step_count)

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

                decision = supervisor.process_actions(env_actions, step_count)
                if decision.reasons:
                    print(f"Supervisor[{decision.profile}/{decision.objective}]: {'; '.join(decision.reasons)}")

                print(f"Executing {len(env_actions)} actions, each action will be repeated {action_downsample_ratio} times")

                for i, a in enumerate(env_actions):
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
