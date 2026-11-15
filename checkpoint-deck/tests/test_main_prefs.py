"""Preferencias de la interfaz (`get_prefs` / `set_pref`): una sola clave booleana, en `prefs.json` aparte de la clave."""

import asyncio
import json
import stat
from pathlib import Path

from test_main_library import KEY, make_plugin


def prefs_file(fake_decky):
    return Path(fake_decky.DECKY_PLUGIN_SETTINGS_DIR) / "prefs.json"


def test_default_is_to_show_unconfigured(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:9", tmp_path, monkeypatch)
    assert asyncio.run(p.get_prefs()) == {"ok": True, "show_unconfigured": True}


def test_set_pref_persists_across_plugin_instances(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:9", tmp_path, monkeypatch)
    out = asyncio.run(p.set_pref("show_unconfigured", False))
    assert out == {"ok": True, "show_unconfigured": False}
    assert json.loads(prefs_file(fake_decky).read_text()) == {"show_unconfigured": False}
    import main

    assert asyncio.run(main.Plugin().get_prefs()) == {"ok": True, "show_unconfigured": False}
    assert asyncio.run(p.set_pref("show_unconfigured", True))["show_unconfigured"] is True
    assert asyncio.run(main.Plugin().get_prefs())["show_unconfigured"] is True


def test_set_pref_rejects_unknown_key_and_non_boolean(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:9", tmp_path, monkeypatch)
    for key, val in (("otra", True), ("show_unconfigured", "no"), ("show_unconfigured", 0), ("show_unconfigured", None), (5, True)):
        out = asyncio.run(p.set_pref(key, val))
        assert out["ok"] is False and out["error"] in ("unknown_pref", "bad_value"), (key, val)
    assert not prefs_file(fake_decky).exists()  # nada se guardó
    assert asyncio.run(p.set_pref("otra", True))["error"] == "unknown_pref"
    assert asyncio.run(p.set_pref("show_unconfigured", "no"))["error"] == "bad_value"


def test_prefs_never_touch_the_key_file_and_ignore_junk(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:9", tmp_path, monkeypatch)
    settings = Path(fake_decky.DECKY_PLUGIN_SETTINGS_DIR) / "settings.json"
    before = settings.read_text()
    asyncio.run(p.set_pref("show_unconfigured", False))
    assert settings.read_text() == before
    assert KEY not in prefs_file(fake_decky).read_text()
    assert stat.S_IMODE(prefs_file(fake_decky).stat().st_mode) == 0o600
    prefs_file(fake_decky).write_text(json.dumps({"show_unconfigured": "x", "extra": 1}))
    assert asyncio.run(p.get_prefs()) == {"ok": True, "show_unconfigured": True}  # valor corrupto: por defecto
    prefs_file(fake_decky).write_text("no es json")
    assert asyncio.run(p.get_prefs()) == {"ok": True, "show_unconfigured": True}
