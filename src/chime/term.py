"""Terminal colors. Disabled when stdout is not a TTY or NO_COLOR is set."""

from __future__ import annotations

import os
import sys

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"


def _color_ok() -> bool:
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty()


def c(text: object, color: str) -> str:
    return f"{color}{text}{RESET}" if _color_ok() else str(text)
