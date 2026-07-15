from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageStat

from neveludens.game_env import get_process_info


REPO = Path(__file__).resolve().parents[1]
DEBUG_DIR = REPO / "debug"
sys.path.insert(0, str(REPO))

import scripts.launcher as launcher


def find_window(process_name: str):
    import pywinctl as pwc

    proc_info = get_process_info(process_name)
    window_name = proc_info["window_name"]
    for window in pwc.getAllWindows():
        if window.title == window_name:
            return window
    raise RuntimeError(f"Não encontrei janela visível para {process_name}.")


def stats(image: Image.Image) -> tuple[tuple[float, float, float], bool]:
    rgb = image.convert("RGB")
    mean = tuple(round(x, 1) for x in ImageStat.Stat(rgb).mean)
    is_dark = sum(mean) / 3 < 8
    return mean, is_dark


def capture_pyautogui(window) -> Image.Image:
    import pyautogui

    left, top, right, bottom = window.left, window.top, window.right, window.bottom
    return pyautogui.screenshot(region=(left, top, right - left, bottom - top))


def capture_dxcam(window) -> Image.Image:
    import dxcam

    left, top, right, bottom = window.left, window.top, window.right, window.bottom
    camera = dxcam.create()
    camera.start(region=(left, top, right, bottom), target_fps=30, video_mode=True)
    time.sleep(0.7)
    frame = camera.get_latest_frame()
    camera.stop()
    if frame is None:
        return Image.new("RGB", (right - left, bottom - top), (0, 0, 0))
    return Image.fromarray(frame)


def save_capture(process_name: str, backend: str) -> Path:
    window = find_window(process_name)
    window.activate()
    time.sleep(0.3)

    if backend == "dxcam":
        image = capture_dxcam(window)
    elif backend == "pyautogui":
        image = capture_pyautogui(window)
    else:
        raise ValueError(f"Backend invalido: {backend}")

    DEBUG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DEBUG_DIR / f"capture_check_{stamp}_{backend}.png"
    image.save(path)
    mean, is_dark = stats(image)
    print(f"{backend}: {path}")
    print(f"  tamanho={image.size[0]}x{image.size[1]} media_rgb={mean}")
    if is_dark:
        print("  AVISO: captura muito escura/preta.")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Testar captura de jogo do NeveLudens")
    parser.add_argument("--process", type=str, default="", help="Game executable name")
    parser.add_argument("--backend", choices=["all", "dxcam", "pyautogui"], default="all")
    args = parser.parse_args()

    os.environ.update(launcher.local_env())
    process_name = args.process or launcher.choose_process(launcher.load_config())
    backends = ["dxcam", "pyautogui"] if args.backend == "all" else [args.backend]

    paths = []
    for backend in backends:
        paths.append(save_capture(process_name, backend))

    print()
    print("Confira as imagens abertas/salvas. A captura correta deve mostrar exatamente a janela do jogo.")
    for path in paths:
        try:
            os.startfile(path)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
