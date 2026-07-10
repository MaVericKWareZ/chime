"""End-to-end CLI checks that don't require firing actual alarms."""

import json
import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from chime import cli, config, state
from chime.cli import _register_bg, _split_flags, cmd_at, run_alarm

CHIME = [sys.executable, "-m", "chime"]


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(CHIME + args, capture_output=True, text=True, check=False)


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Keep every CLI test off the real user config dir — cmd_at reads
    config.get('timezone') for the effective-tz chain."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))


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


class TestRegisterBg:
    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.setattr(state, "is_alive", lambda _pid: True)

    def test_target_is_offset_aware(self, tmp_path, monkeypatch):
        self._isolate(tmp_path, monkeypatch)
        _register_bg(4321, 60, "tea", "Glass", True)
        rec = json.loads((tmp_path / "chime" / "alarms.json").read_text())[0]
        assert datetime.fromisoformat(rec["target"]).utcoffset() is not None

    def test_persists_source_fields_when_given(self, tmp_path, monkeypatch):
        self._isolate(tmp_path, monkeypatch)
        _register_bg(
            4321,
            60,
            "mtg",
            "Glass",
            True,
            source_tz="America/New_York",
            source_label="EDT",
        )
        rec = json.loads((tmp_path / "chime" / "alarms.json").read_text())[0]
        assert rec["source_tz"] == "America/New_York"
        assert rec["source_label"] == "EDT"

    def test_omits_source_fields_when_absent(self, tmp_path, monkeypatch):
        self._isolate(tmp_path, monkeypatch)
        _register_bg(4321, 60, "tea", "Glass", True)
        rec = json.loads((tmp_path / "chime" / "alarms.json").read_text())[0]
        assert "source_tz" not in rec
        assert "source_label" not in rec


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


class TestBackgroundSourceThreading:
    def test_run_alarm_forwards_source_fields(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(cli, "run_background", lambda *a, **k: captured.update(k))
        run_alarm(
            60,
            "mtg",
            _fake_opts(bg=True),
            source_tz="America/New_York",
            record_label="EDT",
        )
        assert captured["source_tz"] == "America/New_York"
        assert captured["source_label"] == "EDT"  # record carries the typed label

    def test_cmd_at_bg_cross_tz_persists_typed_label(self, monkeypatch):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("Asia/Kolkata"))
        captured = {}
        monkeypatch.setattr(cli, "run_background", lambda *a, **k: captured.update(k))
        cmd_at(
            SimpleNamespace(
                time="9am EDT",
                message=["mtg"],
                bg=True,
                sound=None,
                repeat=1,
                say=None,
                no_sound=True,
            )
        )
        assert captured["source_tz"] == "America/New_York"
        assert captured["source_label"] == "EDT"

    def test_cmd_at_bg_same_zone_omits_source_fields(self, monkeypatch):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("America/Los_Angeles"))
        captured = {}
        monkeypatch.setattr(cli, "run_background", lambda *a, **k: captured.update(k))
        cmd_at(
            SimpleNamespace(
                time="9am America/Los_Angeles",
                message=["x"],
                bg=True,
                sound=None,
                repeat=1,
                say=None,
                no_sound=True,
            )
        )
        assert captured.get("source_tz") is None
        assert captured.get("source_label") is None


class TestListSourceLabel:
    def _seed(self, tmp_path, monkeypatch, record):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.setattr(state, "is_alive", lambda _pid: True)
        (tmp_path / "chime").mkdir(parents=True, exist_ok=True)
        (tmp_path / "chime" / "alarms.json").write_text(json.dumps([record]))

    def test_cross_tz_alarm_shows_source_suffix(self, tmp_path, monkeypatch, capsys):
        self._seed(
            tmp_path,
            monkeypatch,
            {
                "pid": 1,
                "message": "meeting",
                "target": "2099-01-01T09:30:00+05:30",
                "source_tz": "America/New_York",
                "source_label": "EDT",
            },
        )
        cli.cmd_list(SimpleNamespace())
        out = capsys.readouterr().out
        assert "meeting" in out
        assert "EDT)" in out  # source label echoed in parens

    def test_same_tz_alarm_has_no_suffix_and_no_crash(self, tmp_path, monkeypatch, capsys):
        self._seed(
            tmp_path,
            monkeypatch,
            {
                "pid": 1,
                "message": "tea",
                "target": "2099-01-01T09:30:00+05:30",
            },
        )
        cli.cmd_list(SimpleNamespace())
        out = capsys.readouterr().out
        alarm_line = next(line for line in out.splitlines() if "tea" in line)
        assert "(" not in alarm_line  # no source suffix for same-tz records


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

    def test_cmd_at_typo_inline_tz_suggests_iana_names(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cmd_at(
                SimpleNamespace(
                    time="9am londn",
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
        assert "did you mean:" in out
        assert "Europe/London" in out


class TestConfigCommand:
    def test_set_timezone_stores_canonical_and_echoes(self, capsys):
        cli.cmd_config(SimpleNamespace(verb="set", key="timezone", value="EDT"))
        out = capsys.readouterr().out
        assert "timezone set to America/New_York" in out
        assert "(EDT)" in out
        assert config.get("timezone") == "America/New_York"

    def test_set_timezone_iana_form_omits_parens(self, capsys):
        cli.cmd_config(SimpleNamespace(verb="set", key="timezone", value="Asia/Kolkata"))
        out = capsys.readouterr().out
        assert "timezone set to Asia/Kolkata" in out
        assert "(" not in out  # label == canonical → no redundant parenthetical

    def test_view_shows_configured_with_system(self, monkeypatch, capsys):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("America/New_York"))
        config.set("timezone", "Asia/Kolkata")
        cli.cmd_config(SimpleNamespace(verb=None, key=None, value=None))
        out = capsys.readouterr().out
        assert "Timezone: Asia/Kolkata (overrides system: America/New_York)" in out

    def test_view_not_set_form(self, monkeypatch, capsys):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("America/New_York"))
        cli.cmd_config(SimpleNamespace(verb=None, key=None, value=None))
        out = capsys.readouterr().out
        assert "Timezone: (not set — using system: America/New_York)" in out

    def test_get_prints_plain_value(self, capsys):
        config.set("timezone", "Asia/Kolkata")
        cli.cmd_config(SimpleNamespace(verb="get", key="timezone", value=None))
        out = capsys.readouterr().out
        assert out == "Asia/Kolkata\n"  # no decoration, script-friendly

    def test_get_unset_exits_nonzero_no_stdout(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.cmd_config(SimpleNamespace(verb="get", key="timezone", value=None))
        assert exc.value.code != 0
        assert capsys.readouterr().out == ""

    def test_unset_removes_key(self, capsys):
        config.set("timezone", "Asia/Kolkata")
        cli.cmd_config(SimpleNamespace(verb="unset", key="timezone", value=None))
        assert config.get("timezone") is None

    def test_reset_wipes_file(self):
        config.set("timezone", "Asia/Kolkata")
        cli.cmd_config(SimpleNamespace(verb="reset", key=None, value=None))
        assert not config.config_file().exists()

    def test_set_ambiguous_errors_and_writes_nothing(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.cmd_config(SimpleNamespace(verb="set", key="timezone", value="IST"))
        assert exc.value.code == 2
        assert "Asia/Kolkata" in capsys.readouterr().out
        assert config.get("timezone") is None

    def test_set_unknown_zone_errors(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.cmd_config(SimpleNamespace(verb="set", key="timezone", value="Mars/Bogus"))
        assert exc.value.code == 2
        assert "unknown timezone" in capsys.readouterr().out

    def test_set_typo_zone_suggests_iana_names(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.cmd_config(SimpleNamespace(verb="set", key="timezone", value="londn"))
        assert exc.value.code == 2
        out = capsys.readouterr().out
        assert "unknown timezone" in out
        assert "did you mean:" in out
        assert "Europe/London" in out
        assert config.get("timezone") is None  # rejected value writes nothing

    def test_set_far_zone_omits_suggestion_line(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.cmd_config(SimpleNamespace(verb="set", key="timezone", value="xyzzy123"))
        assert exc.value.code == 2
        out = capsys.readouterr().out
        assert "unknown timezone" in out
        assert "did you mean" not in out

    def test_set_ambiguous_has_no_suggestion_line(self, capsys):
        # IST already carries a disambiguation list — it must not also get a
        # fuzzy "did you mean" line.
        with pytest.raises(SystemExit):
            cli.cmd_config(SimpleNamespace(verb="set", key="timezone", value="IST"))
        assert "did you mean" not in capsys.readouterr().out

    def test_set_typo_key_errors_with_hint(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.cmd_config(SimpleNamespace(verb="set", key="timezon", value="Asia/Kolkata"))
        assert exc.value.code == 2
        assert "did you mean 'timezone'?" in capsys.readouterr().out

    def test_subcommand_dispatch_through_main(self):
        # End-to-end through argv dispatch: set then get via subprocess
        # (XDG_CONFIG_HOME is monkeypatched into os.environ, so the child inherits it).
        assert run(["config", "set", "timezone", "EDT"]).returncode == 0
        got = run(["config", "get", "timezone"])
        assert got.returncode == 0
        assert got.stdout.strip() == "America/New_York"


class TestEffectiveTzChain:
    """`chime at 9am` resolves inline → --tz → configured → system (ADR-0002)."""

    def _at(self, **overrides):
        base = dict(
            time="9am",
            tz=None,
            message=["x"],
            bg=True,
            sound=None,
            repeat=1,
            say=None,
            no_sound=True,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_configured_tz_schedules_in_that_zone_and_decorates(self, monkeypatch):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("America/New_York"))
        config.set("timezone", "Asia/Kolkata")
        captured = {}
        monkeypatch.setattr(cli, "run_background", lambda *a, **k: captured.update(k))
        cmd_at(self._at())
        assert captured["source_tz"] == "Asia/Kolkata"  # cross-tz config → record persisted

    def test_configured_same_as_system_omits_decoration(self, monkeypatch):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("America/New_York"))
        config.set("timezone", "America/New_York")
        captured = {}
        monkeypatch.setattr(cli, "run_background", lambda *a, **k: captured.update(k))
        cmd_at(self._at())
        assert captured.get("source_tz") is None  # configured == system → byte-identical

    def test_inline_overrides_configured(self, monkeypatch):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("Asia/Kolkata"))
        config.set("timezone", "Asia/Kolkata")
        captured = {}
        monkeypatch.setattr(cli, "run_background", lambda *a, **k: captured.update(k))
        cmd_at(self._at(time="9am EDT"))
        assert captured["source_tz"] == "America/New_York"

    def test_flag_overrides_configured(self, monkeypatch):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("Asia/Kolkata"))
        config.set("timezone", "Asia/Kolkata")
        captured = {}
        monkeypatch.setattr(cli, "run_background", lambda *a, **k: captured.update(k))
        cmd_at(self._at(tz="EDT"))
        assert captured["source_tz"] == "America/New_York"

    def test_configured_cross_tz_foreground_header_decorated(self, monkeypatch):
        # Decorate decision: a configured zone that transforms the wall-clock shows
        # its label in the countdown header, just like an explicit source tz.
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("America/New_York"))
        config.set("timezone", "Asia/Kolkata")
        captured = _capture_label(monkeypatch)
        cmd_at(self._at(bg=False))
        assert "@ 09:00 IST" in captured["label"]

    def test_configured_same_tz_foreground_header_undecorated(self, monkeypatch):
        monkeypatch.setattr(cli.tz, "system_tz", lambda: ZoneInfo("America/New_York"))
        config.set("timezone", "America/New_York")
        captured = _capture_label(monkeypatch)
        cmd_at(self._at(bg=False))
        assert "@ 09:00" in captured["label"]
        for tzname in ("EST", "EDT", "Asia/Kolkata", "America/New_York"):
            assert tzname not in captured["label"]


class TestWhen:
    """`chime when <command>` — Completion notifications (process-monitoring 01)."""

    @pytest.fixture(autouse=True)
    def _no_real_alert(self, monkeypatch):
        self.delivered = []
        monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: self.delivered.append((a, k)))

    @staticmethod
    def _py(code):
        return [sys.executable, "-c", code]

    def test_fires_on_success_and_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["when", *self._py("import sys; sys.exit(0)")])
        assert exc.value.code == 0
        assert len(self.delivered) == 1

    def test_propagates_child_exit_code(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["when", *self._py("import sys; sys.exit(2)")])
        assert exc.value.code == 2

    def test_command_not_found_exits_127(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["when", "definitely-not-a-real-command-xyz"])
        assert exc.value.code == 127

    def test_no_command_errors(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["when"])
        assert exc.value.code == 2

    def test_chime_opts_consumed_command_passed_through(self, monkeypatch):
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return cli.run.CompletionResult(" ".join(argv), "passed", 0, 1.0)

        monkeypatch.setattr(cli.run, "run", fake_run)
        with pytest.raises(SystemExit):
            cli.main(["when", "--sound", "Glass", "make", "test"])
        assert captured["argv"] == ["make", "test"]
        assert self.delivered[0][1]["sound"] == "Glass"

    def test_flags_after_command_go_to_command(self, monkeypatch):
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return cli.run.CompletionResult(" ".join(argv), "passed", 0, 1.0)

        monkeypatch.setattr(cli.run, "run", fake_run)
        with pytest.raises(SystemExit):
            cli.main(["when", "make", "--verbose"])
        assert captured["argv"] == ["make", "--verbose"]

    def test_aborted_suppresses_alert_and_exits_130(self, monkeypatch):
        def fake_run(argv, **kwargs):
            return cli.run.CompletionResult(" ".join(argv), "aborted", 130, 1.0)

        monkeypatch.setattr(cli.run, "run", fake_run)
        with pytest.raises(SystemExit) as exc:
            cli.main(["when", "sleep", "100"])
        assert exc.value.code == 130
        assert self.delivered == []

    # --- firing filters: --only-fail / --only-pass (process-monitoring 03) ---

    def _fake_result(self, monkeypatch, outcome, exit_code):
        monkeypatch.setattr(
            cli.run,
            "run",
            lambda argv, **k: cli.run.CompletionResult(" ".join(argv), outcome, exit_code, 1.0),
        )

    def test_only_fail_suppresses_on_pass(self, monkeypatch, capsys):
        self._fake_result(monkeypatch, "passed", 0)
        with pytest.raises(SystemExit) as exc:
            cli.main(["when", "--only-fail", "make", "test"])
        assert exc.value.code == 0  # child code still propagated
        assert self.delivered == []  # no alert
        assert capsys.readouterr().out == ""  # no 🔔 line either

    def test_only_fail_fires_on_failure(self, monkeypatch):
        self._fake_result(monkeypatch, "failed", 2)
        with pytest.raises(SystemExit) as exc:
            cli.main(["when", "--only-fail", "make", "test"])
        assert exc.value.code == 2
        assert len(self.delivered) == 1

    def test_only_pass_fires_on_success(self, monkeypatch):
        self._fake_result(monkeypatch, "passed", 0)
        with pytest.raises(SystemExit) as exc:
            cli.main(["when", "--only-pass", "make", "test"])
        assert exc.value.code == 0
        assert len(self.delivered) == 1

    def test_only_pass_suppresses_on_failure(self, monkeypatch, capsys):
        self._fake_result(monkeypatch, "failed", 2)
        with pytest.raises(SystemExit) as exc:
            cli.main(["when", "--only-pass", "make", "test"])
        assert exc.value.code == 2  # child code still propagated
        assert self.delivered == []
        assert capsys.readouterr().out == ""

    def test_both_only_flags_error(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["when", "--only-fail", "--only-pass", "make", "test"])
        assert exc.value.code == 2
        assert self.delivered == []

    def test_aborted_never_fires_even_under_only_pass(self, monkeypatch):
        self._fake_result(monkeypatch, "aborted", 130)
        with pytest.raises(SystemExit) as exc:
            cli.main(["when", "--only-pass", "sleep", "100"])
        assert exc.value.code == 130
        assert self.delivered == []


class TestMonitor:
    """`… | chime monitor` — pipe-form Completion notifications (process-monitoring 04)."""

    @pytest.fixture(autouse=True)
    def _no_real_alert(self, monkeypatch):
        self.delivered = []
        monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: self.delivered.append((a, k)))

    def _fake_monitor(self, monkeypatch, label_box=None):
        def fake(stdin_buf, stdout_buf, label):
            if label_box is not None:
                label_box["label"] = label
            return cli.run.CompletionResult(label, "ended", None, 1.0)

        monkeypatch.setattr(cli.run, "monitor", fake)

    def test_fires_on_eof_and_exits_zero(self, monkeypatch, capsys):
        self._fake_monitor(monkeypatch)
        with pytest.raises(SystemExit) as exc:
            cli.main(["monitor"])
        assert exc.value.code == 0
        assert len(self.delivered) == 1
        assert self.delivered[0][0][1].startswith("stream ended")
        assert capsys.readouterr().out.startswith("🔔  stream ended")

    def test_label_reaches_the_alert(self, monkeypatch):
        box = {}
        self._fake_monitor(monkeypatch, label_box=box)
        with pytest.raises(SystemExit):
            cli.main(["monitor", "refactor auth"])
        assert box["label"] == "refactor auth"
        assert self.delivered[0][0][1] == "`refactor auth` stream ended (1s)"

    def test_sound_flag_consumed_by_chime(self, monkeypatch):
        box = {}
        self._fake_monitor(monkeypatch, label_box=box)
        with pytest.raises(SystemExit):
            cli.main(["monitor", "--sound", "Glass", "refactor auth"])
        assert box["label"] == "refactor auth"  # flag not swallowed into the label
        assert self.delivered[0][1]["sound"] == "Glass"

    def test_only_fail_errors(self, monkeypatch):
        self._fake_monitor(monkeypatch)
        with pytest.raises(SystemExit) as exc:
            cli.main(["monitor", "--only-fail"])
        assert exc.value.code == 2
        assert self.delivered == []

    def test_only_pass_errors(self, monkeypatch):
        self._fake_monitor(monkeypatch)
        with pytest.raises(SystemExit) as exc:
            cli.main(["monitor", "--only-pass"])
        assert exc.value.code == 2
        assert self.delivered == []
