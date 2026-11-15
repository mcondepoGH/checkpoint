"""Avisos automáticos de abrir y cerrar (`AutoSync`, `AutoRunner`, `Notices`): con un motor falso, sin red ni Decky."""

import asyncio
import json
import os
import stat
import threading

import checkpoint_client as hc
from checkpoint_auto import AutoRunner, AutoSync, Notices
from checkpoint_hub import HubNetworkError

GAMES = [
    {"id": "g1", "name": "Uno", "enabled": True, "steam_appid": 10, "status": None, "path": "/x/1"},
    {"id": "g2", "name": "Dos", "enabled": False, "steam_appid": 20, "status": None, "path": "/x/2"},
    {"id": "g3", "name": "Tres", "enabled": True, "steam_appid": None, "status": None, "path": "/x/3"},
]


class FakeEngine:
    def __init__(self):
        self.offline = False  # list_games y sync fallan por red
        self.result = {"state": "uploaded", "files": 2}
        self.closed_error = None
        self.synced, self.closed_sent = [], []
        self.opened_error = None
        self.opened_sent, self.closed_results = [], []  # (juego, resultado) de los avisos de apertura / resultados de cierre

    def list_games(self):
        if self.offline:
            raise HubNetworkError("URLError")
        return [dict(g) for g in GAMES]

    def sync_game(self, game, games=None, progress=None):
        self.synced.append(game)
        if self.offline:
            return {"game": game, "state": "error", "code": "connection"}
        return {"game": game, **self.result}

    def notify_closed(self, game, result=None):
        if self.closed_error:
            raise self.closed_error
        self.closed_sent.append(game)
        self.closed_results.append(result)

    def notify_opened(self, game, result=None):
        self.opened_sent.append((game, result))
        if self.opened_error:
            raise self.opened_error
        return {"playing": True}


def make(tmp_path, eng=None, state_dir=None):
    eng = eng or FakeEngine()
    notices = Notices()
    a = AutoSync(lambda: eng, str(state_dir or tmp_path / "st"), notices, log=lambda m: None)
    return a, eng, notices


def codes(n):
    return [(x["code"], x["game"], x["level"]) for x in n.take()]


# ---- abrir
def test_unmapped_app_is_silent(tmp_path):
    a, eng, n = make(tmp_path)
    a.opened(999)  # una app de Steam que no es un juego de Checkpoint
    a.opened(30)
    assert eng.synced == [] and n.take() == []


def test_disabled_or_unassociated_game_is_silent(tmp_path):
    a, eng, n = make(tmp_path)
    a.opened(20)
    assert eng.synced == [] and n.take() == []


def test_opened_syncs_and_reports_download(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "downloaded", "files": 3}
    a.opened(10)
    assert eng.synced == ["g1"] and eng.closed_sent == []  # abrir no avisa de «closed»
    assert codes(n) == [("downloaded", "Uno", "info")]


def test_opened_up_to_date_gives_info_notice(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "up_to_date"}
    a.opened(10)
    assert eng.synced == ["g1"] and codes(n) == [("up_to_date", "Uno", "info")]


def test_opened_conflict_warns_and_touches_nothing_else(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "conflict"}
    a.opened(10)
    assert codes(n) == [("conflict", "Uno", "warning")]
    assert eng.closed_sent == []


def test_opened_error_is_reported_with_code(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "error", "code": "path_forbidden"}
    a.opened(10)
    out = n.take()
    assert (
        out[0]["code"] == "sync_failed"
        and out[0]["params"] == {"reason": "path_forbidden"}
        and out[0]["level"] == "error"
    )


def test_opened_without_network_warns_for_a_known_game_and_does_not_sync(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "up_to_date"}
    a.opened(10)  # con red: aprende que el 10 es «Uno»
    n.take()  # el aviso «al día» de esta primera apertura no interesa aquí
    eng.synced.clear()
    eng.offline = True
    a.opened(10)
    assert eng.synced == []
    assert [c[0] for c in codes(n)] == ["offline_open"]
    assert a.pending() == []  # abrir sin red no deja nada en cola


def test_opened_without_network_is_silent_for_an_unknown_app(tmp_path):
    a, eng, n = make(tmp_path)
    eng.offline = True
    a.opened(999)  # no se sabe si es un juego del hub: no se molesta
    assert eng.synced == [] and n.take() == []


def test_opened_missing_dir_gives_info_notice(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "missing_dir"}
    a.opened(10)
    assert codes(n) == [("missing_dir", "Uno", "info")]


def test_opened_no_path_gives_info_notice(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "no_path"}
    a.opened(10)
    assert codes(n) == [("no_path", "Uno", "info")]


def test_opened_disabled_state_is_silent(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "disabled"}
    a.opened(10)
    assert n.take() == []


def test_opened_uploaded_gives_notice_with_files(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "uploaded", "files": 4}
    a.opened(10)
    out = n.take()
    assert [(x["code"], x["level"], x["params"]) for x in out] == [("uploaded", "info", {"files": 4})]


def test_closed_every_state_gives_exactly_one_notice(tmp_path):
    for state, files in [("uploaded", 2), ("downloaded", 1), ("up_to_date", None), ("no_path", None), ("missing_dir", None)]:
        a, eng, n = make(tmp_path / state)
        eng.result = {"state": state, **({"files": files} if files else {})}
        a.closed(10)
        assert [c[0] for c in codes(n)] == [state], state
        assert eng.closed_sent == ["g1"]


def test_closed_disabled_state_is_silent(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "disabled"}
    a.closed(10)
    assert n.take() == []


def test_open_then_close_gives_one_notice_each(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "up_to_date"}
    a.opened(10)
    a.closed(10)
    assert [c[0] for c in codes(n)] == ["up_to_date", "up_to_date"]


def test_not_linked_is_silent(tmp_path):
    notices = Notices()
    a = AutoSync(lambda: None, str(tmp_path / "st"), notices, log=lambda m: None)
    a.opened(10)
    a.closed(10)
    assert notices.take() == [] and a.pending() == []


# ---- cerrar
def test_closed_uploads_then_tells_the_hub(tmp_path):
    a, eng, n = make(tmp_path)
    a.opened(10)
    n.take()
    a.closed(10)
    assert eng.synced == ["g1", "g1"] and eng.closed_sent == ["g1"]
    assert codes(n) == [("uploaded", "Uno", "info")]
    assert a.pending() == []


def test_closed_conflict_warns_still_tells_hub_and_does_not_queue(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "conflict"}
    a.closed(10)
    assert codes(n) == [("conflict", "Uno", "warning")]
    assert eng.closed_sent == ["g1"] and a.pending() == []


def test_closed_up_to_date_tells_hub_and_gives_notice(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "up_to_date"}
    a.closed(10)
    assert eng.closed_sent == ["g1"] and codes(n) == [("up_to_date", "Uno", "info")]


def test_closed_without_network_queues_and_persists(tmp_path):
    a, eng, n = make(tmp_path)
    a.opened(10)  # con red: aprende el mapeo appid -> juego
    n.take()
    eng.offline = True
    a.closed(10)
    assert codes(n) == [("queued", "Uno", "warning")]
    assert a.pending() == ["g1"] and eng.closed_sent == []
    b, _, _ = make(tmp_path, eng)  # otro arranque del plugin: la cola sigue ahí
    assert b.pending() == ["g1"]
    f = tmp_path / "st" / "auto.json"
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    assert "path" not in f.read_text() and "/x/" not in f.read_text()  # nunca rutas ni claves en disco


def test_closed_offline_uses_cached_mapping_only_if_known(tmp_path):
    a, eng, n = make(tmp_path)
    eng.offline = True
    a.closed(10)  # sin haber visto nunca el juego: no se sabe cuál es
    assert a.pending() == [] and n.take() == []


def test_retry_pending_uploads_tells_hub_and_clears(tmp_path):
    a, eng, n = make(tmp_path)
    a.opened(10)
    eng.offline = True
    a.closed(10)
    n.take()
    eng.offline = False
    a.retry_pending()
    assert eng.closed_sent == ["g1"] and a.pending() == []
    assert codes(n) == [("uploaded", "Uno", "info")]
    assert json.loads((tmp_path / "st" / "auto.json").read_text())["pending"] == []


def test_retry_keeps_entry_while_still_offline_without_new_notice(tmp_path):
    a, eng, n = make(tmp_path)
    a.opened(10)
    eng.offline = True
    a.closed(10)
    n.take()
    a.retry_pending()
    assert a.pending() == ["g1"] and n.take() == []


def test_retry_skips_game_that_is_running_again(tmp_path):
    a, eng, n = make(tmp_path)
    a.opened(10)
    eng.offline = True
    a.closed(10)
    eng.offline = False
    a.mark(10, True)
    eng.synced.clear()
    a.retry_pending()
    assert eng.synced == [] and a.pending() == ["g1"]


def test_closed_notify_failure_by_network_queues(tmp_path):
    a, eng, n = make(tmp_path)
    eng.closed_error = HubNetworkError("URLError")
    a.closed(10)
    assert a.pending() == ["g1"]
    eng.closed_error = None
    a.retry_pending()
    assert eng.closed_sent == ["g1"] and a.pending() == []


def test_closed_notify_hub_busy_409_queues_but_404_is_dropped(tmp_path):
    a, eng, n = make(tmp_path)
    eng.closed_error = hc.HubApiError(409, "err.main.run_in_progress")
    a.closed(10)
    assert a.pending() == ["g1"]
    eng.closed_error = hc.HubApiError(404, "err.main.unknown_game")
    a.retry_pending()
    assert a.pending() == []  # un 404 no mejora reintentando


def test_closed_unauthorized_reports_and_does_not_queue(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "error", "code": "unauthorized"}
    a.closed(10)
    assert codes(n) == [("unauthorized", "Uno", "error")]
    assert a.pending() == []


def test_closed_retryable_hub_error_queues(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "error", "code": "hub_busy"}
    a.closed(10)
    assert a.pending() == ["g1"] and codes(n) == [("queued", "Uno", "warning")]


def test_two_closes_of_same_game_queue_once(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "error", "code": "hub_busy"}
    a.closed(10)
    a.closed(10)
    assert a.pending() == ["g1"]
    assert [c[0] for c in codes(n)] == ["queued"]  # solo avisa la primera vez


def test_corrupt_state_file_is_ignored(tmp_path):
    d = tmp_path / "st"
    d.mkdir()
    (d / "auto.json").write_text("{no es json")
    a, eng, n = make(tmp_path)
    assert a.pending() == []


# ---- juego abierto
def test_running_set_follows_marks(tmp_path):
    a, _, _ = make(tmp_path)
    assert a.is_running(10) is False
    a.mark(10, True)
    assert a.is_running(10) is True
    a.mark(10, False)
    assert a.is_running(10) is False


def test_closed_clears_running_even_if_unmapped(tmp_path):
    a, _, _ = make(tmp_path)
    a.mark(999, True)
    a.mark(999, False)
    assert a.is_running(999) is False


def test_open_mark_without_close_event_expires(tmp_path, monkeypatch):
    import checkpoint_auto

    a, _, _ = make(tmp_path)
    t = [1000.0]
    monkeypatch.setattr(checkpoint_auto.time, "monotonic", lambda: t[0])
    a.mark(10, True)
    assert a.is_running(10) is True
    t[0] += checkpoint_auto.OPEN_MAX_AGE_S + 1  # el evento de cierre se perdió: no queda abierto para siempre
    assert a.is_running(10) is False


# ---- avisos
def test_notices_take_drains_and_are_bounded():
    n = Notices(maxlen=3)
    for i in range(5):
        n.add("downloaded", "G%d" % i, "info")
    got = n.take()
    assert [x["game"] for x in got] == ["G2", "G3", "G4"]
    assert n.take() == []
    assert [x["id"] for x in got] == sorted(x["id"] for x in got)


# ---- ejecución asíncrona
class FakeAuto:
    def __init__(self):
        self.calls, self.marks, self.has = [], [], False
        self.retries = 0
        self.gate = threading.Event()
        self.gate.set()

    def mark(self, appid, running):
        self.marks.append((appid, running))

    def opened(self, appid):
        self.gate.wait(5)
        self.calls.append(("opened", appid))

    def closed(self, appid):
        self.gate.wait(5)
        self.calls.append(("closed", appid))

    def pending(self):
        return ["g1"] if self.has else []

    def retry_pending(self):
        self.retries += 1


async def until(cond, n=300):
    for _ in range(n):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("no se cumple")


def test_runner_marks_immediately_and_processes_in_order():
    async def go():
        auto = FakeAuto()
        auto.gate.clear()
        r = AutoRunner(auto, retry_s=60)
        r.submit(10, True)
        r.submit(10, False)
        assert auto.marks == [(10, True), (10, False)]  # el estado de «abierto» no espera a la cola
        auto.gate.set()
        await until(lambda: len(auto.calls) == 2)
        await r.close()
        return auto.calls

    assert asyncio.run(go()) == [("opened", 10), ("closed", 10)]


def test_runner_retries_pending_periodically():
    async def go():
        auto = FakeAuto()
        auto.has = True
        r = AutoRunner(auto, retry_s=0.02)
        r.submit(10, True)
        await until(lambda: auto.retries >= 2)
        await r.close()

    asyncio.run(go())


def test_runner_does_not_poll_without_pending():
    async def go():
        auto = FakeAuto()
        r = AutoRunner(auto, retry_s=0.01)
        r.submit(10, True)
        await until(lambda: auto.calls)
        await asyncio.sleep(0.1)
        await r.close()
        return auto.retries

    assert asyncio.run(go()) == 0


def test_runner_survives_a_failing_event():
    async def go():
        auto = FakeAuto()
        orig = auto.opened

        def boom(appid):
            if appid == 1:
                raise RuntimeError("fallo")
            orig(appid)

        auto.opened = boom
        r = AutoRunner(auto, retry_s=60, log=lambda m: None)
        r.submit(1, True)
        r.submit(2, True)
        await until(lambda: auto.calls)
        await r.close()
        return auto.calls

    assert asyncio.run(go()) == [("opened", 2)]


def test_runner_close_without_start_is_fine():
    asyncio.run(AutoRunner(FakeAuto()).close())


def test_runner_start_retries_pending_left_by_a_previous_run():
    async def go():
        auto = FakeAuto()
        auto.has = True  # la cola venía guardada de antes de apagar la Deck
        r = AutoRunner(auto, retry_s=0.02)
        r.start()
        await until(lambda: auto.retries >= 1)
        await r.close()

    asyncio.run(go())


# ---- log de cada rama (0.2.3): cada decisión, también las mudas, deja su línea `auto: ...` en el log
def make_logged(tmp_path, eng=None):
    logs = []
    eng = eng or FakeEngine()
    a = AutoSync(lambda: eng, str(tmp_path / "st"), Notices(), log=logs.append)
    return a, eng, logs


def test_autosync_no_longer_keeps_an_activity_ring(tmp_path):
    a, _, _ = make_logged(tmp_path)
    assert not hasattr(a, "note") and not hasattr(a, "activity")
    import checkpoint_auto

    assert not hasattr(checkpoint_auto, "ACTIVITY_MAX")


def test_open_logs_sync_state_and_code(tmp_path):
    a, eng, logs = make_logged(tmp_path)
    a.opened(10)
    assert logs == ["auto: abierto appid 10 (g1): uploaded"]
    eng.result = {"state": "error", "code": "path_forbidden"}
    a.opened(10)
    assert logs[-1] == "auto: abierto appid 10 (g1): error path_forbidden"


def test_up_to_date_open_is_logged(tmp_path):
    eng = FakeEngine()
    eng.result = {"state": "up_to_date"}
    a, _, logs = make_logged(tmp_path, eng)
    a.opened(10)
    assert any("up_to_date" in m for m in logs)


def test_silent_branches_write_a_log(tmp_path):
    a, _, logs = make_logged(tmp_path)
    a.opened(999)
    a.opened(20)
    a.closed(999)
    a.closed(20)
    assert sum("sin juego en el hub" in m for m in logs) == 2
    assert sum("desactivado" in m for m in logs) == 2
    assert "auto: abrir appid 999: sin juego en el hub; no se hace nada" in logs
    assert "auto: cerrado appid 20 (g2): juego desactivado; no se hace nada" in logs


def test_not_linked_no_answer_and_unauthorized_write_a_log(tmp_path):
    logs = []
    a = AutoSync(lambda: None, str(tmp_path / "st"), Notices(), log=logs.append)
    a.opened(10)
    a.closed(10)
    assert logs == [
        "auto: abrir appid 10: dispositivo sin vincular; no se hace nada",
        "auto: cerrado appid 10: dispositivo sin vincular; no se hace nada",
    ]
    b, eng, lb = make_logged(tmp_path / "b")
    eng.offline = True
    b.opened(10)
    assert lb == ["auto: abrir appid 10: sin respuesta del hub (HubNetworkError)"]
    eng2 = FakeEngine()
    eng2.list_games = lambda: (_ for _ in ()).throw(hc.HubApiError(401, None))
    c, _, lc = make_logged(tmp_path / "c", eng2)
    c.opened(10)
    c.closed(10)
    assert lc == [
        "auto: abrir appid 10: sin respuesta del hub (HubApiError)",
        "auto: cerrado appid 10: sin respuesta del hub (HubApiError)",
    ]


def test_close_branches_write_a_log(tmp_path):
    a, eng, logs = make_logged(tmp_path)
    a.closed(10)
    assert logs == ["auto: cierre de g1: uploaded"]
    eng.closed_error = hc.HubApiError(404, "err.main.unknown_game")
    a.closed(10)
    assert logs[-1] == "auto: el hub rechazó el aviso de cierre de g1 (404); no se reintenta"
    eng.closed_error = None
    eng.result = {"state": "error", "code": "connection"}
    a.closed(10)
    assert logs[-1] == "auto: cierre de g1: error connection"
    eng.result = {"state": "uploaded", "files": 1}
    eng.offline = True
    a.closed(10)
    assert logs[-1] == "auto: cerrado appid 10: sin respuesta del hub (HubNetworkError)"
    assert a.pending() == ["g1"]


# ---- aviso de apertura al hub (con el resultado de la sync local) y resultado en el cierre
def test_opened_tells_the_hub_with_the_result_and_notes_it(tmp_path):
    a, eng, n = make(tmp_path)
    eng.result = {"state": "uploaded", "files": 2}
    a.opened(10)
    assert eng.opened_sent == [("g1", {"state": "uploaded"})]  # sin `files`: solo estado (y código)
    assert codes(n) == [("uploaded", "Uno", "info")]  # ningún toast nuevo


def test_opened_result_carries_error_code_only(tmp_path):
    a, eng, _ = make(tmp_path)
    eng.result = {"state": "error", "code": "path_forbidden", "params": {"path": "/home/deck/secreto"}}
    a.opened(10)
    assert eng.opened_sent == [("g1", {"state": "error", "code": "path_forbidden"})]


def test_opened_maps_every_known_state_and_skips_the_rest(tmp_path):
    for state in ("uploaded", "downloaded", "up_to_date", "missing_dir", "no_path", "conflict"):
        a, eng, _ = make(tmp_path / state)
        eng.result = {"state": state}
        a.opened(10)
        assert eng.opened_sent == [("g1", {"state": state})], state
    a, eng, _ = make(tmp_path / "x")
    eng.result = {"state": "disabled"}
    a.opened(10)
    assert eng.opened_sent == []  # un estado que el hub no conoce no se envía


def test_opened_hub_without_support_is_noted_once_and_not_retried(tmp_path):
    for status in (400, 401, 404, 405):
        a, eng, logs = make_logged(tmp_path / str(status))
        n = a._notices
        eng.opened_error = hc.HubApiError(status, "err.x")
        a.opened(10)
        assert len(eng.opened_sent) == 1 and any("hub sin soporte" in m for m in logs), status
        assert codes(n) == [("uploaded", "Uno", "info")]  # ningún toast por esto
        assert a.pending() == []


def test_opened_hub_errors_are_noted_as_error_without_toast_or_retry(tmp_path):
    for exc in (HubNetworkError("URLError"), hc.HubApiError(500, None), hc.HubApiError(429, None), hc.HubApiError(400, "err.hook.result_invalid")):
        a, eng, logs = make_logged(tmp_path / type(exc).__name__ / str(getattr(exc, "status", 0)) / str(getattr(exc, "code", "")))
        n = a._notices
        eng.opened_error = exc
        a.opened(10)
        assert len(eng.opened_sent) == 1 and any("aviso de apertura de g1:" in m and "no se reintenta" in m for m in logs)
        assert codes(n) == [("uploaded", "Uno", "info")] and a.pending() == []


def test_opened_does_not_tell_the_hub_when_offline(tmp_path):
    a, eng, _ = make(tmp_path)
    eng.offline = True
    a.opened(10)
    assert eng.opened_sent == []


def test_closed_sends_the_result(tmp_path):
    a, eng, _ = make(tmp_path)
    eng.result = {"state": "uploaded", "files": 1}
    a.closed(10)
    assert eng.closed_results == [{"state": "uploaded"}]
