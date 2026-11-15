"""Manifiesto local de la carpeta de un juego: `[{path, sha256, size, mtime}]`.

Replica EXACTAMENTE las reglas del hub (`backend/app/sync/fingerprint.py`: `fingerprint` y `dir_manifest`): solo
ficheros regulares (ni enlaces simbólicos, ni ficheros especiales; las carpetas vacías no cuentan), rutas relativas con
`/`, orden por componentes de ruta (como `sorted(rglob("*"))`), mtime entero (`int(st_mtime)`), sha256 por bloques de
1 MiB. El hash del conjunto NO se calcula aquí: lo calcula el hub desde este manifiesto.
"""

import hashlib
import os
import stat
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

BLOCK = 1 << 20  # 1 MiB
MAX_FILES = 50_000  # el hub rechaza manifiestos con más (`MANIFEST_MAX_FILES`)
MAX_FILE_BYTES = 512 * 1024 * 1024  # tope por fichero del hub por defecto (`HOOK_MAX_FILE_MB`)
MAX_PATH = 1024  # `ManifestEntry.path` del hub


class LocalManifestError(Exception):
    """`code`: missing_dir | too_many_files | file_too_large | bad_name | unreadable. `path`: fichero afectado."""

    def __init__(self, code: str, path: Optional[str] = None):
        super().__init__(code)
        self.code, self.path = code, path


def _list_files(root: Path, max_files: int) -> List[Tuple[str, str]]:
    """[(ruta relativa con `/`, ruta absoluta)] de los ficheros regulares, sin seguir enlaces simbólicos."""
    out: List[Tuple[str, str]] = []
    stack = [("", str(root))]
    while stack:
        rel_dir, abs_dir = stack.pop()
        try:
            with os.scandir(abs_dir) as it:
                for e in it:
                    rel = f"{rel_dir}{e.name}"
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append((rel + "/", e.path))
                        elif e.is_file(follow_symlinks=False):
                            out.append((rel, e.path))
                    except OSError:
                        raise LocalManifestError("unreadable", rel) from None
                    if len(out) > max_files:
                        raise LocalManifestError("too_many_files")
        except OSError:
            raise LocalManifestError("unreadable", rel_dir.rstrip("/") or None) from None
    return out


def build_manifest(
    root: Path,
    *,
    max_files: int = MAX_FILES,
    max_file_bytes: int = MAX_FILE_BYTES,
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[Dict]:
    """Manifiesto de `root`. LocalManifestError si no existe, tiene demasiados ficheros, alguno supera el tope (se
    avisa ANTES de calcular ningún hash), un nombre no se puede enviar o algo no se puede leer."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise LocalManifestError("missing_dir")
    files = _list_files(root, max_files)
    for rel, _ in files:
        if "\\" in rel or len(rel) > MAX_PATH:
            raise LocalManifestError("bad_name", rel)  # el hub leería `\` como `/`: no igualaría la carpeta
        try:
            rel.encode("utf-8")
        except UnicodeEncodeError:
            raise LocalManifestError("bad_name", rel) from None
    files.sort(key=lambda f: f[0].split("/"))
    for rel, ap in files:
        try:
            if os.lstat(ap).st_size > max_file_bytes:
                raise LocalManifestError("file_too_large", rel)
        except OSError:
            raise LocalManifestError("unreadable", rel) from None
    out: List[Dict] = []
    for i, (rel, ap) in enumerate(files):
        h = hashlib.sha256()
        try:
            fd = os.open(ap, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(fd, "rb") as f:
                st0 = os.fstat(f.fileno())
                if not stat.S_ISREG(st0.st_mode):
                    continue  # cambió a otra cosa entre el listado y la lectura
                size = 0
                for chunk in iter(lambda: f.read(BLOCK), b""):
                    h.update(chunk)
                    size += len(chunk)
                    if size > max_file_bytes:
                        raise LocalManifestError("file_too_large", rel)
                st = os.fstat(f.fileno())
        except OSError:
            raise LocalManifestError("unreadable", rel) from None
        out.append({"path": rel, "sha256": h.hexdigest(), "size": size, "mtime": max(0, int(st.st_mtime))})
        if progress:
            progress(i + 1, len(files))
    return out
