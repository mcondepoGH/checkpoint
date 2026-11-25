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


def test_icon_path_prefiere_el_bundle_y_cae_al_directorio_del_modulo(tray, tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    ico = tmp_path / "assets" / "checkpoint.ico"
    ico.write_bytes(b"x")
    monkeypatch.setattr(tray.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert tray.icon_path() == str(ico)
    monkeypatch.delattr(tray.sys, "_MEIPASS")
    assert tray.icon_path().endswith("checkpoint.ico")  # el del repositorio, junto a tray.py
    assert Path(tray.icon_path()).parent == TRAY.parent / "assets"


def test_icon_path_none_si_no_hay_recurso(tray, monkeypatch):
    monkeypatch.setattr(tray, "icon_candidates", lambda: ["/no/existe/checkpoint.ico"])
    assert tray.icon_path() is None


def test_image_carga_el_icono_real_de_checkpoint(tray):
    pytest.importorskip("PIL")
    img = tray._image()
    assert img.size == (64, 64) and img.mode == "RGBA"
    # el logo real tiene la esquina transparente (cuadrado redondeado) y no es el círculo azul dibujado: el centro es oscuro/violeta
    assert img.getpixel((0, 0))[3] == 0
    assert img.getpixel((32, 6)) != (37, 99, 235, 255)


def test_image_cae_al_dibujo_si_el_recurso_falla(tray, tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    bad = tmp_path / "checkpoint.ico"
    bad.write_bytes(b"no es un ico")
    monkeypatch.setattr(tray, "icon_candidates", lambda: [str(bad)])
    img = tray._image()
    assert img.size == (64, 64) and img.getpixel((32, 10)) == (37, 99, 235, 255)  # círculo de respaldo
    monkeypatch.setattr(tray, "icon_candidates", lambda: [])
    assert tray._image().getpixel((32, 10)) == (37, 99, 235, 255)


def _watch(tray, states, known=False, **kw):
    import threading

    stop, calls, seq = threading.Event(), [], iter(states)

    def probe(url):
        try:
            return next(seq)
        except StopIteration:
            stop.set()
            return states[-1]

    class Icon:
        def update_menu(self):
            calls.append(1)

    c = tray.TrayController("http://127.0.0.1:8088", "es", probe=probe)
    tray.watch(Icon(), c, stop, fast=0, slow=0, known=known, **kw)
    return calls


def test_watch_actualiza_menu_solo_al_cambiar(tray):
    assert len(_watch(tray, [False, False, True])) == 1
    assert len(_watch(tray, [True, True, True])) == 1  # primera lectura arriba, menú construido con «abajo»
    assert len(_watch(tray, [False, False, False])) == 0


def test_watch_detecta_caida_posterior(tray):
    assert len(_watch(tray, [False, True, True, False, False, True])) == 3


def test_watch_tolera_errores_del_probe_y_del_icono(tray):
    import threading

    stop, n = threading.Event(), {"i": 0}

    def probe(url):
        n["i"] += 1
        if n["i"] == 1:
            raise OSError("x")
        if n["i"] > 3:
            stop.set()
        return True

    class Icon:
        def update_menu(self):
            raise RuntimeError("y")

    tray.watch(Icon(), tray.TrayController("http://h:1", "es", probe=probe), stop, fast=0, slow=0)
    assert n["i"] > 3


def test_watch_termina_con_stop_activado(tray):
    import threading

    stop = threading.Event()
    stop.set()
    c = tray.TrayController("http://h:1", "es", probe=lambda u: pytest.fail("no debe sondear"))
    t = threading.Thread(target=tray.watch, args=(object(), c, stop), kwargs={"fast": 5, "slow": 5})
    t.start()
    t.join(2)
    assert not t.is_alive()
