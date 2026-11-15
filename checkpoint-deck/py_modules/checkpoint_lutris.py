"""Carpeta sugerida para un atajo de Steam que lanza un juego de Lutris (solo biblioteca estándar, solo lectura).

Cadena: `LaunchOptions` del atajo (`lutris:rungameid/N`) -> fila `id=N` de la tabla `games` de `pga.db` -> `configpath` ->
`games/<configpath>.yml` -> `game.prefix`. Si el prefijo no sirve, `directory` de la fila. La carpeta sugerida es el
PREFIJO de Lutris (no se sabe dónde guarda el juego sus partidas); el usuario la confirma o la cambia con «Examinar…».

Dónde busca (por orden): Lutris Flatpak (`~/.var/app/net.lutris.Lutris/data/lutris`, VERIFICADO en una Deck real) y Lutris
nativo (`~/.local/share/lutris`, con los .yml en `games/` o en `~/.config/lutris/games/`; NO VERIFICADO en una Deck real).

Seguridad: `pga.db` se abre con `file:...?mode=ro` (nunca se escribe ni queda `-journal`); el .yml se lee con un
analizador mínimo (sin PyYAML ni dependencias) y solo la sección `game:`; `configpath` no puede salir de `games/`; la ruta
final pasa por `checkpoint_sync.validate_game_path` y debe estar dentro del directorio personal. Todo fallo (ficheros
ausentes, corruptos, base bloqueada) da «sin sugerencia», sin excepción y sin rutas ni usuarios en el log.
"""

import os
import re
import sqlite3
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple
from urllib.parse import quote

from checkpoint_sync import PathNotAllowed, validate_game_path

MAX_YML = 256 * 1024  # un .yml de Lutris pesa pocos KB
MAX_ID = 10**9
_RUN_ID = re.compile(r"(?:^|\s)lutris:rungameid/(\d{1,12})(?=\s|$)")
_SECTION = re.compile(r"^game:\s*(?:#.*)?$")
_KEY = re.compile(r"^(\s+)([A-Za-z_][\w-]*):(?:\s+(.*))?\s*$")

Accept = Callable[[str], bool]


def _noop(_m: str) -> None:
    pass


def parse_game_id(launch_options: Optional[str]) -> Optional[int]:
    """Id numérico de `lutris:rungameid/N` en las `LaunchOptions` de un atajo; None si no es un atajo de Lutris con id."""
    if not isinstance(launch_options, str):
        return None
    m = _RUN_ID.search(launch_options)
    if not m:
        return None
    n = int(m.group(1))
    return n if 0 < n < MAX_ID else None


def _sources(home: Path) -> List[Tuple[Path, List[Path]]]:
    """(carpeta de datos con pga.db, carpetas posibles de los .yml) por orden: Flatpak y nativo."""
    fp = home / ".var/app/net.lutris.Lutris"
    nat = home / ".local/share/lutris"
    return [
        (fp / "data/lutris", [fp / "data/lutris/games", fp / "config/lutris/games"]),
        (nat, [nat / "games", home / ".config/lutris/games"]),
    ]


def _row(db: Path, game_id: int) -> Optional[Tuple[object, object]]:
    """(configpath, directory) de la fila `game_id`, con la base abierta en SOLO LECTURA; None ante cualquier fallo."""
    uri = "file:" + quote(str(db)) + "?mode=ro"
    con = None
    try:
        con = sqlite3.connect(uri, uri=True, timeout=0.3)
        row = con.execute("SELECT configpath, directory FROM games WHERE id = ?", (game_id,)).fetchone()
    except (sqlite3.Error, OSError, ValueError):
        return None
    finally:
        if con is not None:
            try:
                con.close()
            except sqlite3.Error:
                pass
    return (row[0], row[1]) if row else None


def _scalar(raw: str) -> str:
    v = raw.strip()
    if v[:1] == "'":
        end = 1
        while end < len(v):
            if v[end] == "'":
                if v[end + 1 : end + 2] == "'":
                    end += 2
                    continue
                break
            end += 1
        return v[1:end].replace("''", "'")
    if v[:1] == '"':
        m = re.match(r'"((?:[^"\\]|\\.)*)"', v)
        return re.sub(r"\\(.)", r"\1", m.group(1)) if m else v[1:]
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


def _yml_prefix(path: Path) -> Optional[str]:
    """`game.prefix` del .yml de Lutris (analizador mínimo: solo la sección `game:` y sus claves directas)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_YML + 1)
    except OSError:
        return None
    if len(raw) > MAX_YML:
        return None
    in_game, indent = False, None
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            in_game, indent = bool(_SECTION.match(line)), None
            continue
        if not in_game:
            continue
        m = _KEY.match(line)
        if not m:
            continue
        if indent is None:
            indent = m.group(1)
        if m.group(1) == indent and m.group(2) == "prefix" and m.group(3):
            return _scalar(m.group(3)) or None
    return None


def _valid(candidate: object, home: Path, protected: Sequence[Path], accept: Accept) -> Optional[str]:
    """La ruta como la validaría la sincronización, existente, dentro del directorio personal y aceptable; si no, None."""
    if not isinstance(candidate, str):
        return None
    try:
        real = validate_game_path(candidate, home, protected)
    except PathNotAllowed:
        return None
    s = str(real)
    if s != candidate:  # `..`, enlaces o rutas no normalizadas: no se sugieren
        return None
    base = os.path.realpath(home)
    if not (s == base or s.startswith(base.rstrip("/") + "/")):
        return None
    try:
        if not real.is_dir():
            return None
    except OSError:
        return None
    return s if accept(s) else None


def suggest_prefix(
    home: Path,
    launch_options: Optional[str],
    protected: Sequence[Path] = (),
    log: Callable[[str], None] = _noop,
    accept: Accept = lambda _s: True,
) -> str:
    """Carpeta sugerida (prefijo de Lutris; si no sirve, `directory`) para las `LaunchOptions` de un atajo, o "" si no es de
    Lutris o no hay nada válido. Nunca lanza ni escribe."""
    game_id = parse_game_id(launch_options)
    if game_id is None:
        return ""
    home = Path(home)
    for data, ymls in _sources(home):
        db = data / "pga.db"
        try:
            if not db.is_file():
                continue
        except OSError:
            continue
        row = _row(db, game_id)
        if row is None:
            log("lutris: no se pudo leer el juego en la base de datos de Lutris")
            continue
        configpath, directory = row
        prefix = None
        if isinstance(configpath, str) and configpath and "/" not in configpath and "\0" not in configpath and configpath not in (".", ".."):
            for d in ymls:
                prefix = _yml_prefix(d / f"{configpath}.yml")
                if prefix:
                    break
        for cand in (prefix, directory):
            ok = _valid(cand, home, protected, accept)
            if ok:
                return ok
    return ""
