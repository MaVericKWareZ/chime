"""chime — friendly terminal alarms, timers & pomodoro."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("chime-cli")
except PackageNotFoundError:  # not installed (e.g., running from source without `pip install -e .`)
    __version__ = "0.0.0+source"
