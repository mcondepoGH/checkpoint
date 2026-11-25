"""Punto de entrada del hub empaquetado para Windows (PyInstaller, sin consola).

Hace cuatro cosas antes de arrancar `app.cli serve`:
  1. Lee `%APPDATA%\\checkpoint\\.env` (o `CHECKPOINT_HOME_DIR\\.env`), que escribe el instalador con el usuario y la
     contraseña (en claro: documentado). Lo que ya esté en el entorno manda sobre el fichero.
  2. Comprueba el modo sin login: sin credenciales solo se arranca en 127.0.0.1, ::1 o localhost. Si no, avisa con un
     cuadro de mensaje (no hay consola) y sale con código 2.
  3. Sin consola (`sys.stdout`/`sys.stderr` a None), redirige la salida a `<datos>\\logs\\checkpoint.log`.
  4. Lanza el icono de bandeja (tray.py) y, con --open, abre el navegador cuando el hub responde.

Los textos de este fichero van fuera de i18n y en español (como los del CLI)."""

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ENV_FILE = ".env"
LOG_NAME = "checkpoint.log"
LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")
REFUSAL = (
    "no se puede arrancar sin usuario ni contraseña en {host}: solo se permite en 127.0.0.1. "
    "Define CHECKPOINT_USER y CHECKPOINT_PASSWORD o arranca con --host 127.0.0.1"
)


def home_dir(environ=None) -> Path:
    """Carpeta de datos: CHECKPOINT_HOME_DIR, o %APPDATA%\\checkpoint (misma lógica que `settings.native_home`)."""
    environ = os.environ if environ is None else environ
    forced = environ.get("CHECKPOINT_HOME_DIR")
    if forced:
        return Path(forced).expanduser()
    return Path(environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "checkpoint"


def parse_env_file(text: str) -> dict:
    """KEY=VALUE por línea; ignora comentarios, líneas sin `=`, claves que no sean CHECKPOINT_* y comillas envolventes."""
    out = {}
    for line in text.lstrip("﻿").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not key.startswith("CHECKPOINT_"):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def load_env(environ=None) -> dict:
    """Vuelca el .env del usuario en `environ` sin pisar lo que ya haya. Sin fichero o ilegible, no hace nada."""
    environ = os.environ if environ is None else environ
    try:
        text = (home_dir(environ) / ENV_FILE).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return environ
    for k, v in parse_env_file(text).items():
        if environ.get(k) in (None, ""):
            environ[k] = v
    return environ


def effective_host(environ, argv) -> str:
    """--host del argv, o CHECKPOINT_HOST, o 127.0.0.1."""
    for i, a in enumerate(argv):
        if a == "--host" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--host="):
            return a.split("=", 1)[1]
    return environ.get("CHECKPOINT_HOST") or "127.0.0.1"


def _is_local(host) -> bool:
    h = (host or "").strip().lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    return h in LOCAL_HOSTS


def check_mode(environ, argv):
    """Mensaje de rechazo si se pide arrancar sin credenciales en un host no local; None si se puede arrancar."""
    if environ.get("CHECKPOINT_USER") and environ.get("CHECKPOINT_PASSWORD"):
        return None
    host = effective_host(environ, argv)
    return None if _is_local(host) else REFUSAL.format(host=host)


def _notify(message: str) -> None:
    """Cuadro de mensaje de Windows (sin consola no hay otra forma de avisar); en otros sistemas, stderr."""
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "Checkpoint", 0x10)
            return
        except Exception:  # noqa: BLE001 - el aviso es best-effort: queda además en el log
            pass
    print(message, file=sys.stderr)


def _ensure_streams(home: Path) -> None:
    """Sin consola (PyInstaller windowed) stdout/stderr son None y uvicorn falla al loguear: van a un fichero."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stream = open(logs / LOG_NAME, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - vive todo el proceso
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def split_open_flag(argv):
    """(argv sin `--open`, True si estaba). `--open` abre el navegador cuando el hub responde (lo usa el instalador)."""
    return [a for a in argv if a != "--open"], "--open" in argv


def url_for(environ, argv) -> str:
    host = effective_host(environ, argv)
    host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    port = next((argv[i + 1] for i, a in enumerate(argv) if a == "--port" and i + 1 < len(argv)), None)
    port = port or ([a.split("=", 1)[1] for a in argv if a.startswith("--port=")] or [None])[0]
    return f"http://{host}:{port or environ.get('CHECKPOINT_PORT') or '8088'}"


def open_when_ready(url, probe=None, opener=webbrowser.open, timeout=60.0, interval=0.5) -> bool:
    """Espera a que el puerto del hub acepte conexiones y abre el navegador. False si no responde en `timeout` s."""
    probe = probe or _port_open
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe(url):
            opener(url)
            return True
        time.sleep(interval)
    return False


def _port_open(url) -> bool:
    host, _, port = url.split("//", 1)[1].rpartition(":")
    try:
        with socket.create_connection((host.strip("[]"), int(port)), timeout=1):
            return True
    except OSError:
        return False


def _default_serve(argv) -> int:
    from app import cli

    return cli.main(argv)


def _default_tray(url) -> bool:
    """Icono de bandeja (tray.py, junto a este fichero en el bundle). Cualquier fallo se ignora: el hub arranca igual."""
    try:
        import tray

        return tray.start(url, os.environ)
    except Exception as e:  # noqa: BLE001
        print(f"bandeja no disponible: {e}", file=sys.stderr)
        return False


def main(argv=None, serve=None, notify=None, tray=None) -> int:
    argv, open_browser = split_open_flag(list(sys.argv[1:] if argv is None else argv))
    serve = serve or _default_serve
    notify = notify or _notify
    tray = tray or _default_tray
    load_env(os.environ)
    _ensure_streams(home_dir(os.environ))
    problem = check_mode(os.environ, argv)
    if problem:
        print(problem, file=sys.stderr)
        notify(problem)
        return 2
    url = url_for(os.environ, argv)
    tray(url)
    if open_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    return serve(["serve", *argv])


if __name__ == "__main__":
    sys.exit(main())
