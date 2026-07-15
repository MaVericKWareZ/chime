"""Unit + thin-e2e checks for the `chime.watch` poll-source tracer."""

import pytest

from chime import cli
from chime.watch import WatchResult, matches, poll, render_line


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
