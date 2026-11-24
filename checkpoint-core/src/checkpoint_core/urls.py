"""URL del hub: `http(s)://host[:puerto]` sin barra final."""

from typing import Any
from urllib.parse import urlsplit


class HubUrlError(ValueError):
    """`code`: empty | scheme | credentials | path | invalid."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_hub_url(raw: Any) -> str:
    """`http(s)://host[:puerto]` sin barra final. Rechaza credenciales, rutas, parámetros y fragmentos."""
    if not isinstance(raw, str) or not raw.strip():
        raise HubUrlError("empty")
    text = raw.strip()
    if any(c.isspace() or ord(c) < 32 for c in text):
        raise HubUrlError("invalid")
    try:
        parts = urlsplit(text)
        host, port = parts.hostname, parts.port  # `port` lanza ValueError si es inválido
    except ValueError:
        raise HubUrlError("invalid") from None
    if parts.scheme not in ("http", "https"):
        raise HubUrlError("scheme")
    if "@" in parts.netloc:
        raise HubUrlError("credentials")
    if not host:
        raise HubUrlError("invalid")
    if parts.path not in ("", "/") or parts.query or parts.fragment or text.endswith(("?", "#")):
        raise HubUrlError("path")
    shown = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown}" + (f":{port}" if port else "")
