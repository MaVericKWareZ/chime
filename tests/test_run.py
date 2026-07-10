"""Unit + thin-e2e checks for the `chime.run` completion-notification module."""

import sys

import pytest

import chime.run as run_mod
from chime.run import (
    CompletionResult,
    exit_status,
    outcome_for,
    render_line,
    run,
    should_fire,
    split_argv,
)


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


WHEN_BOOL = {"--say", "--no-sound"}
WHEN_VALUE = {"--sound", "--repeat"}


def _split(raw):
    return split_argv(raw, bool_flags=WHEN_BOOL, value_flags=WHEN_VALUE)


# ---------- outcome classifier ----------


def test_outcome_passed_on_zero():
    assert outcome_for(0) == "passed"


def test_outcome_failed_on_nonzero():
    assert outcome_for(2) == "failed"
    assert outcome_for(139) == "failed"


def test_outcome_aborted_when_interrupted():
    # A Chime-caught interrupt is `aborted` regardless of the child's exit code.
    assert outcome_for(130, was_interrupted=True) == "aborted"
    assert outcome_for(0, was_interrupted=True) == "aborted"
    assert outcome_for(139, was_interrupted=True) == "aborted"


# ---------- firing filter (--only-fail / --only-pass) ----------


def test_should_fire_no_filter_fires_on_pass_and_fail():
    # Bare `chime when` (only=None) fires on any completion.
    assert should_fire("passed", None) is True
    assert should_fire("failed", None) is True


def test_should_fire_only_fail():
    assert should_fire("failed", "fail") is True
    assert should_fire("passed", "fail") is False


def test_should_fire_only_pass():
    assert should_fire("passed", "pass") is True
    assert should_fire("failed", "pass") is False


def test_should_fire_aborted_never_fires():
    # An aborted run (Ctrl-C) never fires, whatever the filter.
    assert should_fire("aborted", None) is False
    assert should_fire("aborted", "fail") is False
    assert should_fire("aborted", "pass") is False


# ---------- exit-code mapping ----------


def test_exit_status_propagates_normal_codes():
    assert exit_status(0) == 0
    assert exit_status(2) == 2


def test_exit_status_maps_signal_death():
    assert exit_status(-11) == 139  # SIGSEGV -> 128 + 11


# ---------- argv splitter (model A) ----------


def test_split_bare_command():
    assert _split(["make", "test"]) == ([], ["make", "test"])


def test_split_chime_opts_before_command():
    assert _split(["--sound", "Glass", "make", "test"]) == (
        ["--sound", "Glass"],
        ["make", "test"],
    )


def test_split_flags_after_command_belong_to_command():
    assert _split(["make", "--sound", "x"]) == ([], ["make", "--sound", "x"])


def test_split_double_dash_escape():
    assert _split(["--", "--oddtool"]) == ([], ["--oddtool"])


def test_split_unknown_flag_before_command_raises():
    with pytest.raises(ValueError):
        _split(["--bogus", "make"])


# ---------- completion-line rendering ----------


def test_render_line_shows_command_exit_and_elapsed():
    result = CompletionResult("make test", "passed", 0, 252.0)
    assert render_line(result) == "🔔  `make test` finished — exit 0 (4m 12s)"


def test_render_line_names_signal_on_posix(monkeypatch):
    monkeypatch.setattr(run_mod.sys, "platform", "linux")
    result = CompletionResult("make test", "failed", 139, 123.0)  # 128 + 11
    assert render_line(result) == "🔔  `make test` killed by SIGSEGV (2m 03s)"


def test_render_line_degrades_on_windows(monkeypatch):
    monkeypatch.setattr(run_mod.sys, "platform", "win32")
    result = CompletionResult("make test", "failed", 139, 123.0)
    assert render_line(result) == "🔔  `make test` exited abnormally (code 139) (2m 03s)"


# ---------- run(): thin, portable e2e ----------


def test_run_success():
    result = run(_py("import sys; sys.exit(0)"))
    assert result.outcome == "passed"
    assert result.exit_code == 0
    assert result.command == " ".join(_py("import sys; sys.exit(0)"))
    assert result.elapsed >= 0


def test_run_failure_propagates_exit_code():
    result = run(_py("import sys; sys.exit(2)"))
    assert result.outcome == "failed"
    assert result.exit_code == 2


def test_run_command_not_found_is_127():
    result = run(["definitely-not-a-real-command-xyz"])
    assert result.exit_code == 127
    assert result.outcome == "failed"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX live signals")
def test_run_foreign_sigsegv_is_failed():
    # A signal Chime did NOT catch is a real (failed) completion → 128 + signum.
    result = run(_py("import os, signal; os.kill(os.getpid(), signal.SIGSEGV)"))
    assert result.outcome == "failed"
    assert result.exit_code == 139  # 128 + 11


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX live signals")
def test_run_foreign_sigint_is_failed_not_aborted():
    # A SIGINT death Chime did not catch (targets only the child) is `failed`,
    # never `aborted` — the distinguishing factor is who caught the interrupt.
    result = run(_py("import os, signal; os.kill(os.getpid(), signal.SIGINT)"))
    assert result.outcome == "failed"
    assert result.exit_code == 130  # 128 + 2


def test_run_aborted_on_keyboard_interrupt(monkeypatch):
    # A Chime-caught interrupt (Ctrl-C reaches the child via the shared console)
    # surfaces as `aborted`, exiting 130 — no dependence on real signals.
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(run_mod.subprocess, "run", interrupt)
    result = run(["sleep", "100"])
    assert result.outcome == "aborted"
    assert result.exit_code == 130


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX exec permissions")
def test_run_not_executable_is_126(tmp_path):
    script = tmp_path / "not-exec.sh"
    script.write_text("#!/bin/sh\necho hi\n")  # no +x bit
    result = run([str(script)])
    assert result.exit_code == 126
    assert result.outcome == "failed"
