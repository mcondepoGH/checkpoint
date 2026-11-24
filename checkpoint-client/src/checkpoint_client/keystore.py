"""Dónde se guarda la clave `ckd_` de este equipo.

- Con llavero del sistema (Secret Service: GNOME Keyring, KWallet...) la clave vive allí: servicio `checkpoint-client`,
  usuario `<dispositivo>@<hub>` (el id de dispositivo lo da el hub al vincular y es estable; el hub evita que dos
  vinculaciones distintas compartan entrada). `settings.json` solo guarda metadatos y `key_store: "keyring"`.
- Sin llavero (backend `fail`/`null`, biblioteca ausente o error al usarlo) la clave se queda en `settings.json`
  (0600, carpeta 0700) con `key_store: "file"`.
- Migración: una clave en `settings.json` (formato anterior o alternativa a fichero) se mueve al llavero en cuanto se
  puede. Se escribe, se lee de vuelta y solo entonces se quita del fichero: si algo falla, la clave no se pierde.

La clave nunca se imprime ni se registra desde aquí. Los errores del llavero se tragan a propósito (devuelven el
resultado seguro: usar el fichero); no se incluyen en ningún mensaje porque su texto lo decide el backend.
"""

import os
import sys
from typing import Any, Dict, Optional

from checkpoint_core.protocol import KEY_PREFIX

from . import settings, texts

SERVICE = "checkpoint-client"
KEYRING = "keyring"
FILE = "file"
STORE_FIELD = "key_store"

_migration_warned = False  # el aviso de migración fallida sale una vez por ejecución, no en cada comando


def _backend():
    """El backend de llavero en uso, o None si no hay biblioteca o solo hay un backend que no guarda nada."""
    try:
        import keyring
        from keyring.backends import fail, null
    except ImportError:
        return None
    try:
        kr = keyring.get_keyring()
    except Exception:  # noqa: BLE001  (un backend roto al inicializarse equivale a no tener llavero)
        return None
    if isinstance(kr, (fail.Keyring, null.Keyring)):
        return None
    return kr


def keyring_available() -> bool:
    return _backend() is not None


def username(s: Dict[str, Any]) -> str:
    return f"{s.get('device') or ''}@{s.get('hub_url') or ''}"


def location_label(where: str) -> str:
    return texts.LOCATION_KEYRING if where == KEYRING else texts.LOCATION_FILE


def _keyring_get(s: Dict[str, Any]) -> Optional[str]:
    kr = _backend()
    if kr is None:
        return None
    try:
        value = kr.get_password(SERVICE, username(s))
    except Exception:  # noqa: BLE001
        return None
    return value if isinstance(value, str) and value.startswith(KEY_PREFIX) else None


def _keyring_put(s: Dict[str, Any], key: str) -> bool:
    """Guarda en el llavero y comprueba leyendo de vuelta; False si no hay llavero o no guardó de verdad."""
    kr = _backend()
    if kr is None:
        return False
    try:
        kr.set_password(SERVICE, username(s), key)
        return kr.get_password(SERVICE, username(s)) == key
    except Exception:  # noqa: BLE001
        return False


def _keyring_delete(s: Dict[str, Any]) -> None:
    kr = _backend()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, username(s))
    except Exception:  # noqa: BLE001  (no existía, o el llavero está bloqueado: no hay nada más que hacer aquí)
        pass


def store_key(cfg: str, s: Dict[str, Any], key: str) -> str:
    """Guarda la clave (y `s`, los metadatos) donde se pueda. Devuelve `keyring` o `file`."""
    s = dict(s)
    if _keyring_put(s, key):
        s.pop("key", None)
        s[STORE_FIELD] = KEYRING
        where = KEYRING
    else:
        s["key"] = key
        s[STORE_FIELD] = FILE
        where = FILE
    settings.save_settings(cfg, s)
    return where


def get_key(cfg: str, s: Dict[str, Any]) -> Optional[str]:
    """La clave de esta vinculación, o None. Migra al llavero una clave que esté en `settings.json` si se puede."""
    file_key = s.get("key")
    if isinstance(file_key, str) and file_key.startswith(KEY_PREFIX):
        _migrate(cfg, s, file_key)
        return file_key
    if s.get(STORE_FIELD) == KEYRING:
        return _keyring_get(s)
    return None


def keyring_unreadable(s: Dict[str, Any]) -> bool:
    """Hay una vinculación guardada en el llavero (`key_store=keyring`, con hub) pero la clave no se pudo leer
    (llavero bloqueado o clave borrada). Sin ajustes de vinculación no hay nada que leer: es «no vinculado»."""
    return s.get(STORE_FIELD) == KEYRING and bool(s.get("hub_url"))


def _warn_migration_failed(cfg: str) -> None:
    """Avisa por stderr (una vez por ejecución) si había llavero y no guardó la clave. Sin llavero no hay aviso."""
    global _migration_warned
    if _migration_warned or _backend() is None:
        return
    _migration_warned = True
    print(texts.KEYRING_MIGRATION_FAILED.format(path=settings_path(cfg)), file=sys.stderr)


def _migrate(cfg: str, s: Dict[str, Any], key: str) -> None:
    if not _keyring_put(s, key):
        _warn_migration_failed(cfg)
        return
    clean = {k: v for k, v in s.items() if k != "key"}
    clean[STORE_FIELD] = KEYRING
    try:
        settings.save_settings(cfg, clean)
    except OSError:
        return  # la clave queda en los dos sitios (nunca en ninguno); se reintenta en el siguiente uso
    print(texts.KEYRING_SAVED, file=sys.stderr)


def delete_key(cfg: str, s: Dict[str, Any]) -> None:
    """Borra la clave de donde esté (llavero y fichero) y la anota en `settings.json`; el resto de ajustes se queda."""
    _keyring_delete(s)
    clean = {k: v for k, v in s.items() if k not in ("key", STORE_FIELD)}
    settings.save_settings(cfg, clean)


def settings_path(cfg: str) -> str:
    return os.path.join(cfg, settings.SETTINGS_FILE)
