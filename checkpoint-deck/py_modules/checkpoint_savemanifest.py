"""Manifiesto propio de rutas de guardado (`save_manifest.json`, solo Steam y Lutris): carga, validación e índices.

Formato (`docs/structure.md`): `{"v": 1, "src": ..., "games": [{"n", "steam", "lutris", "slug"?, "paths": [{"r", "p", "os", "x"?, "d"?}]}]}`.
Este módulo NO decide de dónde sale el fichero (descarga del hub: decisión abierta): `SaveManifest.from_bytes` y
`SaveManifest.from_path` lo cargan y `ManifestStore` lo mantiene diferido y cacheado, con ruta configurable (por defecto
`save_manifest.json` en la carpeta de ajustes del plugin; `ManifestStore.set_bytes` lo recibe ya descargado, solo en memoria).
Se indexa al cargar por `steam`, por `lutris`, por `slug` (secundario) y por nombre normalizado (secundario). Una entrada
mal formada se descarta sin romper el resto. Solo biblioteca estándar; nunca escribe.
"""

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

FILE_NAME = "save_manifest.json"
MAX_BYTES = 64 * 1024 * 1024
SUPPORTED_V = 1
ROOTS = frozenset(
    {
        "home", "xdgData", "xdgConfig", "steamCloud", "install",
        "pfxRoaming", "pfxLocal", "pfxLocalLow", "pfxDocs", "pfxSaved", "pfxProgData",
    }
)  # fmt: skip
MAX_REL = 512


class SaveManifestError(ValueError):
    """Manifiesto ilegible, demasiado grande o de una versión que este plugin no entiende."""


def norm_name(text: Any) -> str:
    """Nombre normalizado para comparar: sin acentos ni marcas (™®©), en minúsculas y solo letras y dígitos."""
    if not isinstance(text, str):
        return ""
    t = unicodedata.normalize("NFKD", text.translate(str.maketrans("", "", "™®©℠")))
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in t if not unicodedata.combining(c)).lower())


def _rel_ok(p: Any) -> bool:
    if not isinstance(p, str) or not p or len(p) > MAX_REL or "\0" in p or p.startswith("/"):
        return False
    return not any(part in ("", ".", "..") for part in p.replace("\\", "/").split("/"))


def _clean_game(g: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(g, dict) or not isinstance(g.get("n"), str) or not g["n"]:
        return None
    steam = g.get("steam")
    steam = steam if isinstance(steam, int) and not isinstance(steam, bool) and steam > 0 else None
    lutris = g.get("lutris") if isinstance(g.get("lutris"), str) and g.get("lutris") else None
    slug = g.get("slug") if isinstance(g.get("slug"), str) and g.get("slug") else None
    paths: List[Dict[str, Any]] = []
    for p in g.get("paths") if isinstance(g.get("paths"), list) else []:
        if not isinstance(p, dict) or p.get("r") not in ROOTS or not _rel_ok(p.get("p")):
            continue
        x = p.get("x")
        paths.append(
            {
                "r": p["r"],
                "p": p["p"].replace("\\", "/"),
                "os": p.get("os") if p.get("os") in ("win", "linux") else "linux",
                "x": [e for e in x if isinstance(e, str) and e] if isinstance(x, list) else [],
                "d": p.get("d") is True,
            }
        )
    if not paths:
        return None
    return {"n": g["n"], "steam": steam, "lutris": lutris, "slug": slug, "paths": paths}


class SaveManifest:
    """Manifiesto cargado e indexado (solo lectura)."""

    def __init__(self, raw: Dict[str, Any]) -> None:
        if not isinstance(raw, dict) or raw.get("v") != SUPPORTED_V or not isinstance(raw.get("games"), list):
            raise SaveManifestError("esquema no soportado")
        self.src = raw.get("src") if isinstance(raw.get("src"), str) else ""
        self.games: List[Dict[str, Any]] = [c for c in map(_clean_game, raw["games"]) if c]
        self.by_steam: Dict[int, Dict[str, Any]] = {}
        self.by_lutris: Dict[str, Dict[str, Any]] = {}
        self.by_slug: Dict[str, Dict[str, Any]] = {}
        self.by_name: Dict[str, Dict[str, Any]] = {}
        for g in self.games:  # el primero gana ante un duplicado
            if g["steam"] is not None:
                self.by_steam.setdefault(g["steam"], g)
            if g["lutris"]:
                self.by_lutris.setdefault(g["lutris"], g)
            if g["slug"]:
                self.by_slug.setdefault(g["slug"], g)
            key = norm_name(g["n"])
            if key:
                self.by_name.setdefault(key, g)

    @classmethod
    def from_bytes(cls, raw: Union[bytes, str]) -> "SaveManifest":
        if len(raw) > MAX_BYTES:
            raise SaveManifestError("demasiado grande")
        try:
            return cls(json.loads(raw))
        except (ValueError, RecursionError) as e:
            if isinstance(e, SaveManifestError):
                raise
            raise SaveManifestError("JSON no válido") from e

    @classmethod
    def from_path(cls, path: Union[str, Path]) -> "SaveManifest":
        try:
            if os.path.getsize(path) > MAX_BYTES:
                raise SaveManifestError("demasiado grande")
            with open(path, "rb") as f:
                return cls.from_bytes(f.read())
        except OSError as e:
            raise SaveManifestError("no se pudo leer") from e


class ManifestStore:
    """Manifiesto con carga diferida y cacheada. `path` configurable (`set_path`); `set_bytes` lo recibe ya descargado.
    Con ruta, se recarga solo si cambian mtime o tamaño del fichero. `get()` devuelve None si no hay o no es válido."""

    def __init__(self, default_dir: Union[str, Path, None] = None, log: Callable[[str], None] = lambda _m: None) -> None:
        self._path: Optional[Path] = Path(default_dir) / FILE_NAME if default_dir else None
        self._log = log
        self._cache: Optional[SaveManifest] = None
        self._stamp: Any = None
        self._mem = False

    @property
    def path(self) -> Optional[Path]:
        return self._path

    def set_path(self, path: Union[str, Path]) -> None:
        self._path, self._cache, self._stamp, self._mem = Path(path), None, None, False

    def set_bytes(self, raw: Union[bytes, str]) -> None:
        """Usa estos bytes (ya descargados) en vez del fichero; solo en memoria, no se escribe nada. Lanza `SaveManifestError`."""
        self._cache, self._stamp, self._mem = SaveManifest.from_bytes(raw), None, True

    def get(self) -> Optional[SaveManifest]:
        if self._mem:
            return self._cache
        if self._path is None:
            return None
        try:
            st = os.stat(self._path)
        except OSError:
            self._cache, self._stamp = None, None
            return None
        stamp = (st.st_mtime_ns, st.st_size)
        if self._cache is None or stamp != self._stamp:
            try:
                self._cache = SaveManifest.from_path(self._path)
            except SaveManifestError as e:
                self._log(f"guardado: el manifiesto de rutas no es válido ({e})")
                self._cache = None
            self._stamp = stamp
        return self._cache
