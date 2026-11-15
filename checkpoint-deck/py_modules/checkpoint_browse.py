"""Ruta inicial del selector nativo de Decky (`openFilePicker`). El backend de Decky (`filepicker_ls`) lanza si la ruta no
existe, no es una carpeta o no se puede leer, y su frontend revienta entonces con `TypeError: theError.match is not a
function` (el error le llega como objeto, no como texto). Aquí se comprueba antes y se degrada: ruta -> home -> `/`.
Solo lectura; nunca lanza."""

import os
from pathlib import Path
from typing import Any

SYSTEM_NAMES = ("@Recycle", "@Recently-Snapshot")


def _blocked(path: str) -> bool:
    return any(p.startswith(".@") or p in SYSTEM_NAMES for p in path.split("/") if p)


def _usable(raw: Any) -> str:
    """La ruta limpia (sin barra final) si es absoluta, existe, es carpeta y se puede listar; si no, cadena vacía."""
    try:
        if not isinstance(raw, str) or "\0" in raw:
            return ""
        p = raw.strip()
        if not p.startswith("/") or ".." in p.split("/"):
            return ""
        p = p.rstrip("/") or "/"
        if _blocked(p) or _blocked(os.path.realpath(p)):
            return ""
        with os.scandir(p):  # lo mismo que hará `iterdir()` de Decky: falla si no existe, no es carpeta o no hay permiso
            pass
        return p
    except OSError:
        return ""


def usable_start(raw: Any, home: Path) -> str:
    """Ruta con la que abrir el selector: `raw` si es usable; si no el home; si tampoco, `/`."""
    return _usable(raw) or _usable(str(home)) or "/"
