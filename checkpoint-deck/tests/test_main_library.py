"""Métodos de `Plugin` en main.py (con `decky` falso): biblioteca de Steam y tareas de fondo."""

import asyncio
import importlib
import json
import logging
import shutil
from pathlib import Path

from checkpoint_hub import save_settings

FIX = Path(__file__).parent / "fixtures" / "steam"
KEY = "ckd_clave-de-prueba-9876"


def make_plugin(fake_decky, hub_url, tmp_path, monkeypatch, with_key=True):
    home = tmp_path / "deckhome"
    shutil.copytree(FIX / "home", home)
    shutil.copytree(FIX / "card", tmp_path / "card")
    shutil.copytree(FIX / "empty", tmp_path / "empty")
    vdf = home / ".local/share/Steam/steamapps/libraryfolders.vdf"
    vdf.write_text(vdf.read_text().replace("@HOME@", str(home)).replace("@ROOT@", str(tmp_path)))
    monkeypatch.setenv("HOME", str(home))
    if with_key:
        save_settings(fake_decky.DECKY_PLUGIN_SETTINGS_DIR, {"hub_url": hub_url, "key": KEY, "device": "steam-deck-x"})
    main = importlib.import_module("main")
    p = main.Plugin()
    return p


async def settled(p):
    for _ in range(300):
        s = await p.get_sync_state()
        if not s["running"]:
            return s
        await asyncio.sleep(0.02)
    raise AssertionError("no termina")


def test_refresh_library_ok(fake_decky, scripthub, tmp_path, monkeypatch, caplog):
    hub = scripthub(lambda r: (200, {"associated": [], "suggested": 2, "unchanged": 0, "ignored": 1}, {}))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)

    async def go():
        await p._main()
        started = await p.refresh_library()
        assert started["running"] and started["kind"] == "refresh"
        s = await settled(p)
        await p._unload()
        return s

    with caplog.at_level(logging.DEBUG):
        s = asyncio.run(go())
    assert s["summary"] == {"found": 3, "associated": 0, "suggested": 2, "unchanged": 0, "ignored": 1}
    sent = json.loads(hub.requests[0].body)["games"]
    assert sorted(g["appid"] for g in sent) == [220, 730, 1245620]
    assert all(set(g) == {"appid", "name"} for g in sent)
    assert KEY not in caplog.text


def test_refresh_library_not_linked(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:1", tmp_path, monkeypatch, with_key=False)

    async def go():
        await p._main()
        await p.refresh_library()
        s = await settled(p)
        await p._unload()
        return s

    assert asyncio.run(go())["error"] == "not_linked"


def test_list_games_and_sync_when_not_linked_give_error(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:1", tmp_path, monkeypatch, with_key=False)

    async def go():
        await p._main()
        out = []
        for call in (p.list_games, p.sync_all):
            await call()
            out.append((await settled(p))["error"])
        await p.sync_game("g1")
        out.append((await settled(p))["error"])
        await p._unload()
        return out

    assert asyncio.run(go()) == ["not_linked"] * 3


def test_list_games_with_hub(fake_decky, scripthub, tmp_path, monkeypatch):
    games = [{"id": "g1", "name": "Juego", "enabled": False, "steam_appid": 220, "status": None, "path": "/home/x/y"}]
    hub = scripthub(lambda r: (200, games, {}))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)

    async def go():
        await p._main()
        await p.list_games()
        s = await settled(p)
        await p._unload()
        return s

    s = asyncio.run(go())
    assert [(g["id"], g["state"]) for g in s["games"]] == [("g1", "disabled")]
    assert "/home/x/y" not in json.dumps(s)


def test_unload_without_jobs_is_fine(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://x", tmp_path, monkeypatch, with_key=False)

    async def go():
        await p._main()
        await p._unload()

    asyncio.run(go())


def test_report_error_logs_redacted_ui_failure(fake_decky, tmp_path, monkeypatch, caplog):
    p = make_plugin(fake_decky, "http://127.0.0.1:1", tmp_path, monkeypatch)

    async def go():
        await p._main()
        return await p.report_error(f"TypeError: x con {KEY} y steamid 76561198000000000")

    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(go()) == {"ok": True}
    assert "Checkpoint (interfaz): TypeError" in caplog.text
    assert KEY not in caplog.text and "76561198000000000" not in caplog.text
