import ctypes
import time
import platform
from dataclasses import dataclass

import pyautogui
import dxcam
import pywinctl as pwc
from gymnasium import Env
from gymnasium.spaces import Box, Dict, Discrete
from PIL import Image, ImageChops, ImageStat

import time

import vgamepad as vg

import psutil

assert platform.system().lower() == "windows", "This module is only supported on Windows."
import win32process
import win32gui
import win32api
import win32con

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


def active_xinput_slots():
    """
    Return active XInput indexes without adding dependencies.

    Windows/game APIs decide player order. This gives the Player 2 mode a
    conservative way to know whether a real controller already occupies P1.
    """
    xinput = None
    for dll_name in ("xinput1_4", "xinput9_1_0", "xinput1_3"):
        try:
            xinput = ctypes.windll.LoadLibrary(dll_name)
            break
        except OSError:
            continue
    if xinput is None:
        return []

    class XINPUT_GAMEPAD(ctypes.Structure):
        _fields_ = [
            ("wButtons", ctypes.c_ushort),
            ("bLeftTrigger", ctypes.c_ubyte),
            ("bRightTrigger", ctypes.c_ubyte),
            ("sThumbLX", ctypes.c_short),
            ("sThumbLY", ctypes.c_short),
            ("sThumbRX", ctypes.c_short),
            ("sThumbRY", ctypes.c_short),
        ]

    class XINPUT_STATE(ctypes.Structure):
        _fields_ = [
            ("dwPacketNumber", ctypes.c_ulong),
            ("Gamepad", XINPUT_GAMEPAD),
        ]

    xinput.XInputGetState.argtypes = [ctypes.c_uint, ctypes.POINTER(XINPUT_STATE)]
    xinput.XInputGetState.restype = ctypes.c_uint

    active = []
    for index in range(4):
        state = XINPUT_STATE()
        if xinput.XInputGetState(index, ctypes.byref(state)) == 0:
            active.append(index)
    return active


def get_process_info(process_name):
    """
    Get process information for a given process name on Windows.

    Args:
        process_name (str): Name of the process (e.g., "isaac-ng.exe")

    Returns:
        list: List of dictionaries containing PID, window_name, and architecture
              for each matching process. Returns empty list if no process found.
    """
    results = []
    proxy_keywords = ['d3dproxywindow', 'proxy', 'helper', 'overlay', 'crash', 'cef', 'webview']

    def window_area(hwnd):
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            return 0
        return max(0, right - left) * max(0, bottom - top)

    def score_window(window):
        title = str(window.get("title", "")).lower()
        area = int(window.get("area", 0))
        score = 0
        if window.get("visible"):
            score += 100
        if not window.get("iconic"):
            score += 35
        if area > 0:
            score += min(80, area // 12000)
        if any(keyword in title for keyword in proxy_keywords):
            score -= 80
        if process_name.rsplit(".", 1)[0].lower() in title:
            score += 8
        return score

    # Find all processes with the given name
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'].lower() == process_name.lower():
                pid = proc.info['pid']

                # Get architecture
                try:
                    # Check if process is 32-bit or 64-bit
                    process_handle = win32api.OpenProcess(
                        win32con.PROCESS_QUERY_INFORMATION,
                        False,
                        pid
                    )
                    is_wow64 = win32process.IsWow64Process(process_handle)
                    win32api.CloseHandle(process_handle)

                    # On 64-bit Windows: WOW64 means "Windows 32-bit on Windows 64-bit", i.e. a 32-bit process
                    architecture = "x86" if is_wow64 else "x64"
                except:
                    architecture = "unknown"

                # Find visible windows associated with this PID. Some games spawn
                # multiple same-name helper processes; prefer the process that
                # owns an actual game-sized window.
                windows = []

                def enum_window_callback(hwnd, pid_to_find):
                    _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                    if found_pid == pid_to_find:
                        window_text = win32gui.GetWindowText(hwnd).strip()
                        visible = bool(win32gui.IsWindowVisible(hwnd))
                        area = window_area(hwnd)
                        if visible and area > 0:
                            windows.append({
                                'hwnd': hwnd,
                                'title': window_text,
                                'visible': visible,
                                'iconic': bool(win32gui.IsIconic(hwnd)),
                                'area': area,
                                'score': 0,
                            })
                    return True

                # Find all windows for this PID
                try:
                    win32gui.EnumWindows(enum_window_callback, pid)
                except:
                    pass

                # Choose the best window
                window_name = None
                window_hwnd = None
                window_score = 0
                window_area_value = 0
                if windows:
                    if len(windows) > 1:
                        print(f"Multiple windows found for PID {pid}: {[win['title'] for win in windows]}")
                        print("Using heuristics to select the correct window...")
                    for win in windows:
                        win['score'] = score_window(win)
                    windows.sort(key=lambda win: (win['score'], win['area']), reverse=True)
                    selected = windows[0]
                    window_name = selected['title']
                    window_hwnd = selected['hwnd']
                    window_score = selected['score']
                    window_area_value = selected['area']

                results.append({
                    'pid': pid,
                    'window_name': window_name,
                    'hwnd': window_hwnd,
                    'window_score': window_score,
                    'window_area': window_area_value,
                    'architecture': architecture
                })

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if len(results) == 0:
        raise ValueError(f"No process found with name: {process_name}")
    windowed_results = [result for result in results if result.get('hwnd')]
    if not windowed_results:
        pids = ", ".join(str(result["pid"]) for result in results)
        raise ValueError(
            f"Process '{process_name}' is running (PID(s): {pids}), but no visible game window was found. "
            "Restore the game window, wait past launch/loading helpers, and avoid selecting a launcher/background process."
        )

    windowed_results.sort(
        key=lambda result: (int(result.get('window_score') or 0), int(result.get('window_area') or 0)),
        reverse=True,
    )
    selected = windowed_results[0]
    if len(results) > 1:
        summary = ", ".join(
            f"PID {item['pid']} window={item.get('window_name') or 'None'}"
            for item in results
        )
        print(f"Warning: Multiple processes found with name '{process_name}': {summary}")
        print(
            "Selected process with visible window: "
            f"PID {selected['pid']} ({selected.get('window_name') or 'sem titulo'})"
        )

    return selected


XBOX_MAPPING = {
    "DPAD_UP": "XUSB_GAMEPAD_DPAD_UP",
    "DPAD_DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
    "DPAD_LEFT": "XUSB_GAMEPAD_DPAD_LEFT",
    "DPAD_RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
    "START": "XUSB_GAMEPAD_START",
    "BACK": "XUSB_GAMEPAD_BACK",
    "LEFT_SHOULDER": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "RIGHT_SHOULDER": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "GUIDE": "XUSB_GAMEPAD_GUIDE",
    "WEST": "XUSB_GAMEPAD_X",
    "SOUTH": "XUSB_GAMEPAD_A",
    "EAST": "XUSB_GAMEPAD_B",
    "NORTH": "XUSB_GAMEPAD_Y",
    "LEFT_TRIGGER": "LEFT_TRIGGER",
    "RIGHT_TRIGGER": "RIGHT_TRIGGER",
    "AXIS_LEFTX": "LEFT_JOYSTICK",
    "AXIS_LEFTY": "LEFT_JOYSTICK",
    "AXIS_RIGHTX": "RIGHT_JOYSTICK",
    "AXIS_RIGHTY": "RIGHT_JOYSTICK",
    "LEFT_THUMB": "XUSB_GAMEPAD_LEFT_THUMB",
    "RIGHT_THUMB": "XUSB_GAMEPAD_RIGHT_THUMB",
}

PS4_MAPPING = {
    "DPAD_UP": "DS4_BUTTON_DPAD_NORTH",
    "DPAD_DOWN": "DS4_BUTTON_DPAD_SOUTH",
    "DPAD_LEFT": "DS4_BUTTON_DPAD_WEST",
    "DPAD_RIGHT": "DS4_BUTTON_DPAD_EAST",
    "START": "DS4_BUTTON_OPTIONS",
    "BACK": "DS4_BUTTON_SHARE",
    "LEFT_SHOULDER": "DS4_BUTTON_SHOULDER_LEFT",
    "RIGHT_SHOULDER": "DS4_BUTTON_SHOULDER_RIGHT",
    "GUIDE": "DS4_BUTTON_GUIDE",
    "WEST": "DS4_BUTTON_SQUARE",
    "SOUTH": "DS4_BUTTON_CROSS",
    "EAST": "DS4_BUTTON_CIRCLE",
    "NORTH": "DS4_BUTTON_TRIANGLE",
    "LEFT_TRIGGER": "LEFT_TRIGGER",
    "RIGHT_TRIGGER": "RIGHT_TRIGGER",
    "AXIS_LEFTX": "LEFT_JOYSTICK",
    "AXIS_LEFTY": "LEFT_JOYSTICK",
    "AXIS_RIGHTX": "RIGHT_JOYSTICK",
    "AXIS_RIGHTY": "RIGHT_JOYSTICK",
    "LEFT_THUMB": "DS4_BUTTON_THUMB_LEFT",
    "RIGHT_THUMB": "DS4_BUTTON_THUMB_RIGHT",
}


class GamepadEmulator:
    def __init__(self, controller_type="xbox", system="windows", agent_slot="auto"):
        """
        Initialize the GamepadEmulator with a specific controller type and system.

        Parameters:
        controller_type (str): The type of controller to emulate ("xbox" or "ps4").
        system (str): The operating system to use, which affects joystick value handling.
        agent_slot (str): "auto" keeps the original behavior. "player2" and
                          "player2_coop" try to make the agent the second controller.
        """
        self.controller_type = controller_type
        self.system = system
        self.agent_slot = agent_slot
        self.slot_guard = None

        if agent_slot in {"player2", "player2_coop"}:
            self._prepare_player2_slot()

        self.gamepad = self._create_virtual_gamepad()

        if controller_type == "xbox":
            self.mapping = XBOX_MAPPING
        elif controller_type == "ps4":
            self.mapping = PS4_MAPPING
        else:
            raise ValueError("Unsupported controller type")

        # Initialize joystick values to keep track of the current state
        self.left_joystick_x: int = 0
        self.left_joystick_y: int = 0
        self.right_joystick_x: int = 0
        self.right_joystick_y: int = 0

    def _create_virtual_gamepad(self):
        if self.controller_type == "xbox":
            return vg.VX360Gamepad()
        if self.controller_type == "ps4":
            return vg.VDS4Gamepad()
        raise ValueError("Unsupported controller type")

    def _prepare_player2_slot(self):
        print("Modo Player 2: aguardando o jogador humano assumir o Player 1...")
        time.sleep(5.0)

        active_slots = active_xinput_slots() if self.controller_type == "xbox" else []
        if 0 in active_slots:
            active_players = ", ".join(f"Player {slot + 1}" for slot in active_slots)
            print(f"Modo Player 2: controles XInput ja ativos: {active_players}.")
            if 1 in active_slots:
                print("Modo Player 2: o Player 2 ja parece ocupado; a IA pode cair em outro slot.")
            else:
                print("Modo Player 2: Player 1 ocupado, criando a IA no proximo slot disponivel.")
            return

        print("Modo Player 2: nenhum controle XInput ocupando o Player 1 foi detectado.")
        print("Modo Player 2: criando controle reserva parado para ocupar o Player 1.")
        self.slot_guard = self._create_virtual_gamepad()
        self.slot_guard.reset()
        self.slot_guard.update()
        time.sleep(0.5)
        print("Modo Player 2: criando o controle ativo da IA como proximo jogador.")

    def step(self, action):
        """
        Perform actions based on the provided action dictionary.

        Parameters:
        action (dict): Dictionary of an action to be performed. Keys are control names,
                       and values are their respective states.
        """
        self.gamepad.reset()

        # Handle buttons
        for control in [
            "EAST",
            "SOUTH",
            "NORTH",
            "WEST",
            "BACK",
            "GUIDE",
            "START",
            "DPAD_DOWN",
            "DPAD_LEFT",
            "DPAD_RIGHT",
            "DPAD_UP",
            "LEFT_SHOULDER",
            "RIGHT_SHOULDER",
            "LEFT_THUMB",
            "RIGHT_THUMB",
        ]:
            if control in action:
                if action[control]:
                    self.press_button(control)
                else:
                    self.release_button(control)

        # Handle triggers
        if "LEFT_TRIGGER" in action:
            self.set_trigger("LEFT_TRIGGER", action["LEFT_TRIGGER"][0])
        if "RIGHT_TRIGGER" in action:
            self.set_trigger("RIGHT_TRIGGER", action["RIGHT_TRIGGER"][0])

        # Handle joysticks
        if "AXIS_LEFTX" in action and "AXIS_LEFTY" in action:
            self.set_joystick("AXIS_LEFTX", action["AXIS_LEFTX"][0])
            self.set_joystick("AXIS_LEFTY", action["AXIS_LEFTY"][0])

        if "AXIS_RIGHTX" in action and "AXIS_RIGHTY" in action:
            self.set_joystick("AXIS_RIGHTX", action["AXIS_RIGHTX"][0])
            self.set_joystick("AXIS_RIGHTY", action["AXIS_RIGHTY"][0])

        self.gamepad.update()

    def press_button(self, button):
        """
        Press a button on the gamepad.

        Parameters:
        button (str): The unified name of the button to press.
        """
        button_mapped = self.mapping.get(button)
        if self.controller_type == "xbox":
            self.gamepad.press_button(button=getattr(vg.XUSB_BUTTON, button_mapped))
        elif self.controller_type == "ps4":
            self.gamepad.press_button(button=getattr(vg.DS4_BUTTONS, button_mapped))
        else:
            raise ValueError("Unsupported controller type")

    def release_button(self, button):
        """
        Release a button on the gamepad.

        Parameters:
        button (str): The unified name of the button to release.
        """
        button_mapped = self.mapping.get(button)
        if self.controller_type == "xbox":
            self.gamepad.release_button(button=getattr(vg.XUSB_BUTTON, button_mapped))
        elif self.controller_type == "ps4":
            self.gamepad.release_button(button=getattr(vg.DS4_BUTTONS, button_mapped))
        else:
            raise ValueError("Unsupported controller type")

    def set_trigger(self, trigger, value):
        """
        Set the value of a trigger on the gamepad.

        Parameters:
        trigger (str): The unified name of the trigger.
        value (float): The value to set the trigger to (between 0 and 1).
        """
        value = int(value)
        trigger_mapped = self.mapping.get(trigger)
        if trigger_mapped == "LEFT_TRIGGER":
            self.gamepad.left_trigger(value=value)
        elif trigger_mapped == "RIGHT_TRIGGER":
            self.gamepad.right_trigger(value=value)
        else:
            raise ValueError("Unsupported trigger action")

    def set_joystick(self, joystick, value):
        """
        Set the position of a joystick on the gamepad.

        Parameters:
        joystick (str): The name of the joystick axis.
        value (float): The value to set the joystick axis to (between -32768 and 32767)
        """
        if joystick == "AXIS_LEFTX":
            self.left_joystick_x = value
            self.gamepad.left_joystick(x_value=self.left_joystick_x, y_value=self.left_joystick_y)
        elif joystick == "AXIS_LEFTY":
            if self.system == "windows":
                value = -value - 1
            self.left_joystick_y = value
            self.gamepad.left_joystick(x_value=self.left_joystick_x, y_value=self.left_joystick_y)
        elif joystick == "AXIS_RIGHTX":
            self.right_joystick_x = value
            self.gamepad.right_joystick(
                x_value=self.right_joystick_x, y_value=self.right_joystick_y
            )
        elif joystick == "AXIS_RIGHTY":
            if self.system == "windows":
                value = -value - 1
            self.right_joystick_y = value
            self.gamepad.right_joystick(
                x_value=self.right_joystick_x, y_value=self.right_joystick_y
            )
        else:
            raise ValueError("Unsupported joystick action")

    def wakeup(self, duration=0.1):
        """
        Wake up the controller by pressing a button.

        Parameters:
        duration (float): Duration to press the button.
        """
        self.gamepad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB)
        self.gamepad.update()
        time.sleep(duration)
        self.gamepad.reset()
        self.gamepad.update()
        time.sleep(duration)

    def reset(self):
        """
        Reset the gamepad to its default state.
        """
        self.gamepad.reset()
        self.gamepad.update()

    def close(self):
        """
        Reset virtual controllers before the process exits.
        """
        for gamepad in (getattr(self, "gamepad", None), getattr(self, "slot_guard", None)):
            if gamepad is None:
                continue
            try:
                gamepad.reset()
                gamepad.update()
            except Exception:
                pass


class PyautoguiScreenshotBackend:

    def __init__(self, bbox):
        self.bbox = bbox

    def screenshot(self):
        return pyautogui.screenshot(region=self.bbox)

    def close(self):
        pass


@dataclass(frozen=True)
class CaptureTarget:
    raw_window_rect: tuple[int, int, int, int]
    visible_rect: tuple[int, int, int, int]
    pyautogui_bbox: tuple[int, int, int, int]
    device_idx: int
    output_idx: int
    output_name: str
    output_rect: tuple[int, int, int, int]
    dxcam_region: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return self.visible_rect[2] - self.visible_rect[0]

    @property
    def height(self) -> int:
        return self.visible_rect[3] - self.visible_rect[1]

    @property
    def output_width(self) -> int:
        return self.output_rect[2] - self.output_rect[0]

    @property
    def output_height(self) -> int:
        return self.output_rect[3] - self.output_rect[1]


def _rect_area(rect: tuple[int, int, int, int]) -> int:
    return max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])


def _rect_intersection(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    return (
        max(first[0], second[0]),
        max(first[1], second[1]),
        min(first[2], second[2]),
        min(first[3], second[3]),
    )


def _window_rect(window) -> tuple[int, int, int, int]:
    return (
        int(round(window.left)),
        int(round(window.top)),
        int(round(window.right)),
        int(round(window.bottom)),
    )


def _dxcam_outputs() -> list[dict]:
    import dxcam as dxcam_module

    factory = dxcam_module.__dict__.get("__factory")
    if factory is None:
        return []

    outputs = []
    for device_idx, device_outputs in enumerate(getattr(factory, "outputs", [])):
        for output_idx, output in enumerate(device_outputs):
            try:
                output.update_desc()
                coords = output.desc.DesktopCoordinates
                rect = (
                    int(coords.left),
                    int(coords.top),
                    int(coords.right),
                    int(coords.bottom),
                )
                if _rect_area(rect) <= 0:
                    continue
                outputs.append(
                    {
                        "device_idx": int(device_idx),
                        "output_idx": int(output_idx),
                        "name": str(output.devicename),
                        "rect": rect,
                    }
                )
            except Exception:
                continue
    return outputs


def _select_capture_target(window) -> CaptureTarget:
    raw_rect = _window_rect(window)
    outputs = _dxcam_outputs()
    if not outputs:
        screen_width, screen_height = pyautogui.size()
        outputs = [
            {
                "device_idx": 0,
                "output_idx": 0,
                "name": "primary",
                "rect": (0, 0, int(screen_width), int(screen_height)),
            }
        ]

    best = None
    best_visible = None
    best_area = 0
    for output in outputs:
        visible = _rect_intersection(raw_rect, output["rect"])
        area = _rect_area(visible)
        if area > best_area:
            best = output
            best_visible = visible
            best_area = area

    if best is None or best_visible is None or best_area <= 0:
        raise RuntimeError(
            f"Could not find a visible monitor area for window rect {raw_rect}. "
            "Move the game window onto the main screen and try again."
        )

    out_left, out_top, out_right, out_bottom = best["rect"]
    local_region = (
        max(0, best_visible[0] - out_left),
        max(0, best_visible[1] - out_top),
        min(out_right - out_left, best_visible[2] - out_left),
        min(out_bottom - out_top, best_visible[3] - out_top),
    )
    if _rect_area(local_region) <= 0:
        raise RuntimeError(f"Invalid normalized DXcam region {local_region} for window rect {raw_rect}.")

    pyautogui_bbox = (
        best_visible[0],
        best_visible[1],
        best_visible[2] - best_visible[0],
        best_visible[3] - best_visible[1],
    )
    return CaptureTarget(
        raw_window_rect=raw_rect,
        visible_rect=best_visible,
        pyautogui_bbox=pyautogui_bbox,
        device_idx=best["device_idx"],
        output_idx=best["output_idx"],
        output_name=best["name"],
        output_rect=best["rect"],
        dxcam_region=local_region,
    )


class DxcamScreenshotBackend:
    def __init__(self, target: CaptureTarget, fps):
        self.target = target
        self.camera = None
        self.region = target.dxcam_region
        self.crop_region = None
        self.size = (target.width, target.height)
        self.last_screenshot = None
        self._start(fps)

    def _start(self, fps):
        import dxcam

        full_output_region = (0, 0, self.target.output_width, self.target.output_height)
        region_attempts = [
            (self.region, None, "window region"),
        ]
        if self.region != full_output_region:
            region_attempts.append((full_output_region, self.region, "full output with window crop"))

        last_error = None
        for backend in ("dxgi", "winrt"):
            for processor_backend in ("cv2", "numpy"):
                for start_region, crop_region, description in region_attempts:
                    camera = None
                    try:
                        camera = dxcam.create(
                            device_idx=self.target.device_idx,
                            output_idx=self.target.output_idx,
                            output_color="RGB",
                            backend=backend,
                            processor_backend=processor_backend,
                        )
                        camera.start(region=start_region, target_fps=fps, video_mode=True)
                        self.camera = camera
                        self.crop_region = crop_region
                        print(
                            "DXCAM started: "
                            f"device={self.target.device_idx} output={self.target.output_idx} "
                            f"{self.target.output_name} region={start_region} "
                            f"mode={description} backend={backend}/{processor_backend}",
                            flush=True,
                        )
                        return
                    except Exception as exc:
                        last_error = exc
                        if camera is not None:
                            try:
                                camera.stop()
                            except Exception:
                                pass
                            try:
                                camera.release()
                            except Exception:
                                pass

        raise RuntimeError(
            "DXCAM failed after all capture attempts "
            f"(output={self.target.output_name}, region={self.region}, last error={last_error})"
        )

    def screenshot(self):
        screenshot = self.camera.get_latest_frame()
        if screenshot is None:
            print("DXCAM failed to capture frame, trying to use the latest screenshot", flush=True)
            if self.last_screenshot is not None:
                return self.last_screenshot
            else:
                return Image.new("RGB", self.size, (0, 0, 0))
        screenshot = Image.fromarray(screenshot)
        if self.crop_region is not None:
            screenshot = screenshot.crop(self.crop_region)
        self.last_screenshot = screenshot
        return screenshot

    def close(self):
        try:
            if self.camera is not None:
                self.camera.stop()
        except Exception:
            pass
        try:
            if self.camera is not None:
                self.camera.release()
        except Exception:
            pass


class AutoScreenshotBackend:
    def __init__(self, target: CaptureTarget, fps):
        self.pyautogui_backend = PyautoguiScreenshotBackend(target.pyautogui_bbox)
        self.dxcam_backend = None
        self.active = "dxcam"
        self.previous_sample = None
        self.black_frames = 0
        self.frozen_frames = 0
        self.black_frame_limit = max(90, int(fps * 1.5))
        self.frozen_frame_limit = max(240, int(fps * 4.0))
        self.black_mean_threshold = 4.0
        self.frozen_diff_threshold = 0.03

        try:
            self.dxcam_backend = DxcamScreenshotBackend(target, fps)
        except Exception as exc:
            print(f"DXCAM failed to start ({exc}); falling back to pyautogui.", flush=True)
            self.active = "pyautogui"

    def _sample(self, image):
        return image.convert("L").resize((64, 64), Image.Resampling.BILINEAR)

    def _mean_luma(self, image):
        return ImageStat.Stat(image.convert("L").resize((64, 64), Image.Resampling.BILINEAR)).mean[0]

    def _watch_dxcam(self, image):
        mean_luma = self._mean_luma(image)
        if mean_luma <= self.black_mean_threshold:
            self.black_frames += 1
        else:
            self.black_frames = 0

        sample = self._sample(image)
        if self.previous_sample is not None:
            diff = ImageChops.difference(sample, self.previous_sample)
            mean_diff = ImageStat.Stat(diff).mean[0]
            if mean_diff <= self.frozen_diff_threshold:
                self.frozen_frames += 1
            else:
                self.frozen_frames = 0
        self.previous_sample = sample

        if self.black_frames >= self.black_frame_limit:
            self._fallback(f"DXCAM returned {self.black_frames} very dark frames in a row")
        elif self.frozen_frames >= self.frozen_frame_limit:
            self._fallback(f"DXCAM returned {self.frozen_frames} almost identical frames in a row")

    def _fallback(self, reason):
        if self.active == "pyautogui":
            return
        print(f"{reason}; falling back to pyautogui capture.", flush=True)
        self.active = "pyautogui"
        if self.dxcam_backend is not None:
            self.dxcam_backend.close()

    def screenshot(self):
        if self.active == "pyautogui" or self.dxcam_backend is None:
            return self.pyautogui_backend.screenshot()

        try:
            image = self.dxcam_backend.screenshot()
        except Exception as exc:
            self._fallback(f"DXCAM capture failed ({exc})")
            return self.pyautogui_backend.screenshot()

        self._watch_dxcam(image)
        if self.active == "pyautogui":
            return self.pyautogui_backend.screenshot()
        return image

    def close(self):
        if self.dxcam_backend is not None:
            self.dxcam_backend.close()
        self.pyautogui_backend.close()


class GamepadEnv(Env):
    """
    Base class for creating a game environment controlled with a gamepad.

    Attributes:
    game (str): Name of the game to interact with.
    image_height (int): Height of the observation space.
    image_width (int): Width of the observation space.
    controller_type (str): Platform for the gamepad emulator ("xbox" or "ps4").
    game_speed (float): Speed multiplier for the game.
    env_fps (int): Number of actions to perform per second at normal speed.
    async_mode (bool): Whether to pause/unpause the game during each step.
    """

    def __init__(
            self,
            game,
            image_height=1440,
            image_width=2560,
            controller_type="xbox",
            game_speed=1.0,
            env_fps=10,
            async_mode=True,
            screenshot_backend="auto",
            runtime_mode="precision",
            agent_slot="auto",
    ):
        super().__init__()

        # Assert that system is windows
        os_name = platform.system().lower()
        assert os_name == "windows", "This environment is currently only supported on Windows."
        assert controller_type in ["xbox", "ps4"], "Platform must be either 'xbox' or 'ps4'"
        assert screenshot_backend in ["auto", "pyautogui", "dxcam"], "Screenshot backend must be 'auto', 'pyautogui', or 'dxcam'"
        assert runtime_mode in ["precision", "realtime"], "Runtime mode must be 'precision' or 'realtime'"
        assert agent_slot in ["auto", "player2", "player2_coop"], "Agent slot must be 'auto', 'player2', or 'player2_coop'"

        self.game = game
        self.image_height = int(image_height)
        self.image_width = int(image_width)
        self.game_speed = game_speed
        self.env_fps = env_fps
        self.step_duration = self.calculate_step_duration()
        self.async_mode = async_mode
        self.runtime_mode = runtime_mode
        self._closed = False

        self.gamepad_emulator = GamepadEmulator(
            controller_type=controller_type,
            system=os_name,
            agent_slot=agent_slot,
        )
        proc_info = get_process_info(game)

        self.game_pid = proc_info["pid"]
        self.game_arch = proc_info["architecture"]
        self.game_window_name = proc_info["window_name"]
        self.game_window_hwnd = proc_info.get("hwnd")

        print(
            f"Game process found: {self.game} (PID: {self.game_pid}, Arch: {self.game_arch}, Window: {self.game_window_name})")

        if self.game_pid is None:
            raise Exception(f"Could not find PID for game: {game}")

        self.observation_space = Box(
            low=0, high=255, shape=(self.image_height, self.image_width, 3), dtype="uint8"
        )

        # Define a unified action space
        self.action_space = Dict(
            {
                "BACK": Discrete(2),
                "GUIDE": Discrete(2),
                "RIGHT_SHOULDER": Discrete(2),
                "RIGHT_TRIGGER": Box(low=0.0, high=1.0, shape=(1,)),
                "LEFT_TRIGGER": Box(low=0.0, high=1.0, shape=(1,)),
                "LEFT_SHOULDER": Discrete(2),
                "AXIS_RIGHTX": Box(low=-32768.0, high=32767, shape=(1,)),
                "AXIS_RIGHTY": Box(low=-32768.0, high=32767, shape=(1,)),
                "AXIS_LEFTX": Box(low=-32768.0, high=32767, shape=(1,)),
                "AXIS_LEFTY": Box(low=-32768.0, high=32767, shape=(1,)),
                "LEFT_THUMB": Discrete(2),
                "RIGHT_THUMB": Discrete(2),
                "DPAD_UP": Discrete(2),
                "DPAD_RIGHT": Discrete(2),
                "DPAD_DOWN": Discrete(2),
                "DPAD_LEFT": Discrete(2),
                "WEST": Discrete(2),
                "SOUTH": Discrete(2),
                "EAST": Discrete(2),
                "NORTH": Discrete(2),
                "START": Discrete(2),
            }
        )

        # Determine window name
        windows = pwc.getAllWindows()
        self.game_window = None
        if self.game_window_hwnd:
            for window in windows:
                try:
                    hwnd = window.getHandle()
                except Exception:
                    hwnd = getattr(window, "_hWnd", None)
                if hwnd and int(hwnd) == int(self.game_window_hwnd):
                    self.game_window = window
                    break

        if not self.game_window and self.game_window_name:
            for window in windows:
                if window.title == self.game_window_name:
                    self.game_window = window
                    break

        if not self.game_window:
            raise Exception(
                f"No visible window found for {self.game} "
                f"(selected PID: {self.game_pid}, hwnd: {self.game_window_hwnd}, title: {self.game_window_name})"
            )

        self.game_window.activate()
        self.capture_target = _select_capture_target(self.game_window)
        width, height = self.capture_target.width, self.capture_target.height
        self.bbox = self.capture_target.pyautogui_bbox
        self.dxcam_region = self.capture_target.dxcam_region
        raw_l, raw_t, raw_r, raw_b = self.capture_target.raw_window_rect
        vis_l, vis_t, vis_r, vis_b = self.capture_target.visible_rect
        print(
            "Capture region: "
            f"raw_window=({raw_l},{raw_t},{raw_r},{raw_b}) "
            f"visible=({vis_l},{vis_t},{vis_r},{vis_b}) "
            f"dxcam_output={self.capture_target.output_name} "
            f"dxcam_region={self.dxcam_region} "
            f"width={width}, height={height}, backend={screenshot_backend}",
            flush=True,
        )

        self.speedhack_client = None
        if self.runtime_mode == "precision":
            import xspeedhack as xsh
            # Precision mode keeps the original stepped execution model.
            self.speedhack_client = xsh.Client(process_id=self.game_pid, arch=self.game_arch)
            print("Runtime mode: precision (stepped xspeedhack)")
        else:
            print("Runtime mode: realtime (no xspeedhack)")

        # Get the screenshot backend
        if screenshot_backend == "auto":
            self.screenshot_backend = AutoScreenshotBackend(self.capture_target, self.env_fps)
        elif screenshot_backend == "dxcam":
            self.screenshot_backend = DxcamScreenshotBackend(self.capture_target, self.env_fps)
        elif screenshot_backend == "pyautogui":
            self.screenshot_backend = PyautoguiScreenshotBackend(self.bbox)
        else:
            raise ValueError("Unsupported screenshot backend. Use 'dxcam' or 'pyautogui'.")

    def calculate_step_duration(self):
        """
        Calculate the step duration based on game speed and environment FPS.

        Returns:
        float: Calculated step duration.

        Example:
        If game_speed=1.0 and env_fps=10, then step_duration
        will be 0.1 seconds.
        """
        return 1.0 / (self.env_fps * self.game_speed)

    def unpause(self):
        """
        Unpause the game using the specified method.
        """
        if self.speedhack_client is not None:
            self.speedhack_client.set_speed(1.0)

    def pause(self):
        """
        Pause the game using the specified method.
        """
        if self.speedhack_client is not None:
            self.speedhack_client.set_speed(0.0)

    def perform_action(self, action, duration):
        """
        Perform the action without handling the game pause/unpause.

        Parameters:
        action (dict): Action to be performed.
        duration (float): Duration for the action step.
        """
        self.gamepad_emulator.step(action)
        if self.runtime_mode == "precision":
            start = time.perf_counter()
            self.unpause()
            # Wait until the next step
            end = start + self.step_duration
            now = time.perf_counter()
            while now < end:
                now = time.perf_counter()
            self.pause()
        else:
            time.sleep(duration)

    def step(self, action, step_duration=None):
        """
        Perform an action in the game environment and return the observation.

        Parameters:
        action (dict): Dictionary of the action to be performed. Keys are control names,
                    and values are their respective states.
        step_duration (float, optional): Duration for which the action should be performed.

        Returns:
        tuple: (obs, reward, terminated, truncated, info) where obs is the observation of the game environment after performing the action.
        """
        # Determine the duration for this step
        duration = step_duration if step_duration is not None else self.step_duration

        self.perform_action(action, duration)

        obs = self.render()  # Render after pausing the game

        reward = 0.0
        terminated = False
        truncated = False
        info = {}

        return obs, reward, terminated, truncated, info

    def reset(self, seed=None, options=None):
        """
        Reset the environment to its initial state.

        Parameters:
        seed (int, optional): Random seed.
        options (dict, optional): Additional options for reset.
        """
        self.gamepad_emulator.wakeup(duration=0.1)
        time.sleep(1.0)

    def close(self):
        """
        Close the environment and release any resources.
        """
        if getattr(self, "_closed", False):
            return
        self._closed = True
        if hasattr(self, "gamepad_emulator"):
            try:
                self.gamepad_emulator.close()
            except Exception as exc:
                print(f"Failed to reset virtual gamepad during close: {exc}")
        if getattr(self, "speedhack_client", None) is not None:
            try:
                self.speedhack_client.set_speed(1.0)
            except Exception as exc:
                print(f"Failed to restore game speed during close: {exc}")
        if hasattr(self, "screenshot_backend"):
            try:
                self.screenshot_backend.close()
            except Exception as exc:
                print(f"Failed to close screenshot backend: {exc}")

    def render(self):
        """
        Render the current state of the game window as an observation.

        Returns:
        Image: Observation of the game environment.
        """
        screenshot = self.screenshot_backend.screenshot()
        screenshot = screenshot.resize((self.image_width, self.image_height))

        return screenshot
