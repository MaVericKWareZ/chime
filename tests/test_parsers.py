from datetime import datetime

import pytest

from chime.parsers import fmt_clock, fmt_duration, parse_duration, parse_time


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
        assert result.hour == hour
        assert result.minute == minute
        assert (result.date() - self.now.date()).days == day_offset

    def test_tomorrow_prefix(self):
        result = parse_time("tomorrow 9am", now=self.now)
        assert result.hour == 9
        assert (result.date() - self.now.date()).days == 1

    def test_tomorrow_at_prefix(self):
        result = parse_time("tomorrow at 15:30", now=self.now)
        assert result.hour == 15
        assert result.minute == 30
        assert (result.date() - self.now.date()).days == 1

    def test_case_insensitive(self):
        assert parse_time("3:30PM", now=self.now) == parse_time("3:30pm", now=self.now)

    def test_spaces_tolerated(self):
        assert parse_time(" 3 : 30 pm ", now=self.now) == parse_time("3:30pm", now=self.now)

    def test_target_is_future(self):
        result = parse_time("9am", now=self.now)
        assert result > self.now

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
