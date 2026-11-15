"""Avisos automáticos de abrir y cerrar juegos (Tramo 5). Solo biblioteca estándar.

La interfaz (Steam) avisa con `game_event(appid, running)`; aquí se decide qué hacer:
- Al ABRIR un juego asociado: se sincroniza con el hub (baja el save si toca) y se avisa con un toast. NO se pausa el
  juego (decisión del MVP: `SIGSTOP` queda para después de probar en una Deck real).
- Al CERRAR: se sincroniza (sube el save si toca) y después se avisa al hub con `POST /api/hook/{game}/closed`. Sin red
  (o con el hub ocupado) el cierre queda en una cola que se guarda en disco (la Deck se apaga a menudo) y se reintenta
  cada minuto mientras haya algo pendiente.
- Conflicto: toast de aviso y no se toca nada; se resuelve desde el panel del plugin o desde la web del hub. Tras
  sincronizar al abrir se avisa al hub con `POST /api/hook/{game}/opened` y el resultado (un solo intento, no crítico).
- Un appid que no es un juego del hub (la mayoría de las apps de Steam) no hace nada ni avisa.
Los avisos se acumulan en `Notices`; la interfaz los recoge con `take_notices` y los muestra como toasts. En disco solo
se guardan appid, id y nombre de los juegos: nunca rutas ni claves.
"""

import asyncio
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

import checkpoint_client as hc
from checkpoint_hub import HubNetworkError, load_settings, save_settings

STATE_FILE = "auto.json"
RETRY_S = 60.0  # cada cuánto se reintenta la cola mientras haya algo pendiente
# Errores de una sincronización que merece la pena reintentar (red caída o hub ocupado)
# Un «abierto» sin evento de cierre (se perdió) deja de contar como juego abierto pasado este tiempo
OPEN_MAX_AGE_S = 12 * 3600.0
RETRY_CODES = {"connection", "hub_busy", "hub_changed", "rate_limited", "upload_incomplete"}


# Estados de una sync local que el hub entiende en el resultado de `opened`/`closed` (lista cerrada del hub)
HUB_STATES = {"uploaded", "downloaded", "up_to_date", "missing_dir", "no_path", "conflict", "error"}
# El hub antiguo no tiene `opened` para dispositivos http: 400/404/405, o 401 (su `opened` solo acepta la clave de usuario)
NO_OPENED_STATUS = {400, 401, 404, 405}


def hub_result(res: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resultado de una sync local para el hub: solo `state` y, en un error, `code`. Nunca rutas, ficheros ni `params`.
    None si el estado no es de los que el hub entiende (p. ej. `disabled`)."""
    state = res.get("state")
    if state not in HUB_STATES:
        return None
    code = res.get("code")
    return {"state": state, **({"code": code} if state == "error" and isinstance(code, str) else {})}


class Notices:
    """Avisos pendientes de mostrar en la Deck (toasts). `take()` los entrega y los vacía; guarda como mucho `maxlen`."""

    def __init__(self, maxlen: int = 20):
        self._lock = threading.Lock()
        self._items: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._next = 1

    def add(self, code: str, game: Optional[str], level: str, **params: Any) -> None:
        with self._lock:
            self._items.append({"id": self._next, "code": code, "game": game, "level": level, "params": params})
            self._next += 1

    def take(self) -> List[Dict[str, Any]]:
        with self._lock:
            out = list(self._items)
            self._items.clear()
        return out


class AutoSync:
    """Lógica bloqueante (corre en un hilo): una llamada a la vez, en el orden de los eventos."""

    def __init__(
        self,
        make_engine: Callable[[], Any],
        state_dir: str,
        notices: Notices,
        log: Callable[[str], None] = lambda _m: None,
    ):
        self._make_engine, self._dir, self._notices, self._log = make_engine, state_dir, notices, log
        self._lock = threading.Lock()
        self._running: Dict[int, float] = {}  # appid -> momento (monotonic) en que se marcó abierto
        s = load_settings(state_dir, STATE_FILE)
        games = s.get("games") if isinstance(s.get("games"), dict) else {}
        self._cache: Dict[int, Dict[str, str]] = {
            int(k): {"id": v["id"], "name": v["name"]}
            for k, v in games.items()
            if str(k).isdigit()
            and isinstance(v, dict)
            and isinstance(v.get("id"), str)
            and isinstance(v.get("name"), str)
        }
        pend = s.get("pending") if isinstance(s.get("pending"), list) else []
        self._pending: Dict[str, str] = {
            p["id"]: p["name"]
            for p in pend
            if isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("name"), str)
        }

    # ---- estado
    def mark(self, appid: int, running: bool) -> None:
        with self._lock:
            if running:
                self._running[appid] = time.monotonic()
            else:
                self._running.pop(appid, None)

    def _expire(self) -> None:
        """(con el cerrojo tomado) Olvida los «abiertos» a los que nunca llegó el cierre."""
        now = time.monotonic()
        for a in [a for a, t in self._running.items() if now - t > OPEN_MAX_AGE_S]:
            del self._running[a]
            self._log(f"auto: appid {a} figuraba abierto hace más de {int(OPEN_MAX_AGE_S // 3600)} h sin evento de cierre; se olvida")

    def is_running(self, appid: int) -> bool:
        with self._lock:
            self._expire()
            return appid in self._running

    def pending(self) -> List[str]:
        with self._lock:
            return list(self._pending)

    def _save(self) -> None:
        with self._lock:
            data = {
                "games": {str(a): g for a, g in self._cache.items()},
                "pending": [{"id": i, "name": n} for i, n in self._pending.items()],
            }
        try:
            save_settings(self._dir, data, STATE_FILE)
        except OSError:
            self._log("auto: no se pudo guardar el estado en disco")

    def _remember(self, games: List[Dict[str, Any]]) -> None:
        cache = {
            g["steam_appid"]: {"id": g["id"], "name": g["name"]}
            for g in games
            if isinstance(g.get("steam_appid"), int) and not isinstance(g.get("steam_appid"), bool)
        }
        if cache != self._cache:
            self._cache = cache
            self._save()

    def _queue(self, game_id: str, name: str) -> None:
        if game_id in self._pending:
            return
        with self._lock:
            self._pending[game_id] = name
        self._save()
        self._notices.add("queued", name, "warning")

    def _dequeue(self, game_id: str) -> None:
        if game_id in self._pending:
            with self._lock:
                self._pending.pop(game_id, None)
            self._save()

    # ---- avisos de un resultado de sincronización
    def _report(self, res: Dict[str, Any], name: str) -> None:
        state = res.get("state")
        if state in ("uploaded", "downloaded"):
            self._notices.add(state, name, "info", files=res.get("files"))
        elif state in ("up_to_date", "no_path", "missing_dir"):
            self._notices.add(state, name, "info")  # siempre se avisa, también «al día»; `disabled` no avisa
        elif state == "conflict":
            self._notices.add("conflict", name, "warning")
        elif state == "error":
            code = res.get("code") or "hub_error"
            if code == "unauthorized":
                self._notices.add("unauthorized", name, "error")
            else:
                self._notices.add("sync_failed", name, "error", reason=code)

    @staticmethod
    def _find(games: List[Dict[str, Any]], appid: int) -> Optional[Dict[str, Any]]:
        return next((g for g in games if g.get("steam_appid") == appid), None)

    # ---- eventos
    def opened(self, appid: int) -> None:
        eng = self._make_engine()
        if eng is None:
            self._log(f"auto: abrir appid {appid}: dispositivo sin vincular; no se hace nada")
            return
        try:
            games = eng.list_games()
        except (hc.HubApiError, HubNetworkError) as e:
            unauthorized = isinstance(e, hc.HubApiError) and e.status == 401
            known = self._cache.get(appid)
            if known:  # solo se avisa de un juego que ya se sabe del hub; el resto de apps de Steam no
                if isinstance(e, hc.HubApiError) and e.status == 401:
                    self._notices.add("unauthorized", known["name"], "error")
                else:
                    self._notices.add("offline_open", known["name"], "warning")
            self._log(f"auto: abrir appid {appid}: sin respuesta del hub ({type(e).__name__})")
            return
        self._remember(games)
        g = self._find(games, appid)
        if g is None:
            self.mark(appid, False)  # no es un juego del hub: al cerrarlo no hay nada que sincronizar
            self._log(f"auto: abrir appid {appid}: sin juego en el hub; no se hace nada")
            return
        if not g.get("enabled", True):
            self.mark(appid, False)
            self._log(f"auto: abrir appid {appid} ({g['id']}): juego desactivado; no se hace nada")
            return
        res = eng.sync_game(g["id"], games)
        self._log(f"auto: abierto appid {appid} ({g['id']}): {res.get('state')} {res.get('code') or ''}".rstrip())
        if res.get("state") == "error" and res.get("code") == "connection":
            self._notices.add("offline_open", g["name"], "warning")
            return
        self._report(res, g["name"])
        self._notify_opened(eng, g["id"], g["name"], res)

    def _notify_opened(self, eng: Any, game_id: str, name: str, res: Dict[str, Any]) -> None:
        """Avisa al hub de la apertura con el resultado de la sync. No crítico: sin toasts, un solo intento, nunca
        bloquea ni encola; el resultado queda en el log."""
        result = hub_result(res)
        if result is None:
            return
        try:
            eng.notify_opened(game_id, result)
        except hc.HubApiError as e:
            unsupported = e.status in NO_OPENED_STATUS and e.code != "err.hook.result_invalid"
            self._log(f"auto: aviso de apertura de {game_id}: {'hub sin soporte' if unsupported else 'error'} ({e.status}); no se reintenta")
            return
        except HubNetworkError as e:
            self._log(f"auto: aviso de apertura de {game_id}: error de red ({type(e).__name__}); no se reintenta")
            return

    def closed(self, appid: int) -> None:
        self.mark(appid, False)
        eng = self._make_engine()
        if eng is None:
            self._log(f"auto: cerrado appid {appid}: dispositivo sin vincular; no se hace nada")
            return
        try:
            games = eng.list_games()
        except (hc.HubApiError, HubNetworkError) as e:
            known = self._cache.get(appid)
            unauthorized = isinstance(e, hc.HubApiError) and e.status == 401
            self._log(f"auto: cerrado appid {appid}: sin respuesta del hub ({type(e).__name__})")
            if known and not unauthorized:
                self._queue(known["id"], known["name"])
            elif known:
                self._notices.add("unauthorized", known["name"], "error")
            return
        self._remember(games)
        g = self._find(games, appid)
        if g is None:
            self._log(f"auto: cerrado appid {appid}: sin juego en el hub; no se hace nada")
            return
        if not g.get("enabled", True):
            self._log(f"auto: cerrado appid {appid} ({g['id']}): juego desactivado; no se hace nada")
            return
        self._finish(eng, g["id"], g["name"], games)

    def _finish(self, eng: Any, game_id: str, name: str, games: Optional[List[Dict[str, Any]]]) -> None:
        """Sube lo que toque y avisa del cierre. Si falla por red o hub ocupado, el cierre queda en la cola."""
        res = eng.sync_game(game_id, games)
        self._log(f"auto: cierre de {game_id}: {res.get('state')} {res.get('code') or ''}".rstrip())
        if res.get("state") == "error" and res.get("code") in RETRY_CODES:
            self._queue(game_id, name)
            return
        self._report(res, name)
        if res.get("state") == "error" and res.get("code") == "unauthorized":
            self._dequeue(game_id)
            return
        try:
            eng.notify_closed(game_id, hub_result(res))
        except HubNetworkError:
            self._queue(game_id, name)
            return
        except hc.HubApiError as e:
            if e.status == 429 or e.status >= 500 or e.status == 409:
                self._queue(game_id, name)
                return
            self._log(f"auto: el hub rechazó el aviso de cierre de {game_id} ({e.status}); no se reintenta")
            self._dequeue(game_id)
            return
        self._dequeue(game_id)

    def retry_pending(self) -> None:
        if not self._pending:
            return
        eng = self._make_engine()
        if eng is None:
            return
        try:
            games = eng.list_games()
        except HubNetworkError:
            return
        except hc.HubApiError as e:
            if e.status == 401:  # la clave ya no vale: reintentar no sirve
                with self._lock:
                    names = list(self._pending.values())
                    self._pending.clear()
                self._save()
                for n in names:
                    self._notices.add("unauthorized", n, "error")
            return
        self._remember(games)
        for gid in list(self._pending):
            g = next((x for x in games if x["id"] == gid), None)
            if g is None or not g.get("enabled", True):
                self._dequeue(gid)  # el juego ya no está en el hub o se desactivó
                continue
            appid = g.get("steam_appid")
            if isinstance(appid, int) and self.is_running(appid):
                continue  # se volvió a abrir: su propio cierre lo resolverá
            self._finish(eng, gid, g["name"], games)


class AutoRunner:
    """Cola de eventos asíncrona: procesa de uno en uno (en un hilo) y reintenta la cola de cierres pendientes."""

    def __init__(self, auto: Any, retry_s: Optional[float] = None, log: Callable[[str], None] = lambda _m: None):
        self._auto, self._log = auto, log
        self._retry_s = RETRY_S if retry_s is None else retry_s
        self._queue: "asyncio.Queue[tuple]" = asyncio.Queue()
        self._task: Optional["asyncio.Task[None]"] = None

    def submit(self, appid: int, running: bool) -> None:
        """Anota ya si el juego está abierto (la sincronización manual lo consulta) y encola el evento."""
        self._auto.mark(appid, running)
        self._queue.put_nowait((appid, running))
        self.start()

    def start(self) -> None:
        """Arranca el procesado (una vez). Se llama al cargar el plugin: la cola de cierres que dejó la Deck apagada se
        reintenta sin esperar a que se abra otro juego."""
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._work())

    async def close(self) -> None:
        t = self._task
        if t is not None and not t.done():
            t.cancel()
            await asyncio.gather(t, return_exceptions=True)

    async def _work(self) -> None:
        while True:
            timeout = self._retry_s if self._auto.pending() else None
            try:
                appid, running = await asyncio.wait_for(self._queue.get(), timeout)
            except asyncio.TimeoutError:
                await self._guard(self._auto.retry_pending)
                continue
            await self._guard(self._auto.opened if running else self._auto.closed, appid)

    async def _guard(self, fn: Callable[..., None], *args: Any) -> None:
        try:
            await asyncio.to_thread(fn, *args)
        except Exception as e:  # un fallo en un evento nunca para la cola
            self._log(f"auto: fallo inesperado ({type(e).__name__})")
