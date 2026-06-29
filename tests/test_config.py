import json
from pathlib import Path

import pytest

from chime import config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redirect the config file to a fresh tmp dir for each test."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    yield tmp_path


def test_path_uses_xdg_config_home(tmp_path):
    assert config.config_file() == tmp_path / "chime" / "config.json"


def test_path_posix_fallback_to_dot_config(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert config.config_file() == tmp_path / ".config" / "chime" / "config.json"


def test_path_windows_uses_appdata_roaming(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(config.sys, "platform", "win32")
    roaming = tmp_path / "Roaming"
    monkeypatch.setenv("APPDATA", str(roaming))
    assert config.config_file() == roaming / "chime" / "config.json"


def test_set_then_get_roundtrip():
    config.set("timezone", "America/New_York")
    assert config.get("timezone") == "America/New_York"


def test_unset_removes_key_but_preserves_unknown_keys():
    # An unknown key written by a future chime version must survive a mutation
    # on a different key (preserve-on-read round-trip).
    config.config_file().write_text(json.dumps({"timezone": "Asia/Kolkata", "legacy_key": "keep"}))
    config.unset("timezone")
    assert config.get("timezone") is None
    assert config.get("legacy_key") == "keep"


def test_unset_missing_key_is_noop():
    config.unset("timezone")
    assert not config.config_file().exists()


def test_reset_removes_file():
    config.set("timezone", "America/New_York")
    config.reset()
    assert not config.config_file().exists()


def test_get_returns_default_when_absent():
    assert config.get("timezone", "fallback") == "fallback"


def test_view_returns_full_dict_and_empty_when_missing():
    assert config.view() == {}
    config.set("timezone", "America/New_York")
    assert config.view() == {"timezone": "America/New_York"}


def test_set_typo_raises_with_hint_and_writes_nothing():
    with pytest.raises(config.ConfigError) as excinfo:
        config.set("timezon", "America/New_York")
    assert "did you mean 'timezone'?" in str(excinfo.value)
    assert not config.config_file().exists()


def test_set_far_unknown_key_raises_without_hint():
    with pytest.raises(config.ConfigError) as excinfo:
        config.set("totally_unknown", "X")
    assert "did you mean" not in str(excinfo.value)
    assert not config.config_file().exists()


def test_corrupt_file_warns_to_stderr_and_yields_empty_view(capsys):
    config.config_file().write_text("{ not valid json")
    assert config.view() == {}
    err = capsys.readouterr().err
    assert "is not valid JSON — ignoring" in err


def test_set_recovers_corrupt_file_with_valid_json():
    config.config_file().write_text("{ not valid json")
    config.set("timezone", "America/New_York")
    assert json.loads(config.config_file().read_text()) == {"timezone": "America/New_York"}


def test_write_is_atomic_no_temp_leftover():
    config.set("timezone", "America/New_York")
    d = config.config_dir()
    assert list(d.glob("*.tmp")) == []
    assert json.loads(config.config_file().read_text()) == {"timezone": "America/New_York"}
