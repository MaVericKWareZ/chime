"""Delivery split: `deliver()` fans out to notify/say/sound; `trigger()` still
renders the timer header byte-identically on top of it."""

from chime import alerts


def _record(monkeypatch):
    calls = {}
    monkeypatch.setattr(alerts, "notify", lambda *a, **k: calls.setdefault("notify", (a, k)))
    monkeypatch.setattr(alerts, "speak", lambda *a, **k: calls.setdefault("speak", (a, k)))
    monkeypatch.setattr(
        alerts, "play_sound", lambda *a, **k: calls.setdefault("play_sound", (a, k))
    )
    return calls


def test_deliver_notify_and_sound_no_say(monkeypatch):
    calls = _record(monkeypatch)
    alerts.deliver("chime", "done", sound="Glass", repeat=3, do_say=False, silent=False)
    assert calls["notify"] == (("chime", "done"), {"sound": "Glass"})
    assert "speak" not in calls
    assert calls["play_sound"] == (("Glass",), {"repeat": 3})


def test_deliver_silent_suppresses_sound_and_notify_sound(monkeypatch):
    calls = _record(monkeypatch)
    alerts.deliver("chime", "done", sound="Glass", repeat=3, do_say=False, silent=True)
    assert calls["notify"] == (("chime", "done"), {"sound": None})
    assert "play_sound" not in calls


def test_deliver_say_speaks_message(monkeypatch):
    calls = _record(monkeypatch)
    alerts.deliver("chime", "done", sound="Glass", repeat=1, do_say=True, silent=False)
    assert calls["speak"] == (("done",), {})


def test_trigger_header_unchanged_and_delegates(monkeypatch, capsys):
    calls = {}
    monkeypatch.setattr(alerts, "deliver", lambda *a, **k: calls.setdefault("deliver", (a, k)))
    alerts.trigger("tea", "Glass", 3, False, False)
    out = capsys.readouterr().out
    lines = out.split("\n")
    # blank / headline / timestamp / blank — timestamp text varies, so check framing.
    assert lines[0] == ""
    assert alerts.c("⏰  TEA", alerts.BOLD + alerts.YELLOW) in out
    assert calls["deliver"] == (
        ("Alarm", "tea"),
        {"sound": "Glass", "repeat": 3, "do_say": False, "silent": False},
    )
