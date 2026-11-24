import os
import stat

from checkpoint_client import settings


def test_config_dir_default_is_dot_config(home):
    assert settings.config_dir() == str(home / ".config" / "checkpoint-client")


def test_config_dir_respects_xdg_and_override(home, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert settings.config_dir() == str(tmp_path / "xdg" / "checkpoint-client")
    monkeypatch.setenv("CHECKPOINT_CLIENT_CONFIG_DIR", str(tmp_path / "otra"))
    assert settings.config_dir() == str(tmp_path / "otra")


def test_save_load_roundtrip_with_private_permissions(settings_dir):
    settings.save_settings(settings_dir, {"hub_url": "http://h:1", "key": "ckd_x"})
    assert settings.load_settings(settings_dir) == {"hub_url": "http://h:1", "key": "ckd_x"}
    assert stat.S_IMODE(os.stat(os.path.join(settings_dir, "settings.json")).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(settings_dir).st_mode) == 0o700


def test_load_missing_or_corrupt_is_empty(settings_dir):
    assert settings.load_settings(settings_dir) == {}
    os.makedirs(settings_dir)
    with open(os.path.join(settings_dir, "settings.json"), "w", encoding="utf-8") as f:
        f.write("{no json")
    assert settings.load_settings(settings_dir) == {}


def test_save_leaves_no_temp_files(settings_dir):
    settings.save_settings(settings_dir, {"a": 1})
    settings.save_settings(settings_dir, {"a": 2})
    assert os.listdir(settings_dir) == ["settings.json"]


def test_linked_requires_ckd_key_and_hub(settings_dir):
    assert settings.linked({}) is None
    assert settings.linked({"hub_url": "http://h:1", "key": "ck_usuario"}) is None
    assert settings.linked({"hub_url": "", "key": "ckd_x"}) is None
    assert settings.linked({"hub_url": "http://h:1", "key": "ckd_x", "device": "pc"}) == ("http://h:1", "ckd_x", "pc")
