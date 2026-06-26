import json
import os
from datetime import datetime

import pytest

from chime import state


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Redirect state files to a fresh tmp dir for each test."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    yield tmp_path


def test_load_empty_when_missing():
    assert state.load() == []


def test_save_and_load_roundtrip(monkeypatch):
    # Naive targets are migrated to the system zone on load (ADR-0003); pin $TZ
    # so the round-trip is deterministic. Non-target fields survive verbatim.
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    entries = [
        {"pid": 1234, "message": "tea", "target": "2026-06-13T15:00:00"},
        {"pid": 5678, "message": "", "target": "2026-06-13T16:00:00"},
    ]
    state.save(entries)
    assert state.load() == [
        {"pid": 1234, "message": "tea", "target": "2026-06-13T15:00:00+05:30"},
        {"pid": 5678, "message": "", "target": "2026-06-13T16:00:00+05:30"},
    ]


def test_load_migrates_naive_target_to_system_zone(isolated_state, monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    state.state_file().write_text(
        json.dumps([{"pid": 1, "message": "tea", "target": "2026-06-13T18:30:00"}])
    )
    [rec] = state.load()
    parsed = datetime.fromisoformat(rec["target"])
    assert parsed.utcoffset().total_seconds() == 5.5 * 3600  # +05:30


def test_save_after_load_persists_offset_suffixed_target(isolated_state, monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    state.state_file().write_text(
        json.dumps([{"pid": 1, "message": "tea", "target": "2026-06-13T18:30:00"}])
    )
    state.save(state.load())
    on_disk = json.loads(state.state_file().read_text())[0]["target"]
    assert on_disk == "2026-06-13T18:30:00+05:30"


def test_source_fields_round_trip(isolated_state):
    entry = {
        "pid": 1,
        "message": "standup",
        "target": "2026-06-13T19:00:00+05:30",
        "source_tz": "America/New_York",
        "source_label": "EDT",
    }
    state.save([entry])
    [rec] = state.load()
    assert rec["source_tz"] == "America/New_York"
    assert rec["source_label"] == "EDT"


def test_same_tz_record_has_no_source_fields(isolated_state):
    state.save([{"pid": 1, "message": "x", "target": "2026-06-13T19:00:00+05:30"}])
    [rec] = state.load()
    assert "source_tz" not in rec
    assert "source_label" not in rec


def test_state_file_lives_under_xdg_state_home(isolated_state):
    state.save([{"pid": 1, "message": "x", "target": "2026-01-01T00:00:00"}])
    expected = isolated_state / "chime" / "alarms.json"
    assert expected.exists()
    assert json.loads(expected.read_text())[0]["pid"] == 1


def test_load_handles_corrupt_file(isolated_state):
    f = state.state_file()
    f.write_text("{not json")
    assert state.load() == []


def test_load_handles_non_list_payload(isolated_state):
    f = state.state_file()
    f.write_text('{"oops": true}')
    assert state.load() == []


def test_add_and_remove(monkeypatch):
    monkeypatch.setattr(state, "is_alive", lambda _pid: True)
    state.add({"pid": 1, "message": "a", "target": "2026-01-01T00:00:00"})
    state.add({"pid": 2, "message": "b", "target": "2026-01-01T00:00:00"})
    assert [a["pid"] for a in state.load()] == [1, 2]
    state.remove(1)
    assert [a["pid"] for a in state.load()] == [2]


def test_prune_drops_dead_pids(monkeypatch):
    entries = [
        {"pid": 100, "message": "alive", "target": "2026-01-01T00:00:00"},
        {"pid": 200, "message": "dead", "target": "2026-01-01T00:00:00"},
    ]
    state.save(entries)
    monkeypatch.setattr(state, "is_alive", lambda pid: pid == 100)
    pruned = state.prune()
    assert [a["pid"] for a in pruned] == [100]
    assert [a["pid"] for a in state.load()] == [100]


def test_is_alive_for_self():
    assert state.is_alive(os.getpid()) is True


def test_is_alive_for_unlikely_pid():
    assert state.is_alive(2**31 - 2) is False
