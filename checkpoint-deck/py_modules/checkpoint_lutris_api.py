"""Appid de Steam de un juego de Lutris según la API pública de lutris.net, con caché persistente. Solo biblioteca estándar.

`GET https://lutris.net/api/games/<slug>` (sin credenciales) devuelve, verificado con JSON crudo, `"steamid": <entero>` o
`"steamid": null` si no hay (404 `{"detail": "No Game matches the given query."}` si el slug no existe). Se pregunta UNA vez
por slug y se cachea en `lutris_steam_cache.json` (carpeta de ajustes): `{slug: {"steamid": int|null, "checked_at": epoch}}`.
El positivo no caduca; el negativo (404 o sin steamid) caduca a los 30 días. Los errores transitorios (red, tiempo agotado,
429, 5xx, JSON ilegible) devuelven None y NO se cachean.

Cortesía con el servidor: máx. 20 peticiones nuevas por llamada (`begin_call`), secuenciales, pausa >= 0,5 s entre ellas y tope
de tiempo total; al primer error transitorio la llamada deja de preguntar. Lo que quede sin consultar se pregunta en la
siguiente llamada. Solo sale el slug (dato público del juego instalado); nada más.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

from checkpoint_hub import _OPENER, load_settings, save_settings

API_URL = "https://lutris.net/api/games"
USER_AGENT = "Checkpoint-Decky/1.0"
CACHE_FILE = "lutris_steam_cache.json"
TIMEOUT_S = 3.0
MAX_BODY = 2 * 1024 * 1024  # el JSON de un juego con muchos instaladores pasa de 64 KiB
MAX_NEW_PER_CALL = 20
PAUSE_S = 0.6
CALL_BUDGET_S = 30.0  # tope de tiempo total de las peticiones de una llamada
NEGATIVE_TTL_S = 30 * 86400
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")

Fetch = Callable[[str], Tuple[int, Any]]  # url -> (status HTTP, JSON o None); lanza OSError/ValueError si falla la red


def _default_fetch(url: str) -> Tuple[int, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}, method="GET")
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as r:
            status, raw = r.status, r.read(MAX_BODY + 1)
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return status, None


def _steam_id(body: Any) -> Optional[int]:
    """`steamid` entero positivo (o cadena de dígitos); null, 0, vacío u otra cosa = sin appid."""
    v = body.get("steamid") if isinstance(body, dict) else None
    if isinstance(v, str) and v.isdigit():
        v = int(v)
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


class LutrisSteamLookup:
    def __init__(
        self,
        settings_dir: str,
        *,
        fetch: Optional[Fetch] = None,
        base_url: str = API_URL,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = lambda _m: None,
        max_new: int = MAX_NEW_PER_CALL,
        pause: float = PAUSE_S,
        budget: float = CALL_BUDGET_S,
    ) -> None:
        self._dir, self._fetch, self._base = settings_dir, fetch or _default_fetch, base_url.rstrip("/")
        self._clock, self._sleep, self._mono, self._log = clock, sleep, monotonic, log
        self._max, self._pause, self._budget = max_new, pause, budget
        self._lock = threading.RLock()
        self._cache: Optional[Dict[str, Dict[str, Any]]] = None
        self.begin_call()

    def begin_call(self) -> None:
        """Abre una llamada de `suggest_saves*`: cuota y tiempo propios."""
        with self._lock:
            self.requests = 0  # peticiones de red hechas en esta llamada
            self.pending = 0  # slugs que se habrían consultado pero no cupieron (cuota, tiempo o error transitorio)
            self._start: Optional[float] = None
            self._stopped = False

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self._cache is None:
            raw = load_settings(self._dir, CACHE_FILE)
            self._cache = {
                s: e
                for s, e in raw.items()
                if isinstance(e, dict) and isinstance(e.get("checked_at"), (int, float)) and (e.get("steamid") is None or _steam_id(e))
            }
        return self._cache

    def cached(self, slug: str) -> Tuple[bool, Optional[int]]:
        """(hay respuesta válida en caché, steamid). El negativo caducado cuenta como ausente."""
        e = self._load().get(slug)
        if e is None:
            return False, None
        if e["steamid"] is None and self._clock() - e["checked_at"] >= NEGATIVE_TTL_S:
            return False, None
        return True, e["steamid"]

    def _store(self, slug: str, steamid: Optional[int]) -> None:
        cache = self._load()
        cache[slug] = {"steamid": steamid, "checked_at": self._clock()}
        try:
            save_settings(self._dir, cache, CACHE_FILE)
        except OSError:
            self._log("lutris.net: no se pudo escribir la caché")

    def lookup_steam_id(self, slug: Any) -> Optional[int]:
        """Appid de Steam del slug, de la caché o de UNA petición nueva; None si no hay, o si no se pudo saber ahora."""
        if not isinstance(slug, str) or not _SLUG.match(slug):
            return None
        with self._lock:
            hit, steamid = self.cached(slug)
            if hit:
                return steamid
            now = self._mono()
            if self._start is None:
                self._start = now
            if self._stopped or self.requests >= self._max or now - self._start >= self._budget:
                self.pending += 1
                return None
            if self.requests:
                self._sleep(self._pause)
            self.requests += 1
            try:
                status, body = self._fetch(f"{self._base}/{slug}")
            except (OSError, ValueError, urllib.error.URLError):  # red caída, tiempo agotado, HTTP raro
                self._stopped = True
                self._log("lutris.net: sin respuesta; se deja de preguntar en esta llamada")
                return None
            if status == 200 and isinstance(body, dict):
                steamid = _steam_id(body)
            elif status == 404:
                steamid = None
            else:  # 429, 5xx, 200 ilegible...: transitorio, no se cachea y se corta la llamada
                self._stopped = True
                self._log(f"lutris.net: respuesta {status}; se deja de preguntar en esta llamada")
                return None
            self._store(slug, steamid)
            return steamid
