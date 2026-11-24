"""Papelera de datos (`data/trash/<AAAA-MM-DD_HHMMSS[-n]>/`): lo que la limpieza de datos sin dispositivo ni juego mueve
en vez de borrar. Cada entrada lleva un `manifest.json` (qué era, cuándo, cuánto ocupaba y de dónde salió, siempre con
rutas RELATIVAS a `data/`) y caduca pasados `settings.TRASH_TTL_DAYS` días: el mantenimiento programado la vacía.

Aquí solo hay mecánica de disco (sin config ni locks de juego: los toma el llamador). Todo lo que se mueve se resuelve
dentro de `data/` y nunca se sigue un enlace simbólico."""

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .resolution import iso
from .versions import VERSION_RE

log = logging.getLogger("checkpoint.sync")

# Carpetas de `data/` donde puede haber datos de un juego (la primera ruta de un movimiento debe ser una de ellas).
TOP = ("hub", "versions", "state", "status", "logs", "staging", "resolutions")
MANIFEST = "manifest.json"


class TrashError(Exception):
    """Error con código `err.orphans.*` (y params) para que el router lo convierta en respuesta HTTP."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def plain_name(name) -> bool:
    """¿Un solo componente de ruta, sin separadores, NUL, `.`/`..` ni punto inicial?"""
    return (
        isinstance(name, str)
        and name not in ("", ".", "..")
        and not name.startswith(".")
        and not any(c in name for c in "/\\\x00")
    )


def root(data_dir: Path) -> Path:
    return Path(data_dir) / "trash"


def tree_stats(path: Path) -> Tuple[int, int, float]:
    """(ficheros, bytes, mtime más reciente) de un fichero o carpeta, sin seguir enlaces simbólicos."""
    files = size = 0
    newest = 0.0
    stack = [path]
    while stack:
        p = stack.pop()
        try:
            st = p.lstat()
        except OSError:
            continue
        if p.is_symlink():
            continue
        if p.is_dir():
            try:
                stack.extend(p.iterdir())
            except OSError:
                pass
            continue
        files += 1
        size += st.st_size
        newest = max(newest, st.st_mtime)
    return files, size, newest


def new_entry(data_dir: Path) -> Path:
    """Crea y devuelve una carpeta de entrada nueva (nombre único aunque haya varias en el mismo segundo)."""
    base = root(data_dir)
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    i = 0
    while True:
        d = base / (stamp if i == 0 else f"{stamp}-{i}")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            i += 1


def move_in(data_dir: Path, entry: Path, rel_from: str, rel_to: str) -> dict:
    """Mueve `data/<rel_from>` a `<entry>/<rel_to>`. Rechaza enlaces simbólicos y rutas que no queden dentro de `data/`.
    Devuelve {from, to} (relativas)."""
    data = Path(data_dir).resolve()
    src = data / rel_from
    if src.is_symlink() or not os.path.lexists(src):
        raise TrashError("err.orphans.unsafe")
    if not src.resolve().is_relative_to(data):
        raise TrashError("err.orphans.unsafe")
    dst = entry / rel_to
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"from": rel_from, "to": rel_to}


def write_manifest(entry: Path, created: datetime, items: List[dict]) -> None:
    tmp = entry / f".{MANIFEST}.tmp"
    tmp.write_text(json.dumps({"created": iso(created), "items": items}), encoding="utf-8")
    os.replace(tmp, entry / MANIFEST)


def read_manifest(entry: Path) -> Optional[dict]:
    try:
        m = json.loads((entry / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return m if isinstance(m, dict) and isinstance(m.get("items"), list) else None


def _parse(s) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def created_of(entry: Path, manifest: Optional[dict] = None) -> datetime:
    """Cuándo se creó la entrada: el del manifiesto; sin él (o ilegible), el mtime de la carpeta."""
    t = _parse(manifest.get("created")) if manifest else None
    if t is not None and t.tzinfo is not None:
        return t
    try:
        return datetime.fromtimestamp(entry.stat().st_mtime, timezone.utc)
    except OSError:
        return datetime.now(timezone.utc)


def entries(data_dir: Path) -> Iterable[Path]:
    """Carpetas de entrada reales de la papelera (nombre con formato de fecha; sin enlaces simbólicos)."""
    base = root(data_dir)
    if not base.is_dir() or base.is_symlink():
        return []
    return sorted(
        (d for d in base.iterdir() if d.is_dir() and not d.is_symlink() and VERSION_RE.match(d.name)),
        key=lambda d: d.name,
    )


def purge_expired(data_dir: Path, ttl_days: float, now: Optional[datetime] = None) -> int:
    """Borra las entradas con más de `ttl_days` días (solo ellas). Devuelve cuántas. Nunca lanza por un fallo de disco."""
    now = now or datetime.now(timezone.utc)
    n = 0
    for d in entries(data_dir):
        if now - created_of(d, read_manifest(d)) <= timedelta(days=ttl_days):
            continue
        try:
            shutil.rmtree(d)
            n += 1
        except OSError as e:
            log.warning("papelera: no se pudo vaciar una entrada caducada (%s)", e.__class__.__name__)
    if n:
        log.info("papelera: %d entradas caducadas vaciadas", n)
    return n


def expires_of(entry: Path, manifest: Optional[dict], ttl_days: float) -> datetime:
    return created_of(entry, manifest) + timedelta(days=ttl_days)


def checked_moves(moves, entry: Path) -> List[Tuple[str, str]]:
    """Valida los movimientos de un manifiesto (que se puede haber tocado a mano): `from` = `<carpeta>/<juego>[.json]` o
    `versions/<juego>/<versión>/<origen>`, todo en nombres simples; `to` = relativo y dentro de la entrada."""
    out = []
    if not isinstance(moves, list) or not moves:
        raise TrashError("err.orphans.trash_unknown")
    for m in moves:
        f, t = (m.get("from"), m.get("to")) if isinstance(m, dict) else (None, None)
        if not isinstance(f, str) or not isinstance(t, str):
            raise TrashError("err.orphans.trash_unknown")
        fp, tp = f.split("/"), t.split("/")
        ok_from = fp[0] in TOP and (len(fp) == 2 or (fp[0] == "versions" and len(fp) == 4))
        if not ok_from or not all(plain_name(x) for x in fp[1:]) or not all(plain_name(x) for x in tp):
            raise TrashError("err.orphans.trash_unknown")
        if fp[0] == "versions" and len(fp) == 4 and not VERSION_RE.match(fp[2]):
            raise TrashError("err.orphans.trash_unknown")
        src = entry / t
        if src.is_symlink() or not os.path.lexists(src) or not src.resolve().is_relative_to(entry.resolve()):
            raise TrashError("err.orphans.trash_unknown")
        out.append((f, t))
    return out


def restore_moves(data_dir: Path, entry: Path, moves: List[Tuple[str, str]]) -> None:
    """Devuelve los movimientos a su sitio original. Si ALGÚN destino ya existe no mueve nada (409 para el llamador)."""
    data = Path(data_dir).resolve()
    for f, _ in moves:
        if os.path.lexists(data / f):
            raise TrashError("err.orphans.restore_conflict")
    for f, t in moves:
        dst = data / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(entry / t), str(dst))
        except OSError:
            raise TrashError("err.orphans.restore_failed") from None
