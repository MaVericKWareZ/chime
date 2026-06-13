"""Persistent state for background alarms.

Stored as JSON under $XDG_STATE_HOME/chime/alarms.json
(falls back to ~/.local/state/chime/alarms.json).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        root = Path(base)
    elif sys.platform == "win32":
        # Use LOCALAPPDATA on Windows
        localappdata = os.environ.get("LOCALAPPDATA")
        root = Path(localappdata) if localappdata else Path.home() / "AppData" / "Local"
    else:
        root = Path.home() / ".local" / "state"
    d = root / "chime"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_file() -> Path:
    return state_dir() / "alarms.json"


def load() -> list[dict[str, Any]]:
    f = state_file()
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save(alarms: list[dict[str, Any]]) -> None:
    state_file().write_text(json.dumps(alarms, indent=2))


def is_alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _is_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _is_alive_windows(pid: int) -> bool:
    """On Windows, os.kill(pid, 0) raises — use OpenProcess via ctypes instead."""
    import ctypes  # noqa: PLC0415 — Windows-only path
    from ctypes import wintypes  # noqa: PLC0415 — wintypes is Windows-only

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return exit_code.value == STILL_ACTIVE
        return True
    finally:
        kernel32.CloseHandle(handle)


def prune() -> list[dict[str, Any]]:
    alarms = load()
    alive = [a for a in alarms if is_alive(a["pid"])]
    if len(alive) != len(alarms):
        save(alive)
    return alive


def add(entry: dict[str, Any]) -> None:
    alarms = prune()
    alarms.append(entry)
    save(alarms)


def remove(pid: int) -> None:
    save([a for a in load() if a["pid"] != pid])
