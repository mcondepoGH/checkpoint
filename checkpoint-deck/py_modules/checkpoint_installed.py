"""Juegos de Steam y de Lutris instalados en la Deck, con lo que hace falta para resolver sus rutas de guardado.

Solo biblioteca estándar y SOLO LECTURA (la base de Lutris se abre con `mode=ro`; no se lanza Lutris ni Flatpak).

Steam: raíces y bibliotecas (interna y tarjeta SD) de `libraryfolders.vdf`; cada `appmanifest_<appid>.acf` da el appid, el
nombre y `installdir`. El prefijo de Proton es `<biblioteca>/steamapps/compatdata/<appid>/pfx` y está SIEMPRE en la biblioteca
donde está el juego. La nube de Steam es `<raíz>/userdata/*/<appid>`.

Lutris: Flatpak primero (`~/.var/app/net.lutris.Lutris/data/lutris`, con `pga.db` y `games/*.yml`) y después nativo
(`~/.local/share/lutris`, `~/.config/lutris`); gana la primera instalación que tenga juegos. El prefijo es `game.prefix`
del .yml (nunca deducido por el nombre); la carpeta de instalación, `dirname(game.exe)` solo si `game.exe` es un fichero que
existe; si es una carpeta o no existe, la columna `directory` de la base y, por último, `<prefijo>/drive_c`.

Usuario de Wine: se detecta listando `drive_c/users` (sin `Public`); un enlace (`deck` -> `steamuser`) se resuelve.
"""

import glob
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import checkpoint_lutris
import checkpoint_steam

MAX_LUTRIS_ROWS = 5000
_SYSTEM_USERS = frozenset({"public", "all users", "default", "default user"})
FLATPAK_LUTRIS = ".var/app/net.lutris.Lutris"


def _noop(_m: str) -> None:
    pass


@dataclass
class InstalledGame:
    source: str  # "steam" | "lutris"
    id: int  # appid de Steam o id de la fila de Lutris
    name: str
    prefix: Optional[str] = None  # carpeta con `drive_c` (Wine/Proton); None = juego nativo, solo rutas de Linux
    install: Optional[str] = None
    steam_appid: Optional[int] = None  # Steam: su appid; Lutris: `service_id` si `service` es steam
    slug: Optional[str] = None  # Lutris: `games.slug` (si no, `game_slug` del .yml)
    runner: Optional[str] = None
    userdata: List[str] = field(default_factory=list)  # Steam: `userdata/*/<appid>` existentes
    flatpak: bool = False  # Lutris Flatpak: los juegos nativos ven sus XDG bajo `~/.var/app/net.lutris.Lutris`


def _isdir(p: str) -> bool:
    try:
        return os.path.isdir(p)
    except OSError:
        return False


def wine_users(prefix: str) -> List[str]:
    """Carpetas de usuario de Wine en `<prefijo>/drive_c/users` (reales, sin repetir ni `Public`; `steamuser` primero). Si no hay
    ninguna se devuelve la de `steamuser` (aunque aún no exista), para poder mostrarla como «no encontrada aún»."""
    users = os.path.join(prefix, "drive_c", "users")
    found: Dict[str, str] = {}
    try:
        with os.scandir(users) as it:
            names = sorted(e.name for e in it)
    except OSError:
        names = []
    for n in names:
        if n.casefold() in _SYSTEM_USERS:
            continue
        real = os.path.realpath(os.path.join(users, n))  # `deck` -> `steamuser`: se queda el destino
        if os.path.isdir(real):
            found.setdefault(real, real)
    out = sorted(found, key=lambda r: (os.path.basename(r).casefold() != "steamuser", r))
    return out or [os.path.join(users, "steamuser")]


# ------------------------------------------------------------------------------------------------ Steam
def steam_games(home: Path, log: Callable[[str], None] = _noop) -> List[InstalledGame]:
    out: List[InstalledGame] = []
    seen = set()
    for root in checkpoint_steam.find_steam_roots(home):
        for lib in checkpoint_steam.library_dirs(root, log):
            try:
                names = sorted(x for x in os.listdir(lib) if checkpoint_steam._ACF_RE.match(x))
            except OSError:
                continue
            for fname in names:
                entry = checkpoint_steam._entry(lib / fname)
                if entry is None or entry[0] in seen:
                    continue
                appid, name = entry
                seen.add(appid)
                state = (checkpoint_steam.read_vdf(lib / fname) or {}).get("appstate") or {}
                installdir = state.get("installdir")
                install = None
                if isinstance(installdir, str) and installdir and "/" not in installdir and installdir not in (".", ".."):
                    cand = str(lib / "common" / installdir)
                    install = cand if _isdir(cand) else None
                pfx = str(lib / "compatdata" / str(appid) / "pfx")
                userdata = sorted(glob.glob(os.path.join(glob.escape(str(root)), "userdata", "*", str(appid))))
                out.append(
                    InstalledGame(
                        "steam", appid, name,
                        prefix=pfx if _isdir(pfx) else None,
                        install=install,
                        steam_appid=appid,
                        userdata=[u for u in userdata if _isdir(u)],
                    )
                )  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------------ Lutris
def _db_rows(db: Path) -> List[Dict[str, object]]:
    """Filas de `games` (todas las columnas) con la base en SOLO LECTURA; [] ante cualquier fallo."""
    con = None
    try:
        con = sqlite3.connect("file:" + quote(str(db)) + "?mode=ro", uri=True, timeout=0.3)
        cur = con.execute("SELECT * FROM games LIMIT ?", (MAX_LUTRIS_ROWS,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    except (sqlite3.Error, OSError, ValueError):
        return []
    finally:
        if con is not None:
            try:
                con.close()
            except sqlite3.Error:
                pass


def _str(v: object) -> Optional[str]:
    return v if isinstance(v, str) and v else None


def _lutris_install(exe: Optional[str], directory: Optional[str], prefix: Optional[str]) -> Optional[str]:
    if exe and os.path.isabs(exe) and os.path.isfile(exe):
        return os.path.dirname(exe)
    if directory and os.path.isabs(directory) and _isdir(directory):
        return directory
    if prefix and _isdir(os.path.join(prefix, "drive_c")):
        return os.path.join(prefix, "drive_c")
    return None


def lutris_games(home: Path, log: Callable[[str], None] = _noop) -> List[InstalledGame]:
    """Juegos instalados de Lutris: Flatpak primero y, si no tiene ninguno, nativo."""
    for data, ymls in checkpoint_lutris._sources(Path(home)):
        db = data / "pga.db"
        try:
            if not db.is_file():
                continue
        except OSError:
            continue
        rows = _db_rows(db)
        if not rows:
            continue
        flatpak = str(data).startswith(str(Path(home) / FLATPAK_LUTRIS))
        out: List[InstalledGame] = []
        for r in rows:
            rid, name = r.get("id"), _str(r.get("name"))
            if not isinstance(rid, int) or isinstance(rid, bool) or not name or r.get("installed") in (0, "0", False):
                continue
            cfg = _str(r.get("configpath"))
            yml: Dict[str, Dict[str, str]] = {"game": {}, "top": {}}
            if cfg and "/" not in cfg and "\0" not in cfg and cfg not in (".", ".."):
                for d in ymls:
                    yml = checkpoint_lutris.read_yml(d / f"{cfg}.yml")
                    if yml["game"] or yml["top"]:
                        break
            prefix = yml["game"].get("prefix") or None
            if prefix and not os.path.isabs(prefix):
                prefix = None
            sid = r.get("service_id")
            sid = str(sid) if isinstance(sid, (int, str)) and not isinstance(sid, bool) else ""
            steam_appid = int(sid) if r.get("service") == "steam" and sid.isdigit() and 0 < int(sid) < 2**31 else None
            out.append(
                InstalledGame(
                    "lutris", rid, name,
                    prefix=prefix,
                    install=_lutris_install(yml["game"].get("exe"), _str(r.get("directory")), prefix),
                    steam_appid=steam_appid,
                    slug=_str(r.get("slug")) or yml["top"].get("game_slug") or None,
                    runner=_str(r.get("runner")),
                    flatpak=flatpak,
                )
            )  # fmt: skip
        return out
    return []


def installed_games(home: Path, log: Callable[[str], None] = _noop) -> Tuple[List[InstalledGame], List[InstalledGame]]:
    """(juegos de Steam, juegos de Lutris) instalados bajo `home`."""
    return steam_games(home, log), lutris_games(home, log)
