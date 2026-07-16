from __future__ import annotations

from pathlib import Path


class StopRequested(SystemExit):
    """Raised when the GUI/launcher requested a cooperative shutdown."""

    def __init__(self, message: str = "Stop requested"):
        self.message = message
        super().__init__(130)


def normalize_stop_file(stop_file: str | Path | None) -> Path | None:
    if stop_file is None:
        return None
    text = str(stop_file).strip()
    if not text:
        return None
    return Path(text)


def stop_requested(stop_file: str | Path | None) -> bool:
    path = normalize_stop_file(stop_file)
    return bool(path and path.exists())


def raise_if_stop_requested(stop_file: str | Path | None) -> None:
    if stop_requested(stop_file):
        raise StopRequested("Stop requested")
