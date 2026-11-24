"""CLI de checkpoint-client: link, unlink, games, sync, run, watch y status.

Códigos de salida (como `backend/app/cli.py`): 0 correcto, 1 error, 2 uso, 3 conflicto. Los errores van a stderr y todo
texto visible sale de `texts`. Nunca se imprime ni se registra la clave (`redact`).
"""

import argparse
import os
import subprocess
import sys
import traceback
from typing import Any, Dict, List, Optional, Tuple

from checkpoint_core.names import DeviceNameError, normalize_device_name
from checkpoint_core.redaction import redact
from checkpoint_core.urls import HubUrlError, normalize_hub_url

from . import PROTOCOL, __version__, hub, locks, settings, texts, watcher
from .hubclient import HubApiError
from .hub import HubNetworkError
from .sync import SyncEngine, hub_result

OK, ERROR, USAGE, CONFLICT = 0, 1, 2, 3
SKIPPED = ("no_path", "disabled", "missing_dir")
LOG_FILE = "checkpoint-client.log"


_DETECTOR = watcher.ProcessDetector()  # con psutil real; los tests lo sustituyen


def is_running(game: str) -> bool:
    """¿Está abierto el juego `game` (id del hub)? Mira el `process` que el hub dio en el último `GET /api/games`
    (lo registra `_games`); un juego sin proceso o desconocido cuenta como cerrado."""
    return _DETECTOR.is_running(game)


def _lock_dir() -> str:
    return os.path.join(settings.config_dir(), "locks")


class _Exit(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _out(text: str) -> None:
    print(text, flush=True)


def _err(text: str) -> None:
    print(redact(text), file=sys.stderr, flush=True)


def _fail(text: str, code: int = ERROR) -> "_Exit":
    _err(text)
    return _Exit(code)


# ---------------------------------------------------------------- parser
def _resolve_value(raw: str) -> str:
    if raw not in ("hub", "device"):
        raise argparse.ArgumentTypeError(texts.ERR_BAD_RESOLVE)
    return raw


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="checkpoint-client", description=texts.HELP_ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    link = sub.add_parser("link", help=texts.HELP_LINK, description=texts.HELP_LINK)
    link.add_argument("hub", nargs="?", default=None, help=texts.HELP_LINK_HUB)
    link.add_argument("--name", default=None, help=texts.HELP_LINK_NAME)
    link.add_argument("--force", action="store_true")
    sub.add_parser("unlink", help=texts.HELP_UNLINK, description=texts.HELP_UNLINK)
    games = sub.add_parser("games", help=texts.HELP_GAMES, description=texts.HELP_GAMES)
    games.add_argument("--check", action="store_true", help=texts.HELP_GAMES_CHECK)
    sync = sub.add_parser("sync", help=texts.HELP_SYNC, description=texts.HELP_SYNC)
    sync.add_argument("game", nargs="?", default=None)
    sync.add_argument("--all", action="store_true")
    sync.add_argument("--dry-run", action="store_true", help=texts.HELP_SYNC_DRY_RUN)
    sync.add_argument(
        "--resolve", type=_resolve_value, default=None, metavar="hub|device", help=texts.HELP_SYNC_RESOLVE
    )
    run = sub.add_parser("run", help=texts.HELP_RUN, description=texts.HELP_RUN)
    run.add_argument("game")
    run.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("watch", help=texts.HELP_WATCH, description=texts.HELP_WATCH)
    sub.add_parser("status", help=texts.HELP_STATUS, description=texts.HELP_STATUS)
    return ap


# ---------------------------------------------------------------- contexto: vinculación y conexión
class _Ctx:
    def __init__(self, hub_url: str, key: str, device: Optional[str]):
        self.hub, self.key, self.device = hub_url, key, device
        self.engine = SyncEngine(
            hub_url, key, home=None, protected=[settings.config_dir()], is_running=lambda g: is_running(g)
        )


def _linked() -> Tuple[str, str, Optional[str]]:
    found = settings.linked(settings.load_settings(settings.config_dir()))
    if found is None:
        raise _fail(texts.ERR_NOT_LINKED)
    return found


def _check(hub_url: str, key: str) -> Dict[str, Any]:
    """Ping al hub: devuelve sus datos o termina con el error que toque. Un hub antiguo solo avisa."""
    res, data = hub.check_connection(hub_url, key, PROTOCOL)
    if res == "unauthorized":
        raise _fail(texts.ERR_UNAUTHORIZED)
    if res == "connection":
        raise _fail(texts.ERR_CONNECTION.format(url=hub_url))
    if res == "rate_limited":
        raise _fail(texts.ERR_RATE_LIMITED.format(s=data.get("wait_s", 0)))
    if res != "ok":
        raise _fail(texts.ERR_HUB_ERROR)
    if data["compat"] == "plugin_outdated":
        raise _fail(texts.ERR_CLIENT_OUTDATED.format(min=data["min_plugin_protocol"], n=PROTOCOL))
    if data["compat"] == "hub_old":
        _err(texts.ERR_HUB_OLD)
    return data


def _connect() -> _Ctx:
    hub_url, key, device = _linked()
    _check(hub_url, key)
    return _Ctx(hub_url, key, device)


def _games(ctx: _Ctx) -> List[Dict[str, Any]]:
    try:
        games = ctx.engine.list_games()
        _DETECTOR.set_games(games)
        return games
    except (HubApiError, HubNetworkError) as e:
        res = ctx.engine._error(e)  # noqa: SLF001  (misma traducción de errores que el motor)
        raise _fail(_error_text(res, ctx, None)) from None


def _find(games: List[Dict[str, Any]], ident: str) -> Optional[Dict[str, Any]]:
    for g in games:
        if g["id"] == ident:
            return g
    named = [g for g in games if g["name"] == ident]
    return named[0] if len(named) == 1 else None


# ---------------------------------------------------------------- resultados
def _error_text(res: Dict[str, Any], ctx: _Ctx, game: Optional[Dict[str, Any]]) -> str:
    code, params = res.get("code"), res.get("params") or {}
    if code == "path_forbidden":
        return texts.ERR_PATH_FORBIDDEN.format(path=(game or {}).get("path") or "")
    if code == "rate_limited":
        return texts.ERR_RATE_LIMITED.format(s=params.get("wait_s", 0))
    if code == "connection":
        return texts.ERR_CONNECTION.format(url=ctx.hub)
    if code == "unauthorized":
        return texts.ERR_UNAUTHORIZED
    if code == "game_running":
        return texts.SYNC_RUNNING.format(game=(game or {}).get("name") or "")
    if code in texts.SYNC_ERRORS:
        return texts.SYNC_ERRORS[str(code)]
    return texts.ERR_HUB_ERROR


def _report(res: Dict[str, Any], ctx: _Ctx, game: Dict[str, Any], item: Optional[Tuple[int, int]] = None) -> int:
    """Escribe el resultado de un juego y devuelve OK, ERROR o CONFLICT. `item` = (i, n) con `sync --all`."""
    name, state = game["name"], res.get("state")

    def wrap(text: str) -> str:
        return texts.SYNC_ITEM.format(i=item[0], n=item[1], name=name, message=text) if item else text

    n = res.get("files", 0)
    if state == "uploaded":
        _out(wrap(texts.SYNC_UPLOADED.format(game=name, n=n)))
    elif state == "downloaded":
        _out(wrap(texts.SYNC_DOWNLOADED.format(game=name, n=n, path=game["path"])))
    elif state == "up_to_date":
        _out(wrap(texts.SYNC_UP_TO_DATE.format(game=name)))
    elif state == "upload":
        _out(wrap(texts.CHECK_UPLOAD.format(game=name)))
    elif state == "download":
        _out(wrap(texts.CHECK_DOWNLOAD.format(game=name)))
    elif state == "no_path":
        _out(wrap(texts.SYNC_NO_PATH.format(game=name)))
    elif state == "disabled":
        _out(wrap(texts.SYNC_DISABLED.format(game=name)))
    elif state == "missing_dir":
        _out(wrap(texts.SYNC_MISSING_DIR.format(game=name)))
    elif state == "conflict":
        _err(wrap(texts.SYNC_CONFLICT.format(game=name)))
        _err(texts.SYNC_CONFLICT_HOW.format(game=name))
        if res.get("code") == "resolution_stale":
            _err(texts.SYNC_ERRORS["resolution_stale"])
        return CONFLICT
    else:
        _err(wrap(_error_text(res, ctx, game)))
        return ERROR
    return OK


def _sync_locked(
    ctx: _Ctx, g: Dict[str, Any], games: List[Dict[str, Any]], resolve: Optional[str] = None
) -> Dict[str, Any]:
    """`sync_game` (o `resolve_conflict`) con el lock del juego: si otro proceso del cliente lo tiene, error `busy`."""
    try:
        with locks.exclusive(_lock_dir(), locks.game_name(g["id"])):
            if resolve:
                return ctx.engine.resolve_conflict(g["id"], resolve, games, _progress(g["name"]))
            return ctx.engine.sync_game(g["id"], games, _progress(g["name"]))
    except locks.Busy:
        return {"state": "error", "code": "busy"}


def _progress(name: str):
    def cb(phase: str, i: int, total: int) -> None:
        if i == 0 and phase == "upload":
            _out(texts.SYNC_UPLOADING.format(game=name, n=total))
        elif i == 0 and phase == "download":
            _out(texts.SYNC_DOWNLOADING.format(game=name, n=total))

    return cb


# ---------------------------------------------------------------- comandos
def cmd_link(a: argparse.Namespace) -> int:
    cfg = settings.config_dir()
    s = settings.load_settings(cfg)
    found = settings.linked(s)
    if found and not a.force:
        raise _fail(texts.LINK_ALREADY.format(device=found[2] or ""))
    try:
        url = normalize_hub_url(a.hub if a.hub is not None else s.get("hub_url"))
    except HubUrlError:
        raise _fail(texts.LINK_BAD_URL, USAGE) from None
    try:
        name = normalize_device_name(a.name) if a.name is not None else hub.default_device_name()
    except DeviceNameError:
        raise _fail(texts.ERR_NAME_INVALID, USAGE) from None

    def show_code(code: str) -> None:
        _out(texts.LINK_CODE.format(code=texts.spaced_code(code)))
        _out(texts.LINK_WAITING)

    try:
        device, key = hub.pair(url, name, on_code=show_code, poll_s=hub.POLL_S)
    except hub.PairingError as e:
        raise _fail(_pairing_text(e, url)) from None
    s.update({"hub_url": url, "device": device, "key": key, "device_name": name})
    settings.save_settings(cfg, s)
    _out(texts.LINK_DONE.format(device=device, where="fichero"))
    return OK


def _pairing_text(e: "hub.PairingError", url: str) -> str:
    if e.code == "rejected":
        return texts.LINK_REJECTED
    if e.code == "expired":
        return texts.LINK_EXPIRED
    if e.code == "connection":
        return texts.ERR_CONNECTION.format(url=url)
    if e.code in ("rate_limited", "busy"):
        return texts.ERR_RATE_LIMITED.format(s=e.wait_s)
    if e.code == "name_invalid":
        return texts.ERR_NAME_INVALID
    return texts.ERR_HUB_ERROR


def cmd_unlink(a: argparse.Namespace) -> int:
    _linked()
    cfg = settings.config_dir()
    s = settings.load_settings(cfg)
    for k in ("key", "device"):
        s.pop(k, None)
    settings.save_settings(cfg, s)
    return OK


def cmd_games(a: argparse.Namespace) -> int:
    ctx = _connect()
    games = _games(ctx)
    if not games:
        _out(texts.SYNC_NO_GAMES)
        return OK
    code = OK
    for g in games:
        if a.check:
            res = ctx.engine.check_game(g["id"], games)
            code = max(code, _worst(_report(res, ctx, g), code))
        else:
            st = g.get("status")
            result = st.get("result") if isinstance(st, dict) and isinstance(st.get("result"), str) else "-"
            _out("\t".join([g["id"], g["name"], g["path"] or "", result]))
    return code


def _worst(kind: int, current: int) -> int:
    """Errores primero (1), luego conflictos (3), luego correcto (0)."""
    order = {OK: 0, CONFLICT: 1, ERROR: 2}
    return kind if order[kind] > order[current] else current


def cmd_sync(a: argparse.Namespace) -> int:
    if a.all == bool(a.game) or (a.all and a.resolve):
        raise _fail(texts.ERR_NEED_GAME, USAGE)
    ctx = _connect()
    games = _games(ctx)
    if a.all:
        return _sync_all(ctx, games, a.dry_run)
    g = _find(games, a.game)
    if g is None:
        raise _fail(texts.SYNC_ERRORS["unknown_game"])
    if a.dry_run:
        return _report(ctx.engine.check_game(g["id"], games), ctx, g)
    return _report(_sync_locked(ctx, g, games, a.resolve), ctx, g)


def _sync_all(ctx: _Ctx, games: List[Dict[str, Any]], dry_run: bool) -> int:
    if not games:
        _out(texts.SYNC_NO_GAMES)
        return OK
    ok = conflicts = errors = 0
    code = OK
    for i, g in enumerate(games, 1):
        if dry_run:
            res = ctx.engine.check_game(g["id"], games)
        else:
            res = _sync_locked(ctx, g, games)
        kind = _report(res, ctx, g, (i, len(games)))
        code = _worst(kind, code)
        ok, conflicts, errors = ok + (kind == OK), conflicts + (kind == CONFLICT), errors + (kind == ERROR)
    _out(texts.SYNC_SUMMARY.format(ok=ok, c=conflicts, e=errors))
    return code


def launch(command: List[str]) -> int:
    """Lanza el comando SIN shell, hereda la terminal y espera a que acabe. Ctrl+C no corta la espera: el hijo (mismo
    grupo de procesos) lo recibe y es él quien decide; así el guardado se sube siempre al cerrarlo."""
    proc = subprocess.Popen(command)
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            continue


def _notify(ctx: _Ctx, kind: str, game: str, res: Dict[str, Any]) -> None:
    """Avisa al hub de que el juego se abrió o cerró. No crítico: un fallo no cambia nada."""
    try:
        (ctx.engine.notify_opened if kind == "opened" else ctx.engine.notify_closed)(game, hub_result(res))
    except (HubApiError, HubNetworkError):
        pass


def cmd_run(a: argparse.Namespace) -> int:
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not command:
        raise _fail(texts.ERR_RUN_NO_COMMAND, USAGE)
    ctx = _connect()
    games = _games(ctx)
    g = _find(games, a.game)
    if g is None:
        raise _fail(texts.SYNC_ERRORS["unknown_game"])
    try:
        # mientras se juega el lock es de `run`: el vigilante no toca este juego
        with locks.exclusive(_lock_dir(), locks.game_name(g["id"])):
            return _run_game(ctx, g, games, command)
    except locks.Busy:
        raise _fail(texts.SYNC_ERRORS["busy"]) from None


def _run_game(ctx: _Ctx, g: Dict[str, Any], games: List[Dict[str, Any]], command: List[str]) -> int:
    res = ctx.engine.sync_game(g["id"], games, _progress(g["name"]))
    if res.get("state") in ("no_path", "disabled"):  # nada que sincronizar: no se lanza el juego a ciegas
        raise _fail((texts.SYNC_NO_PATH if res["state"] == "no_path" else texts.SYNC_DISABLED).format(game=g["name"]))
    kind = _report(res, ctx, g) if res.get("state") != "missing_dir" else OK
    if kind != OK:
        raise _Exit(kind)
    _notify(ctx, "opened", g["id"], res)
    try:
        launch(command)
    except OSError as e:
        _notify(ctx, "closed", g["id"], {"state": "up_to_date"})
        raise _fail(texts.ERR_RUN_LAUNCH.format(reason=e.strerror or type(e).__name__)) from None
    res = ctx.engine.sync_game(g["id"], _games(ctx), _progress(g["name"]))
    kind = _report(res, ctx, g)
    _notify(ctx, "closed", g["id"], res)
    return kind


def _log_line(message: str) -> None:
    """Línea del vigilante en el log del cliente (0600), con claves redactadas. Nunca rutas ni ficheros."""
    try:
        cfg = settings.config_dir()
        os.makedirs(cfg, mode=0o700, exist_ok=True)
        fd = os.open(os.path.join(cfg, LOG_FILE), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(redact(message) + "\n")
    except OSError:
        pass


def cmd_watch(a: argparse.Namespace) -> int:
    ctx = _connect()
    _games(ctx)  # falla pronto si el hub no deja ver los juegos
    try:
        with locks.exclusive(_lock_dir(), locks.WATCH):  # un solo vigilante por equipo
            w = watcher.Watcher(
                ctx.engine,
                _DETECTOR,
                settings.config_dir(),
                report=lambda res, g: _report(res, ctx, g),
                out=_out,
                err=_err,
                log=_log_line,
            )
            w.start()
            try:
                w.run()
            except KeyboardInterrupt:
                pass
    except locks.Busy:
        raise _fail(texts.WATCH_RUNNING) from None
    _out(texts.WATCH_STOPPED)
    return OK


def cmd_status(a: argparse.Namespace) -> int:
    def line(key: str, value: str) -> None:
        _out(texts.STATUS_LINE.format(key=texts.STATUS_KEYS[key], value=value))

    code = OK
    try:
        hub_url, key, device = _linked()
        line("hub", hub_url)
        if device:
            line("device", device)
        data = _check(hub_url, key)
        line("connection", texts.STATUS_OK)
        if data.get("protocol") is not None:
            line("protocol", str(data["protocol"]))
    except _Exit as e:
        code = e.code
    line("version", __version__)
    return code


COMMANDS = {
    "link": cmd_link,
    "unlink": cmd_unlink,
    "games": cmd_games,
    "sync": cmd_sync,
    "run": cmd_run,
    "watch": cmd_watch,
    "status": cmd_status,
}


def _log_unexpected() -> str:
    """Guarda el fallo (con claves redactadas) en el log del cliente (0600) y devuelve su ruta."""
    cfg = settings.config_dir()
    os.makedirs(cfg, mode=0o700, exist_ok=True)
    path = os.path.join(cfg, LOG_FILE)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(redact(traceback.format_exc()) + "\n")
    return path


def main(argv: Optional[List[str]] = None) -> int:
    ap = build_parser()
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:  # argparse: --help (0) o error de uso (2)
        return e.code if isinstance(e.code, int) else (OK if e.code is None else USAGE)
    try:
        return COMMANDS[a.cmd](a)
    except _Exit as e:
        return e.code
    except KeyboardInterrupt:
        return ERROR
    except Exception:  # noqa: BLE001  (nada de trazas con datos del usuario en pantalla: van al log, redactadas)
        try:
            _err(texts.ERR_UNEXPECTED.format(log=_log_unexpected()))
        except OSError:
            _err(texts.ERR_UNEXPECTED.format(log=settings.config_dir()))
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
