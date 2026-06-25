"""End-to-end CLI checks that don't require firing actual alarms."""

import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from chime import cli
from chime.cli import _split_flags, cmd_at, run_alarm

CHIME = [sys.executable, "-m", "chime"]


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(CHIME + args, capture_output=True, text=True, check=False)


class TestSplitFlags:
    def test_flags_after_positional(self):
        pos, flags = _split_flags(["10m", "tea", "--bg"])
        assert pos == ["10m", "tea"]
        assert flags == ["--bg"]

    def test_flags_before_positional(self):
        pos, flags = _split_flags(["--bg", "10m", "tea"])
        assert pos == ["10m", "tea"]
        assert flags == ["--bg"]

    def test_value_flag(self):
        pos, flags = _split_flags(["--sound", "Hero", "10m"])
        assert pos == ["10m"]
        assert flags == ["--sound", "Hero"]

    def test_mixed(self):
        pos, flags = _split_flags(["10m", "--sound", "Hero", "tea", "--bg"])
        assert pos == ["10m", "tea"]
        assert flags == ["--sound", "Hero", "--bg"]

    def test_tz_is_value_flag(self):
        pos, flags = _split_flags(["10m", "--tz", "EDT"])
        assert pos == ["10m"]
        assert flags == ["--tz", "EDT"]


class TestCommandSurface:
    def test_help_no_args(self):
        result = run([])
        assert result.returncode == 0
        assert "chime" in result.stdout

    def test_help_flag(self):
        result = run(["--help"])
        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_version(self):
        result = run(["version"])
        assert result.returncode == 0
        assert result.stdout.startswith("chime ")

    def test_version_flag(self):
        result = run(["--version"])
        assert result.returncode == 0
        assert result.stdout.startswith("chime ")

    @pytest.mark.parametrize("listcmd", [["list"], ["ls"]])
    def test_list_when_empty(self, listcmd, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        result = subprocess.run(
            CHIME + listcmd,
            capture_output=True,
            text=True,
            check=False,
            env={**dict(__import__("os").environ), "XDG_STATE_HOME": str(tmp_path)},
        )
        assert result.returncode == 0

    def test_bad_duration_exits_with_error(self):
        result = run(["zzz"])
        assert result.returncode == 2
        assert "not a known command" in result.stderr or "not a known command" in result.stdout

    def test_bad_time_exits_with_error(self):
        result = run(["at", "25:99"])
        assert result.returncode == 2

    def test_unknown_flag_exits_with_error(self):
        result = run(["--bogus", "10m"])
        assert result.returncode == 2

    def test_tz_flag_collision_exits_with_error(self):
        result = run(["at", "9am EDT", "--tz", "Europe/London", "x"])
        assert result.returncode == 2
        out = result.stdout + result.stderr
        assert "conflicting timezones" in out
        assert "EDT" in out and "Europe/London" in out

    def test_tz_flag_same_zone_collision_exits_with_error(self):
        result = run(["at", "9am EDT", "--tz", "America/New_York", "x"])
        assert result.returncode == 2
        assert "conflicting timezones" in (result.stdout + result.stderr)

    @pytest.mark.parametrize("cmd", [["10m"], ["pomodoro"], ["stopwatch"]])
    def test_tz_flag_on_duration_commands_errors(self, cmd):
        result = run([*cmd, "--tz", "EDT"])
        assert result.returncode == 2
        assert "no effect on durations" in (result.stdout + result.stderr)


def _fake_opts(**overrides):
    base = dict(bg=False, sound=None, repeat=1, say=None, no_sound=True)
    base.update(overrides)
    return SimpleNamespace(**base)


def _capture_label(monkeypatch):
    """Patch chime.cli.countdown to capture the label and short-circuit."""
    captured = {}

    def fake_countdown(seconds, label=None):
        captured["label"] = label
        captured["seconds"] = seconds
        return False  # do not trigger alerts

    monkeypatch.setattr(cli, "countdown", fake_countdown)
    return captured


class TestForegroundHeader:
    def test_no_target_dt_header_unchanged(self, monkeypatch):
        captured = _capture_label(monkeypatch)
        run_alarm(60, "hi", _fake_opts())
        assert "@" not in captured["label"]
        assert "hi" in captured["label"]

    def test_naive_target_dt_header_byte_identical(self, monkeypatch):
        captured = _capture_label(monkeypatch)
        target = datetime(2026, 6, 13, 9, 0, 0)  # naive — today's no-tz path
        run_alarm(60, "hi", _fake_opts(), target_dt=target)
        assert "@ 09:00" in captured["label"]
        # No source label — same-tz / no-tz path
        assert "UTC" not in captured["label"]
        assert "EDT" not in captured["label"]

    def test_source_label_appended(self, monkeypatch):
        captured = _capture_label(monkeypatch)
        target = datetime(2026, 6, 13, 9, 0, 0, tzinfo=ZoneInfo("UTC"))
        run_alarm(60, "meeting", _fake_opts(), target_dt=target, source_label="UTC")
        assert "@ 09:00 UTC" in captured["label"]

    def test_cmd_at_utc_from_non_utc_system_shows_suffix(self, monkeypatch):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("Asia/Kolkata"))
        captured = _capture_label(monkeypatch)
        cmd_at(
            SimpleNamespace(
                time="9am UTC",
                message=["meeting"],
                bg=False,
                sound=None,
                repeat=1,
                say=None,
                no_sound=True,
            )
        )
        assert "@ 09:00 UTC" in captured["label"]

    def test_cmd_at_tz_flag_shows_suffix_like_inline(self, monkeypatch):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("Asia/Kolkata"))
        captured = _capture_label(monkeypatch)
        cmd_at(
            SimpleNamespace(
                time="9am",
                tz="EDT",
                message=["meeting"],
                bg=False,
                sound=None,
                repeat=1,
                say=None,
                no_sound=True,
            )
        )
        # Flag form renders identically to the inline `9am EDT` form.
        assert "@ 09:00 EDT" in captured["label"]

    def test_cmd_at_same_tz_no_suffix(self, monkeypatch):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("America/Los_Angeles"))
        captured = _capture_label(monkeypatch)
        cmd_at(
            SimpleNamespace(
                time="9am America/Los_Angeles",
                message=["standup"],
                bg=False,
                sound=None,
                repeat=1,
                say=None,
                no_sound=True,
            )
        )
        assert "@ 09:00" in captured["label"]
        # source == system local → no suffix
        for tzname in ("PDT", "PST", "America/Los_Angeles"):
            assert tzname not in captured["label"]

    def test_cmd_at_invalid_iana_exits_2_no_stdlib_leak(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            cmd_at(
                SimpleNamespace(
                    time="9am Mars/Bogus",
                    message=["x"],
                    bg=False,
                    sound=None,
                    repeat=1,
                    say=None,
                    no_sound=True,
                )
            )
        assert exc.value.code == 2
        out = capsys.readouterr().out
        assert "unknown timezone" in out
        assert "ZoneInfoNotFoundError" not in out
