"""Lógica del plugin de Checkpoint para la Steam Deck, sin depender de Decky (se prueba fuera de la Deck).

Solo biblioteca estándar: el cargador de Decky no garantiza `requests` ni `aiohttp` para los plugins. Las llamadas HTTP
son bloqueantes (`urllib`) y se ejecutan fuera del bucle con `asyncio.to_thread`.

Reglas que cumple todo este módulo:
- El secreto de la solicitud viaja SOLO en la cabecera `X-Pairing-Secret`; la clave `ckd_` SOLO en `Authorization`.
- Ni el secreto ni la clave se escriben en logs ni salen en el estado que ve la interfaz.
- La clave se guarda en un fichero con permisos 0600.
- No se siguen redirecciones ni se usan proxies del entorno (una redirección reenviaría las cabeceras secretas).
"""

import asyncio
import http.client
import json
import os
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple
from urllib.parse import urlsplit

DEVICE_NAME = "Steam Deck"
POLL_S = 3.0  # cada cuánto se pregunta al hub mientras la solicitud está pendiente
BACKOFF_MAX_S = 30.0  # espera máxima entre reintentos tras un error de red
TIMEOUT_S = 10.0
MAX_BODY = 64 * 1024  # el hub responde JSON pequeño; no se lee más
KEY_PREFIX = "ckd_"
SETTINGS_FILE = "settings.json"
DETAIL_MAX = 1500  # el detalle de un fallo se ve entero en la Deck (saneado antes de recortar)
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


# ---------------------------------------------------------------- nombre del dispositivo
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
        if ch == "\u200d":  # unión de emojis compuestos
            continue
        if cat[0] == "C" or cat in ("Zl", "Zp") or (cat == "Zs" and ch != " "):
            raise DeviceNameError("control")
    if not name.strip("."):
        raise DeviceNameError("dots")
    return name


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


def create_pairing(hub: str, name: str = DEVICE_NAME) -> HubResponse:
    return request_json("POST", f"{hub}/api/pairing/requests", body={"name": name, "os": "linux"})


def poll_pairing(hub: str, request_id: str, secret: str) -> HubResponse:
    return request_json("GET", f"{hub}/api/pairing/requests/{request_id}", headers={"X-Pairing-Secret": secret})


def ping(hub: str, key: str) -> HubResponse:
    return request_json("GET", f"{hub}/api/hook/ping", headers={"Authorization": f"Bearer {key}"})


# ---------------------------------------------------------------- ajustes (clave incluida)
def load_settings(directory: str, name: str = SETTINGS_FILE) -> Dict[str, Any]:
    try:
        with open(os.path.join(directory, name), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(directory: str, data: Dict[str, Any], name: str = SETTINGS_FILE) -> None:
    """Escritura atómica con permisos 0600 desde el principio (el fichero temporal nace ya privado)."""
    os.makedirs(directory, exist_ok=True)
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


# Claves de Checkpoint (ck_/ckd_...) y steamid64 (17 cifras que empiezan por 7656119): nunca salen en un log ni en la interfaz
_SENSITIVE = re.compile(r"\bckd?_[A-Za-z0-9_-]+|\b7656119\d{10}\b")


def redact(text: str, *secrets: Optional[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return _SENSITIVE.sub("***", text)


def describe_error(e: BaseException, *secrets: Optional[str], limit: int = DETAIL_MAX) -> str:
    """`Tipo: mensaje` de una excepción, saneado y recortado, para el log y para el detalle que ve la interfaz.
    Un HubApiError/HubNetworkError añade el endpoint (método y ruta, sin servidor ni consulta) y el estado."""
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
Sleep = Callable[[float], Awaitable[None]]


class Pairing:
    """Máquina de estados de la vinculación. `state()` es lo único que ve la interfaz y NUNCA lleva secretos.

    status: unlinked | waiting | linked | rejected | expired | error
    error:  connection | rate_limited | busy | hub_error | bad_response | settings | name_invalid   (solo con status=error)
    """

    def __init__(
        self,
        settings_dir: str,
        log: Callable[[str], None] = lambda _m: None,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll_s: Optional[float] = None,
    ):
        self._dir, self._log, self._sleep, self._clock = settings_dir, log, sleep, clock
        self._poll_s = POLL_S if poll_s is None else poll_s
        self._task: Optional["asyncio.Task[None]"] = None
        self._secret: Optional[str] = None  # secreto de la solicitud: solo en memoria
        self._deadline = 0.0
        s = load_settings(settings_dir)
        self.hub_url: str = s.get("hub_url") if isinstance(s.get("hub_url"), str) else ""
        self.device_name: str = DEVICE_NAME
        try:
            self.device_name = normalize_device_name(s.get("device_name", DEVICE_NAME))
        except DeviceNameError:
            pass  # ajuste ilegible o inválido: se vuelve al nombre por defecto
        self._paired_name: Optional[str] = s.get("paired_name") if isinstance(s.get("paired_name"), str) else None
        self._status = "linked" if self._has_key(s) else "unlinked"
        self._device: Optional[str] = s.get("device") if self._status == "linked" else None
        self._code: Optional[str] = None
        self._error: Optional[str] = None
        self._retry = False  # hay problemas de red, se sigue reintentando
        self._wait_s = 0

    @staticmethod
    def _has_key(s: Dict[str, Any]) -> bool:
        return isinstance(s.get("key"), str) and s["key"].startswith(KEY_PREFIX) and bool(s.get("hub_url"))

    # ---- lectura
    def state(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "hub_url": self.hub_url,
            "status": self._status,
            "device_name": self.device_name,
        }
        if self._status == "waiting":
            out["code"] = self._code
            out["seconds_left"] = max(0, int(self._deadline - self._clock() + 0.999))
            out["retrying"] = self._retry
        if self._status == "linked":
            out["device"] = self._device
            # El hub no renombra solo: si el nombre cambió tras vincular, el panel lo avisa (la clave se conserva)
            out["name_changed"] = self._paired_name is not None and self._paired_name != self.device_name
        if self._status == "error":
            out["error"] = self._error
            out["wait_s"] = self._wait_s
        return out

    def key(self) -> Optional[str]:
        """La clave, solo para uso interno del backend (ping); nunca se devuelve a la interfaz."""
        s = load_settings(self._dir)
        return s["key"] if self._has_key(s) else None

    # ---- acciones
    def set_hub_url(self, raw: str) -> str:
        url = normalize_hub_url(raw)  # lanza HubUrlError
        if url != self.hub_url:
            self.cancel()
            s = load_settings(self._dir)
            s.pop("key", None)  # una clave sirve para un hub concreto
            s.pop("device", None)
            s.pop("paired_name", None)
            self._paired_name = None
            s["hub_url"] = url
            save_settings(self._dir, s)
            self.hub_url = url
            self._set("unlinked")
        return url

    def set_device_name(self, raw: Any) -> str:
        name = normalize_device_name(raw)  # lanza DeviceNameError
        if name != self.device_name:
            s = load_settings(self._dir)
            s["device_name"] = name  # no toca la clave ni el dispositivo vinculado
            save_settings(self._dir, s)
            self.device_name = name
        return name

    def unlink(self) -> None:
        """Borra la clave local. La revocación real (que la clave deje de valer) se hace en el hub."""
        self.cancel()
        s = load_settings(self._dir)
        s.pop("key", None)
        s.pop("device", None)
        s.pop("paired_name", None)
        save_settings(self._dir, s)
        self._paired_name = None
        self._set("unlinked")

    def start(self) -> None:
        if not self.hub_url:
            raise HubUrlError("empty")
        self.cancel()
        self._set("waiting")
        self._code = None
        self._task = asyncio.get_running_loop().create_task(self._run(self.hub_url, self.device_name))

    def cancel(self) -> None:
        t, self._task = self._task, None
        if t is not None and not t.done():
            t.cancel()
        self._secret = None
        if self._status == "waiting":
            self._set("linked" if self.key() else "unlinked")

    async def close(self) -> None:
        """Para `_unload`: cancela y espera a que la tarea acabe."""
        t = self._task
        self.cancel()
        if t is not None:
            await asyncio.gather(t, return_exceptions=True)

    # ---- interno
    def _set(self, status: str, error: Optional[str] = None, wait_s: int = 0) -> None:
        self._status, self._error, self._wait_s, self._retry = status, error, wait_s, False
        if status != "waiting":
            self._code = None
        if status == "unlinked":
            self._device = None

    async def _run(self, hub: str, name: str) -> None:
        try:
            await self._pair(hub, name)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # un fallo inesperado nunca debe dejar la tarea muda
            self._log(f"vinculación: fallo inesperado ({type(e).__name__})")
            self._set("error", "hub_error")
        finally:
            self._secret = None

    async def _pair(self, hub: str, name: str) -> None:
        try:
            r = await asyncio.to_thread(create_pairing, hub, name)
        except HubNetworkError as e:
            self._log(f"vinculación: no se pudo crear la solicitud ({e})")
            return self._set("error", "connection")
        if r.status == 429 or r.status == 503:
            wait = r.retry_after or 0
            self._log(f"vinculación: el hub pide esperar ({r.status}, {wait} s)")
            return self._set("error", "rate_limited" if r.status == 429 else "busy", wait)
        if r.status == 400 and r.error_code == "err.pairing.name_invalid":
            self._log("vinculación: el hub no acepta el nombre del dispositivo")
            return self._set("error", "name_invalid")
        b = r.body if isinstance(r.body, dict) else {}
        if r.status != 201 or not all(isinstance(b.get(k), str) for k in ("id", "code", "secret")):
            self._log(f"vinculación: respuesta inesperada al crear ({r.status} {r.error_code or ''})".rstrip())
            return self._set("error", "hub_error" if r.status != 201 else "bad_response")
        rid, self._secret, self._code = b["id"], b["secret"], b["code"]
        ttl = b["expires_in"] if isinstance(b.get("expires_in"), (int, float)) else 600
        self._deadline = self._clock() + ttl
        self._log(f"vinculación: solicitud creada, caduca en {int(ttl)} s")
        await self._wait(hub, rid, name)

    async def _wait(self, hub: str, rid: str, name: str) -> None:
        failures = 0
        delay = self._poll_s
        while True:
            left = self._deadline - self._clock()
            if left <= 0:
                self._log("vinculación: caducó sin respuesta")
                return self._set("expired")
            await self._sleep(min(delay, left))
            if self._clock() >= self._deadline:
                continue
            secret = self._secret
            if secret is None:
                return
            try:
                r = await asyncio.to_thread(poll_pairing, hub, rid, secret)
            except HubNetworkError as e:
                failures += 1
                self._retry = True
                delay = min(self._poll_s * 2**failures, BACKOFF_MAX_S)
                self._log(f"vinculación: sin conexión ({e}), reintento en {int(delay)} s")
                continue
            if r.status == 429:
                self._retry = True
                delay = float(r.retry_after or self._poll_s * 2)
                self._log(f"vinculación: el hub pide esperar {int(delay)} s")
                continue
            if r.status >= 500:  # el hub o un proxy caído: se reintenta como una caída de red
                failures += 1
                self._retry = True
                delay = min(self._poll_s * 2**failures, BACKOFF_MAX_S)
                continue
            failures, delay, self._retry = 0, self._poll_s, False
            b = r.body if isinstance(r.body, dict) else {}
            if r.status == 404:  # caducada, desconocida o ya recogida
                self._log("vinculación: el hub no conoce la solicitud")
                return self._set("expired")
            if r.status != 200:
                self._log(f"vinculación: respuesta inesperada al consultar ({r.status} {r.error_code or ''})".rstrip())
                return self._set("error", "hub_error")
            st = b.get("status")
            if st == "pending":
                exp = b.get("expires_in")
                if isinstance(exp, (int, float)):
                    self._deadline = self._clock() + exp  # el reloj del hub manda
                continue
            if st == "rejected":
                self._log("vinculación: rechazada en el hub")
                return self._set("rejected")
            if st == "accepted":
                return self._accepted(hub, b, name)
            self._log("vinculación: estado desconocido del hub")
            return self._set("error", "bad_response")

    def _accepted(self, hub: str, b: Dict[str, Any], name: str) -> None:
        key, device = b.get("key"), b.get("device")
        if not (isinstance(key, str) and key.startswith(KEY_PREFIX) and isinstance(device, str) and device):
            self._log("vinculación: respuesta aceptada sin clave o dispositivo válidos")
            return self._set("error", "bad_response")
        try:
            s = load_settings(self._dir)
            s.update({"hub_url": hub, "device": device, "key": key, "paired_name": name})
            save_settings(self._dir, s)
        except OSError as e:
            self._log(f"vinculación: no se pudo guardar la clave ({type(e).__name__})")
            return self._set("error", "settings")
        self._device, self._paired_name = device, name
        self._set("linked")
        self._log(f"vinculación: vinculada al dispositivo {device}")


# ---------------------------------------------------------------- comprobar conexión
_UNSET: Any = object()


def _proto(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def compat(plugin_protocol: Optional[int], hub_protocol: Optional[int], min_plugin_protocol: Optional[int]) -> str:
    """Compatibilidad plugin <-> hub por protocolo (enteros):
    - `hub_old`: el hub no anuncia protocolo (versión vieja): AVISO, no bloquea.
    - `plugin_unknown`: este plugin no declara `checkpointProtocol` (package.json ilegible): no se puede juzgar, no bloquea.
    - `plugin_outdated`: protocolo del plugin < `min_plugin_protocol` del hub: BLOQUEADO hasta actualizar.
    - `ok`."""
    if hub_protocol is None or min_plugin_protocol is None:
        return "hub_old"
    if plugin_protocol is None:
        return "plugin_unknown"
    return "plugin_outdated" if plugin_protocol < min_plugin_protocol else "ok"


def check_connection(hub: str, key: Optional[str], plugin_protocol: Any = _UNSET) -> Tuple[str, Dict[str, Any]]:
    """(resultado, datos). resultado: ok | not_linked | unauthorized | rate_limited | connection | hub_error.
    Con `plugin_protocol` (puede ser None) el resultado `ok` añade `compat`, `protocol`, `min_plugin_protocol` y `plugin_protocol`."""
    if not key or not hub:
        return "not_linked", {}
    try:
        r = ping(hub, key)
    except HubNetworkError:
        return "connection", {}
    if r.status == 200 and isinstance(r.body, dict) and r.body.get("ok") is True:
        data: Dict[str, Any] = {"device": r.body.get("device") if isinstance(r.body.get("device"), str) else None}
        if plugin_protocol is not _UNSET:
            hp, mp = _proto(r.body.get("protocol")), _proto(r.body.get("min_plugin_protocol"))
            data.update(
                compat=compat(plugin_protocol, hp, mp), protocol=hp, min_plugin_protocol=mp, plugin_protocol=plugin_protocol
            )
        return "ok", data
    if r.status == 401:
        return "unauthorized", {}
    if r.status == 429:
        return "rate_limited", {"wait_s": r.retry_after or 0}
    return "hub_error", {}
