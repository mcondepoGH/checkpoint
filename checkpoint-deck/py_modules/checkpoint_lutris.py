"""Carpeta sugerida para un atajo de Steam que lanza un juego de Lutris (solo biblioteca estándar, solo lectura).

Cadena: `LaunchOptions` del atajo (`lutris:rungameid/N`) -> fila `id=N` de la tabla `games` de `pga.db` -> `configpath` ->
`games/<configpath>.yml` -> `game.prefix`. Si el prefijo no sirve, `directory` de la fila. El prefijo entero NO se
sugiere como carpeta de guardado (es demasiado amplio): se buscan CANDIDATOS dentro de `drive_c/users/<usuario>/` y el
usuario elige uno o usa «Examinar…», que abre en `drive_c/users` (`find_saves`).

Candidatos (solo carpetas que EXISTEN y que contienen al menos un fichero; una carpeta sin ficheros no es un guardado):
carpetas de juego en `Documents/My Games/*`, `Documents/*`, `Saved Games/*`, `AppData/Local/*`, `AppData/LocalLow/*/*` y
`AppData/Roaming/*` de cada usuario del prefijo (no de sistema; el nombre del usuario no es fijo: `deck`, `steamuser`...).
Dentro de cada carpeta de juego se buscan, hasta profundidad 6, subcarpetas `SaveGames`, `Saves`, `Save`, `savedata` (sin
distinguir mayúsculas); si hay, ESAS son el candidato (más específico) y no la carpeta del juego. Se filtra el ruido de Wine
y Windows (`_NOISE`). Orden: primero los que coinciden por nombre con el juego (tokens normalizados del nombre y del slug
de Lutris y del nombre del atajo, sin «reimagined», «edition»...; similitud de Jaccard >= 0,5), luego los modificados más
recientemente; máximo 8; sin duplicados; si A contiene a B se queda B (el más específico) salvo que A tenga más ficheros
propios que B tiene en total. Nunca se siguen enlaces simbólicos; el recorrido tiene tope de carpetas, de entradas por
carpeta, de profundidad y de tiempo (`MAX_DIRS`, `MAX_ENTRIES`, `MAX_SECONDS`).

Dónde busca (por orden): Lutris Flatpak (`~/.var/app/net.lutris.Lutris/data/lutris`, VERIFICADO en una Deck real) y Lutris
nativo (`~/.local/share/lutris`, con los .yml en `games/` o en `~/.config/lutris/games/`; NO VERIFICADO en una Deck real).

Toda carpeta sugerida (prefijo, `drive_c/users`, candidatos) pasa por `checkpoint_sync.verified_dir`, la comprobación única del
plugin: existe, es carpeta, se puede listar y pasa la validación de rutas; `checkpoint_games` la repite justo antes de devolver.

Seguridad: `pga.db` se abre con `file:...?mode=ro` (nunca se escribe ni queda `-journal`); el .yml se lee con un
analizador mínimo (sin PyYAML ni dependencias) y solo la sección `game:`; `configpath` no puede salir de `games/`; la ruta
final pasa por `checkpoint_sync.verified_dir` y debe estar dentro del directorio personal. Todo fallo (ficheros
ausentes, corruptos, base bloqueada) da «sin sugerencia», sin excepción y sin rutas ni usuarios en el log.
"""

import os
import re
import sqlite3
import time
import unicodedata
from itertools import islice
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote

from checkpoint_sync import verified_dir

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


def _row(db: Path, game_id: int) -> Optional[Tuple[object, object, List[str]]]:
    """(configpath, directory, [nombre, slug]) de la fila `game_id`, con la base abierta en SOLO LECTURA; None ante cualquier
    fallo. Si faltan las columnas `name` o `slug` (versiones antiguas) se leen solo las que hay."""
    uri = "file:" + quote(str(db)) + "?mode=ro"
    con = None
    try:
        con = sqlite3.connect(uri, uri=True, timeout=0.3)
        row = None
        for cols in ("configpath, directory, name, slug", "configpath, directory, name", "configpath, directory"):
            try:
                row = con.execute(f"SELECT {cols} FROM games WHERE id = ?", (game_id,)).fetchone()
                break
            except sqlite3.OperationalError:
                continue
    except (sqlite3.Error, OSError, ValueError):
        return None
    finally:
        if con is not None:
            try:
                con.close()
            except sqlite3.Error:
                pass
    if not row:
        return None
    return (row[0], row[1], [x for x in row[2:] if isinstance(x, str) and x])


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


_TOP = re.compile(r"^([A-Za-z_][\w-]*):\s+(.*?)\s*$")


def read_yml(path: Path) -> Dict[str, Dict[str, str]]:
    """`{"game": {clave: valor}, "top": {clave: valor}}` del .yml de Lutris (analizador mínimo: claves escalares de la
    sección `game:` y de primer nivel; `{}` en ambas si no se puede leer)."""
    out: Dict[str, Dict[str, str]] = {"game": {}, "top": {}}
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_YML + 1)
    except OSError:
        return out
    if len(raw) > MAX_YML:
        return out
    in_game, indent = False, None
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            in_game, indent = bool(_SECTION.match(line)), None
            t = _TOP.match(line)
            if t and t.group(2):
                out["top"].setdefault(t.group(1), _scalar(t.group(2)))
            continue
        if not in_game:
            continue
        m = _KEY.match(line)
        if not m:
            continue
        if indent is None:
            indent = m.group(1)
        if m.group(1) == indent and m.group(3):
            out["game"].setdefault(m.group(2), _scalar(m.group(3)))
    return out


def _yml_prefix(path: Path) -> Optional[str]:
    """`game.prefix` del .yml de Lutris (solo la sección `game:` y sus claves directas)."""
    return read_yml(path)["game"].get("prefix") or None


def _locate(
    home: Path,
    launch_options: Optional[str],
    protected: Sequence[Path],
    log: Callable[[str], None],
    accept: Accept,
) -> Optional[Tuple[str, List[str]]]:
    """(prefijo validado, nombres del juego en Lutris) o None."""
    game_id = parse_game_id(launch_options)
    if game_id is None:
        return None
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
        configpath, directory, names = row
        prefix = None
        if isinstance(configpath, str) and configpath and "/" not in configpath and "\0" not in configpath and configpath not in (".", ".."):
            for d in ymls:
                prefix = _yml_prefix(d / f"{configpath}.yml")
                if prefix:
                    break
        for cand in (prefix, directory):
            ok = verified_dir(cand, home, protected, accept)
            if ok:
                return ok, names
    return None


def find_prefix(
    home: Path,
    launch_options: Optional[str],
    protected: Sequence[Path] = (),
    log: Callable[[str], None] = _noop,
    accept: Accept = lambda _s: True,
) -> str:
    """Prefijo de Lutris (si no sirve, `directory`) para las `LaunchOptions` de un atajo, o "" si no es de Lutris o no hay nada
    válido. NO es una carpeta de guardado: sirve para buscar candidatos y para abrir «Examinar…». Nunca lanza ni escribe."""
    found = _locate(home, launch_options, protected, log, accept)
    return found[0] if found else ""


# ---------------------------------------------------------------- candidatos de carpeta de guardado
MAX_CANDIDATES = 8
MAX_DEPTH = 6  # profundidad máxima al buscar subcarpetas de guardado dentro de la carpeta del juego
MAX_DIRS = 3000  # carpetas listadas en total por búsqueda
MAX_ENTRIES = 400  # entradas leídas por carpeta
MAX_SECONDS = 3.0
MIN_SIMILARITY = 0.5
_SAVE_NAMES = frozenset({"savegames", "saves", "save", "savedata"})
_SYSTEM_USERS = frozenset({"public", "all users", "default", "default user"})
# Ruido típico de Wine/Windows y de lanzadores: nunca es la carpeta de guardado de un juego (nombres sin mayúsculas).
_NOISE = frozenset(
    {
        "microsoft", "wine", "temp", "tmp", "packages", "programs", "windows", "inetcache", "crashpad", "cache", "caches",
        "logs", "log", "crashes", "crashreports", "crash reports", "d3dscache", "nvidia", "nvidia corporation", "amd", "mesa_shader_cache",
        "mesa_shader_cache_db", "fontconfig", "gecko", "mono", "python", "pip", "history", "webcache", "connecteddeviceplatform",
        "fontcache", "diagnostics", "unity", "steam", "epicgameslauncher", "ubisoft game launcher", "battle.net", "gog.com",
        "my music", "my pictures", "my videos", "my documents", "desktop", "downloads", "music", "pictures", "videos", "templates",
        "start menu", "application data", "local settings", "appdata", "cookies", "recent", "sendto", "nethood", "printhood",
    }
)
# Dentro de la carpeta de un juego solo se ignora lo que claramente no son partidas (el resto, p. ej. «Steam/<id>», sí se recorre).
_INNER_NOISE = frozenset({"logs", "log", "cache", "caches", "crashes", "crashpad", "crashreports", "crash reports", "temp", "tmp", "d3dscache"})
_STOP = frozenset(
    {"reimagined", "remastered", "remaster", "remake", "edition", "definitive", "deluxe", "complete", "goty", "hd", "the", "of", "and", "a", "game", "year"}
)


def _tokens(text: str) -> Set[str]:
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", t)
    return {w for w in re.split(r"[^a-z0-9]+", t.lower()) if w and w not in _STOP}


def similarity(folder: str, names: Sequence[str]) -> float:
    """Similitud de Jaccard (0 a 1) entre los tokens normalizados de `folder` y los de cada nombre del juego; la mayor."""
    a = _tokens(folder)
    best = 0.0
    for n in names:
        b = _tokens(n)
        if a and b:
            best = max(best, len(a & b) / len(a | b))
    return best


class _Budget:
    def __init__(self) -> None:
        self.dirs = 0
        self.deadline = time.monotonic() + MAX_SECONDS

    def spent(self) -> bool:
        return self.dirs >= MAX_DIRS or time.monotonic() > self.deadline


def _entries(path: str, budget: _Budget) -> List[os.DirEntry]:
    """Entradas de una carpeta (tope `MAX_ENTRIES`); vacía si el presupuesto se agotó o no se puede leer. Solo lectura."""
    if budget.spent():
        return []
    budget.dirs += 1
    try:
        with os.scandir(path) as it:
            return list(islice(it, MAX_ENTRIES))
    except OSError:
        return []


def _is_dir(e: os.DirEntry) -> bool:
    try:
        return e.is_dir(follow_symlinks=False)  # nunca se sigue un enlace
    except OSError:
        return False


def _is_file(e: os.DirEntry) -> bool:
    try:
        return e.is_file(follow_symlinks=False)
    except OSError:
        return False


def _subdirs(path: str, budget: _Budget, noise: frozenset = _NOISE) -> List[str]:
    out = []
    for e in sorted(_entries(path, budget), key=lambda x: x.name):
        if _is_dir(e) and e.name.casefold() not in noise:
            out.append(e.path)
    return out


def _stats(path: str, budget: _Budget) -> Tuple[int, float]:
    """(ficheros, mtime más reciente) de lo que hay bajo `path` (sin logs ni cachés, sin enlaces)."""
    files, newest = 0, 0.0
    stack = [(path, 0)]
    while stack:
        d, depth = stack.pop()
        for e in _entries(d, budget):
            if _is_file(e):
                files += 1
                try:
                    newest = max(newest, e.stat(follow_symlinks=False).st_mtime)
                except OSError:
                    pass
            elif _is_dir(e) and depth < MAX_DEPTH and e.name.casefold() not in _INNER_NOISE:
                stack.append((e.path, depth + 1))
    return files, newest


def _save_dirs(game: str, budget: _Budget) -> List[str]:
    """Subcarpetas `SaveGames`/`Saves`/... de la carpeta del juego (profundidad <= MAX_DEPTH, sin entrar en una ya hallada)."""
    found: List[str] = []
    queue = [(game, 0)]
    while queue:
        d, depth = queue.pop(0)
        if depth >= MAX_DEPTH:
            continue
        for sub in _subdirs(d, budget, _INNER_NOISE):
            if os.path.basename(sub).casefold() in _SAVE_NAMES:
                found.append(sub)
            else:
                queue.append((sub, depth + 1))
    return found


def _game_folders(user: str, budget: _Budget) -> List[str]:
    """Carpetas de juego de un usuario del prefijo (donde Windows guarda partidas), sin ruido."""
    out: List[str] = []
    for rel in ("Documents/My Games", "Saved Games", "AppData/Local", "AppData/Roaming"):
        out += _subdirs(os.path.join(user, rel), budget)
    for d in _subdirs(os.path.join(user, "Documents"), budget):
        if os.path.basename(d).casefold() != "my games":
            out.append(d)
    for dev in _subdirs(os.path.join(user, "AppData/LocalLow"), budget):
        out += _subdirs(dev, budget)
    return out


def _users(prefix: str, budget: _Budget) -> List[str]:
    return [u for u in _subdirs(os.path.join(prefix, "drive_c/users"), budget, noise=frozenset()) if os.path.basename(u).casefold() not in _SYSTEM_USERS]


def _prune_nested(found: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Si A contiene a B se queda B (más específico), salvo que A tenga más ficheros propios que B tiene en total: entonces A."""
    drop: Set[str] = set()
    for a in found:
        for b in found:
            if a is b or not b["path"].startswith(a["path"] + "/"):
                continue
            own_a = a["files"] - b["files"]
            drop.add(b["path"] if own_a > b["files"] else a["path"])
    return [c for c in found if c["path"] not in drop]


def find_saves(
    home: Path,
    launch_options: Optional[str],
    protected: Sequence[Path] = (),
    log: Callable[[str], None] = _noop,
    accept: Accept = lambda _s: True,
    name: str = "",
) -> Dict[str, Any]:
    """`{prefix, candidates, browse_start}` de un atajo de Lutris. `candidates`: carpetas que existen con al menos un
    fichero, ordenadas (ver módulo), hasta `MAX_CANDIDATES`. `browse_start`: `<prefijo>/drive_c/users` si existe, si no el
    prefijo, si no "". `prefix` "" = no es un atajo de Lutris o no hay prefijo válido. Solo lectura; nunca lanza."""
    out: Dict[str, Any] = {"prefix": "", "candidates": [], "browse_start": ""}
    home = Path(home)
    found = _locate(home, launch_options, protected, log, lambda _s: True)
    if found is None:
        return out
    prefix, names = found
    out["prefix"] = out["browse_start"] = prefix
    if name:
        names = names + [name]
    users_dir = prefix + "/drive_c/users"
    ok_users = verified_dir(users_dir, home, protected, lambda _s: True)
    if not ok_users:
        return out
    out["browse_start"] = ok_users
    try:
        budget = _Budget()
        cands: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for user in _users(prefix, budget):
            for game in _game_folders(user, budget):
                score = similarity(os.path.basename(game), names)
                specific = _save_dirs(game, budget)
                for path in specific or [game]:
                    if path in seen:
                        continue
                    seen.add(path)
                    files, newest = _stats(path, budget)
                    if not files:
                        continue
                    ok = verified_dir(path, home, protected, accept)
                    if ok and ok.startswith(prefix + "/"):
                        cands.append({"path": ok, "files": files, "mtime": newest, "score": score})
        cands = _prune_nested(cands)
        cands.sort(key=lambda c: (0, -c["score"], -c["mtime"]) if c["score"] >= MIN_SIMILARITY else (1, 0.0, -c["mtime"]))
        out["candidates"] = [c["path"] for c in cands[:MAX_CANDIDATES]]
    except Exception:  # noqa: BLE001  (nunca cuelga ni rompe la configuración: sin candidatos)
        log("lutris: no se pudieron buscar carpetas de guardado en el prefijo")
        out["candidates"] = []
    return out
