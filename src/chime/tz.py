"""Timezone parsing & resolution. Pure logic; only system_tz() touches env / OS."""

from __future__ import annotations

import os
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TzResolutionError(ValueError):
    """Raised when a timezone spec cannot be resolved to a single IANA zone."""


def resolve(spec: str) -> tuple[ZoneInfo, str]:
    spec = spec.strip()
    if spec.upper() == "UTC":
        return ZoneInfo("UTC"), "UTC"
    try:
        return ZoneInfo(spec), spec
    except ZoneInfoNotFoundError:
        raise TzResolutionError(f"unknown timezone: {spec}") from None


def system_tz() -> tzinfo:
    """Return the system's local timezone.

    Honors $TZ on POSIX; falls back to ZoneInfo('localtime'), then to
    datetime.now().astimezone().tzinfo on platforms without a tzdata file.
    """
    tz_env = os.environ.get("TZ")
    if tz_env:
        try:
            return ZoneInfo(tz_env)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    try:
        return ZoneInfo("localtime")
    except ZoneInfoNotFoundError:
        fallback = datetime.now().astimezone().tzinfo
        assert fallback is not None
        return fallback
