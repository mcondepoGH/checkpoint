"""Validación de rutas Linux. La ruta de la carpeta del juego y el manifiesto que da el hub son DATOS NO CONFIABLES.

- `validate_game_path`: absoluta, sin `..`, sin NUL; nunca el directorio personal ni un padre suyo, carpetas del sistema,
  carpetas de usuario como `~/.config` (sí sus subcarpetas) ni las carpetas protegidas (p. ej. la config del cliente); la
  carpeta del juego no puede ser un enlace simbólico ni apuntar a una carpeta prohibida.
- `validate_rel` y `parse_hub_manifest`: cada ruta relativa del manifiesto del hub se valida ANTES de escribir nada.

Solo rutas Linux. Las de Windows no entran aquí.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_REL = 1024
MAX_COMPONENT = 255

SYSTEM_EXACT = {
    "/", "/home", "/run", "/usr", "/etc", "/var", "/tmp", "/opt", "/boot", "/dev", "/proc", "/sys", "/bin", "/sbin",
    "/lib", "/lib64", "/root", "/mnt", "/media", "/srv", "/run/media",
}  # fmt: skip
SYSTEM_TREES = ("/usr", "/etc", "/boot", "/dev", "/proc", "/sys", "/bin", "/sbin", "/lib", "/lib64")
HOME_KEEP = (  # carpetas del usuario que nunca pueden ser (ni contener) la carpeta de un juego; sus subcarpetas sí
    ".local", ".local/share", ".config", ".var", ".var/app", ".steam", ".cache",
)  # fmt: skip


class PathNotAllowed(ValueError):
    """La ruta del hub no es aceptable («ruta no permitida»)."""


class BadManifest(ValueError):
    """El manifiesto del hub no es válido o no es seguro."""


def under(p: str, base: str) -> bool:
    return p == base or p.startswith(base.rstrip("/") + "/")


def _clean(raw: Any) -> str:
    if not isinstance(raw, str) or not raw or "\0" in raw or not raw.startswith("/"):
        raise PathNotAllowed("no absoluta")
    parts = raw.split("/")
    if ".." in parts:
        raise PathNotAllowed("con `..`")
    return "/" + "/".join(p for p in parts if p not in ("", "."))


def _forbidden(p: str, homes: Set[str], keep_inside: List[str], keep_around: List[str]) -> bool:
    """`keep_inside`: ni ellas, ni padres, ni lo de dentro. `keep_around`: ni ellas ni sus padres."""
    if p in SYSTEM_EXACT or any(under(p, t) for t in SYSTEM_TREES):
        return True
    if os.path.dirname(p) == "/home":  # el directorio personal de cualquier usuario
        return True
    for item in homes | set(keep_around):
        if under(item, p):
            return True
    for item in keep_inside:
        if under(item, p) or under(p, item):
            return True
    return False


def validate_game_path(raw: Any, home: Path, protected: Sequence[Path] = ()) -> Path:
    """Ruta real (resuelta) de la carpeta del juego, o PathNotAllowed. No crea nada."""
    p = _clean(raw)
    homes = {str(home), os.path.realpath(home)}
    keep_around = [f"{h}/{k}" for h in homes for k in HOME_KEEP]
    keep_inside = [str(x) for x in protected] + [os.path.realpath(x) for x in protected]
    if _forbidden(p, homes, keep_inside, keep_around):
        raise PathNotAllowed("carpeta protegida")
    if os.path.islink(p):
        raise PathNotAllowed("enlace simbólico")
    real = os.path.realpath(p)
    if real != p and _forbidden(real, homes, keep_inside, keep_around):
        raise PathNotAllowed("la ruta real es una carpeta protegida")
    return Path(real)


def validate_rel(rel: Any) -> str:
    """Ruta relativa segura de un fichero del manifiesto del hub (`\\` -> `/`), o BadManifest."""
    if not isinstance(rel, str) or not rel or "\0" in rel or len(rel) > MAX_REL:
        raise BadManifest("ruta inválida")
    r = rel.replace("\\", "/")
    parts = r.split("/")
    if (
        r.startswith("/")
        or any(x in ("", ".", "..") for x in parts)
        or any(len(x.encode()) > MAX_COMPONENT for x in parts)
    ):
        raise BadManifest("ruta inválida")
    return r


def parse_hub_manifest(raw: Any, max_files: int, max_file_bytes: int) -> List[Dict[str, Any]]:
    """Entradas normalizadas {path, sha256, size, mtime} o BadManifest. Sin duplicados ni choques fichero/carpeta."""
    if not isinstance(raw, list) or not raw:
        raise BadManifest("vacío")
    if len(raw) > max_files:
        raise BadManifest("demasiados ficheros")
    out, seen, dirs = [], set(), set()
    for e in raw:
        if not isinstance(e, dict):
            raise BadManifest("entrada")
        rel = validate_rel(e.get("path"))
        sha, size, mtime = e.get("sha256"), e.get("size"), e.get("mtime")
        sha = sha.lower() if isinstance(sha, str) else ""
        if not SHA_RE.match(sha):
            raise BadManifest("sha256")
        if not (isinstance(size, int) and not isinstance(size, bool) and 0 <= size <= max_file_bytes):
            raise BadManifest("tamaño")
        if not (isinstance(mtime, (int, float)) and not isinstance(mtime, bool) and 0 <= mtime < 2**40):
            raise BadManifest("mtime")
        if rel in seen:
            raise BadManifest("repetida")
        seen.add(rel)
        parts = rel.split("/")
        dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
        out.append({"path": rel, "sha256": sha, "size": size, "mtime": int(mtime)})
    if seen & dirs:
        raise BadManifest("fichero y carpeta con el mismo nombre")
    return out
