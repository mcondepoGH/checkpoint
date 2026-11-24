"""Ajustes del cliente en `~/.config/checkpoint-client` (o `$XDG_CONFIG_HOME/checkpoint-client`).

En esta fase la clave `ckd_` vive en `settings.json` con permisos 0600 (carpeta 0700); el llavero llegará aparte. La clave
nunca se imprime ni se registra.
"""

import json
import os
import tempfile
from typing import Any, Dict, Optional, Tuple

from checkpoint_core.protocol import KEY_PREFIX

SETTINGS_FILE = "settings.json"


def config_dir() -> str:
    override = os.environ.get("CHECKPOINT_CLIENT_CONFIG_DIR")
    if override:
        return override
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "checkpoint-client")


def load_settings(directory: str, name: str = SETTINGS_FILE) -> Dict[str, Any]:
    try:
        with open(os.path.join(directory, name), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(directory: str, data: Dict[str, Any], name: str = SETTINGS_FILE) -> None:
    """Escritura atómica con permisos 0600 desde el principio (el fichero temporal nace ya privado)."""
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".settings-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, os.path.join(directory, name))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def linked(s: Dict[str, Any]) -> Optional[Tuple[str, str, Optional[str]]]:
    """(hub, clave, dispositivo) si los ajustes tienen una vinculación válida; None si no."""
    key, hub = s.get("key"), s.get("hub_url")
    if not (isinstance(key, str) and key.startswith(KEY_PREFIX) and isinstance(hub, str) and hub):
        return None
    dev = s.get("device")
    return hub, key, dev if isinstance(dev, str) else None
