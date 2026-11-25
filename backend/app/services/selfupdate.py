"""Actualización con un clic (instalador de Windows o instalación nativa de Linux): descarga el asset de la Release que
ya detectó `core.updates`, comprueba su SHA-256 contra el hash publicado y lo aplica sin tocar datos ni .env:
- Windows: lanza el instalador en silencio y sale para que él sustituya los ficheros y vuelva a arrancar el hub.
- Linux: extrae el tarball con seguridad en DATA_DIR/update/<versión>/ y lanza DESACOPLADO su `install.sh --upgrade`,
  que reemplaza los ficheros y ejecuta `systemctl --user restart checkpoint` (el hub no sale: lo reinicia systemd).

El cliente no elige nada: ni URL ni versión. Solo se usa lo que el propio servidor comprobó en GitHub (https, host
github.com y asset con el nombre exacto de esa versión). Con un hash que no coincide no se instala nada.
`SelfUpdater` solo distingue la plataforma en `supported()` y en cómo se prepara y lanza el asset (`popen`, inyectable)."""

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
from pathlib import Path
from typing import Callable, Optional

from ..core import runtime, settings, updates
from ..core.runtime import platform_name

log = logging.getLogger("checkpoint.api")
MAX_INSTALLER_BYTES = 400 * 1024 * 1024  # tope de descarga (el instalador real pesa unas decenas de MB)
CHUNK = 256 * 1024
TIMEOUT = 30  # s por lectura de red
EXIT_DELAY = 2.0  # s entre lanzar el instalador y salir (le da tiempo a arrancar y a cerrar la app él mismo)
DETACHED = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
INSTALLER_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
MAX_EXTRACT_BYTES = 1024 * 1024 * 1024  # tope de lo que ocupa el tarball ya extraído (el real: unas decenas de MB)
MAX_EXTRACT_MEMBERS = 20000
# Dos esperas distintas, no confundir:
# - RESTART_WAIT: espera DEL BACKEND (Linux) a que install.sh reinicie el hub antes de dar la actualización por fallida.
# - RESTART_WAIT_WINDOWS / RESTART_WAIT_LINUX: espera DE LA INTERFAZ (s) a que el hub vuelva con la versión nueva; se
#   publica como `espera_reinicio` en GET /api/updates. En Linux es mayor porque install.sh crea el venv e instala
#   las dependencias (pip) antes de reiniciar la unidad.
RESTART_WAIT = (
    600.0  # s que se espera a que install.sh reinicie el hub antes de dar la actualización por fallida (Linux)
)
RESTART_WAIT_WINDOWS = 120  # s que espera la interfaz al hub tras el instalador de Windows
RESTART_WAIT_LINUX = 300  # s que espera la interfaz al hub tras install.sh --upgrade
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateError(Exception):
    """Error con contrato de API: `status` HTTP, `code` y `params` (para el cuerpo `detail`)."""

    def __init__(self, status: int, code: str, **params):
        super().__init__(code)
        self.status, self.code, self.params = status, code, params


def app_root() -> Path:
    """Carpeta de la versión que corre (<base>/<versión>), según dónde está este módulo: <raíz>/backend/app/services."""
    return Path(__file__).resolve().parents[3]


def _linux_native_install() -> bool:
    """Hub de Linux instalado por `install.sh`: la carpeta de la versión lleva `.instalado`, `<base>/current` es el
    enlace a ella (lo que ejecuta la unidad de systemd) y hay `systemctl`. Docker y el repositorio clonado no cuentan."""
    if platform_name() != "linux" or runtime.running_in_docker():
        return False
    root = app_root()
    current = root.parent / "current"
    try:
        if not ((root / ".instalado").is_file() and current.is_symlink() and current.resolve() == root.resolve()):
            return False
    except OSError:
        return False
    return shutil.which(os.environ.get("SYSTEMCTL") or "systemctl") is not None


def supported() -> bool:
    """Windows con el hub empaquetado por el instalador, o Linux con la instalación nativa (macOS, Docker y el
    repositorio clonado mantienen la actualización manual)."""
    if platform_name() == "windows":
        return bool(getattr(sys, "frozen", False))
    return _linux_native_install()


def ui_restart_wait() -> int:
    """Segundos que la interfaz espera a que el hub vuelva tras actualizarse, según la plataforma."""
    return RESTART_WAIT_WINDOWS if platform_name() == "windows" else RESTART_WAIT_LINUX


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


_LINUX_ASSET = re.compile(r"^checkpoint-([0-9A-Za-z][0-9A-Za-z._-]*)-linux\.tar\.gz$")


def _check_member(m: tarfile.TarInfo, root: str) -> None:
    """Un miembro del paquete es seguro si es un fichero o carpeta normal dentro de `root/`: sin rutas absolutas ni `..`,
    sin enlaces (simbólicos o duros) y sin ficheros especiales (dispositivos, FIFO)."""
    name = m.name
    parts = name.split("/")
    if name.startswith("/") or ".." in parts or "\\" in name or "\0" in name:
        raise ValueError(f"ruta no permitida en el paquete: {name[:80]!r}")
    if parts[0] != root:
        raise ValueError(f"el paquete debe tener una única carpeta raíz {root}/: {name[:80]!r}")
    if not (m.isreg() or m.isdir()):
        raise ValueError(f"tipo de miembro no permitido en el paquete: {name[:80]!r}")


def extract_package(tgz: Path, dest: Path, version: str) -> Path:
    """Extrae `checkpoint-<versión>-linux.tar.gz` en `dest` (que se vacía antes) y devuelve `dest/checkpoint-<versión>`.
    Valida TODOS los miembros antes de escribir nada; `ValueError` si algo no cuadra (y `dest` queda vacío)."""
    root = f"checkpoint-{version}"
    shutil.rmtree(dest, ignore_errors=True)
    try:
        with tarfile.open(tgz, "r:gz") as tf:
            members = tf.getmembers()
            if len(members) > MAX_EXTRACT_MEMBERS:
                raise ValueError("el paquete tiene demasiados miembros")
            if sum(m.size for m in members if m.isreg()) > MAX_EXTRACT_BYTES:
                raise ValueError("el paquete supera el tamaño máximo permitido una vez extraído")
            for m in members:
                _check_member(m, root)
            if not any(m.isreg() and m.name == f"{root}/install.sh" for m in members):
                raise ValueError("el paquete no trae install.sh")
            dest.mkdir(parents=True)
            if hasattr(tarfile, "data_filter"):  # Python >= 3.11.4 / 3.12: defensa extra del propio tarfile
                tf.extractall(dest, members=members, filter="data")
            else:  # pragma: no cover - ya validado miembro a miembro arriba
                tf.extractall(dest, members=members)
    except (tarfile.TarError, EOFError, OSError) as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise ValueError(f"paquete ilegible: {e}"[:300]) from e
    except ValueError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    script = dest / root / "install.sh"
    script.chmod(0o755)
    return dest / root


class SelfUpdater:
    def __init__(
        self,
        checker: "updates.UpdateChecker",
        busy: Callable[[], bool],
        opener=None,
        popen=subprocess.Popen,
        exit_fn: Callable[[], None] = lambda: os._exit(0),
        exit_delay: float = EXIT_DELAY,
        restart_wait: float = RESTART_WAIT,
    ):
        self.checker, self.busy = checker, busy
        self._restart_wait = restart_wait
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
        linux = platform_name() != "windows"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob("checkpoint-*-linux.tar.gz*" if linux else "Checkpoint-Setup-*.exe*"):  # restos
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
            cmd, kwargs = self._linux_launch(inst, dest, folder) if linux else self._windows_launch(dest)
            self._popen(cmd, **kwargs)
        except (OSError, ValueError) as e:
            self._fail("err.main.updates.install_failed", reason=str(e)[:300])
            return
        self._set(state="restarting")
        if linux:  # install.sh reinicia la unidad: el hub no sale; si nadie lo reinicia, se da por fallida
            threading.Timer(self._restart_wait, self._restart_overdue, args=(folder,)).start()
        else:
            threading.Timer(self._exit_delay, self._exit).start()

    def _restart_overdue(self, folder: Path) -> None:
        if self.status()["state"] == "restarting":
            version = self.status()["version"]
            self._fail(
                "err.main.updates.install_failed",
                reason=f"la actualización no terminó; revisa {folder / f'upgrade-{version}.log'}",
            )

    @staticmethod
    def _windows_launch(dest: Path):
        return [str(dest), *INSTALLER_ARGS], {"creationflags": DETACHED, "close_fds": True}

    def _linux_launch(self, inst: dict, tgz: Path, folder: Path):
        """Extrae el tarball ya verificado y devuelve el comando y los argumentos de `popen` para `install.sh --upgrade`,
        desacoplado del hub (sesión nueva, stdout/stderr a `upgrade-<versión>.log`, sin las credenciales del hub)."""
        m = _LINUX_ASSET.match(inst["name"])
        if not m:
            raise ValueError("nombre de paquete no válido")
        version = m.group(1)
        pkg = extract_package(tgz, folder / version, version)
        _remove(tgz)  # ya extraído: no se guardan 20-50 MB inútiles
        logf = open(folder / f"upgrade-{version}.log", "wb")  # noqa: SIM115 - lo hereda install.sh; se cierra al terminar él
        env = {k: v for k, v in os.environ.items() if k not in ("CHECKPOINT_USER", "CHECKPOINT_PASSWORD")}
        env["CHECKPOINT_INSTALL_PREFIX"] = str(app_root().parent)
        run = ["bash", str(pkg / "install.sh"), "--upgrade"]
        sdrun = shutil.which("systemd-run")
        if sdrun:
            # Un proceso hijo del hub está en el cgroup de la unidad: `systemctl restart` lo mataría a mitad. Con
            # systemd-run corre en una unidad transitoria propia y sobrevive al reinicio.
            pass_env = [
                k
                for k in (
                    "HOME",
                    "PATH",
                    "XDG_DATA_HOME",
                    "XDG_CONFIG_HOME",
                    "SYSTEMCTL",
                    "LOGINCTL",
                    "CHECKPOINT_MIN_PYTHON",
                )
                if k in env
            ]
            cmd = [sdrun, "--user", "--quiet", "--collect", f"--working-directory={pkg}"]
            cmd += [f"--setenv=CHECKPOINT_INSTALL_PREFIX={env['CHECKPOINT_INSTALL_PREFIX']}"]
            cmd += [f"--setenv={k}={env[k]}" for k in pass_env]
            cmd += [
                f"--property=StandardOutput=append:{logf.name}",
                f"--property=StandardError=append:{logf.name}",
                "--",
                *run,
            ]
        else:
            cmd = run
        kwargs = {
            "cwd": str(pkg),
            "stdin": subprocess.DEVNULL,
            "stdout": logf,
            "stderr": subprocess.STDOUT,
            "env": env,
            "start_new_session": True,
            "close_fds": True,
        }
        return cmd, kwargs

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
