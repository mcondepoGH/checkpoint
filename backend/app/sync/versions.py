"""Versiones guardadas en data/versions/<juego>/ y reemplazo casi atómico de directorios."""

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .fingerprint import fingerprint

VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}(-\d+)?$")


def _fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "-"


def _version_key(name: str):
    """Orden cronológico por el nombre (AAAA-MM-DD_HHMMSS[-n]); el sufijo -n se compara como número."""
    stamp, _, n = name[:17], name[17:18], name[18:]
    return (stamp, int(n) if n.isdigit() else 0)


def list_versions(data_dir: Path, game: str, names: Optional[Dict[str, str]] = None) -> List[dict]:
    """Versiones guardadas de `game` (id). `names` ({id de origen: nombre}) añade el nombre visible a cada origen y,
    si se pasa, marca `unknown: True` en los orígenes que ya no son un dispositivo de la config (borrado o con el nombre
    antiguo; `hub` nunca lo es): se siguen pudiendo restaurar al hub."""
    marks = names is not None
    names = names or {}
    base = Path(data_dir) / "versions" / game
    out = []
    if base.is_dir():
        for d in sorted(base.iterdir(), key=lambda d: _version_key(d.name), reverse=True):
            if d.is_dir() and VERSION_RE.match(d.name):
                sources = []
                for s in sorted(d.iterdir()):
                    if s.is_dir():
                        fp = fingerprint(s)
                        item = {
                            "source": s.name,
                            "name": names.get(s.name, s.name),
                            "files": fp.files,
                            "mtime": _fmt(fp.mtime),
                        }
                        if marks and s.name != "hub" and s.name not in names:
                            item["unknown"] = True
                        sources.append(item)
                out.append({"version": d.name, "sources": sources})
    return out


def count_versions(data_dir: Path, game: str) -> int:
    base = Path(data_dir) / "versions" / game
    if not base.is_dir():
        return 0
    return sum(1 for d in base.iterdir() if d.is_dir() and not d.is_symlink() and VERSION_RE.match(d.name))


def latest_version(data_dir: Path, game: str) -> Optional[str]:
    """Id de la versión más reciente de `game` (orden cronológico), o None si no hay. Barato: solo lista nombres."""
    base = Path(data_dir) / "versions" / game
    if not base.is_dir():
        return None
    names = [d.name for d in base.iterdir() if d.is_dir() and not d.is_symlink() and VERSION_RE.match(d.name)]
    return max(names, key=_version_key) if names else None


def current_state(data_dir: Path, game: str) -> Optional[dict]:
    """Estado actual del hub de `game` ({id, mtime, files, size}) o None si no tiene ficheros. Solo `stat` (nada de
    hashes ni lecturas): lo usa el `/limit` que se consulta cada ~15 s. `id` cambia con cualquier subida (mtime máximo,
    nº de ficheros y tamaño) y sirve para saber si hay que recargar; `mtime` es la fecha de la última modificación."""
    root = Path(data_dir) / "hub" / game
    if not root.is_dir():
        return None
    mt = size = files = 0
    for p in root.rglob("*"):
        if p.is_symlink() or not p.is_file():
            continue
        st = p.stat()
        files += 1
        size += st.st_size
        mt = max(mt, int(st.st_mtime))
    if not files:
        return None
    return {"id": f"{mt}-{files}-{size}", "mtime": _fmt(mt), "files": files, "size": size}


def prune_versions(
    data_dir: Path, game: str, keep: int, log=lambda m: None, protect: Optional[str] = None
) -> List[str]:
    """Borra las versiones MÁS ANTIGUAS de `game` hasta dejar `keep` (0 = sin límite: no borra nada).

    Orden por el nombre de la versión (no por mtime). Nunca borra `protect` (la recién creada) ni deja
    menos de 1. Solo toca directorios reales dentro de data/versions/<slug>/ (symlinks se ignoran).
    Devuelve los nombres borrados. El llamador debe tener el lock del juego.
    """
    if keep <= 0:
        return []
    base = Path(data_dir) / "versions" / game
    root = (Path(data_dir) / "versions").resolve()
    if base.is_symlink() or not base.is_dir() or base.resolve().parent != root:
        return []
    base = base.resolve()
    dirs = sorted(
        (d for d in base.iterdir() if d.is_dir() and not d.is_symlink() and VERSION_RE.match(d.name)),
        key=lambda d: _version_key(d.name),
    )
    done: List[str] = []
    for d in dirs[: max(0, len(dirs) - keep)]:
        if d.name == protect or d.resolve().parent != base:
            continue
        try:
            shutil.rmtree(d)
        except OSError as e:
            log(f"no se pudo eliminar la versión {d.name}: {e}")
            continue
        done.append(d.name)
    if done:
        log(f"poda (máx. {keep}): eliminadas {len(done)} versiones antiguas: {', '.join(done)}")
    return done


def _new_version_dir(data_dir: Path, game: str) -> Path:
    base = Path(data_dir) / "versions" / game
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    # El nombre nuevo debe ordenar DESPUÉS de todas las existentes: si la poda borró `stamp` pero quedan
    # `stamp-1`... (mismo segundo), reutilizarlo lo dejaría como la más antigua (y protegida de la poda).
    last = max(
        (_version_key(x.name) for x in base.iterdir() if x.is_dir() and VERSION_RE.match(x.name)),
        default=None,
    )
    i = 0
    if last and last[0] >= stamp:
        stamp, i = last[0], last[1] + 1
    d = base / (stamp if i == 0 else f"{stamp}-{i}")
    while d.exists():
        i += 1
        d = base / f"{stamp}-{i}"
    d.mkdir()
    return d


def _replace_dir(src: Path, dst: Path):
    """Sustituye dst por copia de src de forma casi atómica."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    new = dst.with_name(dst.name + ".new")
    old = dst.with_name(dst.name + ".old")
    for t in (new, old):
        if t.exists():
            shutil.rmtree(t)
    shutil.copytree(src, new)
    if dst.exists():
        os.rename(dst, old)
    os.rename(new, dst)
    if old.exists():
        shutil.rmtree(old)
