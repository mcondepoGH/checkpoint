"""Actualización con un clic (solo con el instalador de Windows): descarga el instalador de la Release que ya detectó
`core.updates`, comprueba su SHA-256 contra el hash publicado, lo lanza en silencio y sale para que el instalador
sustituya los ficheros y vuelva a arrancar el hub. Los datos y el .env no se tocan.

El cliente no elige nada: ni URL ni versión. Solo se usa lo que el propio servidor comprobó en GitHub (https, host
github.com y asset con el nombre exacto de esa versión). Con un hash que no coincide no se instala nada.
Código reutilizable por «Instalación sin Docker más fácil»: `SelfUpdater` no sabe de Windows salvo en `supported()`
y en cómo se lanza el instalador (`popen`, inyectable)."""

import hashlib
import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from ..core import settings, updates
from ..core.runtime import platform_name

log = logging.getLogger("checkpoint.api")
MAX_INSTALLER_BYTES = 400 * 1024 * 1024  # tope de descarga (el instalador real pesa unas decenas de MB)
CHUNK = 256 * 1024
TIMEOUT = 30  # s por lectura de red
EXIT_DELAY = 2.0  # s entre lanzar el instalador y salir (le da tiempo a arrancar y a cerrar la app él mismo)
DETACHED = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
INSTALLER_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateError(Exception):
    """Error con contrato de API: `status` HTTP, `code` y `params` (para el cuerpo `detail`)."""

    def __init__(self, status: int, code: str, **params):
        super().__init__(code)
        self.status, self.code, self.params = status, code, params


def supported() -> bool:
    """Windows con el hub empaquetado por el instalador (Linux y macOS mantienen la actualización manual)."""
    return platform_name() == "windows" and bool(getattr(sys, "frozen", False))


def sync_running(scheduler, registry) -> bool:
    """¿Hay alguna sincronización en marcha (automática, manual o de hook)?"""
    return scheduler.current is not None or registry.any_active()


def parse_sha256(text: str, name: str) -> Optional[str]:
    """Hash (minúsculas) de un `.sha256` de `sha256sum`/`Get-FileHash`: «<hex>  <nombre>» o solo el hex. Si trae un
    nombre y no es el del instalador, None."""
    for line in (text or "").splitlines():
        parts = line.strip().split(None, 1)
        if not parts or not _HEX64.match(parts[0]):
            continue
        if len(parts) == 2 and parts[1].lstrip("*").strip() != name:
            continue
        return parts[0].lower()
    return None


def _read_small(opener, url: str) -> str:
    with opener.open(_request(url), timeout=TIMEOUT) as r:
        return r.read(4096).decode("utf-8", "replace")


def _request(url: str):
    import urllib.request

    return urllib.request.Request(url, headers={"User-Agent": "Checkpoint-update"})


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


class SelfUpdater:
    def __init__(
        self,
        checker: "updates.UpdateChecker",
        busy: Callable[[], bool],
        opener=None,
        popen=subprocess.Popen,
        exit_fn: Callable[[], None] = lambda: os._exit(0),
        exit_delay: float = EXIT_DELAY,
    ):
        self.checker, self.busy = checker, busy
        self._opener, self._popen, self._exit, self._exit_delay = opener, popen, exit_fn, exit_delay
        self._lock = threading.Lock()
        self._st = {"state": "idle", "version": None, "error": None}

    def status(self) -> dict:
        with self._lock:
            return dict(self._st)

    def _set(self, **kv) -> None:
        with self._lock:
            self._st.update(kv)

    def _fail(self, code: str, **params) -> None:
        log.warning("actualización: %s %s", code, params)
        self._set(state="error", error={"code": code, "params": params})

    def start(self) -> dict:
        """Valida y lanza la actualización en segundo plano; `UpdateError` si no procede."""
        if not supported():
            raise UpdateError(409, "err.main.updates.install_not_supported")
        with self._lock:
            if self._st["state"] in ("downloading", "installing", "restarting"):
                raise UpdateError(409, "err.main.updates.install_failed", reason="ya hay una actualización en curso")
        if self.busy():
            raise UpdateError(409, "err.main.updates.sync_running")
        state = self.checker.state()
        inst = self.checker.latest_installer() if state.get("hay_actualizacion") else None
        if not inst:
            raise UpdateError(409, "err.main.updates.install_failed", reason="no hay una versión nueva con instalador")
        with self._lock:
            self._st = {"state": "downloading", "version": state["ultima"], "error": None}
        threading.Thread(target=self._work, args=(inst,), daemon=True, name="checkpoint-selfupdate").start()
        return self.status()

    # ---- hilo de trabajo ----
    def _work(self, inst: dict) -> None:
        folder = settings.DATA_DIR / "update"
        dest = folder / inst["name"]
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob("Checkpoint-Setup-*.exe*"):  # restos de intentos anteriores
                _remove(old)
            digest = self._download(inst, dest)
            published = parse_sha256(self._text(inst["sha256_url"]), inst["name"])
        except Exception as e:  # noqa: BLE001 - cualquier fallo de red o disco es «no se pudo descargar»
            _remove(dest)
            self._fail("err.main.updates.download_failed", reason=str(e)[:300] or e.__class__.__name__)
            return
        if published is None or published != digest:
            _remove(dest)
            self._fail("err.main.updates.hash_mismatch")
            return
        self._set(state="installing")
        try:
            self._popen([str(dest), *INSTALLER_ARGS], creationflags=DETACHED, close_fds=True)
        except (OSError, ValueError) as e:
            self._fail("err.main.updates.install_failed", reason=str(e)[:300])
            return
        self._set(state="restarting")
        threading.Timer(self._exit_delay, self._exit).start()

    def _open(self):
        if self._opener is None:
            self._opener = updates._opener()  # solo https, también en redirecciones
        return self._opener

    def _text(self, url: str) -> str:
        return _read_small(self._open(), url)

    def _download(self, inst: dict, dest: Path) -> str:
        h, total = hashlib.sha256(), 0
        with self._open().open(_request(inst["url"]), timeout=TIMEOUT) as r, open(dest, "wb") as out:
            while True:
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_INSTALLER_BYTES:
                    raise ValueError("el instalador supera el tamaño máximo permitido")
                h.update(chunk)
                out.write(chunk)
        return h.hexdigest()
