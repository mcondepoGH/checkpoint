"""Versión propia del plugin (semver) y protocolo con el hub, leídos EN EJECUCIÓN del package.json instalado.

- Versión: `version` de package.json (semver `MAJOR.MINOR.PATCH[-pre][+build]`).
- Protocolo: `checkpointProtocol` (entero) de package.json; el hub anuncia el suyo en `GET /api/hook/ping`.
- La validación y la comparación de semver (`parse_semver`, `compare`, `is_newer`) viven en `checkpoint_core.version`
  (compartidas con el cliente de Linux); aquí solo queda lo propio del plugin: dónde está su package.json. Solo biblioteca estándar."""

import json
from pathlib import Path
from typing import Any, Dict

from checkpoint_core.version import parse_semver

PLUGIN_ROOT = Path(__file__).resolve().parent.parent  # carpeta del plugin: junto a main.py (py_modules/ cuelga de ella)


def plugin_dir(decky: Any) -> Path:
    """Carpeta instalada del plugin: `decky.DECKY_PLUGIN_DIR`, o la de este fichero (junto a main.py) si no existe."""
    d = getattr(decky, "DECKY_PLUGIN_DIR", None)
    return Path(d) if isinstance(d, str) and d else PLUGIN_ROOT


def read_version(directory: Any) -> Dict[str, Any]:
    """`{version, protocol}` del package.json de `directory`; None en lo que falte o no sea válido."""
    try:
        pkg = json.loads((Path(directory) / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": None, "protocol": None}
    if not isinstance(pkg, dict):
        return {"version": None, "protocol": None}
    v, p = pkg.get("version"), pkg.get("checkpointProtocol")
    return {
        "version": v if parse_semver(v) else None,
        "protocol": p if isinstance(p, int) and not isinstance(p, bool) and p >= 0 else None,
    }
