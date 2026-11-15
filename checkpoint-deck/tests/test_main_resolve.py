"""`Plugin.resolve_conflict` (main.py, con `decky` falso): valida, respeta plugin antiguo y no vinculado y lanza la tarea."""

import asyncio

from test_main_library import make_plugin, settled


def run(p, game, winner):
    async def go():
        await p._main()
        first = await p.resolve_conflict(game, winner)
        s = await settled(p) if first.get("running") else first
        await p._unload()
        return first, s

    return asyncio.run(go())


def test_bad_winner_is_refused_without_touching_the_hub(fake_decky, scripthub, tmp_path, monkeypatch):
    hub = scripthub(lambda r: (200, [], {}))
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)
    for w in ("newest", "device:x", "", None, 3):
        first, _ = run(p, "g1", w)
        assert first["error"] == "bad_winner" and not first.get("running")
    assert hub.requests == []


def test_not_linked_and_outdated(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:1", tmp_path, monkeypatch, with_key=False)
    first, s = run(p, "g1", "hub")
    assert s["error"] == "not_linked"
    p._compat = "plugin_outdated"
    first, _ = run(p, "g1", "hub")
    assert first["error"] == "plugin_outdated"


def test_resolve_runs_a_background_job_that_fails_cleanly_when_the_game_is_unknown(fake_decky, scripthub, tmp_path, monkeypatch):
    hub = scripthub(lambda r: (200, [], {}))  # /api/games vacío
    p = make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)
    first, s = run(p, "nope", "hub")
    assert first["running"] and first["kind"] == "resolve" and first["game"] == "nope"
    assert s["error"] is None  # el resultado por juego se aplica solo si la fila existe
