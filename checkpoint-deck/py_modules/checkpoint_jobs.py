"""Tareas de fondo del panel: una sola a la vez, con estado en memoria que la interfaz consulta (como la vinculación).

Tipos: `refresh` (buscar juegos de Steam, enviarlos al hub y listar los del hub y los instalados que aún no tienen juego
en el hub: `unconfigured`), `check` (lista de juegos con su estado), `check_one`,
`sync_game`, `resolve` (resolver un conflicto de datos y sincronizar) y `sync_all`. El trabajo bloqueante corre en un hilo (`asyncio.to_thread`); `close()` lo cancela y espera.
`snapshot()` es lo único que ve la interfaz: nunca lleva claves ni rutas (las carpetas se piden aparte, con `paths()`). Cada juego lleva `last_at` (época de su última sincronización correcta); `sync_all` deja además `plan` y `results` (id -> `{state, code?, files?}`).
"""

import asyncio
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import checkpoint_client as hc
from checkpoint_games import is_tool
from checkpoint_hub import HubNetworkError, describe_error


# Errores de `resolve` que no dejan el juego «en conflicto» (la fila pasa a error como en cualquier sync)
NOT_A_CONFLICT_ANYMORE = frozenset({"unknown_game", "path_forbidden", "unauthorized", "bad_winner"})


class Jobs:
    def __init__(
        self,
        make_engine: Callable[[], Any],
        refresh: Callable[[], Tuple[str, Dict[str, Any]]],
        log: Callable[[str], None] = lambda _m: None,
        library: Callable[[], List[Tuple[int, str]]] = lambda: [],
        shortcuts: Callable[[], Set[int]] = lambda: set(),
        on_synced: Callable[[str, Dict[str, Any]], None] = lambda _g, _r: None,
        last_at: Callable[[str], Optional[Dict[str, Any]]] = lambda _g: None,
    ):
        self._make_engine, self._refresh, self._log, self._library = make_engine, refresh, log, library
        self._on_synced, self._last_at = on_synced, last_at  # sellos de «última sincronización» (los guarda main.py)
        self._shortcuts_of = shortcuts  # appids de la biblioteca que son atajos de Steam (juegos que no son de Steam)
        self._shortcuts: Set[int] = set()
        self._installed: Optional[List[Tuple[int, str]]] = None  # None = aún no se ha buscado en Steam
        self._unconfigured: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._task: Optional["asyncio.Task[None]"] = None
        self._engine: Any = None
        self._games: List[Dict[str, Any]] = []
        self._paths: Dict[str, Optional[str]] = {}
        self._reset_run()

    def _reset_run(self) -> None:
        self._s: Dict[str, Any] = {
            "running": False,
            "kind": None,
            "game": None,
            "phase": None,
            "done": 0,
            "total": 0,
            "index": 0,
            "count": 0,
            "error": None,
            "error_params": {},
            "error_detail": None,
            "summary": None,
            "plan": [],  # sync_all: ids de los juegos que se van a recorrer, en orden
            "results": {},  # sync_all: id -> {state, code?, files?} de lo ya hecho (se conserva hasta la siguiente tarea)
        }

    # ---- lectura
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            out = dict(self._s)
            out["error_params"] = dict(out["error_params"])
            out["plan"] = list(out["plan"])
            out["results"] = {k: dict(v) for k, v in out["results"].items()}
            out["games"] = [dict(g) for g in self._games]
            out["unconfigured"] = [dict(u) for u in self._unconfigured]
        return out

    def paths(self) -> Dict[str, Optional[str]]:
        """id -> carpeta que el usuario configuró en el hub para este dispositivo (None sin ruta). Aparte del `snapshot`."""
        with self._lock:
            return dict(self._paths)

    # ---- arranque
    def start(self, kind: str, game: Optional[str] = None, winner: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if self._s["running"]:
                snap = dict(self._s)
                snap["plan"] = list(snap["plan"])
                snap["results"] = {k: dict(v) for k, v in snap["results"].items()}
                snap["games"] = [dict(g) for g in self._games]
                snap["unconfigured"] = [dict(u) for u in self._unconfigured]
                snap["busy"] = True
                return snap
            self._reset_run()
            self._s.update(running=True, kind=kind, game=game)
        self._task = asyncio.get_running_loop().create_task(self._run(kind, game, winner))
        return self.snapshot()

    async def close(self) -> None:
        """Para `_unload`: cancela el motor y espera a que acabe el hilo."""
        eng = self._engine
        if eng is not None:
            eng.cancel()
        t = self._task
        if t is not None:
            await asyncio.gather(t, return_exceptions=True)

    def cancel(self) -> None:
        eng = self._engine
        if eng is not None:
            eng.cancel()

    # ---- interno
    def _set(self, **kw: Any) -> None:
        with self._lock:
            self._s.update(kw)

    def _progress(self, phase: str, done: int, total: int) -> None:
        self._set(phase=phase, done=done, total=total)

    async def _run(self, kind: str, game: Optional[str], winner: Optional[str] = None) -> None:
        try:
            await asyncio.to_thread(self._work, kind, game, winner)
        except asyncio.CancelledError:
            self.cancel()
            raise
        finally:
            self._engine = None
            self._set(running=False, phase=None)

    def _work(self, kind: str, game: Optional[str], winner: Optional[str] = None) -> None:
        try:
            if kind == "refresh":
                res, data = self._refresh()
                if res == "ok":
                    self._set(summary=data)
                    self._installed = list(self._library())
                    self._shortcuts = set(self._shortcuts_of())
                    eng = self._make_engine()
                    if eng is not None:
                        self._engine = eng
                        self._merge(eng.list_games())
                else:
                    params = dict(data) if isinstance(data, dict) else {}
                    self._set(error=res, error_detail=params.pop("detail", None), error_params=params)
                return
            eng = self._make_engine()
            if eng is None:
                return self._set(error="not_linked")
            self._engine = eng
            games = eng.list_games()
            self._merge(games)
            if kind == "check":
                self._each(eng, games, lambda g, i, n: self._apply(eng.check_game(g["id"], games)))
            elif kind == "check_one":
                self._apply(eng.check_game(game, games))
            elif kind == "sync_game":
                self._set(game=game)
                self._apply(eng.sync_game(game, games, self._progress), synced=True)
            elif kind == "resolve":  # conflicto de datos: `winner` es `hub` o `device` (este equipo)
                self._set(game=game)
                res = eng.resolve_conflict(game, winner, games, self._progress)
                if res.get("state") == "error" and res.get("code") not in NOT_A_CONFLICT_ANYMORE:
                    res = {**res, "state": "conflict"}  # no se pudo resolver: el conflicto sigue y se puede reintentar
                self._apply(res, synced=True)
            elif kind == "sync_all":
                self._each(eng, games, lambda g, i, n: self._sync_one(eng, games, g, i, n))
        except (hc.HubApiError, HubNetworkError) as e:
            detail = describe_error(e)
            self._log(f"tarea {kind}: {detail}")
            self._set(**self._code(e), error_detail=detail)
        except Exception as e:  # un fallo inesperado nunca deja la tarea muda: log y detalle saneados (tipo, mensaje, endpoint)
            detail = describe_error(e)
            self._log(f"tarea {kind}: fallo inesperado, {detail}")
            self._set(error="unexpected", error_detail=detail)

    @staticmethod
    def _code(e: Exception) -> Dict[str, Any]:
        if isinstance(e, HubNetworkError):
            return {"error": "connection"}
        assert isinstance(e, hc.HubApiError)
        if e.status == 401:
            return {"error": "unauthorized"}
        if e.status == 429:
            return {"error": "rate_limited", "error_params": {"wait_s": e.wait_s}}
        return {"error": "hub_error", "error_params": {"code": e.code or str(e.status)}}

    def _each(self, eng: Any, games: List[Dict[str, Any]], fn: Callable[[Dict[str, Any], int, int], None]) -> None:
        n = len(games)
        if self._s["kind"] == "sync_all":
            self._set(plan=[g["id"] for g in games])
        for i, g in enumerate(games):
            if eng.cancelled:
                break
            self._set(game=g["id"], index=i + 1, count=n, phase=None, done=0, total=0)
            fn(g, i, n)
        self._set(game=None)

    def _sync_one(self, eng: Any, games, g, i, n) -> None:
        self._set(phase=None, done=0, total=0)
        self._apply(eng.sync_game(g["id"], games, self._progress), synced=True)

    def _merge(self, games: List[Dict[str, Any]]) -> None:
        with self._lock:
            old = {g["id"]: g for g in self._games}
            self._paths = {g["id"]: g.get("path") if isinstance(g.get("path"), str) else None for g in games}
            self._games = []
            for g in games:
                enabled = g.get("enabled", True) is not False
                state = old.get(g["id"], {}).get("state", "unknown")
                if not enabled:
                    state = "disabled"
                elif state == "disabled":
                    state = "unknown"
                self._games.append(
                    {
                        "id": g["id"],
                        "name": g["name"],
                        "appid": g.get("steam_appid"),
                        "enabled": enabled,
                        "state": state,
                        **({"last_at": st["at"]} if (st := self._last_at(g["id"])) else {}),
                        **{k: old[g["id"]][k] for k in ("code", "params", "last") if g["id"] in old and k in old[g["id"]]},
                    }
                )
            self._recount()

    def _recount(self) -> None:
        """Instalados en la Deck sin juego en el hub (se llama con el cerrojo tomado). Las herramientas de Steam
        (Proton, runtimes) no cuentan. Vacío mientras no se haya buscado en Steam."""
        if self._installed is None:
            return
        used = {g["appid"] for g in self._games if g.get("appid")}
        self._unconfigured = [
            {"appid": a, "name": n, **({"source": "shortcut"} if a in self._shortcuts else {})}
            for a, n in self._installed
            if a not in used and not is_tool(n)
        ]

    # ---- cambios que hace la interfaz (el hub ya los aceptó)
    def set_enabled_row(self, game: str, enabled: bool) -> None:
        with self._lock:
            e = next((g for g in self._games if g["id"] == game), None)
            if e is None:
                return
            e["enabled"] = enabled
            e["state"] = "disabled" if not enabled else ("unknown" if e["state"] == "disabled" else e["state"])

    def add_game(self, game: Dict[str, Any]) -> None:
        """Un juego recién creado en el hub: pasa de «sin configurar» a la lista. Sin ruta (no sale del plugin)."""
        with self._lock:
            if isinstance(game.get("path"), str):
                self._paths[game["id"]] = game["path"]
            if all(g["id"] != game["id"] for g in self._games):
                on = game.get("enabled") is not False  # un juego del hub desactivado al que nos unimos sigue desactivado
                self._games.append(
                    {
                        "id": game["id"],
                        "name": game["name"],
                        "appid": game.get("appid"),
                        "enabled": on,
                        "state": "unknown" if on else "disabled",
                    }
                )
            self._recount()

    def _apply(self, res: Dict[str, Any], synced: bool = False) -> None:
        gid = res.get("game")
        if synced:
            try:
                self._on_synced(gid, res)
            except Exception:  # noqa: BLE001  (el sello es accesorio: nunca rompe la tarea)
                self._log("tarea: no se pudo guardar la hora de sincronización")
        with self._lock:
            if synced and self._s["kind"] == "sync_all" and isinstance(gid, str):
                self._s["results"][gid] = {k: v for k, v in res.items() if k in ("state", "code", "files")}
            e = next((g for g in self._games if g["id"] == gid), None)
            if e is None:
                return
            if synced and (st := self._last_at(gid)):
                e["last_at"] = st["at"]
            for k in ("code", "params"):
                e.pop(k, None)
            state = res["state"]
            if synced:
                e["last"] = {k: v for k, v in res.items() if k not in ("game", "params")}
                if state in ("uploaded", "downloaded"):
                    state = "up_to_date"
            e["state"] = state
            for k in ("code", "params"):
                if k in res:
                    e[k] = res[k]
