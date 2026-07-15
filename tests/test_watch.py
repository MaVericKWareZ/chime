"""Unit + thin-e2e checks for the `chime.watch` poll-source tracer."""

from types import SimpleNamespace

import pytest

from chime import cli
from chime.watch import WatchResult, matches, poll, render_line, should_reopen, tail_file


def _stat(size, ino=1, dev=1):
    """A minimal stand-in for `os.stat_result` — only the fields `should_reopen` reads."""
    return SimpleNamespace(st_size=size, st_ino=ino, st_dev=dev)


def _file_driver(actions):
    """Deterministic `(sleep, clock)` for `tail_file`, like the injected clock in the
    poll tests but for a real file: each `sleep` step advances a shared clock *and*
    applies the next scripted action (append/truncate/create). A guard raises once the
    scripted actions are spent so a non-terminating implementation fails fast instead
    of looping forever. `state["sleeps"]` counts idle cycles for staleness assertions.
    """
    now = [0.0]
    state = {"sleeps": 0}

    def sleep(seconds):
        idx = state["sleeps"]
        state["sleeps"] += 1
        now[0] += seconds
        if idx < len(actions):
            actions[idx]()
        elif idx > len(actions) + 3:
            raise RuntimeError("tail_file did not terminate after its scripted actions")

    return sleep, (lambda: now[0]), state


def _fake_matched(capture):
    """A `watch.poll` stand-in that records its call and reports a match."""

    def fake_poll(command, predicate, *, interval, **_kw):
        capture.update(command=command, predicate=predicate, interval=interval, **_kw)
        return WatchResult(command, predicate, "matched", 1, 1.0)

    return fake_poll


def _fake_timed_out(capture):
    """A `watch.poll` stand-in that reports the give-up path (`timed_out`)."""

    def fake_poll(command, predicate, *, interval, **_kw):
        capture.update(command=command, predicate=predicate, interval=interval, **_kw)
        return WatchResult(command, predicate, "timed_out", 5, 10.0)

    return fake_poll


def _fake_tail_matched(capture):
    """A `watch.tail_file` stand-in that records its call and reports a match."""

    def fake_tail(path, predicate, *, interval, **_kw):
        capture.update(path=path, predicate=predicate, interval=interval, **_kw)
        return WatchResult(path, predicate, "matched", 1, 1.0)

    return fake_tail


def test_should_reopen_truncation():
    # Size shrank → the file was truncated in place; re-read from the top.
    assert should_reopen(_stat(size=500), _stat(size=10)) is True


def test_should_reopen_steady_growth_does_not_reopen():
    # Same file, grown (or unchanged) → keep tailing from the current position.
    assert should_reopen(_stat(size=100), _stat(size=200)) is False
    assert should_reopen(_stat(size=100), _stat(size=100)) is False


def test_should_reopen_rotation():
    # Same size but a new inode took the name → logrotate-style rotation.
    assert should_reopen(_stat(size=100, ino=1), _stat(size=100, ino=2)) is True
    # A different device (e.g. moved across mounts) also counts as rotation.
    assert should_reopen(_stat(size=100, dev=1), _stat(size=100, dev=2)) is True


def test_tail_file_fires_on_new_line_only(tmp_path):
    log = tmp_path / "deploy.log"
    log.write_text("Done\n")  # a stale match present *before* the watch starts

    def append():
        log.write_text(log.read_text() + "build Done\n")

    sleep, clock, state = _file_driver([append])
    result = tail_file(str(log), "Done", interval=1.0, sleep=sleep, clock=clock)

    assert result.outcome == "matched"
    assert result.source == str(log)
    assert result.predicate == "Done"
    # Proof the pre-existing "Done" did not fire: we had to sleep (and append) first.
    # A read-from-top bug would return on cycle 1 without ever sleeping.
    assert state["sleeps"] >= 1


def test_tail_file_holds_partial_line_until_newline(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("")  # exists, empty — start tailing from EOF (position 0)

    def append_partial():
        log.write_text(log.read_text() + "Do")  # no newline yet — must not fire

    def complete_line():
        log.write_text(log.read_text() + "ne\n")  # now the line is complete

    sleep, clock, state = _file_driver([append_partial, complete_line])
    result = tail_file(str(log), "Done", interval=1.0, sleep=sleep, clock=clock)

    assert result.outcome == "matched"
    # Firing required the newline: the bare "Do" step alone must not have matched.
    assert state["sleeps"] >= 2


def test_tail_file_waits_for_creation_then_tails_from_top(tmp_path):
    log = tmp_path / "late.log"  # does not exist when the watch starts
    assert not log.exists()

    def create_with_match():
        log.write_text("Done\n")  # the very first line of the new file matches

    sleep, clock, state = _file_driver([create_with_match])
    result = tail_file(str(log), "Done", interval=1.0, sleep=sleep, clock=clock)

    # A file created *after* we start waiting is read from the TOP (not EOF), so its
    # first line fires — and we had to wait (sleep) for it to appear.
    assert result.outcome == "matched"
    assert state["sleeps"] >= 1


def test_tail_file_follows_truncation(tmp_path):
    log = tmp_path / "rot.log"
    log.write_text("first line\n")  # present at start → we seek past it to EOF

    def truncate_and_write():
        log.write_text("Done\n")  # in-place rewind: size shrinks, fresh top line

    sleep, clock, _state = _file_driver([truncate_and_write])
    result = tail_file(str(log), "Done", interval=1.0, sleep=sleep, clock=clock)

    # The size shrank, so the reader re-opens and reads the rewritten file from top.
    assert result.outcome == "matched"


def test_tail_file_follows_rotation_new_inode(tmp_path):
    log = tmp_path / "svc.log"
    log.write_text("old and long enough\n")  # present at start → seek to EOF

    def rotate():
        # logrotate style: move the old file aside, drop a fresh inode in its place.
        (tmp_path / "svc.log.1").write_text(log.read_text())
        log.unlink()
        log.write_text("Done\n")

    sleep, clock, _state = _file_driver([rotate])
    result = tail_file(str(log), "Done", interval=1.0, sleep=sleep, clock=clock)

    # A new inode took the name → re-open and read the rotated-in file from its top.
    assert result.outcome == "matched"


def test_tail_file_times_out_when_never_matches(tmp_path):
    log = tmp_path / "quiet.log"
    log.write_text("nothing to see here\n")  # present, never grows a matching line

    # No scripted actions: every injected sleep just advances the clock.
    sleep, clock, _state = _file_driver([])
    result = tail_file(str(log), "Done", interval=5.0, timeout=10.0, sleep=sleep, clock=clock)

    assert result.outcome == "timed_out"
    assert result.source == str(log)
    assert result.predicate == "Done"


def test_tail_file_keep_watching_fires_each_matching_line(tmp_path):
    log = tmp_path / "stream.log"
    log.write_text("")  # empty at start → tail from EOF (position 0)

    def first():
        log.write_text(log.read_text() + "Done one\n")

    def second():
        log.write_text(log.read_text() + "Done two\n")

    fired = []
    sleep, clock, _state = _file_driver([first, second])
    result = tail_file(
        str(log),
        "Done",
        interval=5.0,
        timeout=10.0,  # bounds the otherwise-unbounded keep-watching loop
        keep_watching=True,
        on_fire=fired.append,
        sleep=sleep,
        clock=clock,
    )

    # keep-watching delivers each matching line via on_fire and never returns
    # `matched` — it only returns when the global timeout fires.
    assert result.outcome == "timed_out"
    assert len(fired) == 2
    assert [r.outcome for r in fired] == ["matched", "matched"]


def test_matches_substring_hit():
    assert matches("service is UP now", "UP") is True


def test_matches_substring_miss():
    assert matches("service is down", "UP") is False


def test_matches_is_case_sensitive():
    # A case-sensitive substring over the whole snapshot: `up` must not match `UP`.
    assert matches("service is UP now", "up") is False


def test_matches_regex_hit():
    assert matches("boom FATAL now", "ERROR|FATAL", regex=True) is True


def test_matches_regex_miss():
    assert matches("all quiet", "ERROR|FATAL", regex=True) is False


def test_matches_substring_treats_metachars_literally():
    # Without --regex, a `.` is a literal dot, not "any char".
    assert matches("a.b", "a.b") is True
    assert matches("axb", "a.b") is False


def test_matches_ignore_case_substring():
    assert matches("service is UP now", "up", ignore_case=True) is True


def test_matches_ignore_case_regex():
    assert matches("boom ERROR now", "error|fatal", regex=True, ignore_case=True) is True


def test_render_line_matched():
    result = WatchResult(
        source="curl -s localhost:8080/health",
        predicate="UP",
        outcome="matched",
        polls=2,
        elapsed=10.0,
    )
    line = render_line(result)
    assert line.startswith("🔔  ")
    assert "curl -s localhost:8080/health" in line
    assert "matched" in line
    assert "UP" in line
    assert "10s" in line  # fmt_duration(10.0)


def test_render_line_timed_out():
    result = WatchResult(
        source="curl -s localhost:8080/health",
        predicate="UP",
        outcome="timed_out",
        polls=3,
        elapsed=600.0,
    )
    line = render_line(result)
    assert line == ("🔔  `curl -s localhost:8080/health` timed out after 10m — no `UP`")


def test_poll_fires_on_first_match():
    result = poll(
        "check-health",
        "UP",
        interval=5.0,
        snapshot=lambda cmd: "status: UP is up",
        sleep=lambda s: None,
        clock=lambda: 0.0,
    )
    assert result.outcome == "matched"
    assert result.polls == 1
    assert result.source == "check-health"
    assert result.predicate == "UP"


def test_poll_polls_until_match():
    outputs = iter(["waiting", "waiting", "status UP"])
    ticks = iter([0.0, 6.0])  # start, then match time

    result = poll(
        "check-health",
        "UP",
        interval=3.0,
        snapshot=lambda cmd: next(outputs),
        sleep=lambda s: None,
        clock=lambda: next(ticks),
    )
    assert result.outcome == "matched"
    assert result.polls == 3
    assert result.elapsed == 6.0


def test_poll_sleeps_interval_between_polls():
    outputs = iter(["miss", "miss", "UP"])
    slept: list[float] = []

    poll(
        "check-health",
        "UP",
        interval=2.0,
        snapshot=lambda cmd: next(outputs),
        sleep=slept.append,
        clock=lambda: 0.0,
    )
    # Two misses → two sleeps of the interval; no sleep after the matching poll.
    assert slept == [2.0, 2.0]


def test_poll_times_out_when_never_matches():
    # `sleep` advances a shared clock, so the loop is deterministic regardless of
    # how many times `clock()` is read internally.
    now = [0.0]
    result = poll(
        "check-health",
        "UP",
        interval=5.0,
        timeout=10.0,
        snapshot=lambda cmd: "still waiting",
        sleep=lambda s: now.__setitem__(0, now[0] + s),
        clock=lambda: now[0],
    )
    assert result.outcome == "timed_out"
    assert result.elapsed == 10.0
    assert result.polls == 3  # polls at t=0, t=5, then t=10 trips the deadline


def test_poll_matches_before_timeout():
    now = [0.0]
    outputs = iter(["waiting", "status UP"])
    result = poll(
        "check-health",
        "UP",
        interval=5.0,
        timeout=100.0,
        snapshot=lambda cmd: next(outputs),
        sleep=lambda s: now.__setitem__(0, now[0] + s),
        clock=lambda: now[0],
    )
    assert result.outcome == "matched"
    assert result.polls == 2


def test_poll_threads_regex_to_matcher():
    # A regex predicate must reach `matches` from the loop, else this snapshot
    # never matches and the run times out instead of matching.
    now = [0.0]
    result = poll(
        "check-health",
        "ERROR|FATAL",
        interval=5.0,
        regex=True,
        timeout=30.0,
        snapshot=lambda cmd: "boom FATAL",
        sleep=lambda s: now.__setitem__(0, now[0] + s),
        clock=lambda: now[0],
    )
    assert result.outcome == "matched"
    assert result.polls == 1


def test_poll_e2e_real_command_matches_stdout():
    # Thin e2e: the default `_snapshot` runner really shells out once and matches.
    result = poll('printf "status: UP\n"', "UP", interval=5.0, sleep=lambda s: None)
    assert result.outcome == "matched"
    assert result.polls == 1
    assert result.elapsed >= 0


def test_poll_default_runner_includes_stderr():
    # The snapshot is combined stdout+stderr, so a predicate on stderr still fires.
    result = poll('printf "boom UP\n" >&2', "UP", interval=5.0, sleep=lambda s: None)
    assert result.outcome == "matched"
    assert result.polls == 1


def test_cli_until_and_bare_positional_are_equivalent(monkeypatch):
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: None)

    cap_flag = {}
    monkeypatch.setattr(cli.watch, "poll", _fake_matched(cap_flag))
    with pytest.raises(SystemExit) as flag_exit:
        cli.main(["watch", "check-health", "--until", "UP"])

    cap_bare = {}
    monkeypatch.setattr(cli.watch, "poll", _fake_matched(cap_bare))
    with pytest.raises(SystemExit) as bare_exit:
        cli.main(["watch", "check-health", "UP"])

    assert flag_exit.value.code == 0
    assert bare_exit.value.code == 0
    assert cap_flag["command"] == cap_bare["command"] == "check-health"
    assert cap_flag["predicate"] == cap_bare["predicate"] == "UP"


def test_cli_regex_and_ignore_case_flow_to_poll(monkeypatch):
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: None)
    cap = {}
    monkeypatch.setattr(cli.watch, "poll", _fake_matched(cap))
    with pytest.raises(SystemExit):
        cli.main(["watch", "check-health", "--regex", "--ignore-case", "--until", "E|F"])
    assert cap["regex"] is True
    assert cap["ignore_case"] is True


def test_cli_regex_ignore_case_default_false(monkeypatch):
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: None)
    cap = {}
    monkeypatch.setattr(cli.watch, "poll", _fake_matched(cap))
    with pytest.raises(SystemExit):
        cli.main(["watch", "check-health", "UP"])
    assert cap["regex"] is False
    assert cap["ignore_case"] is False


def test_cli_interval_flag_changes_cadence(monkeypatch):
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: None)
    cap = {}
    monkeypatch.setattr(cli.watch, "poll", _fake_matched(cap))
    with pytest.raises(SystemExit):
        cli.main(["watch", "check-health", "UP", "--interval", "2s"])
    assert cap["interval"] == 2.0


def test_cli_interval_defaults_to_five_seconds(monkeypatch):
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: None)
    cap = {}
    monkeypatch.setattr(cli.watch, "poll", _fake_matched(cap))
    with pytest.raises(SystemExit):
        cli.main(["watch", "check-health", "UP"])
    assert cap["interval"] == 5.0


def test_cli_sound_flag_flows_to_deliver(monkeypatch):
    delivered = []
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: delivered.append((a, k)))
    monkeypatch.setattr(cli.watch, "poll", _fake_matched({}))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "--sound", "Glass", "check-health", "--until", "UP"])
    assert exit_info.value.code == 0
    assert delivered[0][1]["sound"] == "Glass"


def test_cli_default_sound_applied_when_omitted(monkeypatch):
    delivered = []
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: delivered.append((a, k)))
    monkeypatch.setattr(cli.watch, "poll", _fake_matched({}))
    with pytest.raises(SystemExit):
        cli.main(["watch", "check-health", "UP"])
    assert delivered[0][1]["sound"] == cli.alerts.DEFAULT_SOUND


def test_cli_file_routes_to_tail_file(monkeypatch):
    # Both the --until form and the bare-predicate form resolve to (path, predicate)
    # with the FILE as the source — no command positional in file mode.
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: None)

    cap_flag = {}
    monkeypatch.setattr(cli.watch, "tail_file", _fake_tail_matched(cap_flag))
    with pytest.raises(SystemExit) as flag_exit:
        cli.main(["watch", "--file", "deploy.log", "--until", "Done"])

    cap_bare = {}
    monkeypatch.setattr(cli.watch, "tail_file", _fake_tail_matched(cap_bare))
    with pytest.raises(SystemExit) as bare_exit:
        cli.main(["watch", "--file", "deploy.log", "Done"])

    assert flag_exit.value.code == 0
    assert bare_exit.value.code == 0
    assert cap_flag["path"] == cap_bare["path"] == "deploy.log"
    assert cap_flag["predicate"] == cap_bare["predicate"] == "Done"


def test_cli_file_matched_exits_zero_and_delivers_once(monkeypatch):
    delivered = []
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: delivered.append(k))
    monkeypatch.setattr(cli.watch, "tail_file", _fake_tail_matched({}))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "--file", "deploy.log", "--until", "Done"])
    assert exit_info.value.code == 0
    assert len(delivered) == 1


def test_cli_keep_watching_requires_stream_source():
    # A bare command is a poll source (one-shot); --keep-watching needs --file.
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "echo hi", "UP", "--keep-watching"])
    assert exit_info.value.code == 2


def test_cli_file_aborted_exits_130(monkeypatch):
    # A mid-watch Ctrl-C surfaces as KeyboardInterrupt → fire nothing more, exit 130.
    # Raised directly so the test does not depend on real signals (mirrors run's path).
    delivered = []
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: delivered.append(k))

    def interrupt(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.watch, "tail_file", interrupt)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "--file", "app.log", "--until", "Done", "--keep-watching"])
    assert exit_info.value.code == 130
    assert delivered == []  # the terminal give-up alert is not delivered on abort


def test_cli_file_flags_thread_to_tail_file(monkeypatch):
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: None)
    cap = {}
    monkeypatch.setattr(cli.watch, "tail_file", _fake_tail_matched(cap))
    with pytest.raises(SystemExit):
        cli.main(
            [
                "watch",
                "--file",
                "app.log",
                "--until",
                "E|F",
                "--regex",
                "--ignore-case",
                "--keep-watching",
                "--timeout",
                "30s",
            ]
        )
    assert cap["regex"] is True
    assert cap["ignore_case"] is True
    assert cap["keep_watching"] is True
    assert cap["timeout"] == 30.0


def test_cli_file_bad_timeout_exits_2():
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "--file", "app.log", "--until", "Done", "--timeout", "nope"])
    assert exit_info.value.code == 2


def test_cli_no_command_exits_2():
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch"])
    assert exit_info.value.code == 2


def test_cli_matched_exits_zero_and_delivers(monkeypatch):
    delivered = []
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: delivered.append(k))
    monkeypatch.setattr(cli.watch, "poll", _fake_matched({}))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "check-health", "UP"])
    assert exit_info.value.code == 0
    assert len(delivered) == 1


def test_cli_timed_out_exits_one_and_still_delivers(monkeypatch):
    # The give-up path is a *fired* alert — deliver still runs, only the exit differs.
    delivered = []
    monkeypatch.setattr(cli.alerts, "deliver", lambda *a, **k: delivered.append(k))
    cap = {}
    monkeypatch.setattr(cli.watch, "poll", _fake_timed_out(cap))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "check-health", "UP", "--timeout", "10s"])
    assert exit_info.value.code == 1
    assert len(delivered) == 1
    assert cap["timeout"] == 10.0


def test_cli_bad_timeout_exits_2():
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "check-health", "UP", "--timeout", "nonsense"])
    assert exit_info.value.code == 2


def test_cli_no_predicate_exits_2():
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "check-health"])
    assert exit_info.value.code == 2


def test_cli_predicate_given_twice_exits_2():
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "check-health", "UP", "--until", "UP"])
    assert exit_info.value.code == 2
