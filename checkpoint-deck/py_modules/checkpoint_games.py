"""Juegos desde el plugin: sugerir la ruta de los saves, crear un juego en el hub y activar o desactivar uno.

Solo biblioteca estándar. La ruta se sugiere SOLO con lo que existe en el disco de la Deck (la carpeta del juego dentro
del prefijo de Proton y la carpeta de Steam Cloud); si no hay nada, la ruta queda vacía y la pide la interfaz. Nada se
adivina ni se crea. Errores del hub: `describe_failure` (sin claves ni URL).
"""

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import checkpoint_client as hc
import checkpoint_lutris
import checkpoint_shortcuts
import checkpoint_steam
from checkpoint_hub import HubNetworkError, describe_error
from checkpoint_sync import PathNotAllowed, validate_game_path

# Mismos caracteres que acepta el hub en una ruta (`PATH_CHARS_RE` de config/models.py): una sugerencia que el hub
# rechazaría no se ofrece.
_HUB_PATH = re.compile(r"^[\w .\-/()\[\]+,@~=#{}]+$")
_TOOLS = ("proton", "steam linux runtime", "steamworks common", "steamvr")
# Subcarpetas del usuario de Proton donde los juegos de Windows suelen guardar (por orden de preferencia)
_PROTON_DIRS = ("AppData/Roaming", "AppData/Local", "AppData/LocalLow", "Documents/My Games", "Saved Games", "Documents")
_PFX = "pfx/drive_c/users/steamuser"
MAX_CANDIDATES = 5
_MARKS = str.maketrans("", "", "™®©℠")


def is_tool(name: str) -> bool:
    """Herramientas de Steam que no son juegos (Proton, runtimes...): se ocultan de «sin configurar»."""
    n = name.strip().casefold()
    return any(n == t or n.startswith(t + " ") for t in _TOOLS)


def _isdir(p: Path) -> bool:
    try:
        return p.is_dir()
    except OSError:
        return False


def find_game(home: Path, appid: int) -> Optional[Dict[str, Any]]:
    """Dónde está instalado el juego: `{steamapps, installdir, root}` (o None si no está en ninguna biblioteca)."""
    for root in checkpoint_steam.find_steam_roots(Path(home)):
        for d in checkpoint_steam.library_dirs(root):
            data = checkpoint_steam._read(d / f"appmanifest_{int(appid)}.acf")
            state = data.get("appstate") if data else None
            if isinstance(state, dict):
                inst = state.get("installdir")
                return {"steamapps": d, "root": root, "installdir": inst if isinstance(inst, str) and inst else None}
    return None


def _names(name: str, installdir: Optional[str]) -> List[str]:
    out: List[str] = []
    for n in (name, name.translate(_MARKS).strip(), installdir or ""):
        if n and "/" not in n and n not in (".", "..") and n not in out:
            out.append(n)
    return out


def suggest_path(home: Path, appid: int, name: str) -> Dict[str, Any]:
    """`{path, candidates, source}`: carpetas de saves que EXISTEN. `source`: proton | cloud | "" (nada detectado)."""
    empty: Dict[str, Any] = {"path": "", "candidates": [], "source": ""}
    found = find_game(home, appid)
    if found is None:
        return empty
    cands: List[tuple] = []
    pfx = found["steamapps"] / "compatdata" / str(int(appid)) / _PFX
    names = _names(name, found["installdir"])
    for sub in _PROTON_DIRS:
        for n in names:
            cands.append((pfx / sub / n, "proton"))
    userdata = found["root"] / "userdata"
    try:
        users = sorted(x for x in userdata.iterdir() if x.name.isdigit())
    except OSError:
        users = []
    for u in users:
        cands.append((u / str(int(appid)) / "remote", "cloud"))
    out: List[tuple] = []
    for p, src in cands:
        s = str(p)
        if _isdir(p) and _HUB_PATH.match(s.lstrip("/")) and all(s != o[0] for o in out):
            out.append((s, src))
    out = out[:MAX_CANDIDATES]
    if not out:
        return empty
    return {"path": out[0][0], "candidates": [o[0] for o in out], "source": out[0][1]}


def suggest_shortcut(
    home: Path,
    appid: int,
    protected: Sequence[Path] = (),
    log: Callable[[str], None] = lambda _m: None,
    name: str = "",
) -> Dict[str, Any]:
    """Como `suggest_path`, para un atajo de Steam (juego que no es de Steam): si lanza un juego de Lutris
    (`lutris:rungameid/N` en sus `LaunchOptions`) devuelve `source` = "lutris", `candidates` (carpetas que existen en su
    prefijo, ver `checkpoint_lutris.find_saves`), `path` = la primera ("" si no hay: nada se inventa; el prefijo entero ya no
    se sugiere) y `browse_start` = dónde abrir «Examinar…» (`<prefijo>/drive_c/users`, o el prefijo). Cualquier otro atajo
    (emuladores, Epic...) queda sin sugerencia. Solo lectura."""
    empty: Dict[str, Any] = {"path": "", "candidates": [], "source": ""}
    for root in checkpoint_steam.find_steam_roots(Path(home)):
        opts = checkpoint_shortcuts.find_launch_options(root, appid)
        if opts is None:
            continue
        found = checkpoint_lutris.find_saves(
            home, opts, protected, log, accept=lambda s: bool(_HUB_PATH.match(s.lstrip("/"))), name=name
        )
        if not found["prefix"]:
            return empty
        cands = found["candidates"]
        return {
            "path": cands[0] if cands else "",
            "candidates": cands,
            "source": "lutris",
            "browse_start": found["browse_start"],
        }
    return empty


def describe_failure(e: Exception) -> Dict[str, Any]:
    """Fallo de una llamada al hub como dict para la interfaz: `{ok: False, error, error_params, error_detail}`."""
    detail = describe_error(e)
    if isinstance(e, HubNetworkError):
        return {"ok": False, "error": "connection", "error_params": {}, "error_detail": detail}
    assert isinstance(e, hc.HubApiError)
    params: Dict[str, Any] = {}
    if e.status == 401:
        code = "unauthorized"
    elif e.status == 429:
        code, params = "rate_limited", {"wait_s": e.wait_s}
    elif e.code == "err.steam.game_invalid":
        code = "game_invalid"
        params = {k: v for k, v in e.params.items() if k in ("field", "reason") and isinstance(v, str)}
    elif e.code == "err.steam.game_unknown":
        code = "unknown_game"
    elif e.code == "err.main.config_changed":
        code = "config_changed"
    else:
        code, params = "hub_error", {"code": e.code or str(e.status)}
    return {"ok": False, "error": code, "error_params": params, "error_detail": detail}


class GameTools:
    """Llamadas bloqueantes (corren en un hilo) para crear y activar juegos con la key del dispositivo."""

    def __init__(
        self,
        hub: str,
        key: str,
        *,
        home: Path,
        protected: Sequence[Path] = (),
        log: Callable[[str], None] = lambda _m: None,
    ):
        self._client = hc.HubClient(hub, key)
        self._home, self._protected, self._log = Path(home), list(protected), log

    def create(self, appid: int, name: str, path: str) -> Dict[str, Any]:
        try:
            validate_game_path(path, self._home, self._protected)  # la misma regla que usará la sincronización
        except PathNotAllowed:
            return {"ok": False, "error": "path_forbidden", "error_params": {}, "error_detail": None}
        try:
            game = self._client.create_game(appid, name, path)
        except (hc.HubApiError, HubNetworkError) as e:
            out = describe_failure(e)
            self._log(f"crear juego: {out['error_detail']}")
            return out
        return {"ok": True, "game": game}

    def set_enabled(self, game: str, enabled: bool) -> Dict[str, Any]:
        try:
            out = self._client.set_game_enabled(game, enabled)
        except (hc.HubApiError, HubNetworkError) as e:
            res = describe_failure(e)
            self._log(f"activar o desactivar juego: {res['error_detail']}")
            return res
        return {"ok": True, "game": game, "enabled": out["enabled"]}
