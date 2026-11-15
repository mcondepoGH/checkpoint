"""Biblioteca de Steam de la Deck: lee los `appmanifest_*.acf` (appid y nombre) sin usar la interfaz interna de Steam.

Solo biblioteca estándar. De cada juego sale ÚNICAMENTE el appid y el nombre: nada más del fichero se conserva ni se
envía. Suma los atajos de Steam (juegos que no son de Steam, p. ej. Lutris) de `shortcuts.vdf`. Todo error de un fichero (ilegible, truncado, sin nombre) lo descarta sin romper el resto.
"""

import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import checkpoint_shortcuts

MAX_GAMES = 5000  # igual que `MAX_GAMES` del hub (backend/app/services/steam.py)
MAX_NAME = 200  # igual que `MAX_NAME` del hub
MAX_FILE = 256 * 1024  # un manifiesto real pesa pocos KB; más es basura y no se lee entero
MAX_DEPTH = 32
MAX_APPID = 2**31 - 1  # solo juegos de Steam (appmanifest); los atajos tienen su propio techo (checkpoint_shortcuts.MAX_APPID)
STEAM_ROOTS = (".local/share/Steam", ".steam/steam", ".steam/root", ".var/app/com.valvesoftware.Steam/.local/share/Steam")
_ESC = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}
_ACF_RE = re.compile(r"^appmanifest_\d+\.acf$")


def _noop(_m: str) -> None:
    pass


class VdfError(ValueError):
    """Texto VDF/ACF mal formado."""


def _isdir(p: Path) -> bool:
    """`Path.is_dir()` que no lanza: en Python 3.11 una carpeta sin permiso (tarjeta SD mal montada...) levantaba
    PermissionError y tumbaba todo el escaneo."""
    try:
        return p.is_dir()
    except OSError:
        return False


def _tokens(text: str):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
        elif c in "{}":
            yield c, False
            i += 1
        elif c == '"':
            buf, i = [], i + 1
            while True:
                if i >= n:
                    raise VdfError("cadena sin cerrar")
                ch = text[i]
                if ch == '"':
                    i += 1
                    break
                if ch == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    buf.append(_ESC.get(nxt, "\\" + nxt))
                    i += 2
                else:
                    buf.append(ch)
                    i += 1
            yield "".join(buf), True
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '{}"':
                j += 1
            yield text[i:j], True
            i = j


def parse_vdf(text: str) -> Dict[str, Any]:
    """Diccionario anidado (claves en minúsculas: Steam mezcla `appid`/`AppID`); VdfError si está mal formado."""
    if text.startswith("﻿"):
        text = text[1:]
    toks = list(_tokens(text))
    pos = 0

    def block(depth: int, top: bool) -> Dict[str, Any]:
        nonlocal pos
        if depth > MAX_DEPTH:
            raise VdfError("demasiado anidado")
        out: Dict[str, Any] = {}
        while True:
            if pos >= len(toks):
                if top:
                    return out
                raise VdfError("llave sin cerrar")
            tok, is_str = toks[pos]
            pos += 1
            if not is_str:
                if tok == "}" and not top:
                    return out
                raise VdfError("llave inesperada")
            if pos >= len(toks):
                raise VdfError("clave sin valor")
            val, val_str = toks[pos]
            pos += 1
            if val_str:
                out[tok.lower()] = val
            elif val == "{":
                out[tok.lower()] = block(depth + 1, False)
            else:
                raise VdfError("llave inesperada")

    res = block(0, True)
    if not res:
        raise VdfError("vacío")
    return res


def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE:
            return None
        return parse_vdf(raw.decode("utf-8-sig"))
    except (OSError, ValueError):  # VdfError y UnicodeDecodeError son ValueError
        return None


def find_steam_roots(home: Path) -> List[Path]:
    """Raíces de Steam que existen bajo `home` (sin repetir las que apuntan al mismo sitio)."""
    out: List[Path] = []
    seen = set()
    for rel in STEAM_ROOTS:
        p = Path(home) / rel
        try:
            real = p.resolve()
            if real in seen or not _isdir(p / "steamapps"):
                continue
        except OSError:
            continue
        seen.add(real)
        out.append(p)
    return out


def library_dirs(root: Path, log: Callable[[str], None] = _noop) -> List[Path]:
    """Carpetas `steamapps` de la raíz y de las bibliotecas extra de `libraryfolders.vdf` (tarjeta SD...)."""
    root = Path(root)
    dirs = [root / "steamapps"]
    data = _read(root / "steamapps" / "libraryfolders.vdf")
    folders = data.get("libraryfolders") if data else None
    if isinstance(folders, dict):
        for key in sorted(folders, key=lambda k: (not k.isdigit(), int(k) if k.isdigit() else 0, k)):
            entry = folders[key]
            raw = entry.get("path") if isinstance(entry, dict) else entry if isinstance(entry, str) else None
            if not isinstance(raw, str) or not raw or "\0" in raw or not os.path.isabs(raw):
                continue
            d = Path(raw) / "steamapps"
            if d in dirs:
                continue
            if _isdir(d):
                dirs.append(d)
            else:
                log(f"biblioteca: la carpeta extra {d} no existe o no se puede leer; se omite")
    return [d for d in dirs if _isdir(d)]


def _entry(path: Path) -> Optional[Tuple[int, str]]:
    data = _read(path)
    state = data.get("appstate") if data else None
    if not isinstance(state, dict):
        return None
    appid, name = state.get("appid"), state.get("name")
    if not (isinstance(appid, str) and appid.isascii() and appid.isdigit() and isinstance(name, str)):
        return None
    n = int(appid)
    name = name.strip()[:MAX_NAME].strip()
    if not 0 < n <= MAX_APPID or not name:
        return None
    return n, name


def scan_steam_root(root: Path, limit: int = MAX_GAMES, log: Callable[[str], None] = _noop) -> List[Tuple[int, str]]:
    """[(appid, nombre)] de todas las bibliotecas de una raíz de Steam; la primera biblioteca gana un appid repetido."""
    seen: Dict[int, str] = {}
    for d in library_dirs(root, log):
        try:
            names = sorted(x for x in os.listdir(d) if _ACF_RE.match(x))
        except OSError as e:
            log(f"biblioteca: no se pudo listar {d} ({type(e).__name__}: {e.strerror or e})")
            continue
        for fname in names:
            if len(seen) >= limit:
                return list(seen.items())
            e = _entry(d / fname)
            if e and e[0] not in seen:
                seen[e[0]] = e[1]
    return list(seen.items())


def scan_games(
    home: Optional[Path] = None, limit: int = MAX_GAMES, log: Callable[[str], None] = _noop
) -> Tuple[List[Tuple[int, str]], Set[int]]:
    """(juegos, ids de atajo): los juegos instalados bajo `home` (por defecto el directorio personal) más los atajos de
    Steam, ordenados por appid, y cuáles de esos appids son atajos. Un juego de Steam gana a un atajo con el mismo id."""
    home = Path(home) if home else Path.home()
    seen: Dict[int, str] = {}
    shortcuts: Set[int] = set()
    roots = find_steam_roots(home)
    if not roots:
        log("biblioteca: no hay ninguna raíz de Steam bajo el directorio personal")
    for root in roots:
        for appid, name in scan_steam_root(root, limit, log):
            if len(seen) < limit:
                seen.setdefault(appid, name)
    for root in roots:
        for appid, name in checkpoint_shortcuts.scan_shortcuts(root, limit, log):
            if len(seen) < limit and appid not in seen:
                seen[appid] = name
                shortcuts.add(appid)
    return sorted(seen.items()), shortcuts


def scan_library(home: Optional[Path] = None, limit: int = MAX_GAMES, log: Callable[[str], None] = _noop) -> List[Tuple[int, str]]:
    """Juegos instalados y atajos de Steam bajo `home`, ordenados por appid (sin distinguir el origen: ver `scan_games`)."""
    return scan_games(home, limit, log)[0]
