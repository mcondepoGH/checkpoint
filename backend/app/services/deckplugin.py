"""Zip del plugin de Steam Deck (`Checkpoint.zip`): lectura única de los bytes, suma SHA-256 y versión del plugin.

La ruta es fija (`settings.DECK_ZIP`); nada de la petición llega al sistema de ficheros. Se sirven los MISMOS bytes
sobre los que se calculó la suma (el zip pesa decenas de KB), así que la suma de la cabecera siempre corresponde al
cuerpo aunque el fichero se sustituya a mitad de una petición. Caché por (mtime_ns, tamaño)."""

import hashlib
import io
import json
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..core import settings

FILENAME = "Checkpoint.zip"
VERSION_MEMBER = "Checkpoint/package.json"  # carpeta raíz del zip: ver checkpoint-deck/scripts/package.sh
MAX_BYTES = 32 * 1024 * 1024  # tope de lectura en memoria; el zip real pesa ~40 KB


@dataclass(frozen=True)
class Plugin:
    data: bytes
    sha256: str
    version: Optional[str]
    protocol: Optional[int] = None  # `checkpointProtocol` del package.json del plugin

    @property
    def size(self) -> int:
        return len(self.data)


_lock = threading.Lock()
_cache: dict = {}  # {ruta: (mtime_ns, size, Plugin)}


def _meta(data: bytes) -> tuple:
    """(versión, protocolo) del package.json del zip; None en lo que falte o no sea válido."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            pkg = json.loads(z.read(VERSION_MEMBER))
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        return None, None
    if not isinstance(pkg, dict):
        return None, None
    v, pr = pkg.get("version"), pkg.get("checkpointProtocol")
    v = v if isinstance(v, str) and 0 < len(v) <= 64 else None
    pr = pr if isinstance(pr, int) and not isinstance(pr, bool) and pr >= 0 else None
    return v, pr


def load(path: Optional[Path] = None) -> Optional[Plugin]:
    """El plugin empaquetado, o None si no existe (modo nativo sin `pnpm run zip`) o no es un fichero normal."""
    path = Path(path or settings.DECK_ZIP)
    try:
        st = path.stat()
        if not path.is_file() or st.st_size > MAX_BYTES:
            return None
        key = (st.st_mtime_ns, st.st_size)
        with _lock:
            hit = _cache.get(path)
            if hit and hit[0] == key:
                return hit[1]
        data = path.read_bytes()
    except OSError:
        return None
    version, proto = _meta(data)
    plugin = Plugin(data=data, sha256=hashlib.sha256(data).hexdigest(), version=version, protocol=proto)
    with _lock:
        _cache[path] = (key, plugin)
    return plugin


def info(plugin: Optional[Plugin]) -> dict:
    if plugin is None:
        return {"available": False}
    return {
        "available": True,
        "version": plugin.version,
        "protocol": plugin.protocol,
        "sha256": plugin.sha256,
        "size": plugin.size,
        "filename": FILENAME,
    }
