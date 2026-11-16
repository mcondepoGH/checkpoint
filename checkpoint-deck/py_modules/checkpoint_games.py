"""Juegos desde el plugin: sugerir la ruta de los saves, crear un juego en el hub y activar o desactivar uno.

Solo biblioteca estándar. La ruta se sugiere SOLO con lo que existe en el disco de la Deck (la carpeta del juego dentro
del prefijo de Proton y la carpeta de Steam Cloud); si no hay nada, la ruta queda vacía y la pide la interfaz. Nada se
adivina ni se crea. Errores del hub: `describe_failure` (sin claves ni URL).
"""

import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import checkpoint_client as hc
import checkpoint_lutris
import checkpoint_shortcuts
import checkpoint_steam
from checkpoint_hub import HubNetworkError, describe_error
from checkpoint_sync import PathNotAllowed, validate_game_path, verified_dir

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


def _accept(s: str) -> bool:
    """Filtro del hub: una sugerencia con caracteres que el hub rechazaría no se ofrece."""
    return bool(_HUB_PATH.match(s.lstrip("/")))


def _is_real_dir(p: str) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(p).st_mode)
    except OSError:
        return False


def _nearest_existing(path: str, home: Path, protected: Sequence[Path], roots: Sequence[Any]) -> str:
    """El ancestro existente más profundo de `path` que pasa `verified_dir` (donde abrir «Examinar…»), o ""."""
    cur = os.path.dirname(path)
    while cur and cur != "/":
        ok = verified_dir(cur, home, protected, _accept, roots)
        if ok:
            return ok
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return ""


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


def suggest_path(home: Path, appid: int, name: str, protected: Sequence[Path] = ()) -> Dict[str, Any]:
    """`{path, candidates, source}`: carpetas de saves que EXISTEN y pasan `verified_dir` en este momento. `source`: proton |
    cloud | "" (nada detectado). Sin candidatos, si la ruta «natural» aún no existe (prefijo de Proton o `remote` de Steam
    Cloud), añade `browse_start`: su ancestro existente más profundo y validado, donde abrir «Examinar…»; nada se crea."""
    empty: Dict[str, Any] = {"path": "", "candidates": [], "source": ""}
    found = find_game(home, appid)
    if found is None:
        return empty
    # Los prefijos se construyen sobre la ruta real de la biblioteca (`~/.steam/steam` es un enlace): `verified_dir` exige
    # rutas sin enlaces. La tarjeta SD queda fuera del home, así que su biblioteca y la raíz de Steam son raíces permitidas.
    steamapps = os.path.realpath(found["steamapps"])
    root = os.path.realpath(found["root"])
    roots = [root, steamapps]
    compat = Path(steamapps) / "compatdata" / str(int(appid))
    pfx = compat / _PFX
    names = _names(name, found["installdir"])
    cands: List[tuple] = []
    for sub in _PROTON_DIRS:
        for n in names:
            cands.append((pfx / sub / n, "proton"))
    userdata = Path(root) / "userdata"
    try:
        users = sorted(x for x in userdata.iterdir() if x.name.isdigit())
    except OSError:
        users = []
    for u in users:
        cands.append((u / str(int(appid)) / "remote", "cloud"))
    out: List[tuple] = []
    for p, src in cands:  # la comprobación va aquí, justo antes de devolver
        s = verified_dir(str(p), home, protected, _accept, roots)
        if s and all(s != o[0] for o in out):
            out.append((s, src))
    out = out[:MAX_CANDIDATES]
    if out:
        return {"path": out[0][0], "candidates": [o[0] for o in out], "source": out[0][1]}
    natural = None  # ruta esperada que aún no existe
    if verified_dir(str(compat), home, protected, _accept, roots):
        natural = pfx / "AppData/Roaming" / (names[0] if names else "")
    elif users:
        natural = users[0] / str(int(appid)) / "remote"
    if natural is not None:
        start = _nearest_existing(str(natural), home, protected, roots)
        if start:
            return {**empty, "browse_start": start}
    return empty


def _recheck(found: Dict[str, Any], home: Path, protected: Sequence[Path]) -> Dict[str, Any]:
    """Última comprobación de una sugerencia de Lutris, justo antes de devolverla: cada candidato (y `browse_start`) se vuelve a
    verificar, porque entre el recorrido y la respuesta una carpeta puede haber desaparecido. `path` = el primer candidato que
    queda. Si `browse_start` ya no vale, se sube al ancestro existente."""
    cands = [c for c in found["candidates"] if verified_dir(c, home, protected, _accept)]
    start = found.get("browse_start", "")
    if start and not verified_dir(start, home, protected, _accept):
        start = _nearest_existing(start, home, protected, ())
    return {**found, "path": cands[0] if cands else "", "candidates": cands, "browse_start": start}


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
    se sugiere) y `browse_start` = dónde abrir «Examinar…» (`<prefijo>/drive_c/users`, o el prefijo). Todo se vuelve a
    verificar (`verified_dir`) justo antes de devolverlo. Cualquier otro atajo (emuladores, Epic...) queda sin sugerencia.
    Solo lectura."""
    empty: Dict[str, Any] = {"path": "", "candidates": [], "source": ""}
    for root in checkpoint_steam.find_steam_roots(Path(home)):
        opts = checkpoint_shortcuts.find_launch_options(root, appid)
        if opts is None:
            continue
        found = checkpoint_lutris.find_saves(home, opts, protected, log, accept=_accept, name=name)
        if not found["prefix"]:
            return empty
        cands = found["candidates"]
        return _recheck(
            {"path": cands[0] if cands else "", "candidates": cands, "source": "lutris", "browse_start": found["browse_start"]},
            Path(home),
            protected,
        )
    return empty


def verify_applied(path: Any, home: Path, protected: Sequence[Path] = ()) -> Optional[str]:
    """Ruta que el usuario confirmó de una sugerencia del manifiesto, vuelta a verificar al aplicarla (`verified_dir`, con las
    bibliotecas de Steam como raíces permitidas: tarjeta SD). None si ya no vale. Solo lectura."""
    roots: List[str] = []
    try:
        for root in checkpoint_steam.find_steam_roots(Path(home)):
            roots.append(os.path.realpath(root))
            roots.extend(os.path.realpath(d) for d in checkpoint_steam.library_dirs(root))
    except OSError:
        pass
    return verified_dir(path, home, protected, _accept, roots)


def lutris_shortcut_appid(home: Path, row_id: int, shortcut_appids: Sequence[int]) -> Optional[int]:
    """Appid del atajo de Steam (de `shortcut_appids`) cuyas `LaunchOptions` son `lutris:rungameid/<row_id>`, o None."""
    for appid in shortcut_appids:
        for root in checkpoint_steam.find_steam_roots(Path(home)):
            opts = checkpoint_shortcuts.find_launch_options(root, appid)
            if opts is not None and checkpoint_lutris.parse_game_id(opts) == row_id:
                return appid
    return None


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
        """La carpeta de guardado debe EXISTIR y ser una carpeta (sea sugerida, escrita o elegida con Examinar…); si no, se rechaza
        (`path_missing`) sin llamar al hub ni crear nada."""
        try:
            real = validate_game_path(path, self._home, self._protected)  # la misma regla que usará la sincronización
        except PathNotAllowed:
            return {"ok": False, "error": "path_forbidden", "error_params": {}, "error_detail": None}
        if not _is_real_dir(str(real)):
            self._log("crear juego: la carpeta no existe o no es una carpeta")
            return {"ok": False, "error": "path_missing", "error_params": {}, "error_detail": None}
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
