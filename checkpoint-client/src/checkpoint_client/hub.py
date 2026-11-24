"""Vinculación con el hub y HTTP síncrono (copia adaptada de `checkpoint_hub.py` del plugin, sin asyncio ni Decky).

Solo biblioteca estándar. Reglas de todo el módulo:
- El secreto de la solicitud viaja SOLO en la cabecera `X-Pairing-Secret`; la clave `ckd_` SOLO en `Authorization`.
- Ni el secreto ni la clave se escriben en logs, mensajes ni excepciones (ver `redact`).
- No se siguen redirecciones ni se usan proxies del entorno (una redirección reenviaría las cabeceras secretas).
"""

import http.client
import json
import re
import socket
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlsplit

DEVICE_NAME = "Linux"  # solo si el nombre del equipo no sirve como nombre visible
POLL_S = 3.0  # cada cuánto se pregunta al hub mientras la solicitud está pendiente
BACKOFF_MAX_S = 30.0  # espera máxima entre reintentos tras un error de red
TIMEOUT_S = 10.0
MAX_BODY = 64 * 1024  # el hub responde JSON pequeño; no se lee más
KEY_PREFIX = "ckd_"
NAME_MAX = 64  # igual que `NAME_MAX` del hub (backend/app/config/models.py)


# ---------------------------------------------------------------- URL del hub
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


# ---------------------------------------------------------------- nombre del equipo
class DeviceNameError(ValueError):
    """`code`: empty | spaces | too_long | slash | control | dots (las mismas reglas que `name_error` del hub)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_device_name(raw: Any) -> str:
    """Recorta los bordes y aplica las reglas del hub para un nombre visible; lanza DeviceNameError."""
    if not isinstance(raw, str) or not raw.strip():
        raise DeviceNameError("empty")
    name = raw.strip()
    if "  " in name:
        raise DeviceNameError("spaces")
    if len(name) > NAME_MAX:
        raise DeviceNameError("too_long")
    if "/" in name or "\\" in name:
        raise DeviceNameError("slash")
    for ch in name:
        cat = unicodedata.category(ch)
        if ch == "‍":  # unión de emojis compuestos
            continue
        if cat[0] == "C" or cat in ("Zl", "Zp") or (cat == "Zs" and ch != " "):
            raise DeviceNameError("control")
    if not name.strip("."):
        raise DeviceNameError("dots")
    return name


def default_device_name() -> str:
    """Nombre del equipo (recortado a 64) si es válido; si no, `DEVICE_NAME`."""
    try:
        return normalize_device_name(socket.gethostname()[:NAME_MAX])
    except DeviceNameError:
        return DEVICE_NAME


# ---------------------------------------------------------------- HTTP
class HubNetworkError(Exception):
    """No se pudo hablar con el hub (red caída, tiempo agotado, respuesta ilegible)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # el 3xx llega como HTTPError y se trata como error del hub


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


class HubResponse:
    def __init__(self, status: int, body: Any, headers: Dict[str, str]):
        self.status, self.body, self.headers = status, body, headers

    @property
    def error_code(self) -> Optional[str]:
        """`detail.code` de las respuestas de error del hub (`{detail:{code,params}}`)."""
        d = self.body.get("detail") if isinstance(self.body, dict) else None
        return d.get("code") if isinstance(d, dict) and isinstance(d.get("code"), str) else None

    @property
    def error_params(self) -> Dict[str, Any]:
        d = self.body.get("detail") if isinstance(self.body, dict) else None
        p = d.get("params") if isinstance(d, dict) else None
        return p if isinstance(p, dict) else {}

    @property
    def retry_after(self) -> Optional[int]:
        v = self.headers.get("retry-after", "")
        return int(v) if v.isdigit() else None


def request_json(
    method: str, url: str, *, headers: Optional[Dict[str, str]] = None, body: Any = None, max_body: int = MAX_BODY
) -> HubResponse:
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as r:
            status, raw, hh = r.status, r.read(max_body + 1), r.headers
    except urllib.error.HTTPError as e:
        status, raw, hh = e.code, e.read(max_body + 1), e.headers
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        # No se incluye `e` en el mensaje: podría traer la URL; basta el tipo
        raise HubNetworkError(type(e).__name__) from None
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw and len(raw) <= max_body else None
    except (UnicodeDecodeError, ValueError):
        parsed = None
    return HubResponse(status, parsed, {k.lower(): v for k, v in hh.items()})


def create_pairing(hub: str, name: str) -> HubResponse:
    return request_json("POST", f"{hub}/api/pairing/requests", body={"name": name, "os": "linux"})


def poll_pairing(hub: str, request_id: str, secret: str) -> HubResponse:
    return request_json("GET", f"{hub}/api/pairing/requests/{request_id}", headers={"X-Pairing-Secret": secret})


def ping(hub: str, key: str) -> HubResponse:
    return request_json("GET", f"{hub}/api/hook/ping", headers={"Authorization": f"Bearer {key}"})


# Claves de Checkpoint (ck_/ckd_...): nunca salen en un log ni en un mensaje
_SENSITIVE = re.compile(r"\bckd?_[A-Za-z0-9_-]+")


def redact(text: str, *secrets: Optional[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return _SENSITIVE.sub("***", text)


def describe_error(e: BaseException, *secrets: Optional[str], limit: int = 1500) -> str:
    """`Tipo: mensaje` de una excepción, saneado y recortado. Un HubApiError añade el endpoint (sin servidor) y el estado."""
    status = getattr(e, "status", None)
    if status is not None:
        code = getattr(e, "code", None)
        detail = f"estado {status}" + (f", código {code}" if code else "")
    else:
        detail = str(e)
    text = type(e).__name__ + (f": {detail}" if detail else "")
    endpoint = getattr(e, "endpoint", None)
    if endpoint:
        text += f" [{endpoint}]"
    return redact(text, *secrets)[:limit]


# ---------------------------------------------------------------- vinculación
class PairingError(Exception):
    """`code`: rejected | expired | connection | rate_limited | busy | name_invalid | hub_error | bad_response."""

    def __init__(self, code: str, wait_s: int = 0):
        super().__init__(code)
        self.code, self.wait_s = code, wait_s


def pair(
    hub: str,
    name: str,
    *,
    on_code: Optional[Callable[[str], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    poll_s: float = POLL_S,
) -> Tuple[str, str]:
    """Pide la vinculación, avisa del código de 6 dígitos (`on_code`) y espera a que se acepte en el hub.
    Devuelve (dispositivo, clave `ckd_`) o lanza PairingError. Ctrl+C (KeyboardInterrupt) cancela sin guardar nada."""
    try:
        r = create_pairing(hub, name)
    except HubNetworkError:
        raise PairingError("connection") from None
    if r.status in (429, 503):
        raise PairingError("rate_limited" if r.status == 429 else "busy", r.retry_after or 0)
    if r.status == 400 and r.error_code == "err.pairing.name_invalid":
        raise PairingError("name_invalid")
    b = r.body if isinstance(r.body, dict) else {}
    if r.status != 201:
        raise PairingError("hub_error")
    if not all(isinstance(b.get(k), str) for k in ("id", "code", "secret")):
        raise PairingError("bad_response")
    rid, secret = b["id"], b["secret"]
    ttl = b["expires_in"] if isinstance(b.get("expires_in"), (int, float)) else 600
    deadline = clock() + ttl
    if on_code:
        on_code(b["code"])
    failures, delay = 0, poll_s
    while True:
        left = deadline - clock()
        if left <= 0:
            raise PairingError("expired")
        sleep(min(delay, left))
        if clock() >= deadline:
            continue
        try:
            r = poll_pairing(hub, rid, secret)
        except HubNetworkError:
            failures += 1
            delay = min(poll_s * 2**failures, BACKOFF_MAX_S)
            continue
        if r.status == 429:
            delay = float(r.retry_after or poll_s * 2)
            continue
        if r.status >= 500:  # el hub o un proxy caído: se reintenta como una caída de red
            failures += 1
            delay = min(poll_s * 2**failures, BACKOFF_MAX_S)
            continue
        failures, delay = 0, poll_s
        if r.status == 404:  # caducada, desconocida o ya recogida
            raise PairingError("expired")
        if r.status != 200:
            raise PairingError("hub_error")
        b = r.body if isinstance(r.body, dict) else {}
        st = b.get("status")
        if st == "pending":
            if isinstance(b.get("expires_in"), (int, float)):
                deadline = clock() + b["expires_in"]  # el reloj del hub manda
            continue
        if st == "rejected":
            raise PairingError("rejected")
        if st == "accepted":
            key, device = b.get("key"), b.get("device")
            if not (isinstance(key, str) and key.startswith(KEY_PREFIX) and isinstance(device, str) and device):
                raise PairingError("bad_response")
            return device, key
        raise PairingError("bad_response")


# ---------------------------------------------------------------- comprobar conexión
def _proto(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def compat(client_protocol: int, hub_protocol: Optional[int], min_client_protocol: Optional[int]) -> str:
    """`hub_old`: el hub no anuncia protocolo (aviso, no bloquea). `plugin_outdated`: el protocolo del cliente es menor
    que `min_plugin_protocol` del hub (bloqueado hasta actualizar). `ok` en el resto."""
    if hub_protocol is None or min_client_protocol is None:
        return "hub_old"
    return "plugin_outdated" if client_protocol < min_client_protocol else "ok"


def check_connection(hub: str, key: Optional[str], client_protocol: int) -> Tuple[str, Dict[str, Any]]:
    """(resultado, datos). resultado: ok | not_linked | unauthorized | rate_limited | connection | hub_error.
    Con `ok`, los datos llevan `device`, `compat`, `protocol` y `min_plugin_protocol`."""
    if not key or not hub:
        return "not_linked", {}
    try:
        r = ping(hub, key)
    except HubNetworkError:
        return "connection", {}
    if r.status == 200 and isinstance(r.body, dict) and r.body.get("ok") is True:
        hp, mp = _proto(r.body.get("protocol")), _proto(r.body.get("min_plugin_protocol"))
        device = r.body.get("device") if isinstance(r.body.get("device"), str) else None
        return "ok", {
            "device": device,
            "compat": compat(client_protocol, hp, mp),
            "protocol": hp,
            "min_plugin_protocol": mp,
        }
    if r.status == 401:
        return "unauthorized", {}
    if r.status == 429:
        return "rate_limited", {"wait_s": r.retry_after or 0}
    return "hub_error", {}
