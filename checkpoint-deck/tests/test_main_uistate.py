"""Callables nuevos del panel (v1.3.0): compat, versión vista, sugerencias de carpeta distinta, ignorarlas y detalle de juego."""

import asyncio
import json
from pathlib import Path

import checkpoint_uistate
from test_main_library import make_plugin


def boot(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:9", tmp_path, monkeypatch)
    asyncio.run(p._main())
    return p


def put_games(p, *rows):
    p.jobs._games = [{k: v for k, v in r.items() if k != "path"} for r in rows]
    p.jobs._paths = {r["id"]: r.get("path") for r in rows}


def sugg(appid, *paths, conf="high"):
    return {"source": "steam", "id": appid, "name": "J", "confidence": conf, "paths": list(paths)}


def P(path, **o):
    return {"path": path, "exists": True, "mtime": 5, "size": 9, "files": 1, **o}


def test_get_compat_is_none_until_a_ping_and_follows_it(fake_decky, tmp_path, monkeypatch):
    p = boot(fake_decky, tmp_path, monkeypatch)
    assert asyncio.run(p.get_compat()) == {"compat": None}
    p._compat = "plugin_outdated"
    assert asyncio.run(p.get_compat()) == {"compat": "plugin_outdated"}


def test_ack_version_tells_the_previous_installed_version(fake_decky, tmp_path, monkeypatch):
    p = boot(fake_decky, tmp_path, monkeypatch)
    first = asyncio.run(p.ack_version())
    assert first["ok"] is True and first["previous"] is None and first["current"]
    again = asyncio.run(p.ack_version())
    assert again["previous"] == first["current"]
    seen = Path(fake_decky.DECKY_PLUGIN_SETTINGS_DIR) / "seen_version.json"
    seen.write_text(json.dumps({"version": "0.0.1"}))
    assert asyncio.run(p.ack_version())["previous"] == "0.0.1"


def test_suggest_changes_lists_configured_games_with_a_different_safe_folder(fake_decky, tmp_path, monkeypatch):
    p = boot(fake_decky, tmp_path, monkeypatch)
    put_games(p, {"id": "g1", "name": "Uno", "appid": 10, "path": "/h/vieja"}, {"id": "g2", "name": "Dos", "appid": 20, "path": "/h/ok"})
    monkeypatch.setattr(p.saves, "all", lambda: {"ok": True, "games": [sugg(10, P("/h/nueva")), sugg(20, P("/h/ok"))]})
    out = asyncio.run(p.suggest_changes())
    assert out["ok"] is True and [i["game"] for i in out["items"]] == ["g1"] and out["items"][0]["path"] == "/h/nueva"


def test_suggest_changes_without_manifest_reports_the_error(fake_decky, tmp_path, monkeypatch):
    p = boot(fake_decky, tmp_path, monkeypatch)
    monkeypatch.setattr(p.saves, "all", lambda: {"ok": False, "error": "no_manifest"})
    assert asyncio.run(p.suggest_changes()) == {"ok": False, "error": "no_manifest"}


def test_ignore_suggestion_is_remembered_and_hides_that_folder_only(fake_decky, tmp_path, monkeypatch):
    p = boot(fake_decky, tmp_path, monkeypatch)
    put_games(p, {"id": "g1", "name": "Uno", "appid": 10, "path": "/h/vieja"})
    monkeypatch.setattr(p.saves, "all", lambda: {"ok": True, "games": [sugg(10, P("/h/nueva"))]})
    assert asyncio.run(p.ignore_suggestion("g1", "/h/nueva")) == {"ok": True}
    assert asyncio.run(p.suggest_changes())["items"] == []
    import main

    p2 = main.Plugin()  # persiste entre cargas del plugin
    asyncio.run(p2._main())
    put_games(p2, {"id": "g1", "name": "Uno", "appid": 10, "path": "/h/vieja"})
    monkeypatch.setattr(p2.saves, "all", lambda: {"ok": True, "games": [sugg(10, P("/h/nueva"))]})
    assert asyncio.run(p2.suggest_changes())["items"] == []
    monkeypatch.setattr(p2.saves, "all", lambda: {"ok": True, "games": [sugg(10, P("/h/mas_nueva"))]})
    assert len(asyncio.run(p2.suggest_changes())["items"]) == 1


def test_ignore_suggestion_rejects_unknown_game_and_bad_path(fake_decky, tmp_path, monkeypatch):
    p = boot(fake_decky, tmp_path, monkeypatch)
    put_games(p, {"id": "g1", "name": "Uno", "appid": 10, "path": "/h/v"})
    assert asyncio.run(p.ignore_suggestion("nope", "/x"))["error"] == "unknown_game"
    assert asyncio.run(p.ignore_suggestion("g1", "relativa"))["error"] == "bad_args"


def test_game_detail_measures_the_folder_and_returns_last_sync(fake_decky, tmp_path, monkeypatch):
    p = boot(fake_decky, tmp_path, monkeypatch)
    folder = Path.home() / "Saves" / "J"
    folder.mkdir(parents=True)
    (folder / "a.sav").write_bytes(b"12345")
    put_games(p, {"id": "g1", "name": "Uno", "appid": 10, "path": str(folder)}, {"id": "g2", "name": "Dos", "appid": None, "path": None})
    p.stamps.record("g1", {"state": "uploaded", "files": 1})
    out = asyncio.run(p.game_detail("g1"))
    assert out["ok"] is True and out["path"] == str(folder)
    assert out["folder"]["exists"] is True and out["folder"]["size"] == 5 and out["folder"]["files"] == 1
    assert out["last"]["state"] == "uploaded"
    assert asyncio.run(p.game_detail("g2"))["folder"] == {"exists": False}
    assert asyncio.run(p.game_detail("g2"))["last"] is None
    assert asyncio.run(p.game_detail("nope"))["error"] == "unknown_game"


def test_get_game_paths_returns_the_configured_folders_apart_from_the_sync_state(fake_decky, tmp_path, monkeypatch):
    p = boot(fake_decky, tmp_path, monkeypatch)
    put_games(p, {"id": "g1", "name": "Uno", "appid": 10, "path": "/h/v"}, {"id": "g2", "name": "Dos", "appid": None, "path": None})
    assert asyncio.run(p.get_game_paths()) == {"ok": True, "paths": {"g1": "/h/v", "g2": None}}
    assert all("path" not in g for g in asyncio.run(p.get_sync_state())["games"])


def test_ignored_remove_forgets_one_game_and_persists(tmp_path):
    ig = checkpoint_uistate.Ignored(str(tmp_path))
    ig.add("a", "/x")
    ig.add("b", "/y")
    assert ig.remove("a") is True and ig.remove("nada") is True
    assert checkpoint_uistate.Ignored(str(tmp_path)).as_dict() == {"b": "/y"}
