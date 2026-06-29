"""User configuration for chime.

Stored as JSON under $XDG_CONFIG_HOME/chime/config.json
(falls back to ~/.config/chime/config.json; %APPDATA%\\chime\\config.json on
Windows). A deep module hiding file location, serialization, atomic writes,
unknown-key preservation, and warn-on-corrupt behavior (ADR-0001).
"""

from __future__ import annotations

import contextlib
import difflib
import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from chime.term import YELLOW, c


class ConfigError(ValueError):
    """Raised when a write is rejected (unknown key or invalid value)."""


KNOWN_KEYS = {"timezone"}

# Value validators by key; a later slice registers the timezone validator.
# Empty here means accept-all.
_VALIDATORS: dict[str, Callable[[str], str]] = {}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        root = Path(base)
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    else:
        root = Path.home() / ".config"
    d = root / "chime"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_file() -> Path:
    return config_dir() / "config.json"


def _read() -> dict[str, Any]:
    f = config_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError:
        print(c(f"warning: {f} is not valid JSON — ignoring", YELLOW), file=sys.stderr)
        return {}


def _atomic_write(data: dict[str, Any]) -> None:
    d = config_dir()
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(data, indent=2))
        os.replace(tmp, config_file())
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def get(key: str, default: Any = None) -> Any:
    return _read().get(key, default)


def view() -> dict[str, Any]:
    return _read()


def set(key: str, value: str) -> None:
    if key not in KNOWN_KEYS:
        if difflib.get_close_matches(key, KNOWN_KEYS):
            raise ConfigError(f"unknown key '{key}' — did you mean 'timezone'?")
        raise ConfigError(f"unknown key '{key}'")
    validator = _VALIDATORS.get(key)
    if validator is not None:
        value = validator(value)
    data = _read()
    data[key] = value
    _atomic_write(data)


def unset(key: str) -> None:
    data = _read()
    if key in data:
        del data[key]
        _atomic_write(data)


def reset() -> None:
    config_file().unlink(missing_ok=True)
