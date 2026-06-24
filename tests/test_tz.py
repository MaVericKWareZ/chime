from datetime import tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from chime.tz import TzResolutionError, resolve, system_tz


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
