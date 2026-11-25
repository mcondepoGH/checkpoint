"""Detección de nuevas versiones (solo lectura): consulta las Releases públicas de GitHub.
Canal «stable» (por defecto): solo Releases normales. Canal «beta»: también pre-releases (nunca borradores).

Solo se aplica en instalación nativa. En Docker (se actualiza cambiando la imagen) está inactiva: ni
red, ni caché, ni ajustes.

Nunca descarga ni instala nada. Un fallo de red no es un error para el usuario: se conserva lo último
conocido y se reintenta más tarde. Con la comprobación desactivada no se hace ninguna petición."""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import runtime, settings

REPO = "mcondepoGH/checkpoint"
CACHE_TTL = 6 * 3600  # s de validez de una comprobación correcta
UNKNOWN = "desconocida"
TIMEOUT = 5  # s por petición
MIN_REFRESH = 60  # s mínimos entre comprobaciones forzadas
RETRY_AFTER = 900  # s antes de reintentar tras un fallo
NOTES_MAX = 6000  # caracteres de notas que se devuelven
MAX_BODY = 1_000_000  # bytes máximos de respuesta
SETTINGS_FILE = "updates.json"
CACHE_FILE = "update_cache.json"
_SEMVER_RE = re.compile(
    r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$"
)
CHANNELS = ("stable", "beta")
DEFAULT_CHANNEL = "stable"


def normalize_channel(v) -> str:
    """Valor desconocido -> 'stable'."""
    v = v.strip().lower() if isinstance(v, str) else ""
    return v if v in CHANNELS else DEFAULT_CHANNEL


def parse_semver(s) -> Optional[tuple]:
    """'v1.2.3-rc.1+meta' -> clave ordenable, o None. Orden semver 2.0: núcleo numérico; a igual núcleo, una
    pre-release es MENOR que la estable; entre pre-releases se comparan sus identificadores separados por
    punto (numéricos como número y menores que los alfanuméricos, que van en orden ASCII; menos campos es
    menor si el resto coincide). Los numéricos con ceros a la izquierda no son válidos. La build (+x) se ignora."""
    if not isinstance(s, str):
        return None
    m = _SEMVER_RE.match(s.strip())
    if not m:
        return None
    core = tuple(int(x or 0) for x in m.groups()[:3])
    pre = m.group(4)
    if pre is None:
        return core, 1, ()
    ids = []
    for i in pre.split("."):
        if i.isdigit():
            if len(i) > 1 and i[0] == "0":
                return None
            ids.append((0, int(i), ""))
        else:
            ids.append((1, 0, i))
    return core, 0, tuple(ids)


def format_semver(s) -> Optional[str]:
    """Versión canónica 'X.Y.Z[-pre]' (sin 'v' ni build), o None si no es válida."""
    key = parse_semver(s)
    if key is None:
        return None
    m = _SEMVER_RE.match(s.strip())
    out = ".".join(map(str, key[0]))
    return out + "-" + m.group(4) if m.group(4) else out


def _version_files():
    here = Path(__file__).resolve()
    # Docker: /app/VERSION (junto a app/). Nativo: VERSION en la raíz del repo.
    return [here.parents[2] / "VERSION", here.parents[3] / "VERSION"]


def installed_version() -> str:
    """Única fuente de verdad: el fichero VERSION. Admite sufijo de pre-release (1.0.0-rc.1). Sin fichero o valor no válido (modo desarrollo) -> 'desconocida'."""
    for f in _version_files():
        try:
            raw = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        return format_semver(raw) or UNKNOWN
    return UNKNOWN


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise urllib.error.URLError("redirección no HTTPS rechazada")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(_HttpsOnly())


def fetch_releases(repo: str) -> list:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases?per_page=30",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Checkpoint-update-check"},
    )
    with _opener().open(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read(MAX_BODY))
    if not isinstance(data, list):
        raise ValueError("respuesta inesperada")
    return data


INSTALLER_NAME = (
    "Checkpoint-Setup-{version}.exe"  # instalador de Windows adjunto a la Release; su hash: <nombre>.sha256
)


def _github_download(url) -> Optional[str]:
    """Solo se aceptan descargas https de github.com (las redirecciones a su CDN las sigue `_HttpsOnly`)."""
    if not isinstance(url, str):
        return None
    m = re.match(r"^https://github\.com/[^/?#\s]+/[^/?#\s]+/releases/download/[^?#\s]+$", url)
    return url if m else None


def pick_installer(assets, version) -> Optional[dict]:
    """El instalador de Windows de esa versión y la URL de su hash, o None si falta alguno de los dos (sin hash
    publicado no se ofrece la actualización con un clic)."""
    name = INSTALLER_NAME.format(version=version)
    urls = {}
    for a in assets if isinstance(assets, list) else []:
        if isinstance(a, dict) and a.get("name") in (name, name + ".sha256"):
            urls[a["name"]] = _github_download(a.get("browser_download_url"))
    if not urls.get(name) or not urls.get(name + ".sha256"):
        return None
    return {"name": name, "url": urls[name], "sha256_url": urls[name + ".sha256"]}


def pick_latest(releases, channel: str = DEFAULT_CHANNEL) -> Optional[dict]:
    """Versión más alta ofrecible. stable: sin borradores ni pre-releases (marcadas o por sufijo del tag).
    beta: también pre-releases; gana la más alta de todas (1.0.0 > 1.0.0-rc.2 > 1.0.0-rc.1)."""
    beta = normalize_channel(channel) == "beta"
    best, best_k = None, None
    for r in releases or []:
        if not isinstance(r, dict) or r.get("draft"):
            continue
        k = parse_semver(r.get("tag_name"))
        if k is None:
            continue
        pre = bool(r.get("prerelease")) or k[1] == 0
        if pre and not beta:
            continue
        if best_k is None or k > best_k:
            best, best_k = r, k
    if not best:
        return None
    url = best.get("html_url")
    version = format_semver(best["tag_name"])
    return {
        "version": version,
        "installer": pick_installer(best.get("assets"), version),
        "prerelease": bool(best.get("prerelease")) or best_k[1] == 0,
        "notes": str(best.get("body") or "")[:NOTES_MAX],
        "url": url if isinstance(url, str) and url.startswith("https://") else None,
    }


def applicable() -> bool:
    """Solo en instalación nativa: en Docker la versión la fija la imagen."""
    return not runtime.running_in_docker()


def _iso(ts) -> Optional[str]:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None


class UpdateChecker:
    def __init__(self, fetch: Callable = None, clock: Callable[[], float] = time.time):
        self._fetch = fetch  # None -> fetch_releases (resuelto en cada llamada, para poder sustituirlo)
        self.clock = clock
        self._lock = threading.Lock()
        self._cache = None

    # ---- persistencia (todo tolerante a fallos de disco) ----
    def _read(self, name) -> dict:
        try:
            d = json.loads((settings.DATA_DIR / name).read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, name, data):
        try:
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            p = settings.DATA_DIR / name
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass

    def enabled(self) -> bool:
        v = self._read(SETTINGS_FILE).get("enabled")
        return v if isinstance(v, bool) else True

    def channel(self) -> str:
        """Elección guardada (stable o beta) manda siempre. Sin ella: beta si la versión instalada es una
        pre-release (para poder recibir la siguiente rc), stable en cualquier otro caso."""
        v = self._read(SETTINGS_FILE).get("channel")
        if v in CHANNELS:
            return v
        k = parse_semver(installed_version())
        return "beta" if k is not None and k[1] == 0 else DEFAULT_CHANNEL

    def _merge_settings(self, **kv):
        cur = self._read(SETTINGS_FILE)
        cur.update(kv)
        self._write(SETTINGS_FILE, cur)

    def set_enabled(self, value: bool):
        self._merge_settings(enabled=bool(value))

    def set_channel(self, value: str):
        """Valor desconocido -> ValueError (la API responde 422). Cambiar de canal invalida la caché
        (la clave de la caché incluye el canal)."""
        if value not in CHANNELS:
            raise ValueError("canal no válido")
        self._merge_settings(channel=value)

    # ---- estado ----
    @staticmethod
    def _same(c, repo, channel) -> bool:
        return bool(c) and c.get("repo") == repo and c.get("channel") == channel

    def _do_fetch(self, repo, channel, now, forced=False):
        old = self._cache if self._same(self._cache, repo, channel) else {}
        # forced_at solo lo escribe un refresco manual; los fetch automáticos lo conservan.
        forced_at = now if forced else old.get("forced_at")
        try:
            latest = pick_latest((self._fetch or fetch_releases)(repo), channel)
            self._cache = {
                "repo": repo,
                "channel": channel,
                "attempt_at": now,
                "forced_at": forced_at,
                "checked_at": now,
                "ok": True,
                "latest": latest,
            }
        except Exception:  # red caída, límite de GitHub, JSON roto...: silencioso, se conserva lo anterior
            self._cache = {
                "repo": repo,
                "channel": channel,
                "attempt_at": now,
                "forced_at": forced_at,
                "checked_at": old.get("checked_at"),
                "ok": False,
                "latest": old.get("latest"),
            }
        self._write(CACHE_FILE, self._cache)

    def latest_installer(self) -> Optional[dict]:
        """Instalador de Windows de la última versión conocida (caché), o None. No hace red."""
        with self._lock:
            if self._cache is None:
                self._cache = self._read(CACHE_FILE) or {}
            inst = ((self._cache or {}).get("latest") or {}).get("installer")
        if not isinstance(inst, dict) or not isinstance(inst.get("name"), str):
            return None
        # La caché está en disco: se vuelve a validar lo que se va a descargar.
        if not (_github_download(inst.get("url")) and _github_download(inst.get("sha256_url"))):
            return None
        return inst

    def state(self, refresh: bool = False) -> dict:
        actual = installed_version()
        if not applicable():
            # Sin red, sin caché, sin leer ajustes guardados: campos neutros y sin error.
            return {
                "aplicable": False,
                "actual": actual,
                "ultima": None,
                "hay_actualizacion": False,
                "notas": "",
                "url": None,
                "comprobado_en": None,
                "error": None,
                "habilitado": False,
                "repo": REPO,
                "canal": DEFAULT_CHANNEL,
                "prerelease": False,
            }
        base = {
            "aplicable": True,
            "actual": actual,
            "ultima": None,
            "hay_actualizacion": False,
            "notas": "",
            "url": None,
            "comprobado_en": None,
            "error": None,
            "habilitado": self.enabled(),
            "repo": REPO,
            "canal": self.channel(),
            "prerelease": False,
        }
        if not base["habilitado"]:
            return base
        with self._lock:
            repo, channel, now = base["repo"], base["canal"], self.clock()
            if self._cache is None:
                self._cache = self._read(CACHE_FILE) or {}
            c = self._cache
            known = self._same(c, repo, channel) and isinstance(c.get("attempt_at"), (int, float))
            age = now - c["attempt_at"] if known else None
            # El límite cuenta solo refrescos manuales (forced_at; cachés viejas sin él no limitan)
            # y no aplica si el último intento falló: el usuario debe poder reintentar.
            forced_at = c.get("forced_at") if known else None
            forced_age = now - forced_at if isinstance(forced_at, (int, float)) else None
            if refresh and c.get("ok") and forced_age is not None and 0 <= forced_age < MIN_REFRESH:
                base["limitado"] = True
            else:
                ttl = CACHE_TTL if c.get("ok") else RETRY_AFTER
                if refresh or not known or age >= ttl or age < 0:
                    self._do_fetch(repo, channel, now, forced=refresh)
            c = self._cache if self._same(self._cache, repo, channel) else {}
        latest = c.get("latest") or {}
        base["ultima"] = latest.get("version")
        base["notas"] = latest.get("notes") or ""
        base["url"] = latest.get("url")
        base["prerelease"] = bool(latest.get("prerelease"))
        base["comprobado_en"] = _iso(c.get("checked_at"))
        base["error"] = None if c.get("ok", True) else "no se pudo comprobar"
        a, u = parse_semver(actual), parse_semver(base["ultima"])
        base["hay_actualizacion"] = bool(a and u and u > a)
        return base
