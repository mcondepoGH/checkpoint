"""Métodos de `Plugin` en main.py (con `decky` falso): biblioteca de Steam y tareas de fondo."""

import asyncio
import importlib
import json
import logging
import shutil
from pathlib import Path

from checkpoint_hub import save_settings

FIX = Path(__file__).parent / "fixtures" / "steam"
KEY = "ckd_" + "k" * 40


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


def _diag_lines(caplog):
    return [r.getMessage() for r in caplog.records if "evento crudo" in r.getMessage()]


def test_diag_game_event_logs_exact_line_without_pairing(fake_decky, tmp_path, monkeypatch, caplog):
    p = make_plugin(fake_decky, "http://127.0.0.1:1", tmp_path, monkeypatch, with_key=False)

    async def go():
        await p._main()
        return [await p.diag_game_event("0", "number", "true"), await p.diag_game_event("abc", "string", "undefined")]

    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(go()) == [{"ok": True}, {"ok": True}]
    assert _diag_lines(caplog) == [
        "auto: evento crudo unAppID=0 tipo=number bRunning=true",
        "auto: evento crudo unAppID=abc tipo=string bRunning=undefined",
    ]


def test_diag_game_event_sanitizes_and_truncates(fake_decky, tmp_path, monkeypatch, caplog):
    p = make_plugin(fake_decky, "http://127.0.0.1:1", tmp_path, monkeypatch)

    async def go():
        await p._main()
        await p.diag_game_event("1\n2\x1b[0m" + "x" * 500, "t", f"con {KEY}")

    with caplog.at_level(logging.DEBUG):
        asyncio.run(go())
    (line,) = _diag_lines(caplog)
    assert "\n" not in line and "\x1b" not in line and KEY not in line
    assert line.startswith("auto: evento crudo unAppID=1?2?[0m" + "x" * 57 + " tipo=t")  # 64 caracteres exactos
    assert len(line) < 64 * 3 + 60


def test_diag_game_event_dedupes_and_limits_rate(fake_decky, tmp_path, monkeypatch, caplog):
    import main

    p = make_plugin(fake_decky, "http://127.0.0.1:1", tmp_path, monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])

    async def go():
        await p._main()
        for _ in range(5):  # repetidos seguidos: una sola línea
            await p.diag_game_event("7", "number", "true")
        for i in range(100):  # distintos: tope por ventana
            await p.diag_game_event(str(100 + i), "number", "true")
        clock[0] += main.DIAG_WINDOW  # ventana nueva: vuelve a registrar
        await p.diag_game_event("999", "number", "false")

    with caplog.at_level(logging.DEBUG):
        asyncio.run(go())
    lines = _diag_lines(caplog)
    assert lines.count("auto: evento crudo unAppID=7 tipo=number bRunning=true") == 1
    assert len(lines) == main.DIAG_MAX_PER_WINDOW + 1
    assert lines[-1] == "auto: evento crudo unAppID=999 tipo=number bRunning=false"


def test_diag_game_event_never_raises(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:1", tmp_path, monkeypatch)

    class Bad:
        def __str__(self):
            raise RuntimeError("boom")

    # sin _main (sin pairing) y con un valor que no se deja convertir a texto
    assert asyncio.run(p.diag_game_event("1", "number", "true")) == {"ok": True}
    assert asyncio.run(p.diag_game_event(Bad(), None, None)) == {"ok": True}
