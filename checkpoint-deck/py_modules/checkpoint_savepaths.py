"""Resolvedor de rutas de guardado: convierte las rutas del manifiesto propio en rutas absolutas de ESTA Deck y mide las que existen.

Solo lectura y solo biblioteca estándar. Raíces del manifiesto (`r`): `home` (el HOME real), `xdgData` (`~/.local/share`),
`xdgConfig` (`~/.config`), `steamCloud` (`<raíz de Steam>/userdata/*/<appid>/`), `install` (carpeta de instalación) y las
de Wine/Proton bajo `<prefijo>/drive_c/users/<usuario>/`: `pfxRoaming` (AppData/Roaming), `pfxLocal` (AppData/Local),
`pfxLocalLow` (AppData/LocalLow), `pfxDocs` (Documents), `pfxSaved` (Saved Games) y `pfxProgData` (`drive_c/ProgramData`).
Juego con prefijo: se usan las rutas `os` = win (y `steamCloud`); sin prefijo (nativo): solo las de Linux, sin raíces `pfx*`.
Un juego de Lutris Flatpak nativo ve también sus XDG bajo `~/.var/app/net.lutris.Lutris/{data,config}` (NO verificado).

Una regla con comodines (`*`, `?`, `[...]`) se expande con `glob`: si coincide con carpetas, una entrada por carpeta (máx.
`MAX_DIR_MATCHES`); si solo con ficheros, UNA entrada agrupada con la ruta con comodín. Si una regla con comodín de fichero y
la carpeta que lo contiene salen a la vez, solo se queda la carpeta. Los patrones `x` (excluir al sugerir) no cuentan en
tamaño, ficheros ni mtime. Medición acotada (`MEASURE_DEPTH` niveles, `MAX_SCAN` entradas, tiempo): nunca se lee el
contenido de un fichero ni se siguen enlaces simbólicos.
"""

import fnmatch
import glob
import os
import time
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import checkpoint_installed as ci

MEASURE_DEPTH = 3
MAX_SCAN = 1500  # entradas leídas por medición
MAX_ENTRIES_DIR = 400  # entradas leídas por carpeta
MAX_SECONDS = 1.0  # por medición
MAX_GLOB = 50  # coincidencias leídas de un comodín
MAX_DIR_MATCHES = 10
# Metadatos de Steam que no son partidas: no cuentan en tamaño, ficheros ni mtime (nombre exacto, sensible a mayúsculas).
IGNORED_FILES = frozenset({"steam_autocloud.vdf"})


@dataclass
class Candidate:
    pattern: str  # ruta absoluta, posiblemente con comodines
    rule: str  # `<raíz>:<subruta>` de la regla del manifiesto
    excludes: List[str] = field(default_factory=list)
    doubtful: bool = False  # ruta `d: true` del manifiesto (heurística, p. ej. LÖVE)


def _has_magic(p: str) -> bool:
    return glob.has_magic(p)


def base_dirs(g: ci.InstalledGame, home: Path) -> Dict[str, List[str]]:
    """Carpetas base de cada raíz para este juego (vacía = esa raíz no aplica)."""
    h = str(home)
    out: Dict[str, List[str]] = {
        "home": [h],
        "xdgData": [os.path.join(h, ".local/share")],
        "xdgConfig": [os.path.join(h, ".config")],
        "steamCloud": list(g.userdata[:MAX_DIR_MATCHES]),  # una por cuenta con carpeta del appid; mismo tope que un comodín
        "install": [g.install] if g.install else [],
    }
    if g.flatpak and not g.prefix:
        fp = os.path.join(h, ci.FLATPAK_LUTRIS)
        out["xdgData"].append(os.path.join(fp, "data"))
        out["xdgConfig"].append(os.path.join(fp, "config"))
    if g.prefix:
        users = ci.wine_users(g.prefix)
        for root, sub in (
            ("pfxRoaming", "AppData/Roaming"), ("pfxLocal", "AppData/Local"), ("pfxLocalLow", "AppData/LocalLow"),
            ("pfxDocs", "Documents"), ("pfxSaved", "Saved Games"),
        ):  # fmt: skip
            out[root] = [os.path.join(u, sub) for u in users]
        out["pfxProgData"] = [os.path.join(g.prefix, "drive_c", "ProgramData")]
    return out


def candidates(mg: Dict[str, Any], g: ci.InstalledGame, home: Path) -> List[Candidate]:
    """Rutas absolutas candidatas de un juego del manifiesto en esta Deck (sin comprobar que existan)."""
    bases = base_dirs(g, home)
    want = "win" if g.prefix else "linux"
    found: Dict[str, Candidate] = {}
    for rule in mg["paths"]:
        if rule["r"] != "steamCloud" and rule["os"] != want:  # steamCloud va siempre, con o sin prefijo
            continue
        for base in bases.get(rule["r"], []):
            pat = os.path.join(base, rule["p"])
            cand = found.setdefault(pat, Candidate(pat, f"{rule['r']}:{rule['p']}", list(rule["x"]), bool(rule.get("d"))))
            if not rule.get("d"):
                cand.doubtful = False  # la misma ruta como no dudosa gana
    # la carpeta gana al comodín de fichero que cuelga de ella
    for pat in list(found):
        if _has_magic(pat) and not _has_magic(os.path.dirname(pat)) and os.path.dirname(pat) in found:
            del found[pat]
    return list(found.values())


class Budget:
    """Tope de tiempo compartido por todas las mediciones de una petición."""

    def __init__(self, seconds: float = 30.0) -> None:
        self.deadline = time.monotonic() + seconds

    def spent(self) -> bool:
        return time.monotonic() > self.deadline


def _excluded(name: str, rel: str, patterns: Sequence[str]) -> bool:
    n, r = name.casefold(), rel.casefold()
    return any(fnmatch.fnmatchcase(n, p.casefold()) or fnmatch.fnmatchcase(r, p.casefold()) for p in patterns)


def measure(path: str, excludes: Sequence[str] = (), budget: Optional[Budget] = None) -> Dict[str, Any]:
    """{size, files, mtime, truncated} de un fichero o carpeta (hasta `MEASURE_DEPTH` niveles; sin enlaces ni contenido)."""
    size, files, newest, truncated = 0, 0, 0.0, False
    try:
        st = os.lstat(path)
    except OSError:
        return {"size": None, "files": None, "mtime": None, "truncated": False}
    if not os.path.isdir(path) or os.path.islink(path):
        return {"size": st.st_size, "files": 1, "mtime": st.st_mtime, "truncated": False}
    started = time.monotonic()
    scanned = 0
    stack = [(path, "", 0)]
    while stack:
        d, rel, depth = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(islice(it, MAX_ENTRIES_DIR + 1))
        except OSError:
            continue
        if len(entries) > MAX_ENTRIES_DIR:
            entries, truncated = entries[:MAX_ENTRIES_DIR], True
        for e in entries:
            scanned += 1
            if scanned > MAX_SCAN or time.monotonic() - started > MAX_SECONDS or (budget and budget.spent()):
                return {"size": size, "files": files, "mtime": newest or st.st_mtime, "truncated": True}
            erel = f"{rel}/{e.name}" if rel else e.name
            if _excluded(e.name, erel, excludes):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if depth + 1 < MEASURE_DEPTH:
                        stack.append((e.path, erel, depth + 1))
                    else:
                        truncated = True
                elif e.is_file(follow_symlinks=False):
                    if e.name in IGNORED_FILES:
                        continue
                    s = e.stat(follow_symlinks=False)
                    size, files, newest = size + s.st_size, files + 1, max(newest, s.st_mtime)
            except OSError:
                continue
    return {"size": size, "files": files, "mtime": newest or st.st_mtime, "truncated": truncated}


def _entry(path: str, rule: str, m: Optional[Dict[str, Any]], doubtful: bool = False) -> Dict[str, Any]:
    if m is None:
        return {"path": path, "exists": False, "mtime": None, "size": None, "files": None, "truncated": False, "rule": rule, "doubtful": doubtful}
    return {"path": path, "exists": True, **m, "rule": rule, "doubtful": doubtful}


def evaluate(c: Candidate, budget: Optional[Budget] = None) -> List[Dict[str, Any]]:
    """Entradas `{path, exists, mtime, size, files, truncated, rule, doubtful}` de un candidato. Sin coincidencias: una sola, `exists` falso."""
    if os.path.lexists(c.pattern):
        if _excluded(os.path.basename(c.pattern), os.path.basename(c.pattern), c.excludes) and not os.path.isdir(c.pattern):
            return [_entry(c.pattern, c.rule, None, c.doubtful)]
        return [_entry(c.pattern, c.rule, measure(c.pattern, c.excludes, budget), c.doubtful)]
    if not _has_magic(c.pattern):
        return [_entry(c.pattern, c.rule, None, c.doubtful)]
    try:
        hits = sorted(islice(glob.iglob(c.pattern), MAX_GLOB))
    except OSError:
        hits = []
    hits = [h for h in hits if not _excluded(os.path.basename(h), os.path.basename(h), c.excludes)]
    dirs = [h for h in hits if os.path.isdir(h) and not os.path.islink(h)]
    if dirs:
        return [_entry(h, c.rule, measure(h, c.excludes, budget), c.doubtful) for h in dirs[:MAX_DIR_MATCHES]]
    if not hits:
        return [_entry(c.pattern, c.rule, None, c.doubtful)]
    ms = [measure(h, c.excludes, budget) for h in hits]
    group = {
        "size": sum(m["size"] or 0 for m in ms),
        "files": sum(m["files"] or 0 for m in ms),
        "mtime": max(m["mtime"] or 0.0 for m in ms),
        "truncated": any(m["truncated"] for m in ms),
    }
    return [_entry(c.pattern, c.rule, group, c.doubtful)]
