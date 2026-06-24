from datetime import tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from chime.tz import TzResolutionError, is_recognized_abbrev, resolve, system_tz


def test_resolve_utc_uppercase():
    zone, label = resolve("UTC")
    assert zone == ZoneInfo("UTC")
    assert label == "UTC"


def test_resolve_utc_lowercase():
    zone, label = resolve("utc")
    assert zone == ZoneInfo("UTC")
    assert label == "UTC"


def test_resolve_iana_passthrough():
    zone, label = resolve("America/New_York")
    assert zone == ZoneInfo("America/New_York")
    assert label == "America/New_York"


def test_resolve_invalid_iana_raises_structured_not_zoneinfo():
    with pytest.raises(TzResolutionError):
        resolve("Mars/Bogus")
    # And the stdlib exception must NOT leak across the boundary.
    try:
        resolve("Mars/Bogus")
    except ZoneInfoNotFoundError:
        pytest.fail("ZoneInfoNotFoundError leaked across chime.tz boundary")
    except TzResolutionError:
        pass


@pytest.mark.parametrize(
    ("abbrev", "iana"),
    [
        ("EDT", "America/New_York"),
        ("EST", "America/New_York"),
        ("CDT", "America/Chicago"),
        ("MDT", "America/Denver"),
        ("MST", "America/Denver"),
        ("PDT", "America/Los_Angeles"),
        ("PST", "America/Los_Angeles"),
        ("JST", "Asia/Tokyo"),
        ("KST", "Asia/Seoul"),
        ("AEST", "Australia/Sydney"),
        ("AEDT", "Australia/Sydney"),
        ("GMT", "UTC"),
        ("UTC", "UTC"),
    ],
)
def test_resolve_abbreviation_table(abbrev, iana):
    zone, label = resolve(abbrev)
    assert zone.key == iana
    # Label is the uppercased canonical form of what the user typed.
    assert label == abbrev


def test_resolve_abbreviation_case_insensitive():
    zone, label = resolve("pst")
    assert zone.key == "America/Los_Angeles"
    assert label == "PST"


def test_resolve_gmt_is_utc_alias():
    zone, label = resolve("GMT")
    assert zone == ZoneInfo("UTC")
    assert label == "GMT"


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("edt", True),
        ("EDT", True),
        (" pst ", True),
        ("CST", False),  # ambiguous — slice 03
        ("9am", False),
        ("America/New_York", False),
    ],
)
def test_is_recognized_abbrev(token, expected):
    assert is_recognized_abbrev(token) is expected


def test_resolve_est_is_new_york_not_fixed_offset():
    # The stdlib ships a fixed-offset zone literally named EST (UTC-5, no DST).
    # Chime must treat EST as a *zone alias* for America/New_York so summer DST
    # is honored — the table must win over ZoneInfo("EST").
    zone, label = resolve("EST")
    assert zone.key == "America/New_York"
    assert label == "EST"


def test_resolve_unrecognized_token_raises():
    with pytest.raises(TzResolutionError):
        resolve("FOO")


def test_tz_resolution_error_is_value_error():
    assert issubclass(TzResolutionError, ValueError)


def test_system_tz_returns_tzinfo():
    assert isinstance(system_tz(), tzinfo)


def test_system_tz_honors_tz_env(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/London")
    result = system_tz()
    # Using .key avoids tying the assertion to ZoneInfo's __eq__ specifics.
    assert getattr(result, "key", None) == "Europe/London"
