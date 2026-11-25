"""Arranque de Checkpoint al iniciar sesión en Windows, con una Tarea Programada de ese usuario.

Solo con el instalador de Windows (hub congelado con PyInstaller): el ejecutable que se programa es `sys.executable`.
La tarea se define con un XML (`schtasks /Create /XML`) con un disparador de inicio de sesión LIMITADO a este usuario y
nivel de ejecución normal: así no hace falta ser Administrador (un `/SC ONLOGON` sin usuario sí lo exige).
Desactivado por defecto: solo se crea si el usuario lo activa en Ajustes. Desactivarlo borra la tarea y no detiene el
hub que ya está en marcha."""

import getpass
import os
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

from ..core.runtime import platform_name

TASK_NAME = "Checkpoint"
TIMEOUT = 20  # s por llamada a schtasks


class AutostartError(Exception):
    """Fallo al consultar o cambiar la tarea. `code` es el código de error de la API; `reason` va en `params`."""

    def __init__(self, code: str, reason: str = ""):
        super().__init__(code if not reason else f"{code}: {reason}")
        self.code, self.reason = code, reason


def supported() -> bool:
    """Windows con el hub empaquetado por el instalador (en desarrollo no hay un .exe que programar)."""
    return platform_name() == "windows" and bool(getattr(sys, "frozen", False))


def current_user() -> str:
    """DOMINIO\\usuario de quien ejecuta el hub (el que inició sesión)."""
    domain = os.environ.get("USERDOMAIN")
    user = getpass.getuser()
    return f"{domain}\\{user}" if domain else user


def task_xml(exe: str, user: str) -> str:
    """Definición de la tarea: al iniciar sesión `user`, ejecuta `exe` como ese usuario, sin elevar y sin límite de
    tiempo (el hub no termina), sin parar si va con batería."""
    exe, user = escape(exe), escape(user)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Arranca Checkpoint al iniciar sesión.</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <StartWhenAvailable>true</StartWhenAvailable>
  </Settings>
  <Actions Context="Author"><Exec><Command>{exe}</Command></Exec></Actions>
</Task>
"""


def _run(cmd, run):
    kw = {"capture_output": True, "text": True, "timeout": TIMEOUT}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return (run or subprocess.run)(cmd, **kw)


def _reason(p) -> str:
    return ((p.stderr or "").strip() or (p.stdout or "").strip() or f"código {p.returncode}")[:300]


def is_enabled(run=None) -> bool:
    """¿Existe la tarea? Sin soporte o sin `schtasks`, False."""
    if not supported():
        return False
    try:
        return _run(["schtasks", "/Query", "/TN", TASK_NAME], run).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def enable(run=None) -> None:
    if not supported():
        raise AutostartError("err.main.autostart.not_supported")
    fd, path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:  # schtasks espera UTF-16 con BOM
            f.write(task_xml(sys.executable, current_user()))
        p = _run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", path, "/F"], run)
    except (OSError, subprocess.SubprocessError) as e:
        raise AutostartError("err.main.autostart.create_failed", str(e)[:300]) from None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if p.returncode != 0:
        raise AutostartError("err.main.autostart.create_failed", _reason(p))


def disable(run=None, exists=None) -> None:
    """Borra la tarea. Si no existía, no es un error."""
    if not supported():
        raise AutostartError("err.main.autostart.not_supported")
    try:
        p = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], run)
    except (OSError, subprocess.SubprocessError) as e:
        raise AutostartError("err.main.autostart.remove_failed", str(e)[:300]) from None
    if p.returncode != 0 and (exists or (lambda: is_enabled(run)))():
        raise AutostartError("err.main.autostart.remove_failed", _reason(p))
