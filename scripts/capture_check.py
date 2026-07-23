from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageStat

from neveludens.game_env import DxcamScreenshotBackend, _select_capture_target, get_process_info


REPO = Path(__file__).resolve().parents[1]
DEBUG_DIR = REPO / "debug"
sys.path.insert(0, str(REPO))

import scripts.launcher as launcher


def find_window(process_name: str):
    import pywinctl as pwc

    proc_info = get_process_info(process_name)
    window_name = proc_info["window_name"]
    window_hwnd = proc_info.get("hwnd")
    for window in pwc.getAllWindows():
        try:
            hwnd = window.getHandle()
        except Exception:
            hwnd = getattr(window, "_hWnd", None)
        if window_hwnd and hwnd and int(hwnd) == int(window_hwnd):
            return window
        if not window_hwnd and window.title == window_name:
            return window
    raise RuntimeError(
        f"Nao encontrei janela visivel para {process_name} "
        f"(PID: {proc_info.get('pid')}, hwnd: {window_hwnd}, titulo: {window_name})."
    )


def stats(image: Image.Image) -> tuple[tuple[float, float, float], bool]:
    rgb = image.convert("RGB")
    mean = tuple(round(x, 1) for x in ImageStat.Stat(rgb).mean)
    is_dark = sum(mean) / 3 < 8
    return mean, is_dark


def capture_pyautogui(window) -> Image.Image:
    import pyautogui

    target = _select_capture_target(window)
    return pyautogui.screenshot(region=target.pyautogui_bbox)


def capture_dxcam(window) -> Image.Image:
    target = _select_capture_target(window)
    backend = DxcamScreenshotBackend(target, fps=30)
    try:
        time.sleep(0.7)
        return backend.screenshot()
    finally:
        backend.close()


def save_capture(process_name: str, backend: str) -> Path:
    window = find_window(process_name)
    window.activate()
    time.sleep(0.3)
    target = _select_capture_target(window)
    print(
        "Regiao de captura: "
        f"janela={target.raw_window_rect} visivel={target.visible_rect} "
        f"dxcam={target.dxcam_region} monitor={target.output_name}"
    )

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
