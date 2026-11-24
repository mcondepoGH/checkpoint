"""Vigilante de procesos: detección con psutil (falso) y ciclo abrir / cerrar / reintentar contra un hub falso.

El motor es el real (`SyncEngine`) contra `FakeHub`; solo el detector de procesos y el reloj son falsos.
"""

import json
import os
import subprocess
import time
import types
from pathlib import Path

import pytest
from conftest import KEY

from checkpoint_client import locks, texts, watcher
from checkpoint_client.hub import HubNetworkError
from checkpoint_client.hubclient import HubApiError
from checkpoint_client.sync import SyncEngine

GAME = "g1"
PROC = "mijuego.exe"


class FakePsutil:
    """Lo mínimo de `psutil` que usa el vigilante: `process_iter(attrs)` con objetos que llevan `.info`."""

    def __init__(self):
        self.procs = []

    def add(self, name, exe=None, cmdline=None):
        self.procs.append({"name": name, "exe": exe, "cmdline": cmdline})

    def clear(self):
        self.procs.clear()

    def process_iter(self, attrs=None):
        return [types.SimpleNamespace(info=dict(p)) for p in self.procs]


class Flaky:
    """Motor real con el hub «caído» a voluntad: red rota en cada llamada."""

    def __init__(self, engine):
        self.engine, self.down = engine, False

    def __getattr__(self, name):
        return getattr(self.engine, name)

    def list_games(self):
        if self.down:
            raise HubNetworkError("caído")
        return self.engine.list_games()

    def sync_game(self, game, games=None, progress=None):
        if self.down:
            return {"state": "error", "code": "connection", "game": game}
        return self.engine.sync_game(game, games, progress)

    def notify_opened(self, game, result=None):
        if self.down:
            raise HubNetworkError("caído")
        return self.engine.notify_opened(game, result)

    def notify_closed(self, game, result=None):
        if self.down:
            raise HubNetworkError("caído")
        return self.engine.notify_closed(game, result)


class Env:
    def __init__(self, fakehub, home, cfg):
        self.hub, self.home, self.cfg = fakehub, home, cfg
        self.save = home / "Games" / "g1"
        self.ps = FakePsutil()
        self.out, self.err, self.slept, self.reports = [], [], [], []
        self.now = 1000.0
        fakehub.games = [
            {
                "id": GAME,
                "name": "Mi Juego",
                "enabled": True,
                "steam_appid": None,
                "status": None,
                "path": str(self.save),
                "process": PROC,
            }  # fmt: skip
        ]
        self.engine = Flaky(SyncEngine(fakehub.url, KEY, home=home, protected=[Path(cfg)], sleep=lambda _s: None))
        self.on_sleep = None

    def sleep(self, s):
        self.slept.append(s)
        if self.on_sleep:
            self.on_sleep()

    def make(self, **kw):
        return watcher.Watcher(
            self.engine,
            watcher.ProcessDetector(self.ps),
            self.cfg,
            report=lambda res, g: self.reports.append((g["id"], res.get("state"))),
            out=self.out.append,
            err=self.err.append,
            sleep=self.sleep,
            clock=lambda: self.now,
            **kw,
        )

    def put(self, rel, data):
        p = self.save / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def pending(self):
        p = Path(self.cfg) / "watch.json"
        return json.loads(p.read_text(encoding="utf-8"))["pending"] if p.exists() else []


@pytest.fixture
def env(fakehub, home, tmp_path):
    return Env(fakehub, home, str(tmp_path / "cfg"))


# ---------------------------------------------------------------- detección
def info(name="x", exe=None, cmdline=None):
    return {"name": name, "exe": exe, "cmdline": cmdline}


def test_match_ignores_case():
    assert watcher.matches("MiJuego.EXE", [info("mijuego.exe")])
    assert watcher.matches("mijuego.exe", [info("MIJUEGO.EXE")])


def test_match_no_match_for_other_processes_or_prefixes():
    assert not watcher.matches("mijuego.exe", [info("otro"), info("mijuego"), info("mijuego.exe.bak")])
    assert not watcher.matches("mijuego.exe", [info(None), {}])


def test_match_truncated_name_of_15_characters():
    """psutil en Linux trunca `name()` a 15 caracteres: el nombre largo del hub debe seguir encontrándolo."""
    target = "MyVeryLongGameName.exe"
    truncated = target[:15].lower()
    assert len(truncated) == 15
    assert watcher.matches(target, [info(truncated)])
    assert not watcher.matches(target, [info("MyVeryLongGameX")])  # 15 caracteres pero otro proceso
    assert not watcher.matches("short", [info("shor")])  # un nombre corto no se acepta como prefijo


def test_match_falls_back_to_exe_and_cmdline_basename():
    target = "MyVeryLongGameName.exe"
    assert watcher.matches(target, [info("MyVeryLongGameN", exe="/opt/g/MyVeryLongGameName.exe")])
    assert watcher.matches(target, [info("wine64-preloader", cmdline=["/opt/g/MyVeryLongGameName.exe", "-x"])])
    assert watcher.matches(target, [info("wine", cmdline=["Z:\\games\\MyVeryLongGameName.exe"])])
    assert not watcher.matches(target, [info("vim", cmdline=["vim", "MyVeryLongGameName.exe"])])


def test_detector_is_running_by_game_id(env):
    d = watcher.ProcessDetector(env.ps)
    d.set_games(env.hub.games)
    assert d.is_running(GAME) is False and d.is_running("desconocido") is False
    env.ps.add(PROC.upper())
    assert d.is_running(GAME) is True


# ---------------------------------------------------------------- ciclo
def test_never_seen_game_does_nothing(env):
    w = env.make()
    w.start()
    w.tick()
    assert env.hub.events == [] and not env.slept
    assert env.out == [texts.WATCH_START.format(n=1)]


def test_open_then_close_uploads_and_notifies_without_downloading_first(env):
    env.hub.files[GAME] = {"a.sav": b"hub-viejo"}  # el hub ya tiene un guardado: al abrir NO se baja
    env.hub.base[GAME] = None
    w = env.make()
    w.start()
    w.tick()
    env.ps.add(PROC)
    w.tick()
    assert env.out[-1] == texts.WATCH_OPENED.format(game="Mi Juego")
    assert not env.save.exists()  # no se bajó nada
    assert [e[:2] for e in env.hub.events] == [("opened", GAME)]
    env.put("a.sav", b"nuevo")  # se juega
    env.hub.files[GAME] = {}
    env.hub.base[GAME] = None
    env.ps.clear()
    w.tick()
    assert env.slept == [watcher.SETTLE_S]  # espera a que se liberen los ficheros
    assert env.out[-1] == texts.WATCH_CLOSED.format(game="Mi Juego")
    assert env.hub.files[GAME] == {"a.sav": b"nuevo"}
    assert [e[:2] for e in env.hub.events] == [("opened", GAME), ("closed", GAME)]
    assert env.hub.events[1][2] == {"result": {"state": "uploaded"}}
    assert env.reports == [(GAME, "uploaded")]


def test_game_already_open_when_the_watcher_starts_is_not_downloaded(env):
    env.hub.files[GAME] = {"a.sav": b"hub"}
    env.hub.base[GAME] = None
    env.ps.add(PROC)
    w = env.make()
    w.start()
    w.tick()
    assert env.out[-1] == texts.WATCH_ALREADY_OPEN.format(game="Mi Juego")
    assert not env.save.exists() and env.hub.files[GAME] == {"a.sav": b"hub"}
    env.put("b.sav", b"mio")
    env.hub.files[GAME] = {}
    env.ps.clear()
    w.tick()
    assert env.hub.files[GAME] == {"b.sav": b"mio"}  # se sube al cerrarlo
    assert env.hub.events[-1][:2] == ("closed", GAME)


def test_game_without_process_is_warned_and_skipped(env):
    env.hub.games.append({**env.hub.games[0], "id": "g2", "name": "Sin Proceso", "process": None})
    env.hub.games.append({**env.hub.games[0], "id": "g3", "name": "Otro", "process": ""})
    w = env.make()
    w.start()
    assert env.err == [texts.WATCH_NO_PROCESS.format(game="Sin Proceso"), texts.WATCH_NO_PROCESS.format(game="Otro")]
    assert env.out == [texts.WATCH_START.format(n=1)]
    w.tick()  # el aviso no se repite
    assert len(env.err) == 2


def test_hub_that_never_sends_process_is_the_same_as_none(env):
    for g in env.hub.games:
        g.pop("process")
    w = env.make()
    w.start()
    assert env.err == [texts.WATCH_NO_PROCESS.format(game="Mi Juego")]
    assert env.out == [texts.WATCH_START.format(n=0)]


def test_disabled_games_are_not_watched(env):
    env.hub.games[0]["enabled"] = False
    w = env.make()
    w.start()
    assert env.out == [texts.WATCH_START.format(n=0)] and env.err == []


def test_game_reopened_during_the_wait_is_not_uploaded(env):
    env.put("a.sav", b"x")
    w = env.make()
    w.start()
    env.ps.add(PROC)
    w.tick()
    env.ps.clear()
    env.on_sleep = lambda: env.ps.add(PROC)  # el juego vuelve a aparecer mientras se espera
    w.tick()
    assert [e[:2] for e in env.hub.events] == [("opened", GAME)] and not env.hub.files.get(GAME)
    env.on_sleep = None
    env.ps.clear()
    w.tick()
    assert env.hub.files[GAME] == {"a.sav": b"x"}


def test_conflict_is_reported_and_closed_is_still_notified(env):
    env.hub.files[GAME] = {"a.sav": b"hub"}
    env.hub.base[GAME] = "otra-huella"
    env.put("a.sav", b"local")
    w = env.make()
    w.start()
    env.ps.add(PROC)
    w.tick()
    env.ps.clear()
    w.tick()
    assert env.reports == [(GAME, "conflict")]
    assert env.hub.files[GAME] == {"a.sav": b"hub"}  # no se tocó nada
    assert env.hub.events[-1][:2] == ("closed", GAME) and env.pending() == []


# ---------------------------------------------------------------- hub caído y cola persistente
def play(env, w):
    w.start()
    env.ps.add(PROC)
    w.tick()
    env.put("a.sav", b"partida")
    env.ps.clear()


def test_hub_down_on_close_queues_the_close_on_disk_and_retries(env):
    w = env.make()
    play(env, w)
    env.engine.down = True
    w.tick()
    assert env.out[-1] == texts.WATCH_OFFLINE.format(game="Mi Juego")
    assert env.pending() == [{"id": GAME, "name": "Mi Juego"}]
    assert not env.hub.files.get(GAME)
    w.tick()  # antes de tiempo no se reintenta (ni se repite el aviso)
    assert env.out.count(texts.WATCH_OFFLINE.format(game="Mi Juego")) == 1
    env.now += watcher.RETRY_S
    w.tick()  # el hub sigue caído: sigue en la cola
    assert env.pending() == [{"id": GAME, "name": "Mi Juego"}]
    env.engine.down = False
    env.now += watcher.RETRY_S
    w.tick()
    assert env.hub.files[GAME] == {"a.sav": b"partida"}
    assert env.hub.events[-1][:2] == ("closed", GAME)
    assert env.pending() == []


def test_pending_close_survives_a_restart_of_the_watcher(env):
    w = env.make()
    play(env, w)
    env.engine.down = True
    w.tick()
    env.engine.down = False
    w2 = env.make()  # otro proceso: lee la cola del disco y reintenta al arrancar
    w2.start()
    w2.tick()
    assert env.hub.files[GAME] == {"a.sav": b"partida"} and env.pending() == []
    assert (Path(env.cfg) / "watch.json").stat().st_mode & 0o777 == 0o600


def test_pending_file_holds_only_id_and_name(env):
    w = env.make()
    play(env, w)
    env.engine.down = True
    w.tick()
    raw = (Path(env.cfg) / "watch.json").read_text(encoding="utf-8")
    assert str(env.home) not in raw and KEY not in raw


def test_sync_ok_but_closed_notice_fails_is_retried(env, monkeypatch):
    w = env.make()
    play(env, w)

    def boom(game, result=None):
        raise HubNetworkError("caído")

    real = env.engine.engine.notify_closed
    monkeypatch.setattr(env.engine.engine, "notify_closed", boom)
    w.tick()
    assert env.hub.files[GAME] == {"a.sav": b"partida"}  # ya subido
    assert env.pending() == [{"id": GAME, "name": "Mi Juego"}]
    monkeypatch.setattr(env.engine.engine, "notify_closed", real)
    env.now += watcher.RETRY_S
    w.tick()
    assert env.hub.events[-1][:2] == ("closed", GAME) and env.pending() == []


def test_hub_rejecting_the_closed_notice_is_not_retried_forever(env, monkeypatch):
    w = env.make()
    play(env, w)

    def reject(game, result=None):
        raise HubApiError(400, "err.hook.result_invalid")

    monkeypatch.setattr(env.engine.engine, "notify_closed", reject)
    w.tick()
    assert env.pending() == []


def test_retry_waits_while_the_game_is_open_again(env):
    w = env.make()
    play(env, w)
    env.engine.down = True
    w.tick()
    env.engine.down = False
    env.ps.add(PROC)  # se vuelve a abrir
    w.tick()
    env.now += watcher.RETRY_S
    w.tick()
    assert env.pending() == [{"id": GAME, "name": "Mi Juego"}] and not env.hub.files.get(GAME)


def test_retry_drops_games_the_hub_no_longer_has(env):
    w = env.make()
    play(env, w)
    env.engine.down = True
    w.tick()
    env.engine.down = False
    env.hub.games.clear()
    env.now += watcher.RETRY_S
    w.tick()
    assert env.pending() == []


def test_unexpected_error_in_one_game_does_not_stop_the_loop(env, monkeypatch):
    w = env.make()
    w.start()
    monkeypatch.setattr(w.detector, "snapshot", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    w.tick()  # no revienta


# ---------------------------------------------------------------- lock
def test_game_owned_by_another_client_process_is_left_alone(env):
    """`run` tiene el lock del juego mientras se juega: el vigilante ni avisa ni sube; lo hace `run`."""
    env.put("a.sav", b"x")
    w = env.make()
    w.start()
    with locks.exclusive(os.path.join(env.cfg, "locks"), locks.game_name(GAME)):
        env.ps.add(PROC)
        w.tick()
        env.ps.clear()
        w.tick()
    assert env.hub.events == [] and not env.hub.files.get(GAME) and env.pending() == []
    assert env.out == [texts.WATCH_START.format(n=1)]


def test_close_while_another_sync_holds_the_lock_is_retried_silently(env):
    env.put("a.sav", b"x")
    w = env.make()
    w.start()
    env.ps.add(PROC)
    w.tick()
    env.ps.clear()
    with locks.exclusive(os.path.join(env.cfg, "locks"), locks.game_name(GAME)):
        w.tick()
        assert env.pending() == [{"id": GAME, "name": "Mi Juego"}] and not env.hub.files.get(GAME)
        assert texts.WATCH_OFFLINE.format(game="Mi Juego") not in env.out
    env.now += watcher.RETRY_S
    w.tick()
    assert env.hub.files[GAME] == {"a.sav": b"x"} and env.pending() == []


def test_run_loop_polls_and_stops_with_ctrl_c(env):
    calls = []

    def sleep(s):
        calls.append(s)
        if len(calls) == 3:
            raise KeyboardInterrupt

    env.sleep = sleep
    w = env.make(poll_s=0.5)
    with pytest.raises(KeyboardInterrupt):
        w.run()
    assert calls == [0.5, 0.5, 0.5]


# ---------------------------------------------------------------- proceso real
def test_real_process_is_detected_while_it_runs(tmp_path):
    """Un `sleep` copiado con otro nombre largo (más de 15 caracteres, como un juego): detección con psutil real."""
    pytest.importorskip("psutil")
    sleep_bin = Path("/bin/sleep")
    if not sleep_bin.exists():
        pytest.skip("no hay /bin/sleep")
    name = "checkpoint-fake-game-xyz.exe"  # 28 caracteres: el comm del kernel se trunca a 15
    fake = tmp_path / name
    try:
        fake.write_bytes(sleep_bin.read_bytes())
        fake.chmod(0o755)
        proc = subprocess.Popen([str(fake), "30"])
    except OSError as e:  # pragma: no cover - depende del entorno
        pytest.skip(f"no se puede ejecutar la copia: {e}")
    try:
        d = watcher.ProcessDetector()
        d.set_games([{"id": GAME, "process": name}])
        for _ in range(50):
            if d.is_running(GAME):
                break
            time.sleep(0.1)
        assert d.is_running(GAME) is True
        proc.kill()
        proc.wait()
        assert d.is_running(GAME) is False
    finally:
        proc.kill()
        proc.wait()
