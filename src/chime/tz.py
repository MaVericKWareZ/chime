"""Timezone parsing & resolution. Pure logic; only system_tz() touches env / OS."""

from __future__ import annotations

import os
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TzResolutionError(ValueError):
    """Raised when a timezone spec cannot be resolved to a single IANA zone."""


# Unambiguous timezone abbreviations, mapped to canonical IANA zones and treated
# as *zone aliases* (per ADR-0002): EST and EDT both resolve to America/New_York
# and DST comes from zoneinfo at the target moment, not the abbreviation. The
# table is consulted before ZoneInfo(spec) so platform fixed-offset zones named
# EST/GMT cannot win. CST is intentionally absent — it's ambiguous (slice 03).
_ABBREVIATIONS = {
    "EDT": "America/New_York",
    "EST": "America/New_York",
    "CDT": "America/Chicago",
    "MDT": "America/Denver",
    "MST": "America/Denver",
    "PDT": "America/Los_Angeles",
    "PST": "America/Los_Angeles",
    "JST": "Asia/Tokyo",
    "KST": "Asia/Seoul",
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
    "GMT": "UTC",
    "UTC": "UTC",
}


def resolve(spec: str) -> tuple[ZoneInfo, str]:
    spec = spec.strip()
    key = spec.upper()
    if key in _ABBREVIATIONS:
        return ZoneInfo(_ABBREVIATIONS[key]), key
    try:
        return ZoneInfo(spec), spec
    except ZoneInfoNotFoundError:
        raise TzResolutionError(f"unknown timezone: {spec}") from None


def is_recognized_abbrev(token: str) -> bool:
    """Whether ``token`` is an unambiguous abbreviation Chime resolves directly.

    Lets the parser decide if a trailing token is a source-tz without exposing
    the abbreviation table itself.
    """
    return token.strip().upper() in _ABBREVIATIONS


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
