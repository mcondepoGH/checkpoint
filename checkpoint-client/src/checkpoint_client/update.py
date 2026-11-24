"""Aviso de versión nueva del cliente (SOLO LECTURA: no descarga ni instala nada).

- Fuente: la última Release estable del repositorio en GitHub (API pública `releases/latest`, sin autenticación, sin
  token y sin enviar nunca la clave `ckd_`). `releases/latest` ya excluye borradores y pre-releases: solo hay canal estable.
- La versión del cliente sale de los assets de esa Release: `checkpoint_client-X.Y.Z-*.whl` (el wheel que sube el
  workflow de Release). Si la Release NO trae ningún wheel del cliente (por ejemplo una Release solo del hub), el
  resultado es «sin versión nueva»: se dice «al día» y no se avisa de nada. Un wheel con versión PEP 440 de
  pre-release (`1.0.0rc1`) tampoco cuenta (canal estable).
- Caché de la última respuesta correcta en el directorio de configuración (`update_cache.json`, 0600): 6 h como máximo.
  Un fallo no se cachea. Se compara siempre con la versión instalada en el momento, no al guardar.
- Tolerante a fallos: tiempo máximo corto, respuesta limitada y cualquier error se devuelve como `state: error` con un
  `reason` (nunca una traza). Solo biblioteca estándar; sin shell.

Para probar sin red real, `CHECKPOINT_CLIENT_RELEASES_URL` sustituye la URL de la API (la caché es por URL).
"""

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

from checkpoint_core.version import is_newer, parse_semver

from . import __version__, settings

REPO = "mcondepoGH/checkpoint"  # el mismo que usa el hub (`backend/app/core/updates.py`)
RELEASES_ENV = "CHECKPOINT_CLIENT_RELEASES_URL"
CACHE_FILE = "update_cache.json"
CACHE_TTL = 6 * 3600  # s de validez de una consulta correcta (como el hub)
TIMEOUT = 5.0  # s por consulta
MAX_BODY = 1_000_000  # bytes máximos de respuesta
_WHEEL = re.compile(r"^checkpoint_client-(\d+\.\d+\.\d+)-[^/\\\s]+\.whl$")


def releases_url() -> str:
    return os.environ.get(RELEASES_ENV) or f"https://api.github.com/repos/{REPO}/releases/latest"


class UpdateError(Exception):
    """`reason`: rate_limited | timeout | network | http | invalid."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------- consulta
class _HttpsRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            return None  # una redirección a http (o a otro esquema) se trata como error de la API
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsRedirects)


def fetch_latest(url: str, timeout: float = TIMEOUT) -> Dict[str, Any]:
    """`GET <url>` público y sin credenciales; devuelve la Release (dict) o lanza UpdateError."""
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"checkpoint-client/{__version__}"},
    )
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            raw = r.read(MAX_BODY + 1)
    except urllib.error.HTTPError as e:
        raise UpdateError("rate_limited" if e.code in (403, 429) else "http") from None
    except (socket.timeout, TimeoutError):
        raise UpdateError("timeout") from None
    except urllib.error.URLError as e:
        raise UpdateError("timeout" if isinstance(e.reason, (socket.timeout, TimeoutError)) else "network") from None
    except OSError:
        raise UpdateError("network") from None
    if len(raw) > MAX_BODY:
        raise UpdateError("invalid")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise UpdateError("invalid") from None
    if not isinstance(data, dict):
        raise UpdateError("invalid")
    return data


# ---------------------------------------------------------------- wheel de la Release
def parse_wheel_version(name: Any) -> Optional[str]:
    """`checkpoint_client-X.Y.Z-py3-none-any.whl` -> `X.Y.Z` (semver válido); si no, None."""
    if not isinstance(name, str):
        return None
    m = _WHEEL.match(name)
    return m.group(1) if m and parse_semver(m.group(1)) else None


def pick_wheel(release: Any) -> Optional[Tuple[str, str]]:
    """(versión, url de descarga https) del wheel más alto de una Release estable; None si no hay ninguno."""
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    assets = release.get("assets")
    best: Optional[Tuple[str, str]] = None
    for a in assets if isinstance(assets, list) else []:
        if not isinstance(a, dict):
            continue
        v, url = parse_wheel_version(a.get("name")), a.get("browser_download_url")
        if v is None or not (isinstance(url, str) and url.startswith("https://")):
            continue
        if best is None or is_newer(v, best[0]):
            best = (v, url)
    return best


# ---------------------------------------------------------------- caché
def _read_cache(cfg: str, source: str, now: float) -> Optional[Dict[str, Any]]:
    c = settings.load_settings(cfg, CACHE_FILE)
    t, latest, url = c.get("checked_at"), c.get("latest"), c.get("wheel_url")
    if c.get("source") != source or isinstance(t, bool) or not isinstance(t, (int, float)):
        return None
    if not 0 <= now - t < CACHE_TTL:  # caducada, o el reloj retrocedió
        return None
    if latest is not None and not (parse_semver(latest) and isinstance(url, str)):
        return None
    return {"latest": latest, "wheel_url": url if latest else None}


def _write_cache(cfg: str, source: str, now: float, latest: Optional[str], url: Optional[str]) -> None:
    try:
        settings.save_settings(
            cfg, {"source": source, "checked_at": now, "latest": latest, "wheel_url": url}, CACHE_FILE
        )
    except OSError:
        pass  # sin caché se consulta cada vez: no es un error para el usuario


# ---------------------------------------------------------------- comprobación
def check(
    cfg: str,
    current: str,
    *,
    fetch: Optional[Callable[[str, float], Dict[str, Any]]] = None,
    clock: Callable[[], float] = time.time,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    """`{state, current, latest, wheel_url, reason}`. `state`: `available` (hay un wheel estrictamente mayor),
    `up_to_date` (incluye «la Release no trae wheel») o `error` (con `reason`, ver UpdateError)."""
    source = url or releases_url()
    out: Dict[str, Any] = {"state": "up_to_date", "current": current, "latest": None, "wheel_url": None, "reason": None}
    now = clock()
    found = _read_cache(cfg, source, now)
    if found is None:
        try:
            wheel = pick_wheel((fetch or fetch_latest)(source, TIMEOUT))
        except UpdateError as e:
            out.update(state="error", reason=e.reason)
            return out
        found = {"latest": wheel[0] if wheel else None, "wheel_url": wheel[1] if wheel else None}
        _write_cache(cfg, source, now, found["latest"], found["wheel_url"])
    out.update(latest=found["latest"], wheel_url=found["wheel_url"])
    if found["latest"] and is_newer(found["latest"], current):
        out["state"] = "available"
    return out
