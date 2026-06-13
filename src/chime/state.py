"""Persistent state for background alarms.

Stored as JSON under $XDG_STATE_HOME/chime/alarms.json
(falls back to ~/.local/state/chime/alarms.json).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
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
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


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
