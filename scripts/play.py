import os
import sys
import time
import json
import atexit
from pathlib import Path
from collections import OrderedDict
from contextlib import nullcontext

import cv2
import numpy as np
from PIL import Image

from neveludens.game_env import GamepadEnv
from neveludens.shared import BUTTON_ACTION_TOKENS, PATH_REPO
from neveludens.inference_viz import create_viz, VideoRecorder
from neveludens.inference_client import ModelClient
from neveludens.supervisor import ObjectiveSupervisor
from neveludens.fighting import FightingAssist
from neveludens.stop_control import normalize_stop_file, raise_if_stop_requested

import argparse
parser = argparse.ArgumentParser(description="VLM Inference")
parser.add_argument("--process", type=str, default="celeste.exe", help="Game to play")
parser.add_argument("--allow-menu", action="store_true", help="Allow menu actions (kept for compatibility)")
parser.add_argument("--block-menu", action="store_true", help="Block START/BACK/GUIDE menu actions")
parser.add_argument("--port", type=int, default=5555, help="Port for model server")
parser.add_argument("--screenshot-backend", choices=["auto", "dxcam", "pyautogui"], default="auto", help="Screenshot backend")
parser.add_argument("--runtime-mode", choices=["precision", "realtime"], default="precision", help="Runtime mode")
parser.add_argument("--output-mode", choices=["normal", "debug"], default="normal", help="Output mode")
parser.add_argument("--game-mode", choices=["default", "fighting"], default="default", help="Game-specific optional mode")
parser.add_argument("--agent-slot", choices=["auto", "player2"], default="auto", help="Agent controller slot preference")
recovery_group = parser.add_mutually_exclusive_group()
recovery_group.add_argument("--smart-recovery", dest="smart_recovery", action="store_true", default=True, help="Enable temporal memory and anti-loop recovery")
recovery_group.add_argument("--no-smart-recovery", dest="smart_recovery", action="store_false", help="Disable temporal memory and anti-loop recovery")
parser.add_argument("--no-special-init", action="store_true", help="Skip game-specific startup button macro")
parser.add_argument("--stop-file", default="", help="Internal file used by the GUI to request a safe stop")

args = parser.parse_args()
stop_file = normalize_stop_file(args.stop_file)
menu_allowed = not args.block_menu

env = None
_cleanup_done = False


def check_stop():
    raise_if_stop_requested(stop_file)


def cleanup_environment():
    global env, _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    if env is None:
        return
    try:
        env.unpause()
    except Exception as exc:
        print(f"Falha ao devolver velocidade normal ao jogo: {exc}")
    try:
        env.close()
    except Exception as exc:
        print(f"Falha ao fechar ambiente do jogo: {exc}")


atexit.register(cleanup_environment)

check_stop()
policy = ModelClient(port=args.port, stop_file=stop_file)
policy.reset()
policy_info = policy.info()
check_stop()
action_downsample_ratio = policy_info["action_downsample_ratio"]
debug_outputs = args.output_mode == "debug"
print(f"Modo de captura: {args.runtime_mode}")
print(f"Saidas: {args.output_mode}")
print(f"Modo de jogo: {args.game_mode}")
print(f"Jogador do agente: {args.agent_slot}")
print(f"Recuperacao inteligente: {'ligada' if args.smart_recovery else 'desligada'}")

CKPT_NAME = Path(policy_info["ckpt_path"]).stem
if not menu_allowed:
    print("Ações de menu bloqueadas: previsões START/BACK/GUIDE serão ignoradas.")
else:
    print("Ações de menu liberadas: previsões START/BACK/GUIDE podem chegar ao jogo.")

BUTTON_PRESS_THRES = 0.5

PATH_DEBUG = PATH_REPO / "debug"
PATH_OUT = (PATH_REPO / "out" / CKPT_NAME).resolve()

PATH_MP4_DEBUG = None
PATH_MP4_CLEAN = None
PATH_ACTIONS = None
PATH_SUPERVISOR = None

if debug_outputs:
    PATH_DEBUG.mkdir(parents=True, exist_ok=True)
    PATH_OUT.mkdir(parents=True, exist_ok=True)

    artifact_files = []
    for pattern in ("*_DEBUG.mp4", "*_CLEAN.mp4", "*_ACTIONS.json", "*_SUPERVISOR.json"):
        artifact_files.extend(PATH_OUT.glob(pattern))
    existing_numbers = [f.name.split("_")[0] for f in artifact_files]
    existing_numbers = [int(n) for n in existing_numbers if n.isdigit()]
    next_number = max(existing_numbers, default=0) + 1

    PATH_MP4_DEBUG = PATH_OUT / f"{next_number:04d}_DEBUG.mp4"
    PATH_MP4_CLEAN = PATH_OUT / f"{next_number:04d}_CLEAN.mp4"
    PATH_ACTIONS = PATH_OUT / f"{next_number:04d}_ACTIONS.json"
    PATH_SUPERVISOR = PATH_OUT / f"{next_number:04d}_SUPERVISOR.json"

supervisor = ObjectiveSupervisor(
    process_name=args.process,
    allow_menu=menu_allowed,
    enable_recovery=args.smart_recovery,
    log_path=PATH_SUPERVISOR,
)
print(f"Supervisor profile: {supervisor.profile.name} ({supervisor.profile.genre})")
if not args.smart_recovery:
    print("Recuperacao inteligente desativada.")
fighting_assist = FightingAssist(
    enabled=args.game_mode == "fighting",
    process_name=args.process,
    agent_slot=args.agent_slot,
)
if fighting_assist.enabled:
    print("Modo jogo de luta ativado: movimento lateral, pulos e ritmo de ataque incentivados.")

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
    check_stop()
    print(f"{3 - i}...")
    time.sleep(1)

try:
    check_stop()
    env = GamepadEnv(
        game=args.process,
        game_speed=1.0,
        env_fps=60,
        async_mode=True,
        screenshot_backend=args.screenshot_backend,
        runtime_mode=args.runtime_mode,
        agent_slot=args.agent_slot,
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


def press_gamepad_button(button, duration=0.08):
    env.gamepad_emulator.press_button(button)
    env.gamepad_emulator.gamepad.update()
    time.sleep(duration)
    env.gamepad_emulator.release_button(button)
    env.gamepad_emulator.gamepad.update()


def run_player2_join_macro():
    print("Modo Player 2: movendo para a direita e confirmando entrada...")
    env.gamepad_emulator.reset()
    time.sleep(0.1)

    env.gamepad_emulator.set_joystick("AXIS_LEFTX", 32767)
    env.gamepad_emulator.set_joystick("AXIS_LEFTY", 0)
    env.gamepad_emulator.press_button("DPAD_RIGHT")
    env.gamepad_emulator.gamepad.update()
    time.sleep(0.55)

    env.gamepad_emulator.release_button("DPAD_RIGHT")
    env.gamepad_emulator.set_joystick("AXIS_LEFTX", 0)
    env.gamepad_emulator.set_joystick("AXIS_LEFTY", 0)
    env.gamepad_emulator.gamepad.update()
    time.sleep(0.12)

    press_gamepad_button("SOUTH", duration=0.12)
    time.sleep(0.15)
    env.gamepad_emulator.reset()


# These games may require a menu/button nudge to initialize the controller.
if args.process.lower() in {"isaac-ng.exe", "cuphead.exe"} and not args.no_special_init:
    print(f"GamepadEnv ready for {args.process} at {env.env_fps} FPS")
    print("Executando macro automática de inicialização para este jogo...")
    for i in range(3):
        check_stop()
        print(f"{3 - i}...")
        time.sleep(1)

    def press(button):
        press_gamepad_button(button, duration=0.05)

    press("SOUTH")
    for k in range(5):
        check_stop()
        press("EAST")
        time.sleep(0.3)
elif args.process.lower() in {"isaac-ng.exe", "cuphead.exe"}:
    print(f"Skipping special startup button macro for {args.process}.")

env.reset()
if args.agent_slot == "player2":
    check_stop()
    run_player2_join_macro()
env.pause()


# Initial call to get state
check_stop()
obs, reward, terminated, truncated, info = env.step(action=zero_action)

frames = None
step_count = 0

debug_recorder_context = VideoRecorder(str(PATH_MP4_DEBUG), fps=60, crf=32, preset="medium") if debug_outputs else nullcontext(None)
clean_recorder_context = VideoRecorder(str(PATH_MP4_CLEAN), fps=60, crf=28, preset="medium") if debug_outputs else nullcontext(None)

with debug_recorder_context as debug_recorder:
    with clean_recorder_context as clean_recorder:
        try:
            while True:
                check_stop()
                obs = preprocess_img(obs)
                if debug_outputs:
                    obs.save(PATH_DEBUG / f"{step_count:05d}.png")
                perception_state = supervisor.observe(obs, step_count)

                pred = policy.predict(obs)
                check_stop()

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

                fighting_decision = fighting_assist.apply(env_actions, perception_state, step_count, obs)
                if fighting_decision.reasons:
                    print(f"Fighting[{fighting_decision.changed_actions}]: {'; '.join(fighting_decision.reasons)}")

                if debug_outputs:
                    print(f"Executing {len(env_actions)} actions, each action will be repeated {action_downsample_ratio} times")

                for i, a in enumerate(env_actions):
                    for _ in range(action_downsample_ratio):
                        check_stop()
                        obs, reward, terminated, truncated, info = env.step(action=a)

                        if debug_outputs:
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
                if debug_outputs:
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
            cleanup_environment()
