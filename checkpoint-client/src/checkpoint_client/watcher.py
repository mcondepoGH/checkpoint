"""Vigilante de procesos: sube el guardado de un juego cuando se cierra, sin tocar el lanzador.

Detecta apertura y cierre por el `process` que el hub da de cada juego (GET /api/games con key de dispositivo) usando
`psutil`. Reglas (las de la tarjeta):
- NO baja antes de abrir: el vigilante no se adelanta al arranque. Si el juego ya estaba abierto al arrancar el
  vigilante, tampoco baja: sube al cerrarlo.
- Al cerrar espera unos segundos a que se liberen los ficheros, sincroniza (sube) y avisa `opened`/`closed` al hub.
- Si el hub no responde al cerrar, el cierre queda en una cola en disco (`watch.json`, solo id y nombre del juego) y se
  reintenta cada minuto, también tras reiniciar el vigilante. Es el comportamiento de `checkpoint_auto.py` del plugin.
- Un juego sin `process` se avisa y se omite (`run` sigue funcionando).
- Un juego cuyo lock tiene otro proceso del cliente (`run`) se deja en paz: lo sube ese proceso.

Detección: el nombre del proceso se compara sin mayúsculas. Con psutil en Linux `name()` sale truncado a 15 caracteres
(`comm` del kernel): se acepta el nombre cortado si el del hub empieza por él, y hay respaldo por `exe` y por el primer
argumento de `cmdline` (con `/` o con la barra invertida como separador). Con Wine/Proton el proceso es un .exe bajo Linux: cómo se ve en
psutil NO está verificado (los respaldos están pensados para ello).
"""

import os
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import hub, locks, settings, texts
from .hubclient import HubApiError
from .hub import HubNetworkError
from .sync import hub_result

STATE_FILE = "watch.json"
POLL_S = 2.0  # cada cuánto se mira la lista de procesos
SETTLE_S = 5.0  # espera tras el cierre para que el juego termine de soltar los ficheros
RETRY_S = 60.0  # cada cuánto se reintenta la cola mientras haya algo pendiente
REFRESH_S = 300.0  # cada cuánto se vuelve a pedir la lista de juegos al hub
COMM_MAX = 15  # longitud a la que el kernel de Linux trunca el nombre del proceso
# Errores de una sincronización que merece la pena reintentar (red caída, hub ocupado, otro proceso con el juego)
RETRY_CODES = {"connection", "hub_busy", "hub_changed", "rate_limited", "upload_incomplete", "busy"}


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def matches(process: str, snapshot: Iterable[Dict[str, Any]]) -> bool:
    """¿Hay en `snapshot` (lista de {name, exe, cmdline}) un proceso que sea `process`?"""
    target = _base(process).lower()
    if not target:
        return False
    for p in snapshot:
        name = p.get("name")
        if isinstance(name, str):
            n = name.lower()
            if n == target or (len(n) >= COMM_MAX and target.startswith(n)):
                return True
        exe = p.get("exe")
        if isinstance(exe, str) and exe and _base(exe).lower() == target:
            return True
        cmd = p.get("cmdline")
        if isinstance(cmd, (list, tuple)) and cmd and isinstance(cmd[0], str) and _base(cmd[0]).lower() == target:
            return True
    return False


class ProcessDetector:
    """Mira los procesos con psutil. `psutil_module` solo se inyecta en los tests."""

    def __init__(self, psutil_module: Any = None):
        if psutil_module is None:
            import psutil as psutil_module  # noqa: PLC0415  (dependencia declarada; import tardío para poder falsearla)
        self._psutil = psutil_module
        self._process: Dict[str, str] = {}

    def set_games(self, games: Iterable[Dict[str, Any]]) -> None:
        self._process = {
            g["id"]: g["process"] for g in games if isinstance(g.get("process"), str) and g["process"].strip()
        }

    def snapshot(self) -> List[Dict[str, Any]]:
        return [dict(p.info) for p in self._psutil.process_iter(["name", "exe", "cmdline"])]

    def is_running(self, game: str) -> bool:
        process = self._process.get(game)
        return bool(process) and matches(process, self.snapshot())


class Watcher:
    """Un ciclo de vigilancia: `start()` una vez, luego `tick()` cada `poll_s` (o `run()`, que lo hace hasta Ctrl+C)."""

    def __init__(
        self,
        engine: Any,
        detector: ProcessDetector,
        state_dir: str,
        *,
        report: Callable[[Dict[str, Any], Dict[str, Any]], Any],
        out: Callable[[str], None],
        err: Callable[[str], None],
        log: Callable[[str], None] = lambda _m: None,
        sleep: Optional[Callable[[float], None]] = None,
        clock: Callable[[], float] = time.monotonic,
        settle_s: float = SETTLE_S,
        poll_s: float = POLL_S,
        retry_s: float = RETRY_S,
        refresh_s: float = REFRESH_S,
    ):
        self.engine, self.detector, self._dir = engine, detector, state_dir
        self._report, self._out, self._err, self._log = report, out, err, log
        self._sleep = sleep or time.sleep
        self._clock = clock
        self._settle_s, self._poll_s, self._retry_s, self._refresh_s = settle_s, poll_s, retry_s, refresh_s
        self._games: List[Dict[str, Any]] = []
        self._open: Dict[str, str] = {}  # id -> "own" (lo sube este vigilante) | "external" (lo lleva otro proceso)
        self._warned: set = set()
        self._first = True
        self._next_refresh = self._next_retry = 0.0
        s = settings.load_settings(state_dir, STATE_FILE)
        pend = s.get("pending") if isinstance(s.get("pending"), list) else []
        self._pending: Dict[str, str] = {
            p["id"]: p["name"]
            for p in pend
            if isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("name"), str)
        }

    # ---- juegos
    def _watched(self) -> List[Dict[str, Any]]:
        return [
            g
            for g in self._games
            if g.get("enabled", True) and isinstance(g.get("process"), str) and g["process"].strip()
        ]

    def _load_games(self) -> bool:
        try:
            games = self.engine.list_games()
        except (HubApiError, HubNetworkError):
            return False
        self._games = games
        self.detector.set_games(games)
        known = {g["id"] for g in games}
        for gid in [i for i in self._open if i not in known]:
            del self._open[gid]
        for g in games:
            if g.get("enabled", True) and not (isinstance(g.get("process"), str) and g["process"].strip()):
                if g["id"] not in self._warned:
                    self._warned.add(g["id"])
                    self._err(texts.WATCH_NO_PROCESS.format(game=g["name"]))
        return True

    def start(self) -> int:
        """Primera carga de juegos y mensaje de arranque. Devuelve cuántos se vigilan."""
        self._load_games()
        self._next_refresh = self._clock() + self._refresh_s
        n = len(self._watched())
        self._out(texts.WATCH_START.format(n=n))
        return n

    # ---- cola persistente
    def _save(self) -> None:
        data = {"pending": [{"id": i, "name": n} for i, n in self._pending.items()]}
        try:
            settings.save_settings(self._dir, data, STATE_FILE)
        except OSError:
            self._log("vigilante: no se pudo guardar la cola en disco")

    def _queue(self, game: Dict[str, Any], say: bool) -> None:
        if game["id"] in self._pending:
            return
        self._pending[game["id"]] = game["name"]
        self._save()
        if say:
            self._out(texts.WATCH_OFFLINE.format(game=game["name"]))

    def _dequeue(self, game_id: str) -> None:
        if self._pending.pop(game_id, None) is not None:
            self._save()

    # ---- ciclo
    def tick(self) -> None:
        try:
            self._tick()
        except Exception as e:  # noqa: BLE001  (un fallo no para el vigilante; el detalle redactado va al log)
            self._log(hub.redact(f"vigilante: fallo inesperado ({type(e).__name__}: {e})"))

    def _tick(self) -> None:
        now = self._clock()
        if now >= self._next_refresh:
            self._next_refresh = now + self._refresh_s
            self._load_games()
        snap = self.detector.snapshot()
        for g in self._watched():
            running = matches(g["process"], snap)
            was = g["id"] in self._open
            if running and not was:
                self._on_open(g)
            elif was and not running:
                self._on_close(g)
        self._first = False
        if self._pending and now >= self._next_retry:
            self._next_retry = now + self._retry_s
            self._retry()

    def _lock_dir(self) -> str:
        return os.path.join(self._dir, "locks")

    def _on_open(self, g: Dict[str, Any]) -> None:
        if locks.is_locked(self._lock_dir(), locks.game_name(g["id"])):
            self._open[g["id"]] = "external"  # `run` lo lleva: ni avisa ni sube
            return
        self._open[g["id"]] = "own"
        text = texts.WATCH_ALREADY_OPEN if self._first else texts.WATCH_OPENED
        self._out(text.format(game=g["name"]))
        try:
            self.engine.notify_opened(g["id"], None)  # no se ha sincronizado nada al abrir: sin resultado
        except (HubApiError, HubNetworkError):
            self._log(f"vigilante: no se pudo avisar de la apertura de {g['id']}")

    def _on_close(self, g: Dict[str, Any]) -> None:
        owner = self._open.pop(g["id"])
        if owner == "external":
            return
        self._sleep(self._settle_s)
        if matches(g["process"], self.detector.snapshot()):
            self._open[g["id"]] = owner  # volvió a aparecer: era una pausa del lanzador, no un cierre
            return
        self._out(texts.WATCH_CLOSED.format(game=g["name"]))
        self._finish(g)

    def _finish(self, g: Dict[str, Any]) -> None:
        """Sube lo que toque y avisa del cierre. Si no se puede (hub sin respuesta u ocupado), queda en la cola."""
        gid = g["id"]
        try:
            with locks.exclusive(self._lock_dir(), locks.game_name(gid)):
                res = self.engine.sync_game(gid, None)
        except locks.Busy:
            self._queue(g, say=False)  # otro proceso del cliente lo está sincronizando: se reintenta
            return
        self._log(f"vigilante: cierre de {gid}: {res.get('state')} {res.get('code') or ''}".rstrip())
        if res.get("state") == "error" and res.get("code") in RETRY_CODES:
            self._queue(g, say=True)
            return
        self._report(res, g)
        if res.get("state") == "error" and res.get("code") == "unauthorized":
            self._dequeue(gid)
            return
        try:
            self.engine.notify_closed(gid, hub_result(res))
        except HubNetworkError:
            self._queue(g, say=True)
            return
        except HubApiError as e:
            if e.status == 429 or e.status >= 500 or e.status == 409:
                self._queue(g, say=True)
                return
            self._log(f"vigilante: el hub rechazó el aviso de cierre de {gid} ({e.status}); no se reintenta")
        self._dequeue(gid)

    def _retry(self) -> None:
        try:
            games = self.engine.list_games()
        except HubNetworkError:
            return
        except HubApiError as e:
            if e.status == 401:  # la clave ya no vale: reintentar no sirve
                self._pending.clear()
                self._save()
            return
        for gid in list(self._pending):
            g = next((x for x in games if x["id"] == gid), None)
            if g is None or not g.get("enabled", True):
                self._dequeue(gid)  # el juego ya no está en el hub o se desactivó
            elif gid in self._open:
                continue  # se volvió a abrir: su propio cierre lo resolverá
            else:
                self._finish(g)

    def run(self) -> None:
        """Bucle hasta Ctrl+C (`KeyboardInterrupt` sube a quien llama)."""
        while True:
            self.tick()
            self._sleep(self._poll_s)
