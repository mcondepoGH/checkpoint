"""Cliente del hub para la sincronización (`/api/steam/library` y `/api/hook/*`), con la clave `ckd_` en `Authorization`.

Mismas reglas que `checkpoint_hub`: sin redirecciones, sin proxies del entorno, y la clave ni la URL completa salen
jamás en un mensaje, un log ni una excepción. Solo biblioteca estándar.
"""

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

from checkpoint_hub import _OPENER, HubNetworkError, describe_error, request_json

BIG_BODY = 16 * 1024 * 1024  # respuestas grandes (manifiesto de hasta 50 000 ficheros)
RETRIES = 3  # reintentos tras el primer intento (red, 5xx y 429)
BACKOFF_S = 1.0  # espera inicial; se duplica en cada reintento
BACKOFF_MAX_S = 30.0
RETRY_AFTER_MAX_S = 60  # un 429 que pide esperar más no se espera: se avisa a quien llama

MAX_FILE_BYTES = 512 * 1024 * 1024  # tope por fichero del hub por defecto (`HOOK_MAX_FILE_MB`)
RESYNCS = 5  # veces que una subida acepta el `received` que le dice el hub antes de rendirse
CHUNK = 64 * 1024
TIMEOUT_S = 60.0  # lectura/escritura de ficheros: más holgado que el de las llamadas JSON

Sleep = Callable[[float], None]


class FileTooLarge(Exception):
    """El fichero supera el tope por fichero del hub: no se intenta subir."""


class HubApiError(Exception):
    """El hub respondió con un error. `code` es el `detail.code` del hub (o None); nunca lleva URL ni clave."""

    def __init__(self, status: int, code: Optional[str], params: Optional[Dict[str, Any]] = None, wait_s: int = 0):
        super().__init__(f"{status} {code or ''}".strip())
        self.status, self.code, self.params, self.wait_s = status, code, params or {}, wait_s
        self.endpoint: Optional[str] = None  # `MÉTODO /ruta` (sin servidor ni consulta); lo rellena HubClient.call


class _Retry(Exception):
    def __init__(self, wait: Optional[float], cause: Exception):
        super().__init__("retry")
        self.wait, self.cause = wait, cause


class _Slice:
    """Lee como mucho `left` bytes del fichero (que ya está en su posición): el cuerpo de una subida en streaming."""

    def __init__(self, f: BinaryIO, left: int):
        self._f, self._left, self.sent = f, left, 0

    def read(self, n: int = -1) -> bytes:
        n = self._left if n is None or n < 0 else min(n, self._left)
        data = self._f.read(n)
        self._left -= len(data)
        self.sent += len(data)
        return data


def _game(game: str) -> str:
    return f"/api/hook/{quote(game, safe='')}"


def _result_body(result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Cuerpo `{"result": {...}}` de `opened`/`closed`; None (sin cuerpo) si no hay resultado."""
    return {"result": result} if result else None


def _length(r) -> Optional[int]:
    v = r.headers.get("Content-Length", "")
    return int(v) if v.isdigit() else None


class HubClient:
    def __init__(self, hub: str, key: str, *, sleep: Sleep = time.sleep, retries: int = RETRIES):
        self._hub, self._key, self._sleep, self._retries = hub, key, sleep, retries

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"}

    def _backoff(self, attempt: int) -> float:
        return min(BACKOFF_S * 2**attempt, BACKOFF_MAX_S)

    def call(self, method: str, path: str, *, body: Any = None, max_body: int = BIG_BODY, retry: bool = True) -> Any:
        """Ver `_call`; además marca en el error el endpoint (`MÉTODO /ruta`, sin servidor ni consulta) para el log."""
        try:
            return self._call(method, path, body=body, max_body=max_body, retry=retry)
        except (HubApiError, HubNetworkError) as e:
            if getattr(e, "endpoint", None) is None:
                e.endpoint = f"{method} {path.split('?', 1)[0]}"  # type: ignore[attr-defined]
            raise

    def _call(self, method: str, path: str, *, body: Any = None, max_body: int = BIG_BODY, retry: bool = True) -> Any:
        """JSON de la respuesta 2xx. Reintenta con espera creciente SOLO errores de red, 5xx y 429; el resto de
        errores del hub salen como HubApiError y los de red como HubNetworkError."""
        attempt = 0
        while True:
            try:
                r = request_json(method, self._hub + path, headers=self._headers(), body=body, max_body=max_body)
            except HubNetworkError:
                if not retry or attempt >= self._retries:
                    raise
                self._sleep(self._backoff(attempt))
                attempt += 1
                continue
            if 200 <= r.status < 300:
                return r.body
            wait = r.retry_after or 0
            if r.status == 429 and wait > RETRY_AFTER_MAX_S:
                raise HubApiError(429, r.error_code, r.error_params, wait)
            if retry and attempt < self._retries and (r.status == 429 or r.status >= 500):
                self._sleep(float(wait) if r.status == 429 and wait else self._backoff(attempt))
                attempt += 1
                continue
            raise HubApiError(r.status, r.error_code, r.error_params, wait)

    # ---- juegos y huella
    def get_games(self) -> List[Dict[str, Any]]:
        """Juegos de este dispositivo: [{id, name, enabled, steam_appid, status, path}]; `path` es None si no hay ruta."""
        out = self.call("GET", "/api/games")
        if not isinstance(out, list):
            raise HubApiError(200, "bad_response")
        games = []
        for g in out:
            if not (isinstance(g, dict) and isinstance(g.get("id"), str) and isinstance(g.get("name"), str)):
                continue
            path = g.get("path")
            games.append({**g, "path": path if isinstance(path, str) and path else None})
        return games

    def fingerprint(self, game: str, manifest: List[Dict], with_manifest: bool = False) -> Dict[str, Any]:
        q = "?manifest=1" if with_manifest else ""
        out = self.call("POST", f"{_game(game)}/fingerprint{q}", body=manifest)
        if not isinstance(out, dict) or not isinstance(out.get("action"), str):
            raise HubApiError(200, "bad_response")
        return out

    def commit(self, game: str, expect: Optional[str], manifest: List[Dict]) -> Dict[str, Any]:
        out = self.call("POST", f"{_game(game)}/commit", body={"expect": expect, "manifest": manifest})
        if not isinstance(out, dict):
            raise HubApiError(200, "bad_response")
        return out

    def set_resolution(self, game: str, winner: str, expect: Dict[str, Optional[str]]) -> Dict[str, Any]:
        """Deja en el hub la resolución pendiente de un conflicto de datos de este dispositivo: `winner` (`hub` o
        `device`) y `expect` (`{hub, device}`: las huellas del `fingerprint` en conflicto). No cambia ficheros: la aplica
        el siguiente `fingerprint`. Un hub antiguo (sin esta ruta) responde 404/405 sin código: lo decide quien llama."""
        out = self.call("PUT", f"{_game(game)}/resolution", body={"winner": winner, "expect": expect})
        if not isinstance(out, dict):
            raise HubApiError(200, "bad_response")
        return out

    def closed(self, game: str, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Aviso «se cerró el juego»: el hub limpia el «jugando» y deja constancia en el historial (no sincroniza).
        `result` (opcional, `{state, code?}`) es el resultado de la sync local; sin él, sin cuerpo (como siempre)."""
        out = self.call("POST", f"{_game(game)}/closed", body=_result_body(result))
        if not isinstance(out, dict):
            raise HubApiError(200, "bad_response")
        return out

    def opened(self, game: str, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Aviso «se abrió el juego» (ya sincronizado): el hub lo marca «jugando» y lo anota en su historial; no
        sincroniza. Un solo intento (`retry=False`): no es crítico y no debe retrasar nada. Un hub antiguo responde
        400/401/404/405: lo decide quien llama."""
        out = self.call("POST", f"{_game(game)}/opened", body=_result_body(result), retry=False)
        if not isinstance(out, dict):
            raise HubApiError(200, "bad_response")
        return out

    # ---- ficheros (streaming)
    def _stream(self, method: str, path: str, headers: Dict[str, str], data: Optional[BinaryIO] = None):
        """Abre la petición sin leer el cuerpo de la respuesta. HubApiError si el hub responde >= 400; HubNetworkError
        si no se pudo hablar con él (sin URL ni clave en el mensaje)."""
        req = urllib.request.Request(
            self._hub + path, data=data, headers={**self._headers(), **headers}, method=method
        )
        try:
            return _OPENER.open(req, timeout=TIMEOUT_S)
        except urllib.error.HTTPError as e:
            try:
                raw = e.read(64 * 1024)
                body = json.loads(raw.decode("utf-8")) if raw else None
            except (OSError, http.client.HTTPException, ValueError):
                body = None
            d = body.get("detail") if isinstance(body, dict) else None
            code = d.get("code") if isinstance(d, dict) and isinstance(d.get("code"), str) else None
            params = d.get("params") if isinstance(d, dict) and isinstance(d.get("params"), dict) else {}
            ra = e.headers.get("Retry-After", "")
            raise HubApiError(e.code, code, params, int(ra) if ra.isdigit() else 0) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise HubNetworkError(type(e).__name__) from None

    def download_file(self, game: str, rel: str, dest: Path, offset: int = 0) -> int:
        """Descarga `rel` del hub a `dest`, añadiendo desde `offset` (con `Range`). Si el hub no sirve el rango, empieza
        de cero. Reanuda tras un corte con espera creciente. Devuelve los bytes que tiene `dest` al acabar."""
        path = f"{_game(game)}/files?{urlencode({'path': rel}, quote_via=quote)}"
        attempt = restarts = 0
        offset = max(0, offset)
        while True:
            if offset and not (os.path.isfile(dest) and os.path.getsize(dest) >= offset):
                offset = 0  # lo que había en disco ya no está: de cero
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            try:
                try:
                    r = self._stream("GET", path, headers)
                except HubApiError as e:
                    if e.status == 416 and offset and restarts == 0:
                        restarts, offset = 1, 0  # el trozo local no vale: de cero
                        continue
                    if (e.status == 429 and e.wait_s <= RETRY_AFTER_MAX_S) or e.status >= 500:
                        raise _Retry(float(e.wait_s) if e.status == 429 and e.wait_s else None, e) from None
                    raise
                with r:
                    start = self._start(r, offset)
                    expected = _length(r)
                    with open(dest, "r+b" if start else "wb") as f:
                        if start:
                            f.truncate(start)
                            f.seek(start)
                        got = 0
                        while True:
                            chunk = r.read(CHUNK)
                            if not chunk:
                                break
                            f.write(chunk)
                            got += len(chunk)
                    if expected is not None and got != expected:
                        raise HubNetworkError("IncompleteRead")
                    return start + got
            except (HubNetworkError, _Retry) as e:
                if attempt >= self._retries:
                    raise (e.cause if isinstance(e, _Retry) else e) from None
                self._sleep(e.wait if isinstance(e, _Retry) and e.wait else self._backoff(attempt))
                attempt += 1
                try:
                    offset = os.path.getsize(dest)  # reanuda desde lo que ya hay
                except OSError:
                    offset = 0

    @staticmethod
    def _start(r, offset: int) -> int:
        """Primer byte que sirve la respuesta: 0 (200) o el `offset` pedido (206 con `Content-Range` coherente)."""
        if r.status == 200:
            return 0
        m = re.match(r"^bytes (\d+)-(\d+)/(\d+)$", r.headers.get("Content-Range", ""))
        if r.status == 206 and m and int(m.group(1)) == offset and offset > 0:
            return offset
        raise HubApiError(r.status, "bad_response")

    def upload_file(self, game: str, rel: str, abs_path: Path, size: int, sha256: str) -> Dict[str, Any]:
        """Sube un fichero en streaming desde disco, reanudable: tras un corte o un 409 de `upload_offset_mismatch`
        sigue desde los bytes que el hub dice tener (`received`). FileTooLarge si supera el tope (sin subir nada)."""
        if size > MAX_FILE_BYTES:
            raise FileTooLarge(rel)
        attempt = resyncs = 0
        offset = 0
        body: Optional[_Slice] = None
        while True:
            q = urlencode({"path": rel, "size": size, "sha256": sha256, "offset": offset}, quote_via=quote)
            try:
                with open(abs_path, "rb") as f:
                    f.seek(offset)
                    body = _Slice(f, size - offset)
                    req_headers = {"Content-Type": "application/octet-stream", "Content-Length": str(size - offset)}
                    with self._stream("PUT", f"{_game(game)}/files?{q}", req_headers, body) as r:  # type: ignore[arg-type]
                        out = json.loads(r.read(64 * 1024).decode("utf-8"))
                if not isinstance(out, dict):
                    raise HubApiError(200, "bad_response")
                return out
            except HubApiError as e:
                if e.code == "err.hook.upload_offset_mismatch":
                    got = e.params.get("received")
                    resyncs += 1
                    if resyncs > RESYNCS or not isinstance(got, int) or isinstance(got, bool) or not 0 <= got < size:
                        raise
                    offset = got
                    continue
                if e.status == 429 and e.wait_s > RETRY_AFTER_MAX_S:
                    raise
                if not (e.status == 429 or e.status >= 500) or attempt >= self._retries:
                    raise
                self._sleep(float(e.wait_s) if e.status == 429 and e.wait_s else self._backoff(attempt))
                attempt += 1
            except (HubNetworkError, ValueError):
                if attempt >= self._retries:
                    raise HubNetworkError("upload") from None
                self._sleep(self._backoff(attempt))
                attempt += 1
                # El hub pudo quedarse con una parte: se sondea justo tras lo enviado; si no la tiene, responde 409 con
                # `received` y se continúa desde ahí.
                if body is not None and 0 < offset + body.sent < size:
                    offset += body.sent

    def create_game(self, appid: int, name: str, path: str) -> Dict[str, Any]:
        """Crea en el hub un juego de este dispositivo: `{id, name, appid, path}` (más `joined`, `devices`, `enabled`
        si el hub unió este dispositivo a un juego existente). Sin reintentos."""
        out = self.call("POST", "/api/steam/games", body={"appid": appid, "name": name, "path": path}, retry=False)
        if not isinstance(out, dict) or not isinstance(out.get("id"), str):
            raise HubApiError(200, "bad_response")
        return out

    def set_game_enabled(self, game: str, enabled: bool) -> Dict[str, Any]:
        """Activa o desactiva uno de los juegos de este dispositivo (vale para todo el hub): `{game, enabled}`."""
        out = self.call("PUT", f"/api/steam/games/{quote(game, safe='')}/enabled", body={"enabled": enabled})
        if not isinstance(out, dict) or not isinstance(out.get("enabled"), bool):
            raise HubApiError(200, "bad_response")
        return out

    def set_game_path(self, game: str, path: str) -> Dict[str, Any]:
        """Cambia la carpeta de guardado de ESTE dispositivo en uno de sus juegos: `{game, path}` (la ruta ya normalizada
        por el hub). El hub olvida el estado recordado de este dispositivo y juego."""
        out = self.call("PUT", f"/api/steam/games/{quote(game, safe='')}/path", body={"path": path})
        if not isinstance(out, dict) or not isinstance(out.get("path"), str) or not isinstance(out.get("game"), str):
            raise HubApiError(200, "bad_response")
        return out

    def post_library(self, games: List[Tuple[int, str]]) -> Dict[str, Any]:
        body = {"games": [{"appid": a, "name": n} for a, n in games]}
        out = self.call("POST", "/api/steam/library", body=body)
        if not isinstance(out, dict):
            raise HubApiError(200, "bad_response")
        return out


def refresh_library(
    hub: str,
    key: Optional[str],
    scan: Callable[[], List[Tuple[int, str]]],
    sleep: Sleep = time.sleep,
    log: Callable[[str], None] = lambda _m: None,
) -> Tuple[str, Dict[str, Any]]:
    """Escanea la biblioteca de Steam y la envía al hub. (resultado, datos); resultado: ok | not_linked | no_steam |
    unauthorized | rate_limited | connection | config_changed | hub_error."""
    if not key or not hub:
        return "not_linked", {}
    games = scan()
    if not games:
        log("biblioteca: no se encontró ningún juego instalado")
        return "no_steam", {}
    client = HubClient(hub, key, sleep=sleep)
    out: Dict[str, Any] = {}
    for attempt in range(2):  # 409 `err.main.config_changed` (el hub cambió la config a la vez): se reintenta una vez
        try:
            out = client.post_library(games)
            break
        except HubNetworkError as e:
            detail = describe_error(e)
            log(f"biblioteca: {detail}")
            return "connection", {"detail": detail}
        except HubApiError as e:
            detail = describe_error(e)
            log(f"biblioteca: {detail}")
            if e.status == 401:
                return "unauthorized", {"detail": detail}
            if e.status == 429:
                return "rate_limited", {"wait_s": e.wait_s, "detail": detail}
            if e.code == "err.main.config_changed":
                if attempt == 0:
                    continue
                return "config_changed", {"detail": detail}
            return "hub_error", {"code": e.code, "detail": detail}
    assoc = out.get("associated")
    return "ok", {
        "found": len(games),
        "associated": len(assoc) if isinstance(assoc, list) else 0,
        "suggested": _int(out.get("suggested")),
        "unchanged": _int(out.get("unchanged")),
        "ignored": _int(out.get("ignored")),
    }


def _int(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0
