"""Launcher del instalador de Windows (packaging/windows/launcher.py): .env del usuario, comprobación del modo sin
login y arranque. Se carga por ruta (no es parte del paquete `app`) y corre en Linux con mocks."""

import importlib.util
import sys
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[2] / "packaging" / "windows" / "launcher.py"


@pytest.fixture
def launcher():
    spec = importlib.util.spec_from_file_location("checkpoint_launcher", LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_env_file_ignora_comentarios_y_quita_comillas(launcher):
    text = '# comentario\n\nCHECKPOINT_USER=ana\nCHECKPOINT_PASSWORD="a=b c"\n  CHECKPOINT_PORT = 9000 \nsinigual\n=x\n'
    assert launcher.parse_env_file(text) == {
        "CHECKPOINT_USER": "ana",
        "CHECKPOINT_PASSWORD": "a=b c",
        "CHECKPOINT_PORT": "9000",
    }


def test_parse_env_file_acepta_bom_y_crlf(launcher):
    assert launcher.parse_env_file("﻿CHECKPOINT_USER=ana\r\nCHECKPOINT_PASSWORD=x\r\n") == {
        "CHECKPOINT_USER": "ana",
        "CHECKPOINT_PASSWORD": "x",
    }


def test_parse_env_file_solo_claves_checkpoint(launcher):
    assert launcher.parse_env_file("PATH=/x\nCHECKPOINT_LANG=en\n") == {"CHECKPOINT_LANG": "en"}


def test_home_dir_prioriza_home_dir_y_si_no_appdata(launcher):
    assert launcher.home_dir({"CHECKPOINT_HOME_DIR": "/x/y"}) == Path("/x/y")
    assert launcher.home_dir({"APPDATA": "/r/AppData"}) == Path("/r/AppData") / "checkpoint"


def test_load_env_lee_el_fichero_y_el_entorno_manda(launcher, tmp_path):
    (tmp_path / ".env").write_text("CHECKPOINT_USER=ana\nCHECKPOINT_PORT=9000\n", encoding="utf-8")
    env = {"CHECKPOINT_HOME_DIR": str(tmp_path), "CHECKPOINT_PORT": "7000"}
    launcher.load_env(env)
    assert env["CHECKPOINT_USER"] == "ana"
    assert env["CHECKPOINT_PORT"] == "7000"


def test_load_env_sin_fichero_no_falla(launcher, tmp_path):
    env = {"CHECKPOINT_HOME_DIR": str(tmp_path)}
    launcher.load_env(env)
    assert env == {"CHECKPOINT_HOME_DIR": str(tmp_path)}


@pytest.mark.parametrize(
    "env,argv,expected",
    [
        ({}, [], "127.0.0.1"),
        ({"CHECKPOINT_HOST": "0.0.0.0"}, [], "0.0.0.0"),
        ({"CHECKPOINT_HOST": "0.0.0.0"}, ["--host", "127.0.0.1"], "127.0.0.1"),
        ({}, ["--host=192.168.1.5"], "192.168.1.5"),
    ],
)
def test_effective_host(launcher, env, argv, expected):
    assert launcher.effective_host(env, argv) == expected


def test_check_mode_rechaza_sin_login_expuesto(launcher):
    msg = launcher.check_mode({}, ["--host", "0.0.0.0"])
    assert msg and "0.0.0.0" in msg and "CHECKPOINT_USER" in msg


def test_check_mode_acepta_local_o_con_credenciales(launcher):
    assert launcher.check_mode({}, []) is None
    assert (
        launcher.check_mode({"CHECKPOINT_USER": "a", "CHECKPOINT_PASSWORD": "b", "CHECKPOINT_HOST": "0.0.0.0"}, [])
        is None
    )


def test_main_carga_env_y_sirve(launcher, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("CHECKPOINT_USER=ana\nCHECKPOINT_PASSWORD=x\n", encoding="utf-8")
    monkeypatch.setenv("CHECKPOINT_HOME_DIR", str(tmp_path))
    monkeypatch.delenv("CHECKPOINT_USER", raising=False)
    monkeypatch.delenv("CHECKPOINT_PASSWORD", raising=False)
    calls = []
    rc = launcher.main(["--port", "9001"], serve=lambda argv: calls.append(argv) or 0, notify=lambda m: None)
    assert rc == 0
    assert calls == [["serve", "--port", "9001"]]
    import os

    assert os.environ["CHECKPOINT_USER"] == "ana"
    monkeypatch.delenv("CHECKPOINT_USER")
    monkeypatch.delenv("CHECKPOINT_PASSWORD")


def test_main_rechazo_notifica_y_devuelve_2(launcher, tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_HOME_DIR", str(tmp_path))
    monkeypatch.delenv("CHECKPOINT_USER", raising=False)
    monkeypatch.delenv("CHECKPOINT_PASSWORD", raising=False)
    msgs, served = [], []
    rc = launcher.main(["--host", "0.0.0.0"], serve=lambda a: served.append(a) or 0, notify=msgs.append)
    assert rc == 2 and not served and len(msgs) == 1 and "0.0.0.0" in msgs[0]


def test_main_sin_consola_redirige_a_log(launcher, tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_HOME_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    seen = {}

    def serve(argv):
        seen["stderr_ok"] = sys.stderr is not None
        print("hola", file=sys.stderr)
        return 0

    assert launcher.main([], serve=serve, notify=lambda m: None) == 0
    assert seen["stderr_ok"]
    sys.stderr.flush()
    assert "hola" in (tmp_path / "logs" / "checkpoint.log").read_text(encoding="utf-8")


def test_split_open_flag(launcher):
    assert launcher.split_open_flag(["--open", "--port", "1"]) == (["--port", "1"], True)
    assert launcher.split_open_flag([]) == ([], False)


@pytest.mark.parametrize(
    "env,argv,expected",
    [
        ({}, [], "http://127.0.0.1:8088"),
        ({"CHECKPOINT_PORT": "9"}, [], "http://127.0.0.1:9"),
        ({}, ["--port", "7", "--host", "::1"], "http://[::1]:7"),
        ({"CHECKPOINT_HOST": "0.0.0.0"}, ["--port=5"], "http://127.0.0.1:5"),
    ],
)
def test_url_for(launcher, env, argv, expected):
    assert launcher.url_for(env, argv) == expected


def test_open_when_ready_abre_cuando_responde_y_se_rinde_si_no(launcher):
    opened = []
    answers = iter([False, False, True])
    assert (
        launcher.open_when_ready("http://x:1", probe=lambda u: next(answers), opener=opened.append, interval=0) is True
    )
    assert opened == ["http://x:1"]
    assert (
        launcher.open_when_ready("http://x:1", probe=lambda u: False, opener=opened.append, timeout=0.05, interval=0)
        is False
    )
    assert len(opened) == 1


def test_main_con_open_lanza_el_hilo(launcher, tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_HOME_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(launcher, "open_when_ready", lambda url, **kw: calls.append(url))
    served = []
    assert launcher.main(["--open"], serve=lambda a: served.append(a) or 0, notify=lambda m: None) == 0
    assert served == [["serve"]]
    import time

    for _ in range(50):
        if calls:
            break
        time.sleep(0.02)
    assert calls == ["http://127.0.0.1:8088"]


def test_port_open_detecta_un_puerto_escuchando(launcher):
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        assert launcher._port_open(f"http://127.0.0.1:{s.getsockname()[1]}") is True
    assert launcher._port_open("http://127.0.0.1:1") is False


def test_main_lanza_la_bandeja_con_la_url_y_un_fallo_no_impide_servir(launcher, tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_HOME_DIR", str(tmp_path))
    urls = []
    assert launcher.main(["--port", "9"], serve=lambda a: 0, notify=lambda m: None, tray=urls.append) == 0
    assert urls == ["http://127.0.0.1:9"]


def test_tray_por_defecto_no_rompe_el_arranque(launcher, tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_HOME_DIR", str(tmp_path))
    assert launcher.main([], serve=lambda a: 0, notify=lambda m: None) == 0  # sin `tray` importable: False en silencio
