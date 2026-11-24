"""Vinculación con el hub y HTTP síncrono (versión adaptada de `checkpoint_hub.py` del plugin, sin asyncio ni Decky).

Las reglas puras (URL del hub, nombre del dispositivo, redacción, compatibilidad por protocolo) viven en `checkpoint_core`.
Solo biblioteca estándar y `checkpoint_core`. Reglas de todo el módulo:
- El secreto de la solicitud viaja SOLO en la cabecera `X-Pairing-Secret`; la clave `ckd_` SOLO en `Authorization`.
- Ni el secreto ni la clave se escriben en logs, mensajes ni excepciones (ver `checkpoint_core.redaction.redact`).
- No se siguen redirecciones ni se usan proxies del entorno (una redirección reenviaría las cabeceras secretas).
"""

import http.client
import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

from checkpoint_core.names import NAME_MAX, DeviceNameError, normalize_device_name
from checkpoint_core.protocol import KEY_PREFIX, compat, parse_protocol

DEVICE_NAME = "Linux"  # solo si el nombre del equipo no sirve como nombre visible
POLL_S = 3.0  # cada cuánto se pregunta al hub mientras la solicitud está pendiente
BACKOFF_MAX_S = 30.0  # espera máxima entre reintentos tras un error de red
TIMEOUT_S = 10.0
MAX_BODY = 64 * 1024  # el hub responde JSON pequeño; no se lee más


# ---------------------------------------------------------------- nombre del equipo
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
        hp, mp = parse_protocol(r.body.get("protocol")), parse_protocol(r.body.get("min_plugin_protocol"))
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
