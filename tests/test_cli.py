"""End-to-end CLI checks that don't require firing actual alarms."""

import subprocess
import sys

import pytest

from chime.cli import _split_flags

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
