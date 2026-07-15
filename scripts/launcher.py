from __future__ import annotations

import json
import os
import argparse
import pickle
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
HF_EXE = REPO / ".venv" / "Scripts" / "hf.exe"
CHECKPOINT = REPO / "models" / "ng.pt"
CONFIG_PATH = REPO / "neveludens_local_config.json"
LOG_DIR = REPO / "logs"
DEFAULT_PORT = 5555
MODEL_REPO = "nvidia/" + "Nitro" + "Gen"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NeveLudens local launcher")
    parser.add_argument("--process", type=str, default="", help="Game executable name")
    parser.add_argument(
        "--screenshot-backend",
        choices=["auto", "dxcam", "pyautogui"],
        default="auto",
        help="Screenshot backend. 'auto' uses dxcam first and pyautogui as fallback.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Local inference server port")
    parser.add_argument("--no-special-init", action="store_true", help="Skip Isaac/Cuphead startup macro")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of asking for a process when --process is missing.",
    )
    return parser.parse_args(argv)


def local_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DEBUG"] = "0"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["HF_HOME"] = str(REPO / ".cache" / "huggingface")
    env["HF_HUB_CACHE"] = str(REPO / ".cache" / "huggingface" / "hub")
    env["TRANSFORMERS_CACHE"] = str(REPO / ".cache" / "huggingface" / "transformers")
    env["TORCH_HOME"] = str(REPO / ".cache" / "torch")
    env["PIP_CACHE_DIR"] = str(REPO / ".cache" / "pip")
    env["PATH"] = str(REPO / ".venv" / "Scripts") + os.pathsep + env.get("PATH", "")
    return env


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def header() -> None:
    print("=" * 70)
    print("NeveLudens - Iniciador local")
    print("=" * 70)
    print(f"Projeto: {REPO}")
    print(f"Modelo : {CHECKPOINT}")
    print()


def console_safe(text: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def preflight() -> None:
    if not VENV_PYTHON.exists():
        raise RuntimeError("Ambiente .venv não encontrado. Rode iniciar.bat novamente.")

    if not CHECKPOINT.exists():
        download_checkpoint()

    import torch
    import vgamepad as vg

    if not torch.cuda.is_available():
        raise RuntimeError(
            "PyTorch não encontrou CUDA. O NeveLudens atual exige GPU NVIDIA com CUDA."
        )

    # Create and release one virtual controller to catch driver problems early.
    gamepad = vg.VX360Gamepad()
    gamepad.reset()
    gamepad.update()

    print(f"CUDA OK: {torch.cuda.get_device_name(0)}")
    print("Controle virtual OK")
    print()


def download_checkpoint() -> None:
    print("Checkpoint não encontrado. Baixando modelo base ng.pt...")
    (REPO / "models").mkdir(exist_ok=True)
    if not HF_EXE.exists():
        raise RuntimeError("Comando hf.exe não encontrado na .venv.")
    subprocess.check_call(
        [str(HF_EXE), "download", MODEL_REPO, "ng.pt", "--local-dir", "models"],
        cwd=REPO,
        env=local_env(),
    )


def visible_window_processes() -> list[tuple[str, str, int]]:
    import psutil
    import win32gui
    import win32process

    skip = {
        "applicationframehost.exe",
        "brave.exe",
        "chrome.exe",
        "code.exe",
        "cmd.exe",
        "conhost.exe",
        "dwm.exe",
        "firefox.exe",
        "msedge.exe",
        "explorer.exe",
        "powershell.exe",
        "rtkuwp.exe",
        "searchhost.exe",
        "shellexperiencehost.exe",
        "shellhost.exe",
        "steam.exe",
        "steamwebhelper.exe",
        "tabtip.exe",
        "textinputhost.exe",
        "windowsterminal.exe",
    }
    found: dict[str, tuple[str, str, int]] = {}

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            proc = psutil.Process(pid)
            name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return True
        if not name.lower().endswith(".exe") or name.lower() in skip:
            return True
        found.setdefault(name.lower(), (name, title, pid))
        return True

    win32gui.EnumWindows(callback, None)
    return sorted(found.values(), key=lambda item: item[0].lower())


def choose_process(config: dict) -> str:
    last = config.get("process", "")
    while True:
        processes = visible_window_processes()
        print("Abra o jogo antes de continuar. Janelas detectadas:")
        if processes:
            for idx, (name, title, pid) in enumerate(processes[:30], start=1):
                safe_title = console_safe(title[:60])
                print(f"  {idx:2d}. {name:<28} PID {pid:<7} {safe_title}")
        else:
            print("  Nenhuma janela de jogo detectada agora.")
        print()

        default_text = f" [{last}]" if last else ""
        answer = input(
            "Digite o numero da lista ou o nome exato do .exe do jogo"
            f"{default_text} (R para atualizar): "
        ).strip()

        if not answer and last:
            return last
        if answer.lower() == "r":
            print()
            continue
        if answer.isdigit():
            idx = int(answer)
            if 1 <= idx <= len(processes):
                return processes[idx - 1][0]
            print("Número fora da lista.")
            continue
        if answer:
            if not answer.lower().endswith(".exe"):
                answer += ".exe"
            return answer

        print("Informe um processo ou pressione R para atualizar.")


def raw_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def find_free_port(start: int) -> int:
    for port in range(start, 65536):
        if not raw_port_open(port):
            return port
    raise RuntimeError("Não encontrei porta livre.")


def server_info(port: int, timeout_ms: int = 1000) -> dict | None:
    import zmq

    context = zmq.Context()
    sock = context.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
    try:
        sock.connect(f"tcp://127.0.0.1:{port}")
        sock.send(pickle.dumps({"type": "info"}))
        response = pickle.loads(sock.recv())
        if response.get("status") == "ok":
            return response.get("info", {})
    except Exception:
        return None
    finally:
        sock.close()
        context.term()
    return None


def tail(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return ""
    data = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(data[-lines:])


def start_server(port: int, env: dict[str, str]) -> tuple[subprocess.Popen, Path]:
    LOG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"server_{stamp}.log"
    log_file = log_path.open("w", encoding="utf-8", errors="replace")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(
        [str(VENV_PYTHON), "scripts/serve.py", str(CHECKPOINT), "--port", str(port)],
        cwd=REPO,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    print(f"Servidor iniciando em segundo plano. Log: {log_path}")
    return proc, log_path


def wait_for_server(proc: subprocess.Popen, port: int, log_path: Path, timeout_s: int = 300) -> dict:
    started = time.time()
    last_notice = 0.0
    while time.time() - started < timeout_s:
        if proc.poll() is not None:
            raise RuntimeError(
                "Servidor encerrou antes de ficar pronto.\n\n"
                f"Ultimas linhas do log:\n{tail(log_path)}"
            )
        info = server_info(port, timeout_ms=1500)
        if info is not None:
            return info
        if time.time() - last_notice > 10:
            elapsed = int(time.time() - started)
            print(f"Aguardando servidor carregar o modelo... {elapsed}s")
            last_notice = time.time()
        time.sleep(1.5)

    raise RuntimeError(
        "Servidor demorou demais para responder.\n\n"
        f"Veja o log em: {log_path}\n\n"
        f"Ultimas linhas do log:\n{tail(log_path)}"
    )


def stop_server(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    print("Encerrando servidor...")
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_player(
    process_name: str,
    port: int,
    allow_menu: bool,
    screenshot_backend: str,
    special_init: bool,
    env: dict[str, str],
) -> int:
    cmd = [
        str(VENV_PYTHON),
        "scripts/play.py",
        "--process",
        process_name,
        "--port",
        str(port),
        "--screenshot-backend",
        screenshot_backend,
    ]
    if allow_menu:
        cmd.append("--allow-menu")
    if not special_init:
        cmd.append("--no-special-init")
    print()
    print("Servidor pronto. Iniciando controle do jogo.")
    print("Para parar, pressione Ctrl+C nesta janela.")
    print()
    return subprocess.call(cmd, cwd=REPO, env=env)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env = local_env()
    os.environ.update(env)
    header()

    try:
        preflight()
    except Exception as exc:
        print(f"Falha na verificacao inicial: {exc}")
        return 1

    config = load_config()
    if args.process:
        process_name = args.process.strip()
        if not process_name.lower().endswith(".exe"):
            process_name += ".exe"
    elif args.non_interactive:
        print("Nenhum processo informado. Escolha um jogo na interface antes de iniciar.")
        return 2
    else:
        process_name = choose_process(config)

    allow_menu = True
    screenshot_backend = args.screenshot_backend
    special_init = process_name.lower() in {"isaac-ng.exe", "cuphead.exe"} and not args.no_special_init
    if special_init:
        print("Macro especial de inicialização ativada para este jogo.")
    print("Ações START/BACK/GUIDE: liberadas")
    print(f"Captura: {screenshot_backend}")
    print(f"Porta do servidor: {args.port}")
    port = args.port

    if raw_port_open(port):
        info = server_info(port)
        if info is not None:
            print(f"Usando servidor NeveLudens que ja esta rodando na porta {port}.")
            server_proc = None
            log_path = None
        else:
            new_port = find_free_port(port + 1)
            print(f"Porta {port} está ocupada. Vou usar {new_port}.")
            port = new_port
            server_proc, log_path = start_server(port, env)
            info = wait_for_server(server_proc, port, log_path)
    else:
        server_proc, log_path = start_server(port, env)
        info = wait_for_server(server_proc, port, log_path)

    print(f"Modelo: {Path(info.get('ckpt_path', str(CHECKPOINT))).name}")
    print(f"Jogo/processo: {process_name}")
    print(f"Porta: {port}")
    print("Captura: dxcam com fallback conservador para pyautogui")
    print("Ações de menu: liberadas")

    config.update({
        "process": process_name,
        "allow_menu": True,
        "screenshot_backend": screenshot_backend,
        "special_init": special_init,
        "port": port,
    })
    save_config(config)

    try:
        return run_player(process_name, port, allow_menu, screenshot_backend, special_init, env)
    except KeyboardInterrupt:
        print()
        print("Interrompido pelo usuário.")
        return 130
    finally:
        stop_server(server_proc)


if __name__ == "__main__":
    sys.exit(main())
