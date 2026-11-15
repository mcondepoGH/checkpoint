"""Atajos de Steam de la Deck (juegos que no son de Steam añadidos a mano, p. ej. Lutris): lee `shortcuts.vdf`.

Solo biblioteca estándar. El fichero es VDF BINARIO (formato público de Steam): diccionarios (tipo 0), cadenas (1),
enteros de 32 bits (2) y fin de diccionario (8). De cada atajo se conserva `appid`, `AppName`, `Exe`, `StartDir` y
`LaunchOptions` (esta última solo se lee en local, para sugerir la carpeta de los atajos de Lutris: `checkpoint_lutris`);
solo el appid y el nombre salen de la Deck (hacia el hub). Todo error de un fichero (ausente, ilegible, corrupto) lo
descarta sin romper el resto y sin poner ruta ni steamid en el log.

VERIFICADO en una Deck real (2026-11-15, solo lectura): el `appid` del fichero es el mismo número que Steam entrega como
`unAppID` en el evento `SteamClient.GameSessions`. Los tests usan ficheros sintéticos, no capturas.
"""

import os
import struct
import zlib
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

MAX_GAMES = 5000  # igual que `MAX_GAMES` del hub
MAX_NAME = 200  # igual que `MAX_NAME` del hub
MAX_FILE = 4 * 1024 * 1024  # un shortcuts.vdf real pesa pocos KB; más es basura y no se lee entero
MAX_DEPTH = 16
MAX_APPID = 2**32 - 1  # los atajos usan ids de 32 bits sin signo (el hub no tiene techo; `valid_appid` solo pide > 0)


def _noop(_m: str) -> None:
    pass


class ShortcutsError(ValueError):
    """VDF binario mal formado."""


class Shortcut(NamedTuple):
    appid: Optional[int]  # None = el fichero no lo trae
    name: str
    exe: str
    start_dir: str
    launch_options: str = ""


# tipos de valor del VDF binario -> bytes fijos que ocupan (los que no se interpretan se saltan)
_FIXED = {3: 4, 4: 4, 6: 4, 7: 8, 10: 8}


def derive_appid(exe: str, name: str) -> int:
    """Id de 32 bits de un atajo a partir de `Exe` (tal cual está en el fichero, con sus comillas) y `AppName`:
    crc32(exe + nombre) con el bit alto activado. NO VERIFICADO contra una Deck real: por eso `scan_shortcuts` solo lo
    usa si se le pide (`derive_missing=True`); Steam reciente escribe el `appid` en el fichero."""
    return zlib.crc32((exe + name).encode("utf-8")) | 0x80000000


def _cstr(data: bytes, pos: int) -> Tuple[str, int]:
    end = data.find(b"\x00", pos)
    if end < 0:
        raise ShortcutsError("cadena sin cerrar")
    return data[pos:end].decode("utf-8", "replace"), end + 1


def _dict(data: bytes, pos: int, depth: int) -> Tuple[Dict[str, object], int]:
    """Lee pares hasta el fin de diccionario (8); devuelve (valores, posición tras el 8)."""
    if depth > MAX_DEPTH:
        raise ShortcutsError("demasiado anidado")
    out: Dict[str, object] = {}
    while True:
        if pos >= len(data):
            raise ShortcutsError("diccionario sin cerrar")
        t = data[pos]
        pos += 1
        if t == 8:
            return out, pos
        key, pos = _cstr(data, pos)
        key = key.lower()
        if t == 0:
            out[key], pos = _dict(data, pos, depth + 1)
        elif t == 1:
            out[key], pos = _cstr(data, pos)
        elif t == 2:
            if pos + 4 > len(data):
                raise ShortcutsError("entero truncado")
            out[key] = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        elif t in _FIXED:
            if pos + _FIXED[t] > len(data):
                raise ShortcutsError("valor truncado")
            pos += _FIXED[t]
        else:
            raise ShortcutsError(f"tipo desconocido {t}")


def parse_shortcuts(data: bytes) -> List[Shortcut]:
    """Atajos de un `shortcuts.vdf` (en el orden del fichero); ShortcutsError si está mal formado."""
    root, _ = _root(data)
    block = root.get("shortcuts")
    if not isinstance(block, dict):
        return []
    out: List[Shortcut] = []
    for key in sorted(block, key=lambda k: (not k.isdigit(), int(k) if k.isdigit() else 0, k)):
        e = block[key]
        if not isinstance(e, dict):
            continue
        appid = e.get("appid")
        name, exe, sdir, lopts = e.get("appname"), e.get("exe"), e.get("startdir"), e.get("launchoptions")
        out.append(
            Shortcut(
                appid if isinstance(appid, int) else None,
                name if isinstance(name, str) else "",
                exe if isinstance(exe, str) else "",
                sdir if isinstance(sdir, str) else "",
                lopts if isinstance(lopts, str) else "",
            )
        )
    return out


def _root(data: bytes) -> Tuple[Dict[str, object], int]:
    """El fichero es el contenido de un diccionario raíz: `\\x00shortcuts\\x00 ... \\x08` y un `\\x08` final."""
    if not data:
        raise ShortcutsError("vacío")
    return _dict(data, 0, 0)


def _read(path: Path) -> Optional[bytes]:
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE + 1)
    except OSError:
        return None
    return None if len(raw) > MAX_FILE else raw


def scan_shortcuts(
    root: Path, limit: int = MAX_GAMES, log: Callable[[str], None] = _noop, derive_missing: bool = False
) -> List[Tuple[int, str]]:
    """[(appid, nombre)] de los atajos de todos los usuarios de Steam de una raíz (`userdata/<id>/config/shortcuts.vdf`).
    Un appid repetido (mismo atajo en dos usuarios) cuenta una vez. Sin appid en el fichero: se omite (y se avisa en el
    log) salvo `derive_missing`, que lo deriva de Exe + nombre (NO VERIFICADO)."""
    userdata = Path(root) / "userdata"
    try:
        users = sorted(x for x in os.listdir(userdata) if x.isascii() and x.isdigit())
    except OSError:
        return []
    seen: Dict[int, str] = {}
    for u in users:
        raw = _read(userdata / u / "config" / "shortcuts.vdf")
        if raw is None:
            continue
        try:
            items = parse_shortcuts(raw)
        except ShortcutsError as e:
            log(f"atajos: un shortcuts.vdf está mal formado ({e}); se omite")
            continue
        for sh in items:
            if len(seen) >= limit:
                return list(seen.items())
            name = sh.name.strip()[:MAX_NAME].strip()
            appid = sh.appid
            if not name:
                continue
            if not appid:
                if not derive_missing:
                    log("atajos: un atajo no trae appid en shortcuts.vdf; se omite")
                    continue
                appid = derive_appid(sh.exe, sh.name)
            if 0 < appid <= MAX_APPID:
                seen.setdefault(appid, name)
    return list(seen.items())


def find_launch_options(root: Path, appid: int) -> Optional[str]:
    """`LaunchOptions` del atajo con ese `appid` en cualquiera de los usuarios de una raíz de Steam (None si no hay
    atajo con ese número; "" si no trae opciones). Solo lectura; un fichero ilegible o corrupto se salta."""
    userdata = Path(root) / "userdata"
    try:
        users = sorted(x for x in os.listdir(userdata) if x.isascii() and x.isdigit())
    except OSError:
        return None
    for u in users:
        raw = _read(userdata / u / "config" / "shortcuts.vdf")
        if raw is None:
            continue
        try:
            items = parse_shortcuts(raw)
        except ShortcutsError:
            continue
        for sh in items:
            if sh.appid == appid:
                return sh.launch_options
    return None
