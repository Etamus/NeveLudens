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
from neveludens.advanced_memory import AdvancedGameMemory
from neveludens.memory import action_value
from neveludens.multimodal_supervisor import AsyncMultimodalSupervisor
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
parser.add_argument("--game-mode", choices=["default", "fighting", "split_screen"], default="default", help="Game-specific optional mode")
parser.add_argument("--agent-slot", choices=["auto", "player2", "player2_coop"], default="auto", help="Agent controller slot preference")
parser.add_argument("--multimodal-supervisor", choices=["disabled", "enabled"], default="disabled", help="Optional Qwen3.5 4B visual supervisor")
parser.add_argument("--advanced-memory", action="store_true", help="Enable opt-in visual/place/result/per-game memory")
recovery_group = parser.add_mutually_exclusive_group()
recovery_group.add_argument("--smart-recovery", dest="smart_recovery", action="store_true", default=True, help="Enable temporal memory and anti-loop recovery")
recovery_group.add_argument("--no-smart-recovery", dest="smart_recovery", action="store_false", help="Disable temporal memory and anti-loop recovery")
parser.add_argument("--no-special-init", action="store_true", help="Skip game-specific startup button macro")
parser.add_argument("--stop-file", default="", help="Internal file used by the GUI to request a safe stop")

args = parser.parse_args()
stop_file = normalize_stop_file(args.stop_file)
menu_allowed = bool(args.allow_menu and not args.block_menu)

env = None
multimodal_supervisor = None
advanced_memory = None
_cleanup_done = False


def check_stop():
    raise_if_stop_requested(stop_file)


def cleanup_environment():
    global env, _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    if multimodal_supervisor is not None:
        try:
            multimodal_supervisor.close()
        except Exception:
            pass
    if advanced_memory is not None:
        try:
            advanced_memory.close()
        except Exception:
            pass
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
if args.game_mode == "split_screen":
    original_downsample_ratio = action_downsample_ratio
    action_downsample_ratio = 1
    print(
        "Modo Tela dividida: inputs acelerados "
        f"(action_downsample_ratio {original_downsample_ratio} -> {action_downsample_ratio})."
    )
debug_outputs = args.output_mode == "debug"
print(f"Modo de captura: {args.runtime_mode}")
print(f"Saidas: {args.output_mode}")
print(f"Modo de jogo: {args.game_mode}")
print(f"Modo de jogador: {args.agent_slot}")
print(f"Supervisor multimodal: {args.multimodal_supervisor}")
print(f"Recuperacao inteligente: {'ligada' if args.smart_recovery else 'desligada'}")
print(f"Memoria avancada: {'ligada' if args.advanced_memory else 'desligada'}")

CKPT_NAME = Path(policy_info["ckpt_path"]).stem
if not menu_allowed:
    print("Ações de menu bloqueadas: previsões START/BACK/GUIDE serão ignoradas.")
else:
    print("Ações de menu liberadas: previsões START/BACK/GUIDE podem chegar ao jogo.")

BUTTON_PRESS_THRES = 0.5

PATH_DEBUG = PATH_REPO / "debug"
PATH_OUT = (PATH_REPO / "out" / CKPT_NAME).resolve()
PATH_LAST_MODEL_CAPTURE = (PATH_REPO / "out" / "last_model_capture.png").resolve()

PATH_MP4_DEBUG = None
PATH_MP4_CLEAN = None
PATH_ACTIONS = None
PATH_SUPERVISOR = None
last_capture_warning_shown = False


def save_last_model_capture(image):
    """Persist one replaceable preview without creating per-frame artifacts."""
    global last_capture_warning_shown
    temporary_path = PATH_LAST_MODEL_CAPTURE.with_suffix(".tmp.png")
    try:
        PATH_LAST_MODEL_CAPTURE.parent.mkdir(parents=True, exist_ok=True)
        image.save(temporary_path, format="PNG", compress_level=1)
        os.replace(temporary_path, PATH_LAST_MODEL_CAPTURE)
    except Exception as exc:
        if not last_capture_warning_shown:
            print(f"Aviso: não foi possível salvar a última captura do modelo: {exc}")
            last_capture_warning_shown = True
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass

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
if args.game_mode == "split_screen":
    print("Modo Tela dividida ativado: modelo e VLM recebem somente a metade esquerda da tela.")
    print("Modo Tela dividida: continuidade de input e escape anti-travamento ativados.")
advanced_memory = AdvancedGameMemory(
    process_name=args.process,
    enabled=args.advanced_memory,
)
if args.advanced_memory:
    print("Memoria avancada ativada: visual curta, lugares, resultados, memoria por jogo e resumo para VLM.")
multimodal_supervisor = AsyncMultimodalSupervisor(
    enabled=args.multimodal_supervisor == "enabled",
    process_name=args.process,
    game_mode="default" if args.game_mode == "split_screen" else args.game_mode,
)
if args.multimodal_supervisor == "enabled":
    print("Supervisor multimodal ativado: Qwen3.5 4B, bitsandbytes 4-bit, assincrono.")

def preprocess_img(main_image):
    main_cv = cv2.cvtColor(np.array(main_image), cv2.COLOR_RGB2BGR)
    final_image = cv2.resize(main_cv, (256, 256), interpolation=cv2.INTER_AREA)
    return Image.fromarray(cv2.cvtColor(final_image, cv2.COLOR_BGR2RGB))


def crop_left_half(image):
    width, height = image.size
    return image.crop((0, 0, max(1, width // 2), height))


class SplitScreenInputAssist:
    """Small input-only assist for split-screen mode.

    It does not inspect objects, paths or targets. It only prevents long neutral
    controller gaps and applies a short alternate movement when visual progress
    appears stuck.
    """

    def __init__(self, enabled):
        self.enabled = enabled
        self.last_lx = 0
        self.last_ly = -22000
        self.passive_streak = 0
        self.escape_index = 0
        self.last_escape_step = -999

    def apply(self, actions, perception, memory_snapshot, step):
        if not self.enabled or not actions:
            return []
        if perception.is_dark or perception.likely_loading or perception.likely_menu_or_overlay:
            self.passive_streak = 0
            return []

        reasons = []
        movement_ratio = self._movement_ratio(actions)
        observed_move = self._last_observed_movement(actions)
        if observed_move is not None:
            self.last_lx, self.last_ly = observed_move

        stuck_reason = self._stuck_reason(perception, memory_snapshot, movement_ratio)
        if stuck_reason and step - self.last_escape_step >= 4:
            lx, ly = self._next_escape()
            changed = self._apply_movement(actions, lx, ly, force=True, tail_only=False, camera=True)
            if changed:
                self.last_lx, self.last_ly = lx, ly
                self.last_escape_step = step
                reasons.append(f"escape anti-travamento: {stuck_reason}")
            return reasons

        if movement_ratio < 0.22:
            self.passive_streak += 1
        else:
            self.passive_streak = 0

        if self.passive_streak >= 1:
            changed = self._apply_movement(
                actions,
                self.last_lx,
                self.last_ly,
                force=False,
                tail_only=False,
                camera=False,
            )
            if changed:
                reasons.append("continuidade de movimento durante pausa do modelo")
        elif observed_move is not None:
            changed = self._apply_movement(
                actions,
                self.last_lx,
                self.last_ly,
                force=False,
                tail_only=True,
                camera=False,
            )
            if changed:
                reasons.append("mantendo ultimo movimento entre predicoes")
        return reasons

    def _movement_ratio(self, actions):
        moving = 0
        for action in actions:
            if self._has_movement(action):
                moving += 1
        return moving / max(1, len(actions))

    def _has_movement(self, action):
        return (
            abs(action_value(action, "AXIS_LEFTX")) > 8500
            or abs(action_value(action, "AXIS_LEFTY")) > 8500
            or bool(action.get("DPAD_LEFT", 0))
            or bool(action.get("DPAD_RIGHT", 0))
            or bool(action.get("DPAD_UP", 0))
            or bool(action.get("DPAD_DOWN", 0))
        )

    def _last_observed_movement(self, actions):
        for action in reversed(actions):
            lx = action_value(action, "AXIS_LEFTX")
            ly = action_value(action, "AXIS_LEFTY")
            if abs(lx) > 8500 or abs(ly) > 8500:
                return lx, ly
            if action.get("DPAD_LEFT", 0):
                return -22000, 0
            if action.get("DPAD_RIGHT", 0):
                return 22000, 0
            if action.get("DPAD_UP", 0):
                return 0, -22000
            if action.get("DPAD_DOWN", 0):
                return 0, 22000
        return None

    def _stuck_reason(self, perception, memory_snapshot, movement_ratio):
        low_motion = int(memory_snapshot.get("low_motion_streak", 0) or 0)
        static = int(memory_snapshot.get("static_streak", 0) or 0)
        repeated = int(memory_snapshot.get("repeated_action_streak", 0) or 0)
        if perception.likely_static_screen and movement_ratio >= 0.20:
            return "tela estatica com movimento ativo"
        if low_motion >= 3 and movement_ratio >= 0.20:
            return f"{low_motion} passos com pouco movimento visual"
        if static >= 3:
            return f"{static} passos em tela quase igual"
        if repeated >= 5 and movement_ratio < 0.35:
            return f"{repeated} acoes repetidas sem deslocamento"
        return ""

    def _next_escape(self):
        escapes = [
            (26000, 0),
            (-26000, 0),
            (0, 23000),
            (22000, -12000),
            (-22000, -12000),
            (0, -24000),
        ]
        lx, ly = escapes[self.escape_index % len(escapes)]
        self.escape_index += 1
        return lx, ly

    def _apply_movement(self, actions, lx, ly, force, tail_only, camera):
        changed = 0
        selected = actions[-3:] if tail_only else actions
        for action in selected:
            changed += self._set_axis(action, "AXIS_LEFTX", lx, force)
            changed += self._set_axis(action, "AXIS_LEFTY", ly, force)
            if camera and lx:
                changed += self._set_axis(action, "AXIS_RIGHTX", int(lx * 0.45), False)
            changed += self._set_dpad(action, lx, ly, force)
        return changed

    def _set_axis(self, action, name, value, force):
        current = action_value(action, name)
        if current == value:
            return 0
        same_direction = current == 0 or current * value >= 0
        stronger = abs(value) > abs(current)
        if not force and not (same_direction and stronger):
            return 0
        action[name] = np.array([int(value)], dtype=np.long)
        return 1

    def _set_dpad(self, action, lx, ly, force):
        changed = 0
        values = {
            "DPAD_LEFT": lx < -5000,
            "DPAD_RIGHT": lx > 5000,
            "DPAD_UP": ly < -5000,
            "DPAD_DOWN": ly > 5000,
        }
        for name, value in values.items():
            if name not in action:
                continue
            new_value = 1 if value else 0
            current = 1 if action.get(name, 0) else 0
            if current == new_value:
                continue
            if not force and current and not new_value:
                continue
            action[name] = new_value
            changed += 1
        return changed

split_screen_input_assist = SplitScreenInputAssist(enabled=args.game_mode == "split_screen")

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


def run_player2_coop_join_macro():
    print("Modo Player 2 Co-op: confirmando, aguardando 5s, movendo para a esquerda, confirmando e aguardando de novo...")
    env.gamepad_emulator.reset()
    time.sleep(0.1)

    press_gamepad_button("SOUTH", duration=0.12)
    time.sleep(5.0)

    env.gamepad_emulator.set_joystick("AXIS_LEFTX", -32768)
    env.gamepad_emulator.set_joystick("AXIS_LEFTY", 0)
    env.gamepad_emulator.press_button("DPAD_LEFT")
    env.gamepad_emulator.gamepad.update()
    time.sleep(0.55)

    env.gamepad_emulator.release_button("DPAD_LEFT")
    env.gamepad_emulator.set_joystick("AXIS_LEFTX", 0)
    env.gamepad_emulator.set_joystick("AXIS_LEFTY", 0)
    env.gamepad_emulator.gamepad.update()
    time.sleep(0.12)

    press_gamepad_button("SOUTH", duration=0.12)
    time.sleep(5.0)
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
elif args.agent_slot == "player2_coop":
    check_stop()
    run_player2_coop_join_macro()
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
                raw_obs = obs
                model_raw_obs = crop_left_half(raw_obs) if args.game_mode == "split_screen" else raw_obs
                obs = preprocess_img(model_raw_obs)
                if debug_outputs:
                    obs.save(PATH_DEBUG / f"{step_count:05d}.png")
                    save_last_model_capture(obs)
                perception_state = supervisor.observe(obs, step_count)
                advanced_memory_state = {}
                if advanced_memory is not None and advanced_memory.enabled:
                    advanced_memory_state = advanced_memory.observe(model_raw_obs, perception_state, step_count)

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

                vlm_memory = dict(decision.memory or {})
                if advanced_memory_state:
                    vlm_memory["advanced"] = advanced_memory.vlm_summary()

                multimodal_supervisor.submit(
                    model_raw_obs,
                    perception_state,
                    vlm_memory,
                    decision.profile,
                    step_count,
                )

                fighting_decision = fighting_assist.apply(env_actions, perception_state, step_count, obs)
                if fighting_decision.reasons:
                    print(f"Fighting[{fighting_decision.changed_actions}]: {'; '.join(fighting_decision.reasons)}")

                multimodal_reasons = multimodal_supervisor.apply(env_actions)
                if multimodal_reasons:
                    print(f"Supervisor multimodal: {'; '.join(multimodal_reasons)}")

                if advanced_memory is not None and advanced_memory.enabled:
                    advanced_decision = advanced_memory.process_actions(env_actions, perception_state, step_count)
                    if advanced_decision.reasons:
                        print(f"Memoria avancada[{advanced_decision.changed_actions}]: {'; '.join(advanced_decision.reasons)}")

                split_reasons = split_screen_input_assist.apply(
                    env_actions,
                    perception_state,
                    decision.memory,
                    step_count,
                )
                if split_reasons:
                    print(f"Tela dividida: {'; '.join(split_reasons)}")

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
