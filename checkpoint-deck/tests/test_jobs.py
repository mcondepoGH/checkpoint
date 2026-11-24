"""Tareas de fondo del panel (`Jobs`): estado en memoria que la interfaz consulta; con un motor falso."""

import asyncio
import threading

import checkpoint_client as hc
from checkpoint_hub import HubNetworkError
from checkpoint_jobs import Jobs

GAMES = [
    {"id": "g1", "name": "Uno", "enabled": True, "steam_appid": 10, "status": None, "path": "/x/1"},
    {"id": "g2", "name": "Dos", "enabled": True, "steam_appid": None, "status": None, "path": "/x/2"},
]


class FakeEngine:
    def __init__(self):
        self.cancelled = False
        self.states = {"g1": {"state": "upload"}, "g2": {"state": "conflict"}}
        self.gate = None  # Event: bloquea sync_game hasta que se abra
        self.entered = threading.Event()
        self.fail = None

    def list_games(self):
        if self.fail:
            raise self.fail
        return GAMES

    def check_game(self, game, games=None):
        return {"game": game, **self.states[game]}

    def sync_game(self, game, games=None, progress=None):
        self.entered.set()
        if progress:
            progress("upload", 3, 12)
        if self.gate:
            self.gate.wait(5)
        if self.cancelled:
            return {"game": game, "state": "error", "code": "cancelled"}
        return {"game": game, "state": "uploaded", "files": 12}

    def sync_all(self, progress=None):
        return [self.sync_game(g["id"], None, progress) for g in GAMES]

    def cancel(self):
        self.cancelled = True
        if self.gate:
            self.gate.set()


def make(engine=None, refresh=None):
    eng = engine or FakeEngine()
    return Jobs(lambda: eng, refresh or (lambda: ("ok", {"found": 2})), log=lambda m: None), eng


async def settle(j):
    for _ in range(400):
        if not j.snapshot()["running"]:
            return j.snapshot()
        await asyncio.sleep(0.01)
    raise AssertionError("la tarea no termina")


def test_initial_state_is_idle():
    j, _ = make()
    s = j.snapshot()
    assert s["running"] is False and s["games"] == [] and s["error"] is None and s["summary"] is None


def test_check_lists_games_with_states():
    async def go():
        j, _ = make()
        assert j.start("check")["running"] is True
        return await settle(j)

    s = asyncio.run(go())
    assert [(g["id"], g["name"], g["appid"], g["state"]) for g in s["games"]] == [
        ("g1", "Uno", 10, "upload"),
        ("g2", "Dos", None, "conflict"),
    ]
    assert s["error"] is None and s["kind"] == "check"
    assert "path" not in s["games"][0]  # la ruta no sale al panel


def test_sync_game_updates_entry_and_reports_progress():
    async def go():
        j, eng = make()
        j.start("check")
        await settle(j)
        eng.gate = threading.Event()
        j.start("sync_game", "g1")
        for _ in range(200):
            await asyncio.sleep(0.01)
            s = j.snapshot()
            if s["phase"]:
                break
        mid = j.snapshot()
        eng.gate.set()
        return mid, await settle(j)

    mid, end = asyncio.run(go())
    assert mid["running"] and mid["game"] == "g1" and (mid["phase"], mid["done"], mid["total"]) == ("upload", 3, 12)
    g1 = end["games"][0]
    assert g1["state"] == "up_to_date" and g1["last"] == {"state": "uploaded", "files": 12}
    assert end["games"][1]["state"] == "conflict"  # el otro no se toca


def test_sync_failure_keeps_error_code():
    async def go():
        j, eng = make()
        j.start("check")
        await settle(j)
        eng.sync_game = lambda g, games=None, progress=None: {"game": g, "state": "error", "code": "hub_changed"}
        j.start("sync_game", "g1")
        return await settle(j)

    g1 = asyncio.run(go())["games"][0]
    assert g1["state"] == "error" and g1["code"] == "hub_changed"


def test_sync_all_updates_all():
    async def go():
        j, _ = make()
        j.start("check")
        await settle(j)
        j.start("sync_all")
        return await settle(j)

    s = asyncio.run(go())
    assert [g["last"]["state"] for g in s["games"]] == ["uploaded", "uploaded"]


def test_busy_when_running():
    async def go():
        j, eng = make()
        eng.gate = threading.Event()
        first = j.start("sync_game", "g1")
        second = j.start("check")
        eng.gate.set()
        await settle(j)
        return first, second

    first, second = asyncio.run(go())
    assert first["running"] and second["busy"] is True


def test_not_linked_gives_error():
    async def go():
        j = Jobs(lambda: None, lambda: ("not_linked", {}), log=lambda m: None)
        s = j.start("check")
        return s, await settle(j)

    s, end = asyncio.run(go())
    assert end["error"] == "not_linked" and end["running"] is False


def test_hub_errors_map_to_codes():
    async def go(exc):
        j, eng = make()
        eng.fail = exc
        j.start("check")
        return (await settle(j))["error"]

    assert asyncio.run(go(HubNetworkError("x"))) == "connection"
    assert asyncio.run(go(hc.HubApiError(401, "err.auth"))) == "unauthorized"
    assert asyncio.run(go(hc.HubApiError(429, "x", wait_s=9))) == "rate_limited"
    assert asyncio.run(go(hc.HubApiError(500, "x"))) == "hub_error"


def test_unexpected_exception_is_contained_and_logged_by_type():
    logs = []

    async def go():
        eng = FakeEngine()
        eng.fail = RuntimeError("clave ckd_secreta en el mensaje")
        j = Jobs(lambda: eng, lambda: ("ok", {}), log=logs.append)
        j.start("check")
        return await settle(j)

    s = asyncio.run(go())
    assert s["error"] == "unexpected" and s["running"] is False
    assert logs and all("ckd_secreta" not in m for m in logs)
    # el fallo ya no es mudo: el log y el estado llevan el tipo y el mensaje saneado
    assert any("RuntimeError" in m for m in logs)
    assert s["error_detail"] == "RuntimeError: clave *** en el mensaje"


def test_hub_error_detail_has_status_and_endpoint():
    async def go():
        eng = FakeEngine()
        e = hc.HubApiError(502, "err.x")
        e.endpoint = "GET /api/games"
        eng.fail = e
        j = Jobs(lambda: eng, lambda: ("ok", {}))
        j.start("check")
        return await settle(j)

    s = asyncio.run(go())
    assert s["error"] == "hub_error" and s["error_detail"] == "HubApiError: estado 502, código err.x [GET /api/games]"


def test_refresh_stores_summary_and_errors():
    async def go(res):
        j, _ = make(refresh=lambda: res)
        j.start("refresh")
        return await settle(j)

    ok = asyncio.run(go(("ok", {"found": 5, "associated": 1, "suggested": 2, "unchanged": 1, "ignored": 1})))
    assert ok["summary"]["found"] == 5 and ok["error"] is None
    assert asyncio.run(go(("unauthorized", {})))["error"] == "unauthorized"
    rl = asyncio.run(go(("rate_limited", {"wait_s": 30})))
    assert rl["error"] == "rate_limited" and rl["error_params"] == {"wait_s": 30}
    assert asyncio.run(go(("no_steam", {})))["error"] == "no_steam"


def test_close_cancels_running_job():
    async def go():
        j, eng = make()
        eng.gate = threading.Event()
        j.start("sync_game", "g1")
        await asyncio.sleep(0.05)
        await asyncio.wait_for(j.close(), 5)
        return j.snapshot(), eng

    s, eng = asyncio.run(go())
    assert eng.cancelled and s["running"] is False


# ---- juegos sin configurar y activar o desactivar
def make_lib(library, games=None, refresh=None):
    eng = FakeEngine()
    if games is not None:
        eng.list_games = lambda: games
    j = Jobs(lambda: eng, refresh or (lambda: ("ok", {"found": 4})), log=lambda m: None, library=lambda: library)
    return j, eng


LIB = [(10, "Uno"), (30, "Treinta"), (40, "Cuarenta"), (50, "Proton 9.0"), (60, "Seis")]


def test_refresh_lists_hub_games_and_the_installed_ones_without_a_hub_game():
    async def go():
        j, _ = make_lib(LIB)
        j.start("refresh")
        return await settle(j)

    s = asyncio.run(go())
    assert [g["id"] for g in s["games"]] == ["g1", "g2"]
    assert s["unconfigured"] == [
        {"appid": 30, "name": "Treinta"},
        {"appid": 40, "name": "Cuarenta"},
        {"appid": 60, "name": "Seis"},
    ]  # 10 ya está en el hub; «Proton 9.0» es una herramienta
    assert s["summary"] == {"found": 4}


def test_unconfigured_is_empty_until_the_library_has_been_searched():
    async def go():
        j, _ = make_lib(LIB)
        j.start("check")
        return await settle(j)

    assert asyncio.run(go())["unconfigured"] == []


def test_refresh_failure_leaves_no_unconfigured_and_keeps_the_error():
    async def go():
        j, _ = make_lib(LIB, refresh=lambda: ("connection", {"detail": "x"}))
        j.start("refresh")
        return await settle(j)

    s = asyncio.run(go())
    assert s["error"] == "connection" and s["unconfigured"] == []


def test_rows_carry_enabled_and_a_disabled_game_shows_disabled_until_checked():
    games = [
        {"id": "g1", "name": "Uno", "enabled": True, "steam_appid": 10, "path": "/x/1"},
        {"id": "g2", "name": "Dos", "enabled": False, "steam_appid": 20, "path": "/x/2"},
    ]

    async def go():
        j, _ = make_lib([], games=games)
        j.start("refresh")
        return await settle(j)

    s = asyncio.run(go())
    assert [(g["id"], g["enabled"], g["state"]) for g in s["games"]] == [("g1", True, "unknown"), ("g2", False, "disabled")]


def test_set_enabled_row_updates_state_both_ways():
    async def go():
        j, _ = make_lib(LIB)
        j.start("refresh")
        await settle(j)
        j.set_enabled_row("g1", False)
        off = j.snapshot()["games"][0]
        j.set_enabled_row("g1", True)
        on = j.snapshot()["games"][0]
        j.set_enabled_row("nope", False)  # desconocido: no hace nada
        return off, on

    off, on = asyncio.run(go())
    assert (off["enabled"], off["state"]) == (False, "disabled")
    assert (on["enabled"], on["state"]) == (True, "unknown")


def test_add_game_moves_it_from_unconfigured_to_games():
    async def go():
        j, _ = make_lib(LIB)
        j.start("refresh")
        await settle(j)
        j.add_game({"id": "treinta", "name": "Treinta", "appid": 30, "path": "/p"})
        return j.snapshot()

    s = asyncio.run(go())
    assert [g["id"] for g in s["games"]] == ["g1", "g2", "treinta"]
    assert s["games"][2]["appid"] == 30 and s["games"][2]["enabled"] is True and s["games"][2]["state"] == "unknown"
    assert [u["appid"] for u in s["unconfigured"]] == [40, 60]
    assert "path" not in s["games"][2]  # nunca la ruta en el estado de la interfaz


def test_resolve_job_runs_the_engine_and_updates_the_row():
    class Eng(FakeEngine):
        def resolve_conflict(self, game, winner, games=None, progress=None):
            self.resolved = (game, winner)
            return {"game": game, "state": "downloaded", "files": 2}

    async def go():
        j, eng = make(Eng())
        j.start("check")
        await settle(j)
        assert j.start("resolve", "g2", "hub")["kind"] == "resolve"
        return eng, await settle(j)

    eng, end = asyncio.run(go())
    assert eng.resolved == ("g2", "hub")
    g2 = end["games"][1]
    assert g2["state"] == "up_to_date" and g2["last"] == {"state": "downloaded", "files": 2}


def test_resolve_job_that_stays_in_conflict_keeps_the_code():
    class Eng(FakeEngine):
        def resolve_conflict(self, game, winner, games=None, progress=None):
            return {"game": game, "state": "conflict", "code": "resolution_stale"}

    async def go():
        j, _ = make(Eng())
        j.start("check")
        await settle(j)
        j.start("resolve", "g2", "device")
        return await settle(j)

    g2 = asyncio.run(go())["games"][1]
    assert g2["state"] == "conflict" and g2["code"] == "resolution_stale"


def test_resolve_job_failure_keeps_the_row_in_conflict_with_the_reason():
    class Eng(FakeEngine):
        def resolve_conflict(self, game, winner, games=None, progress=None):
            return {"game": game, "state": "error", "code": "game_running"}

    async def go():
        j, _ = make(Eng())
        j.start("check")
        await settle(j)
        j.start("resolve", "g2", "hub")
        return await settle(j)

    g2 = asyncio.run(go())["games"][1]
    assert g2["state"] == "conflict" and g2["code"] == "game_running"  # el conflicto sigue ahí: se puede reintentar


def test_unconfigured_marks_shortcuts_with_their_origin():
    async def go():
        eng = FakeEngine()
        lib = [(30, "Treinta"), (3_000_000_001, "Atajo")]
        j = Jobs(lambda: eng, lambda: ("ok", {"found": 2}), log=lambda m: None, library=lambda: lib, shortcuts=lambda: {3_000_000_001})
        j.start("refresh")
        return await settle(j)

    s = asyncio.run(go())
    assert s["unconfigured"] == [{"appid": 30, "name": "Treinta"}, {"appid": 3_000_000_001, "name": "Atajo", "source": "shortcut"}]


def test_sync_all_leaves_plan_and_results_per_game_and_calls_on_synced():
    async def go():
        eng = FakeEngine()
        eng.states = {}
        seen = []
        j = Jobs(lambda: eng, lambda: ("ok", {}), log=lambda m: None, on_synced=lambda g, r: seen.append((g, r["state"])), last_at=lambda g: {"at": 77} if g == "g1" else None)
        j.start("sync_all")
        s = await settle(j)
        return s, seen, j

    s, seen, j = asyncio.run(go())
    assert s["plan"] == ["g1", "g2"]
    assert s["results"] == {"g1": {"state": "uploaded", "files": 12}, "g2": {"state": "uploaded", "files": 12}}
    assert seen == [("g1", "uploaded"), ("g2", "uploaded")]
    rows = {g["id"]: g for g in s["games"]}
    assert rows["g1"]["last_at"] == 77 and "last_at" not in rows["g2"]
    assert "path" not in rows["g1"]  # la ruta no va en el estado: se pide aparte
    assert j.paths() == {"g1": "/x/1", "g2": "/x/2"}


def test_sync_all_keeps_going_after_a_conflict_or_error_and_check_leaves_no_results():
    async def go():
        eng = FakeEngine()
        out = {"g1": {"state": "conflict"}, "g2": {"state": "error", "code": "game_running"}}
        eng.sync_game = lambda game, games=None, progress=None: {"game": game, **out[game]}
        j = Jobs(lambda: eng, lambda: ("ok", {}), log=lambda m: None)
        j.start("sync_all")
        s = await settle(j)
        j.start("check")
        return s, await settle(j)

    s, s2 = asyncio.run(go())
    assert s["results"] == {"g1": {"state": "conflict"}, "g2": {"state": "error", "code": "game_running"}}
    assert s2["results"] == {} and s2["plan"] == []  # una tarea nueva limpia lo anterior


def test_a_failing_on_synced_callback_never_breaks_the_task():
    async def go():
        eng = FakeEngine()

        def boom(_g, _r):
            raise OSError("disco lleno")

        j = Jobs(lambda: eng, lambda: ("ok", {}), log=lambda m: None, on_synced=boom)
        j.start("sync_game", "g1")
        return await settle(j)

    s = asyncio.run(go())
    assert s["error"] is None and {g["id"]: g["state"] for g in s["games"]}["g1"] == "up_to_date"


def test_set_path_row_updates_the_path_and_resets_the_state_without_syncing():
    async def go():
        j, _ = make_lib(LIB)
        j.start("refresh")
        await settle(j)
        j._games[0]["state"] = "conflict"
        j._games[0]["code"] = "x"
        j.set_path_row("g1", "/nueva/ruta")
        s = j.snapshot()["games"][0]
        j.set_path_row("nope", "/otra")  # desconocido: no hace nada
        return j, s

    j, g1 = asyncio.run(go())
    assert j.paths()["g1"] == "/nueva/ruta" and "nope" not in j.paths()
    assert g1["state"] == "unknown" and "code" not in g1 and "params" not in g1
    assert not j.snapshot()["running"]


def test_set_path_row_keeps_a_disabled_game_disabled():
    async def go():
        j, _ = make_lib(LIB)
        j.start("refresh")
        await settle(j)
        j.set_enabled_row("g1", False)
        j.set_path_row("g1", "/n")
        return j.snapshot()["games"][0]

    g = asyncio.run(go())
    assert (g["enabled"], g["state"]) == (False, "disabled")
