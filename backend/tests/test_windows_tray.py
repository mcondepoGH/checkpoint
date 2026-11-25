"""Icono de bandeja del hub de Windows (packaging/windows/tray.py): lógica de textos, menú y acciones con mocks.
pystray y Pillow solo se importan al crear el icono real (en Windows), así que aquí no hacen falta."""

import importlib.util
from pathlib import Path

import pytest

TRAY = Path(__file__).resolve().parents[2] / "packaging" / "windows" / "tray.py"


@pytest.fixture
def tray():
    spec = importlib.util.spec_from_file_location("checkpoint_tray", TRAY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pick_lang(tray):
    assert tray.pick_lang({"CHECKPOINT_LANG": "en-US"}, "es_ES") == "en"
    assert tray.pick_lang({"CHECKPOINT_LANG": "xx"}, "en_GB") == "es"  # como el hub: valor no soportado = español
    assert tray.pick_lang({}, "es_ES") == "es"
    assert tray.pick_lang({}, "fr_FR") == "es"  # no soportado: español, como el hub
    assert tray.pick_lang({}, None) == "es"


def test_textos_aprobados(tray):
    es, en = tray.TEXTS["es"], tray.TEXTS["en"]
    assert es["tooltip"] == "Checkpoint está en marcha" and en["tooltip"] == "Checkpoint is running"
    assert es["open"] == "Abrir Checkpoint" and en["stop"] == "Stop Checkpoint"
    assert es["unreachable"] == "Checkpoint no responde" and en["unreachable"] == "Checkpoint is not responding"
    assert es["confirm"] == "¿Detener Checkpoint? Las sincronizaciones en curso se interrumpirán."
    assert en["confirm"] == "Stop Checkpoint? Syncs in progress will be interrupted."
    assert es.keys() == en.keys()


def test_menu_con_hub_respondiendo(tray):
    c = tray.TrayController("http://127.0.0.1:8088", "es", probe=lambda u: True)
    assert [i["label"] for i in c.menu()] == ["Abrir Checkpoint", "Detener Checkpoint"]
    assert all(i["enabled"] for i in c.menu())


def test_menu_sin_respuesta_avisa_y_deshabilita_abrir(tray):
    c = tray.TrayController("http://127.0.0.1:8088", "en", probe=lambda u: False)
    items = c.menu()
    assert items[0] == {"id": "status", "label": "Checkpoint is not responding", "enabled": False}
    assert [i["id"] for i in items] == ["status", "open", "stop"]
    assert next(i for i in items if i["id"] == "open")["enabled"] is False
    assert next(i for i in items if i["id"] == "stop")["enabled"] is True  # detener siempre se puede


def test_abrir_usa_el_navegador(tray):
    opened = []
    c = tray.TrayController("http://127.0.0.1:8088", "es", probe=lambda u: True, opener=opened.append)
    c.open()
    assert opened == ["http://127.0.0.1:8088"]


def test_detener_pide_confirmacion(tray):
    stopped, asked = [], []
    c = tray.TrayController(
        "http://x",
        "es",
        probe=lambda u: True,
        confirm=lambda m: asked.append(m) or False,
        stop=lambda: stopped.append(1),
    )
    c.stop()
    assert asked == ["¿Detener Checkpoint? Las sincronizaciones en curso se interrumpirán."] and stopped == []
    c.confirm = lambda m: True
    c.stop()
    assert stopped == [1]


def test_start_no_hace_nada_fuera_de_windows_y_nunca_lanza(tray, monkeypatch):
    monkeypatch.setattr(tray.sys, "platform", "linux")
    assert tray.start("http://x", {}) is False
    monkeypatch.setattr(tray.sys, "platform", "win32")
    assert tray.start("http://x", {"CHECKPOINT_NO_TRAY": "1"}) is False
    # En «Windows» simulado, sin pystray instalado: falla en silencio (el hub arranca igual).
    assert tray.start("http://x", {}) is False
