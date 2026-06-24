from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from chime.parsers import ParsedTime, fmt_clock, fmt_duration, parse_duration, parse_time


class TestParseDuration:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("10m", 600),
            ("1h", 3600),
            ("1h30m", 5400),
            ("90s", 90),
            ("0.5h", 1800),
            ("45m30s", 2730),
            ("1d", 86400),
            ("30", 1800),  # bare = minutes
            ("2.5", 150),
            ("  1h 30m  ", 5400),  # spaces tolerated
            ("1H30M", 5400),  # case-insensitive
        ],
    )
    def test_valid(self, text, expected):
        assert parse_duration(text) == expected

    @pytest.mark.parametrize(
        "text",
        ["", "   ", "abc", "10x", "1h30", "h30m", "--", "1.2.3", "10m20"],
    )
    def test_invalid(self, text):
        with pytest.raises(ValueError):
            parse_duration(text)


class TestParseTime:
    def setup_method(self):
        self.now = datetime(2026, 6, 13, 14, 0, 0)

    @pytest.mark.parametrize(
        ("text", "hour", "minute", "day_offset"),
        [
            ("15:30", 15, 30, 0),
            ("3:30pm", 15, 30, 0),
            ("3pm", 15, 0, 0),
            ("9am", 9, 0, 1),  # past today -> tomorrow
            ("9:00", 9, 0, 1),
            ("12am", 0, 0, 1),
            ("12pm", 12, 0, 1),  # 12:00 = past 14:00 -> tomorrow
            ("16:00", 16, 0, 0),
            ("4pm", 16, 0, 0),
        ],
    )
    def test_valid_times(self, text, hour, minute, day_offset):
        result = parse_time(text, now=self.now)
        assert isinstance(result, ParsedTime)
        assert result.target.hour == hour
        assert result.target.minute == minute
        assert (result.target.date() - self.now.date()).days == day_offset
        assert result.source_tz is None
        assert result.source_label is None

    def test_tomorrow_prefix(self):
        result = parse_time("tomorrow 9am", now=self.now)
        assert result.target.hour == 9
        assert (result.target.date() - self.now.date()).days == 1

    def test_tomorrow_at_prefix(self):
        result = parse_time("tomorrow at 15:30", now=self.now)
        assert result.target.hour == 15
        assert result.target.minute == 30
        assert (result.target.date() - self.now.date()).days == 1

    def test_case_insensitive(self):
        assert parse_time("3:30PM", now=self.now) == parse_time("3:30pm", now=self.now)

    def test_spaces_tolerated(self):
        assert parse_time(" 3 : 30 pm ", now=self.now) == parse_time("3:30pm", now=self.now)

    def test_target_is_future(self):
        result = parse_time("9am", now=self.now)
        assert result.target > self.now

    def test_no_tz_path_returns_naive_target(self):
        result = parse_time("9am", now=self.now)
        assert result.target.tzinfo is None
        assert result.source_tz is None
        assert result.source_label is None

    def test_trailing_utc_token(self):
        # 14:00 IST = 08:30 UTC, so 9am UTC is still ahead today.
        aware_now = datetime(2026, 6, 13, 14, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        result = parse_time("9am UTC", now=aware_now)
        assert result.source_tz == ZoneInfo("UTC")
        assert result.source_label == "UTC"
        assert result.target.tzinfo == ZoneInfo("UTC")
        assert result.target.hour == 9
        assert result.target.minute == 0

    def test_trailing_iana_token(self):
        aware_now = datetime(2026, 6, 13, 14, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        result = parse_time("9am America/New_York", now=aware_now)
        assert result.source_tz == ZoneInfo("America/New_York")
        assert result.source_label == "America/New_York"
        assert result.target.tzinfo == ZoneInfo("America/New_York")
        assert result.target.hour == 9
        # June → EDT, the resolved tzname at the target moment
        assert result.target.tzname() == "EDT"

    def test_trailing_abbreviation_token(self):
        aware_now = datetime(2026, 6, 13, 14, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        result = parse_time("9am EDT", now=aware_now)
        assert result.source_tz == ZoneInfo("America/New_York")
        assert result.source_label == "EDT"
        assert result.target.tzinfo.key == "America/New_York"
        assert result.target.hour == 9

    @pytest.mark.parametrize("text", ["9am pst", "9am Edt", "9am eDt"])
    def test_trailing_abbreviation_case_insensitive(self, text):
        aware_now = datetime(2026, 6, 13, 14, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        result = parse_time(text, now=aware_now)
        assert result.source_tz is not None
        assert result.target.tzinfo is not None

    def test_abbreviation_dst_flip_summer(self):
        # EST typed against a June `now` resolves to a wall-clock that is actually
        # EDT at the target moment — the abbreviation is an alias, not an offset.
        aware_now = datetime(2026, 6, 13, 14, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        result = parse_time("9am EST", now=aware_now)
        assert result.source_label == "EST"
        assert result.target.tzname() == "EDT"

    def test_abbreviation_dst_flip_winter(self):
        aware_now = datetime(2026, 1, 13, 14, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        result = parse_time("9am EDT", now=aware_now)
        assert result.source_label == "EDT"
        assert result.target.tzname() == "EST"

    def test_invalid_iana_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_time("9am Mars/Bogus", now=self.now)

    def test_tomorrow_prefix_with_tz(self):
        aware_now = datetime(2026, 6, 13, 14, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        result = parse_time("tomorrow 9am UTC", now=aware_now)
        assert result.source_tz == ZoneInfo("UTC")
        assert result.target.hour == 9
        # 14:00 IST on 13 June = 08:30 UTC on 13 June.
        # tomorrow → target should be on 14 June UTC.
        assert result.target.date().day == 14

    @pytest.mark.parametrize(
        "text",
        ["", "abc", "25:00", "9pmm", "9:60am", "13pm", ":30", "1:2:3"],
    )
    def test_invalid(self, text):
        with pytest.raises(ValueError):
            parse_time(text, now=self.now)


class TestFmtDuration:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "0s"),
            (45, "45s"),
            (60, "1m"),
            (90, "1m 30s"),
            (3600, "1h"),
            (3660, "1h 01m"),
            (3661, "1h 01m 01s"),
            (5400, "1h 30m"),
            (90061, "25h 01m 01s"),
        ],
    )
    def test_format(self, seconds, expected):
        assert fmt_duration(seconds) == expected

    def test_rounds(self):
        assert fmt_duration(89.6) == "1m 30s"


class TestFmtClock:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "00:00"),
            (59, "00:59"),
            (60, "01:00"),
            (599, "09:59"),
            (3600, "01:00:00"),
            (3661, "01:01:01"),
            (-5, "00:00"),  # clamps negative
        ],
    )
    def test_format(self, seconds, expected):
        assert fmt_clock(seconds) == expected
