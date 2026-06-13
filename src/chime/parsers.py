"""Pure parsing & formatting helpers — no side effects, easily testable."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)([smhd])")
_BARE_NUMBER = re.compile(r"\d+(\.\d+)?")


def parse_duration(s: str) -> float:
    """Parse '10m', '1h30m', '90s', '0.5h'. Bare number = minutes."""
    s = s.strip().lower().replace(" ", "")
    if not s:
        raise ValueError("empty duration")
    if _BARE_NUMBER.fullmatch(s):
        return float(s) * 60
    total = 0.0
    pos = 0
    matched = False
    for m in _DURATION_PATTERN.finditer(s):
        if m.start() != pos:
            raise ValueError(f"can't parse duration: {s}")
        total += float(m.group(1)) * _DURATION_UNITS[m.group(2)]
        pos = m.end()
        matched = True
    if not matched or pos != len(s):
        raise ValueError(f"can't parse duration: {s}")
    return total


def parse_time(s: str, *, now: datetime | None = None) -> datetime:
    """Parse '15:30', '3:30pm', '9am', 'tomorrow 9am' → future datetime.

    Past clock times roll forward to tomorrow.
    """
    s = s.strip().lower().replace(" ", "")
    if not s:
        raise ValueError("empty time")
    now = now or datetime.now()
    days_ahead = 0
    if s.startswith("tomorrow"):
        days_ahead = 1
        s = s[len("tomorrow") :]
        if s.startswith("at"):
            s = s[2:]
    ampm: str | None = None
    for suffix, kind in (("pm", "pm"), ("am", "am"), ("p", "pm"), ("a", "am")):
        if s.endswith(suffix):
            ampm = kind
            s = s[: -len(suffix)]
            break
    if ":" in s:
        parts = s.split(":")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            raise ValueError(f"bad time: {s}")
        hour, minute = int(parts[0]), int(parts[1])
    else:
        if not s.isdigit():
            raise ValueError(f"bad time: {s}")
        hour, minute = int(s), 0
    if ampm is not None:
        if not (1 <= hour <= 12):
            raise ValueError(f"hour {hour} is not valid with am/pm")
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid time: {hour:02d}:{minute:02d}")
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    target += timedelta(days=days_ahead)
    if days_ahead == 0 and target <= now:
        target += timedelta(days=1)
    return target


def fmt_duration(sec: float) -> str:
    sec = round(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        m, s = divmod(sec, 60)
        return f"{m}m {s:02d}s" if s else f"{m}m"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if s:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{h}h {m:02d}m"
    return f"{h}h"


def fmt_clock(sec: float) -> str:
    sec = max(0, round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
