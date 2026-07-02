"""Timezone parsing & resolution. Pure logic; only system_tz() touches env / OS."""

from __future__ import annotations

import difflib
import os
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones


class TzResolutionError(ValueError):
    """Raised when a timezone spec cannot be resolved to a single IANA zone.

    ``spec`` carries the offending input on the plain unknown-timezone path so a
    caller can feed it to :func:`suggest` without re-parsing the message. It stays
    ``None`` on the ambiguous/collision subclasses (which carry their own data and
    must not trigger fuzzy suggestions).
    """

    spec: str | None = None


class AmbiguousAbbreviationError(TzResolutionError):
    """Raised when an abbreviation maps to more than one IANA zone (per ADR-0002).

    Carries the offending ``abbrev`` and the ordered ``candidates`` so callers can
    present the disambiguation list without parsing the message string.
    """

    def __init__(self, abbrev: str, candidates: list[str]) -> None:
        self.abbrev = abbrev
        self.candidates = candidates
        super().__init__(
            f"ambiguous timezone abbreviation '{abbrev}' — could be "
            f"{', '.join(candidates)}; use the full IANA name instead"
        )


class TimezoneCollisionError(TzResolutionError):
    """Raised when a source timezone is given both inline and via ``--tz`` (ADR-0002,
    policy A1) — always an error, even when both forms resolve to the same zone.

    Carries the two raw ``inline`` and ``flag`` source strings so the message can
    name both and the user can spot the conflict.
    """

    def __init__(self, inline: str, flag: str) -> None:
        self.inline = inline
        self.flag = flag
        super().__init__(
            f"conflicting timezones: inline '{inline}' and --tz '{flag}' — specify only one"
        )


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


# Ambiguous abbreviations (per ADR-0002): each maps to several IANA zones, so
# Chime refuses to guess and errors with the candidate list. Checked before
# _ABBREVIATIONS and the ZoneInfo passthrough so a platform fixed-offset zone
# named CST/IST can never silently win. Order matches the disambiguation message.
_AMBIGUOUS = {
    "IST": ["Asia/Kolkata", "Europe/Dublin", "Asia/Jerusalem"],
    "CST": ["America/Chicago", "Asia/Shanghai", "America/Havana"],
    "BST": ["Europe/London", "Asia/Dhaka", "Pacific/Bougainville"],
    "AST": ["America/Halifax", "Asia/Riyadh"],
}


def resolve(spec: str) -> tuple[ZoneInfo, str]:
    spec = spec.strip()
    key = spec.upper()
    if key in _AMBIGUOUS:
        raise AmbiguousAbbreviationError(key, list(_AMBIGUOUS[key]))
    if key in _ABBREVIATIONS:
        return ZoneInfo(_ABBREVIATIONS[key]), key
    try:
        return ZoneInfo(spec), spec
    except ZoneInfoNotFoundError:
        err = TzResolutionError(f"unknown timezone: {spec}")
        err.spec = spec
        raise err from None


def is_recognized_abbrev(token: str) -> bool:
    """Whether ``token`` is an unambiguous abbreviation Chime resolves directly.

    Lets the parser decide if a trailing token is a source-tz without exposing
    the abbreviation table itself.
    """
    return token.strip().upper() in _ABBREVIATIONS


def is_ambiguous_abbrev(token: str) -> bool:
    """Whether ``token`` is an ambiguous abbreviation Chime refuses to resolve.

    Lets the parser route these to :func:`resolve` (which raises a structured
    error) instead of mistaking them for unparseable time text.
    """
    return token.strip().upper() in _AMBIGUOUS


# Similarity threshold for suggest(). Tuned below the difflib default (0.6) so a
# short typo like 'londn' still reaches 'europe/london' — the region prefix
# ('europe/') dilutes the ratio — while nonsense like 'xyzzy123' still matches
# nothing. Case-folded matching (see suggest) is what makes the city part line up.
_SUGGEST_CUTOFF = 0.5


def suggest(bad_spec: str) -> list[str]:
    """Return up to three IANA zone names closest to an invalid ``bad_spec``.

    Pure and case-insensitive: matches the folded input against folded zone names
    (``difflib.get_close_matches`` is case-sensitive) and maps hits back to their
    canonical form. Returns ``[]`` when nothing is close enough, so callers can
    omit a "did you mean" line. No I/O beyond the in-memory tz database.
    """
    folded = bad_spec.strip().lower()
    if not folded:
        return []
    lower_to_zone = {z.lower(): z for z in available_timezones()}
    matches = difflib.get_close_matches(folded, lower_to_zone, n=3, cutoff=_SUGGEST_CUTOFF)
    return [lower_to_zone[m] for m in matches]


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
