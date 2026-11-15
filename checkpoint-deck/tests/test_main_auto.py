"""Avisos de abrir y cerrar en `Plugin` (main.py, con `decky` falso y un hub falso por HTTP)."""

import asyncio
import json
import logging
import stat
from pathlib import Path

from test_main_library import KEY, make_plugin

SAVE = "/home/deck/saves/uno"


def hub_handler(state):
    def handler(r):
        path = r.path.split("?")[0]
        if path == "/api/games":
            return (
                200,
                [
                    {
                        "id": "g1",
                        "name": "Uno",
                        "enabled": True,
                        "steam_appid": 10,
                        "status": None,
                        "path": state["path"],
                    }
                ],
                {},
            )
        if path.endswith("/fingerprint"):
            return 200, {"action": state.get("action", "none")}, {}
        if path.endswith("/closed"):
            return 200, {"game": "g1", "device": "d", "recorded": True, "outcome": "ok"}, {}
        return 404, {"detail": {"code": "nope", "params": {}}}, {}

    return handler


async def drain(p, want, n=300):
    got = []
    for _ in range(n):
        got += await p.take_notices()
        if len(got) >= want:
            return got
        await asyncio.sleep(0.02)
    return got


def test_unlinked_plugin_ignores_events(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:9", tmp_path, monkeypatch, with_key=False)

    async def go():
        await p._main()
        r = await p.game_event(10, True)
        await asyncio.sleep(0.1)
        n = await p.take_notices()
        await p._unload()
        return r, n

    r, n = asyncio.run(go())
    assert r == {"ok": True} and n == []


def test_open_and_close_flow_tells_the_hub(fake_decky, scripthub, tmp_path, monkeypatch, caplog):
    save = tmp_path / "deckhome" / "saves" / "uno"
    state = {"path": str(save)}
    hub = scripthub(hub_handler(state))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)
    save.mkdir(parents=True)
    (save / "a.sav").write_bytes(b"1")

    async def go():
        await p._main()
        await p.game_event(10, True)
        await p.game_event(10, False)
        for _ in range(300):
            if any(r.path.endswith("/closed") for r in hub.requests):
                break
            await asyncio.sleep(0.02)
        await p._unload()

    with caplog.at_level(logging.DEBUG):
        asyncio.run(go())
    paths = [(r.method, r.path.split("?")[0]) for r in hub.requests]
    assert ("POST", "/api/hook/g1/fingerprint") in paths
    assert paths[-1] == ("POST", "/api/hook/g1/closed")
    assert KEY not in caplog.text
    f = Path(fake_decky.DECKY_PLUGIN_SETTINGS_DIR) / "auto.json"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert json.loads(f.read_text())["games"] == {"10": {"id": "g1", "name": "Uno"}}


def test_conflict_on_open_gives_a_notice(fake_decky, scripthub, tmp_path, monkeypatch):
    save = tmp_path / "deckhome" / "saves" / "uno"
    hub = scripthub(hub_handler({"path": str(save), "action": "conflict"}))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)
    save.mkdir(parents=True)
    (save / "a.sav").write_bytes(b"1")

    async def go():
        await p._main()
        await p.game_event(10, True)
        got = await drain(p, 1)
        await p._unload()
        return got

    got = asyncio.run(go())
    assert [(x["code"], x["game"], x["level"]) for x in got] == [("conflict", "Uno", "warning")]


def test_manual_sync_is_refused_while_the_game_runs(fake_decky, scripthub, tmp_path, monkeypatch):
    save = tmp_path / "deckhome" / "saves" / "uno"
    hub = scripthub(hub_handler({"path": str(save), "action": "none"}))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)
    save.mkdir(parents=True)
    (save / "a.sav").write_bytes(b"1")

    async def settle():
        for _ in range(300):
            s = await p.get_sync_state()
            if not s["running"]:
                return s
            await asyncio.sleep(0.02)

    async def go():
        await p._main()
        await p.game_event(10, True)  # solo anota «abierto»; el evento se procesa aparte
        await p.sync_game("g1")
        s1 = await settle()
        await p.game_event(10, False)
        await asyncio.sleep(0.3)
        await p.sync_game("g1")
        s2 = await settle()
        await p._unload()
        return s1, s2

    s1, s2 = asyncio.run(go())
    g1 = [g for g in s1["games"] if g["id"] == "g1"][0]
    assert g1["state"] == "error" and g1["code"] == "game_running"
    g2 = [g for g in s2["games"] if g["id"] == "g1"][0]
    assert g2["state"] == "up_to_date"


def test_unload_stops_the_event_worker(fake_decky, scripthub, tmp_path, monkeypatch):
    hub = scripthub(hub_handler({"path": "/x"}))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)

    async def go():
        await p._main()
        await p.game_event(10, True)
        await p._unload()
        return p.auto_runner._task.done()

    assert asyncio.run(go()) is True


def test_main_retries_the_queue_saved_before_a_reboot(fake_decky, scripthub, tmp_path, monkeypatch):
    save = tmp_path / "deckhome" / "saves" / "uno"
    hub = scripthub(hub_handler({"path": str(save), "action": "none"}))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)
    save.mkdir(parents=True)
    (save / "a.sav").write_bytes(b"1")
    from checkpoint_hub import save_settings

    save_settings(
        fake_decky.DECKY_PLUGIN_SETTINGS_DIR,
        {"games": {"10": {"id": "g1", "name": "Uno"}}, "pending": [{"id": "g1", "name": "Uno"}]},
        "auto.json",
    )
    import checkpoint_auto

    monkeypatch.setattr(checkpoint_auto, "RETRY_S", 0.05)

    async def go():
        await p._main()  # sin ningún evento de juego: el arranque basta para reintentar la cola
        for _ in range(300):
            if any(r.path.endswith("/closed") for r in hub.requests):
                break
            await asyncio.sleep(0.02)
        await p._unload()

    asyncio.run(go())
    assert any(r.path.endswith("/closed") for r in hub.requests)
    assert json.loads((Path(fake_decky.DECKY_PLUGIN_SETTINGS_DIR) / "auto.json").read_text())["pending"] == []


# ---- 0.2.3: avisos a través de main.py, aviso de prueba, actividad
def sync_returns(monkeypatch, result):
    import checkpoint_sync

    monkeypatch.setattr(checkpoint_sync.SyncEngine, "sync_game", lambda self, gid, games=None, *a, **k: result)


def test_uploaded_via_main_delivers_the_notice(fake_decky, scripthub, tmp_path, monkeypatch):
    save = tmp_path / "deckhome" / "saves" / "uno"
    hub = scripthub(hub_handler({"path": str(save)}))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)
    save.mkdir(parents=True)
    sync_returns(monkeypatch, {"state": "uploaded", "files": 3})

    async def go():
        await p._main()
        await p.game_event(10, True)
        got = await drain(p, 1)
        again = await p.take_notices()
        await p._unload()
        return got, again

    got, again = asyncio.run(go())
    assert [(x["code"], x["game"], x["level"], x["params"]) for x in got] == [("uploaded", "Uno", "info", {"files": 3})]
    assert again == []


def test_downloaded_via_main_delivers_the_notice(fake_decky, scripthub, tmp_path, monkeypatch):
    save = tmp_path / "deckhome" / "saves" / "uno"
    hub = scripthub(hub_handler({"path": str(save)}))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)
    save.mkdir(parents=True)
    sync_returns(monkeypatch, {"state": "downloaded", "files": 2})

    async def go():
        await p._main()
        await p.game_event(10, True)
        got = await drain(p, 1)
        await p._unload()
        return got

    got = asyncio.run(go())
    assert [(x["code"], x["params"]) for x in got] == [("downloaded", {"files": 2})]


def test_test_notice_no_longer_exists(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:9", tmp_path, monkeypatch)
    assert not hasattr(p, "test_notice")


def test_take_notices_logs_each_delivered_code_without_secrets(fake_decky, tmp_path, monkeypatch, caplog):
    p = make_plugin(fake_decky, "http://127.0.0.1:9", tmp_path, monkeypatch)

    async def go():
        await p._main()
        p.notices.add("uploaded", "Uno", "info")
        await p.take_notices()
        await p.take_notices()  # vacío: no se registra nada
        await p._unload()

    with caplog.at_level(logging.DEBUG):
        asyncio.run(go())
    assert caplog.text.count("auto: aviso entregado uploaded") == 1
    assert KEY not in caplog.text


def test_get_activity_no_longer_exists(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:9", tmp_path, monkeypatch)
    assert not hasattr(p, "get_activity")


def test_events_walk_open_close_and_ignore_leaving_log_lines(fake_decky, scripthub, tmp_path, monkeypatch, caplog):
    save = tmp_path / "deckhome" / "saves" / "uno"
    hub = scripthub(hub_handler({"path": str(save)}))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)
    save.mkdir(parents=True)
    (save / "a.sav").write_bytes(b"1")

    async def wait_for(text):
        for _ in range(300):
            if text in caplog.text:
                return
            await asyncio.sleep(0.02)

    async def go():
        await p._main()
        await p.game_event(10, True)
        await wait_for("auto: abierto appid 10")
        await p.game_event(999, True)
        await wait_for("auto: abrir appid 999: sin juego en el hub")
        await p.game_event(10, False)
        await wait_for("auto: cierre de g1")
        await p._unload()

    with caplog.at_level(logging.DEBUG):
        asyncio.run(go())
    for line in ("auto: abierto appid 10 (g1)", "auto: abrir appid 999: sin juego en el hub", "auto: cierre de g1"):
        assert line in caplog.text, line
    assert KEY not in caplog.text and str(save) not in caplog.text


def test_outdated_plugin_event_is_logged_and_not_queued(fake_decky, tmp_path, monkeypatch, caplog):
    p = make_plugin(fake_decky, "http://127.0.0.1:9", tmp_path, monkeypatch)

    async def go():
        await p._main()
        p._compat = "plugin_outdated"
        await p.game_event(10, True)
        await p._unload()

    with caplog.at_level(logging.DEBUG):
        asyncio.run(go())
    assert "auto: evento appid 10 descartado: plugin_outdated" in caplog.text


def test_unlinked_event_logs_no_vinculado(fake_decky, tmp_path, monkeypatch, caplog):
    p = make_plugin(fake_decky, "http://127.0.0.1:9", tmp_path, monkeypatch, with_key=False)

    async def go():
        await p._main()
        await p.game_event(10, True)
        for _ in range(100):
            if "dispositivo sin vincular" in caplog.text:
                break
            await asyncio.sleep(0.02)
        await p._unload()

    with caplog.at_level(logging.DEBUG):
        asyncio.run(go())
    assert "auto: abrir appid 10: dispositivo sin vincular; no se hace nada" in caplog.text


def _run_event(fake_decky, scripthub, tmp_path, monkeypatch, result, running, appid=10, handler=None):
    save = tmp_path / "deckhome" / "saves" / "uno"
    hub = scripthub((handler or hub_handler)({"path": str(save)}))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)
    save.mkdir(parents=True)
    sync_returns(monkeypatch, result)

    async def go():
        await p._main()
        await p.game_event(appid, running)
        got = await drain(p, 1, n=60)
        await asyncio.sleep(0.2)
        got += await p.take_notices()
        await p._unload()
        return got

    return asyncio.run(go())


def test_every_state_gives_one_notice_on_open_and_close_via_main(fake_decky, scripthub, tmp_path, monkeypatch):
    cases = [
        ("uploaded", {"state": "uploaded", "files": 2}),
        ("downloaded", {"state": "downloaded", "files": 2}),
        ("up_to_date", {"state": "up_to_date"}),
        ("no_path", {"state": "no_path"}),
        ("missing_dir", {"state": "missing_dir"}),
    ]
    for running in (True, False):
        for code, res in cases:
            sub = tmp_path / f"{code}-{running}"
            sub.mkdir()
            got = _run_event(fake_decky, scripthub, sub, monkeypatch, res, running)
            assert [(x["code"], x["game"]) for x in got] == [(code, "Uno")], (code, running)
            assert got[0]["level"] == "info"


def test_disabled_state_and_unmapped_app_give_no_notice_via_main(fake_decky, scripthub, tmp_path, monkeypatch):
    for i, (res, appid) in enumerate([({"state": "disabled"}, 10), ({"state": "up_to_date"}, 777)]):
        for running in (True, False):
            sub = tmp_path / f"{i}-{running}"
            sub.mkdir()
            assert _run_event(fake_decky, scripthub, sub, monkeypatch, res, running, appid=appid) == []
