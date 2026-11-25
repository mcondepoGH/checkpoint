"""Icono de bandeja del hub en Windows: «Abrir Checkpoint» y «Detener Checkpoint» (sin Administrador de tareas).

Corre en un hilo aparte del launcher (`start`), con pystray + Pillow (solo se importan en Windows y al crear el icono).
Si algo falla (librería ausente, sin bandeja), el hub arranca igual y el motivo queda en el log: la bandeja nunca lo
impide. Se desactiva con CHECKPOINT_NO_TRAY=1. Textos fuera de i18n del hub, aprobados en es/en."""

import os
import socket
import sys
import threading
import webbrowser

TEXTS = {
    "es": {
        "tooltip": "Checkpoint está en marcha",
        "open": "Abrir Checkpoint",
        "stop": "Detener Checkpoint",
        "unreachable": "Checkpoint no responde",
        "confirm": "¿Detener Checkpoint? Las sincronizaciones en curso se interrumpirán.",
    },
    "en": {
        "tooltip": "Checkpoint is running",
        "open": "Open Checkpoint",
        "stop": "Stop Checkpoint",
        "unreachable": "Checkpoint is not responding",
        "confirm": "Stop Checkpoint? Syncs in progress will be interrupted.",
    },
}


def pick_lang(environ, system_lang=None) -> str:
    """CHECKPOINT_LANG, si no el idioma de Windows; no soportado = español (como el hub)."""
    raw = environ.get("CHECKPOINT_LANG") or system_lang or ""
    short = raw.strip().lower().replace("_", "-").split("-")[0]
    return short if short in TEXTS else "es"


def system_lang():
    """Idioma de Windows (p. ej. «es-ES») con GetUserDefaultLocaleName; None si no se puede saber."""
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(85)
        return (
            buf.value
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85)
            else None
        )
    except Exception:  # noqa: BLE001
        return None


def port_open(url) -> bool:
    host, _, port = url.split("//", 1)[1].rpartition(":")
    try:
        with socket.create_connection((host.strip("[]"), int(port)), timeout=1):
            return True
    except OSError:
        return False


def _confirm_box(message: str) -> bool:
    import ctypes

    return (
        ctypes.windll.user32.MessageBoxW(None, message, "Checkpoint", 0x24) == 6
    )  # Sí/No + pregunta -> IDYES


def _hard_stop() -> None:
    os._exit(
        0
    )  # el hub corre uvicorn en el hilo principal: no hay un cierre limpio al alcance del icono


class TrayController:
    """Lógica del menú, sin dependencias gráficas: se prueba con mocks."""

    def __init__(
        self,
        url,
        lang,
        probe=port_open,
        opener=webbrowser.open,
        confirm=_confirm_box,
        stop=_hard_stop,
    ):
        self.url, self.t = url, TEXTS[lang]
        self.probe, self.opener, self.confirm, self._stop = probe, opener, confirm, stop

    def menu(self) -> list:
        alive = bool(self.probe(self.url))
        items = []
        if not alive:
            items.append(
                {"id": "status", "label": self.t["unreachable"], "enabled": False}
            )
        items.append({"id": "open", "label": self.t["open"], "enabled": alive})
        items.append({"id": "stop", "label": self.t["stop"], "enabled": True})
        return items

    def open(self) -> None:
        self.opener(self.url)

    def stop(self) -> None:
        if self.confirm(self.t["confirm"]):
            self._stop()


def icon_candidates():
    """Dónde buscar el icono: el bundle de PyInstaller (assets/, ver checkpoint.spec) y, sin empaquetar, junto a este fichero."""
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(getattr(sys, "_MEIPASS", here), "assets", "checkpoint.ico"),
        os.path.join(here, "assets", "checkpoint.ico"),
    ]


def icon_path():
    return next((p for p in icon_candidates() if os.path.isfile(p)), None)


def _drawn_image(size=64):
    """Respaldo: círculo azul con rombo dibujado al vuelo, si el icono real no se puede cargar."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(37, 99, 235, 255))
    d.polygon([(22, 32), (32, 20), (42, 32), (32, 44)], fill=(255, 255, 255, 255))
    return img


def _image(size=64):
    """Icono de Checkpoint (assets/checkpoint.ico del bundle) a 64x64; si falla, el dibujo de respaldo."""
    try:
        from PIL import Image

        path = icon_path()
        if path:
            with Image.open(path) as ico:
                ico.size = max(
                    ico.info.get("sizes") or {ico.size}
                )  # el mayor tamaño del .ico, para reducir sin perder calidad
                img = ico.convert("RGBA")
            return img.resize((size, size), Image.LANCZOS)
    except Exception as e:  # noqa: BLE001
        print(
            f"icono de bandeja no disponible, se usa el dibujado: {e}", file=sys.stderr
        )
    return _drawn_image(size)


def watch(icon, controller, stop, fast=1.0, slow=3.0, known=False) -> None:
    """Vigila el hub y llama a icon.update_menu() cuando cambia vivo/caído (pystray no reevalúa el menú solo).
    `known` = estado con el que se construyó el menú (el launcher lanza la bandeja antes de que el hub escuche).
    Sondea cada `fast` s hasta ver el hub arriba, y cada `slow` s después. Termina al activar `stop`."""
    while not stop.is_set():
        try:
            alive = bool(controller.probe(controller.url))
        except Exception:  # noqa: BLE001
            alive = False
        if alive != known:
            known = alive
            try:
                icon.update_menu()
            except Exception as e:  # noqa: BLE001
                print(f"bandeja: no se pudo actualizar el menú: {e}", file=sys.stderr)
        if stop.wait(slow if known else fast):
            break


def run(url, lang) -> None:
    import pystray

    c = TrayController(url, lang)

    def menu():
        # pystray evalúa el menú al abrirlo: así «no responde» refleja el estado de ese momento.
        return (
            pystray.MenuItem(
                i["label"],
                {"open": c.open, "stop": c.stop}.get(i["id"], lambda: None),
                enabled=i["enabled"],
            )
            for i in c.menu()
        )

    icon = pystray.Icon("checkpoint", _image(), c.t["tooltip"], pystray.Menu(menu))
    stop = threading.Event()
    threading.Thread(
        target=watch, args=(icon, c, stop), daemon=True, name="checkpoint-tray-watch"
    ).start()
    try:
        icon.run()
    finally:
        stop.set()


def start(url, environ=None) -> bool:
    """Lanza la bandeja en un hilo daemon. False si no aplica (no es Windows, desactivada) o no pudo arrancar."""
    environ = os.environ if environ is None else environ
    if not sys.platform.startswith("win") or environ.get("CHECKPOINT_NO_TRAY") == "1":
        return False
    try:
        lang = pick_lang(environ, system_lang())
        import pystray  # noqa: F401 - falla aquí, no dentro del hilo, si no está

        threading.Thread(
            target=run, args=(url, lang), daemon=True, name="checkpoint-tray"
        ).start()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"bandeja no disponible: {e}", file=sys.stderr)
        return False
