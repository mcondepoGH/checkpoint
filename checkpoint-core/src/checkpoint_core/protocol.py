"""Clave de dispositivo y compatibilidad por protocolo (enteros) entre un cliente del hub y el hub."""

from typing import Any, Optional

KEY_PREFIX = "ckd_"  # prefijo de la clave de dispositivo


def parse_protocol(v: Any) -> Optional[int]:
    """El protocolo que anuncia el hub o declara un cliente: un entero >= 0 (un booleano no vale), si no None."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def compat(own_protocol: Optional[int], hub_protocol: Optional[int], min_protocol: Optional[int]) -> str:
    """Compatibilidad cliente <-> hub por protocolo (`own_protocol` es el del plugin o el del cliente):
    - `hub_old`: el hub no anuncia protocolo (versión vieja): AVISO, no bloquea.
    - `plugin_unknown`: este cliente no declara su protocolo (el plugin con un package.json ilegible): no se puede juzgar, no bloquea.
    - `plugin_outdated`: protocolo propio < `min_plugin_protocol` del hub: BLOQUEADO hasta actualizar.
    - `ok`."""
    if hub_protocol is None or min_protocol is None:
        return "hub_old"
    if own_protocol is None:
        return "plugin_unknown"
    return "plugin_outdated" if own_protocol < min_protocol else "ok"
