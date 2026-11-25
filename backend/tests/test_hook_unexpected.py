"""Excepción inesperada del sync en un aviso de apertura o de cierre: el hilo del run no debe morir sin dejar rastro.
Dos puntos de fallo: el `runner` (lo captura `Scheduler.run_game`: error `err.sync.unexpected`) y el propio `run_game`
(sin red en `work()` de `HookService.start_run`). Sin esperas fijas: reloj falso del vigilante y sondeos acotados."""

import logging
import threading

import pytest

from app.users import history
from test_hook_close import cl, hist, hopen, mk, wait_for  # noqa: F401 (fixtures)
from test_hook_close_history import SENSITIVE, seen_running, sim  # noqa: F401 (fixtures)

CODE = "err.sync.unexpected"


def ctx(c):
    return c.app.state.ctx


def all_runs_done(c, n=1):
    """Hay al menos `n` runs y todos terminaron (`n` evita dar por buena una espera con solo el run de `opened`)."""
    runs = list(ctx(c).runs._runs.values())
    return len(runs) >= n and all(r.done for r in runs)


def boom_runner(*a, **k):
    raise RuntimeError(SENSITIVE)


def boom_run_game(*a, **k):
    raise RuntimeError(SENSITIVE)


@pytest.fixture
def thread_errors(monkeypatch):
    """Excepciones no capturadas de hilos (lo que imprimiría `threading.excepthook`): si el hilo muere, caen aquí."""
    errs = []
    monkeypatch.setattr(threading, "excepthook", lambda args: errs.append(args.exc_type))
    return errs


def check_unexpected_entry(e, trigger):
    assert e["trigger"] == trigger and e["result"] == "error" and e["device"] == "dev-1"
    assert e["code"] == "err.scheduler.summary"  # el resumen envuelve la causa; el código real va en el juego
    assert e["params"]["causes"][0]["code"] == CODE
    g = e["games"]["g1"]
    assert g["result"] == "error" and g["code"] == CODE and g["name"] == "Mi Juego"
    assert g["params"]["type"] == "RuntimeError"
    return g["params"]


# ---- el runner lanza (lo captura run_game) ----
def test_opened_runner_exception_returns_error_and_saves_history(cl, monkeypatch, caplog, thread_errors):
    caplog.set_level(logging.INFO, logger="checkpoint.hook")
    monkeypatch.setattr(ctx(cl).scheduler, "runner", boom_runner)
    r = hopen(cl)
    j = r.json()
    assert r.status_code == 200 and j["ok"] is False and j["outcome"] == "error" and j["code"] == CODE
    assert wait_for(lambda: all_runs_done(cl))
    assert thread_errors == []  # el hilo no murió con una excepción
    h = hist("hook")
    assert len(h) == 1
    params = check_unexpected_entry(h[0], "hook")
    # Hoy `detail` lleva `str(e)` pasado por `history.short` (redacta lo que reconoce como secreto y trunca): se
    # documenta el comportamiento actual, no se exige que sea más estricto.
    assert params["detail"] == history.short(SENSITIVE)
    assert wait_for(
        lambda: any(
            "resultado=error" in r.getMessage() and "code=err.scheduler.summary" in r.getMessage()
            for r in caplog.records
        )
    )
    assert all("SECRETO" not in r.getMessage() for r in caplog.records)  # el log no lleva el mensaje de la excepción


def test_closed_runner_exception_saves_history_and_watcher_survives(cl, sim, monkeypatch, caplog, thread_errors):
    caplog.set_level(logging.INFO, logger="checkpoint.hook")
    seen_running(cl)
    monkeypatch.setattr(ctx(cl).scheduler, "runner", boom_runner)
    cl.proc.running = False
    assert wait_for(lambda: hist("hook_closed"))
    h = hist("hook_closed")
    assert len(h) == 1
    params = check_unexpected_entry(h[0], "hook_closed")
    assert params["detail"] == history.short(SENSITIVE)
    assert wait_for(lambda: all_runs_done(cl))
    assert thread_errors == []
    assert wait_for(lambda: cl.app.state.watcher.tasks == {})  # sin reintento
    assert any(
        "resultado=error" in r.getMessage() and "code=err.scheduler.summary" in r.getMessage() for r in caplog.records
    )
    assert all("SECRETO" not in r.getMessage() for r in caplog.records)


# ---- el propio run_game lanza (no debería: «nunca lanza», pero work() no tiene red) ----
def test_opened_run_game_exception_marks_run_done_and_thread_ends(cl, monkeypatch, thread_errors):
    monkeypatch.setattr(ctx(cl).scheduler, "run_game", boom_run_game)
    r = hopen(cl)
    assert r.status_code == 200 and r.json()["outcome"] == "error"
    assert wait_for(lambda: all_runs_done(cl))  # el `finally` marca el run como hecho y libera al lanzador
    assert thread_errors == []  # work() captura la excepción: el hilo termina limpio


def test_opened_run_game_exception_returns_error_and_saves_history(cl, monkeypatch, thread_errors):
    monkeypatch.setattr(ctx(cl).scheduler, "run_game", boom_run_game)
    r = hopen(cl)
    assert r.status_code == 200 and r.json()["outcome"] == "error"
    assert wait_for(lambda: hist("hook"))
    assert thread_errors == []


def test_closed_run_game_exception_marks_run_done_and_watcher_survives(cl, sim, monkeypatch, thread_errors):
    seen_running(cl)
    real = ctx(cl).scheduler.run_game
    monkeypatch.setattr(ctx(cl).scheduler, "run_game", boom_run_game)
    cl.proc.running = False
    assert wait_for(lambda: all_runs_done(cl, 2))  # el run de `opened` + el del cierre
    assert wait_for(lambda: cl.app.state.watcher.tasks == {})
    assert thread_errors == []
    monkeypatch.setattr(ctx(cl).scheduler, "run_game", real)  # el vigilante sigue vivo: otra apertura se arma
    assert hopen(cl).status_code == 200


def test_closed_run_game_exception_saves_history(cl, sim, monkeypatch, thread_errors):
    seen_running(cl)
    monkeypatch.setattr(ctx(cl).scheduler, "run_game", boom_run_game)
    cl.proc.running = False
    assert wait_for(lambda: all_runs_done(cl, 2))
    assert wait_for(lambda: hist("hook_closed"))
    assert thread_errors == []


def test_run_game_exception_message_not_in_log(cl, monkeypatch, caplog, thread_errors):
    caplog.set_level(logging.DEBUG, logger="checkpoint.hook")
    secret = "/mnt/privado/ruta tok_ABCDEF123456"

    def boom(*a, **k):
        raise RuntimeError(secret)

    monkeypatch.setattr(ctx(cl).scheduler, "run_game", boom)
    r = hopen(cl)
    assert r.status_code == 200 and r.json()["outcome"] == "error"
    assert wait_for(lambda: all_runs_done(cl))
    assert any("RuntimeError" in x.getMessage() for x in caplog.records)
    assert all(secret not in x.getMessage() and "tok_ABCDEF" not in x.getMessage() for x in caplog.records)
    assert thread_errors == []
