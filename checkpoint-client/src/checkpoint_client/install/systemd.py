"""Unidad `systemd --user` que arranca `checkpoint-client watch` al iniciar sesión.

La unidad solo lleva el comando (ruta absoluta, sin shell) y la política de reinicio: ni claves ni direcciones del hub;
el vigilante lee su vinculación de `~/.config/checkpoint-client` como siempre. Los comandos de `systemctl` pasan por un
ejecutor inyectable (`runner`) para probarlos sin tocar el systemd real.

Instalar es idempotente: reescribe la unidad, recarga, `enable --now` y, si la unidad cambió, reinicia el servicio. Si
algo falla, la unidad vuelve a como estaba (o se borra si era nueva). Desinstalar hace `disable --now` y borra la unidad;
no toca la vinculación ni los datos.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

UNIT_NAME = "checkpoint-client.service"
RESTART_SEC = 30  # un `watch` que falla (sin vinculación, hub caído al arrancar) no se reintenta en bucle rápido
TIMEOUT_S = 30


class Unavailable(Exception):
    """No hay `systemd --user` utilizable en esta sesión."""


class InstallError(Exception):
    """No se pudo instalar o quitar la unidad; `reason` es la causa en una línea."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


Runner = Callable[[List[str]], "subprocess.CompletedProcess[str]"]


def run_command(argv: List[str]) -> "subprocess.CompletedProcess[str]":
    """Ejecuta un comando SIN shell y con la salida capturada en UTF-8."""
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_S, check=False)


def unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "systemd" / "user"


def unit_path() -> Path:
    return unit_dir() / UNIT_NAME


def exec_command(python: Optional[str] = None) -> List[str]:
    """Comando del vigilante con ruta absoluta del entorno donde está instalado el cliente: el script
    `checkpoint-client` junto al intérprete (pipx/venv) o, si no está, `<intérprete> -m checkpoint_client watch`."""
    import sys  # noqa: PLC0415  (para que los tests puedan pasar otro intérprete)

    py = os.path.abspath(python or sys.executable)  # sin resolver enlaces: el del venv no es el del sistema
    script = os.path.join(os.path.dirname(py), "checkpoint-client")
    if os.path.isfile(script) and os.access(script, os.X_OK):
        return [script, "watch"]
    return [py, "-m", "checkpoint_client", "watch"]


def _quote(arg: str) -> str:
    """Un argumento de `ExecStart=` entre comillas: `\\` y `"` escapados; `%` y `$` duplicados (especificadores)."""
    esc = arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return f'"{esc}"'


def unit_text(command: List[str]) -> str:
    return (
        "[Unit]\n"
        "Description=Checkpoint: vigilante de guardados de juegos\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={' '.join(_quote(a) for a in command)}\n"
        "Restart=on-failure\n"
        f"RestartSec={RESTART_SEC}\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _systemctl(runner: Runner, *args: str) -> "subprocess.CompletedProcess[str]":
    return runner(["systemctl", "--user", *args])


def _reason(res: "subprocess.CompletedProcess[str]") -> str:
    for text in (res.stderr, res.stdout):
        for line in (text or "").splitlines():
            if line.strip():
                return line.strip()
    return f"systemctl terminó con código {res.returncode}"


def _require_user_manager(runner: Runner) -> None:
    try:
        ok = _systemctl(runner, "show-environment").returncode == 0
    except (OSError, subprocess.SubprocessError):  # sin binario systemctl o colgado
        ok = False
    if not ok:
        raise Unavailable()


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".checkpoint-client-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _restore(runner: Runner, path: Path, previous: Optional[str]) -> None:
    """Deja la unidad como estaba (o sin ella) y recarga; lo que falle aquí no se puede deshacer más."""
    try:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            _write(path, previous)
        _systemctl(runner, "daemon-reload")
    except (OSError, subprocess.SubprocessError):
        pass


def install(runner: Runner = None, exec_command: Optional[List[str]] = None) -> None:  # type: ignore[assignment]
    runner = runner or run_command
    command = exec_command if exec_command is not None else globals()["exec_command"]()
    _require_user_manager(runner)
    path, text = unit_path(), unit_text(command)
    previous = _read(path)
    try:
        _write(path, text)
    except OSError as e:
        raise InstallError(e.strerror or type(e).__name__) from None
    try:
        for args in (("daemon-reload",), ("enable", "--now", UNIT_NAME)):
            res = _systemctl(runner, *args)
            if res.returncode != 0:
                raise InstallError(_reason(res))
        if previous is not None and previous != text:  # el servicio ya corría con la unidad vieja
            res = _systemctl(runner, "restart", UNIT_NAME)
            if res.returncode != 0:
                raise InstallError(_reason(res))
    except (InstallError, subprocess.SubprocessError) as e:
        _restore(runner, path, previous)
        raise (e if isinstance(e, InstallError) else InstallError(type(e).__name__)) from None


def uninstall(runner: Runner = None) -> None:  # type: ignore[assignment]
    runner = runner or run_command
    _require_user_manager(runner)
    path = unit_path()
    if not path.exists():
        return
    try:
        res = _systemctl(runner, "disable", "--now", UNIT_NAME)
        if res.returncode != 0:
            raise InstallError(_reason(res))
        path.unlink(missing_ok=True)
        _systemctl(runner, "daemon-reload")
    except OSError as e:
        raise InstallError(e.strerror or type(e).__name__) from None
    except subprocess.SubprocessError as e:
        raise InstallError(type(e).__name__) from None
