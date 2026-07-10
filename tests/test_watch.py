"""Unit + thin-e2e checks for the `chime.watch` poll-source tracer."""

import pytest

from chime import cli
from chime.watch import WatchResult, matches, poll, render_line


def _fake_matched(capture):
    """A `watch.poll` stand-in that records its call and reports a match."""

    def fake_poll(command, predicate, *, interval, **_kw):
        capture.update(command=command, predicate=predicate, interval=interval)
        return WatchResult(command, predicate, "matched", 1, 1.0)

    return fake_poll


def test_matches_substring_hit():
    assert matches("service is UP now", "UP") is True


def test_matches_substring_miss():
    assert matches("service is down", "UP") is False


def test_matches_is_case_sensitive():
    # A case-sensitive substring over the whole snapshot: `up` must not match `UP`.
    assert matches("service is UP now", "up") is False


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


def test_cli_no_predicate_exits_2():
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "check-health"])
    assert exit_info.value.code == 2


def test_cli_predicate_given_twice_exits_2():
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["watch", "check-health", "UP", "--until", "UP"])
    assert exit_info.value.code == 2
