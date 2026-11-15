"""Consulta de actualizaciones del plugin desde el hub (solo biblioteca estándar, SOLO LECTURA).

El plugin avisa de que hay una versión nueva pero NO la descarga ni la instala: la única forma de actualizar es
«Ajustes de Decky > Desarrollador > Instalar plugin desde URL» con `<hub>/api/deck/plugin`.

- `fetch_info`: consulta pública (sin clave `ckd_`) a `/api/deck/plugin/info`.
- `evaluate`: ¿hay versión ESTRICTAMENTE mayor? (semver propio, `checkpoint_version.py`) y si el hub es viejo.
Comprobado en una Deck real: «Instalar plugin desde URL» acepta la dirección http del hub. Que Decky recargue el
plugin sin reiniciar puede variar según la versión de Decky."""

from typing import Any, Dict, Optional

from checkpoint_hub import request_json
from checkpoint_version import is_newer, parse_semver


# ---------------------------------------------------------------- consulta (solo lectura)
def fetch_info(hub: str) -> Optional[Dict[str, Any]]:
    """`GET /api/deck/plugin/info` (público, sin clave). None si el hub no lo tiene (hub viejo) o no es JSON válido."""
    r = request_json("GET", f"{hub}/api/deck/plugin/info")
    return r.body if r.status == 200 and isinstance(r.body, dict) else None


def evaluate(
    info: Any, current: Optional[str], plugin_protocol: Optional[int], hub_protocol: Optional[int]
) -> Dict[str, Any]:
    """Decide qué mostrar. `state`: up_to_date | available | unavailable | unknown. Solo se ofrece una versión
    ESTRICTAMENTE mayor (semver; una pre-release es menor que su release). `reason` = `hub_old` si el hub no anuncia
    `protocol` (versión vieja: se avisa), si no None."""
    out: Dict[str, Any] = {"state": "unavailable", "current": current, "latest": None, "reason": None}
    if parse_semver(current) is None:
        out["state"] = "unknown"
        return out
    if not isinstance(info, dict) or info.get("available") is not True:
        return out
    latest = info.get("version")
    if parse_semver(latest) is None:
        return out
    out["latest"] = latest
    if not is_newer(latest, current):
        out["state"] = "up_to_date"
        return out
    out["state"] = "available"
    if hub_protocol is None:
        out["reason"] = "hub_old"
    return out
