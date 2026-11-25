"""Modo sin login: solo con host local (127.0.0.1, ::1, localhost). Otro host sin credenciales: el hub no arranca."""

import pytest
from fastapi.testclient import TestClient

from app import cli
from app.api.auth import Auth
from app.core import settings
from app.main import create_app


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch, tmp_path):
    for k in ("USER", "PASSWORD", "HOST"):
        monkeypatch.delenv("CHECKPOINT_" + k, raising=False)
    monkeypatch.setattr(settings, "NO_LOGIN_ALLOWED", False)
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "static").mkdir()
    (tmp_path / "static/index.html").write_text("<html>app</html>", encoding="utf-8")


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "[::1]", "localhost", "LocalHost"])
def test_is_local_host_acepta_solo_loopback(host):
    assert settings.is_local_host(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.1", "::", "", None, "127.0.0.2", "localhost.example.com"])
def test_is_local_host_rechaza_el_resto(host):
    assert not settings.is_local_host(host)


def test_auth_sin_credenciales_sigue_fallando_por_defecto():
    with pytest.raises(RuntimeError):
        Auth.from_env({})
    with pytest.raises(RuntimeError):
        Auth.from_env({"CHECKPOINT_USER": "u"})


def test_auth_sin_login_deja_pasar_sin_cookie():
    a = Auth.from_env({}, allow_no_login=True, rounds=4)
    assert a.no_login and a.user == settings.NO_LOGIN_USER
    assert a.valid(None) and a.valid("cualquier-cosa")


def test_con_credenciales_no_hay_sin_login_aunque_se_permita():
    a = Auth.from_env({"CHECKPOINT_USER": "u", "CHECKPOINT_PASSWORD": "p"}, allow_no_login=True, rounds=4)
    assert not a.no_login and not a.valid(None)


def test_api_en_modo_sin_login():
    c = TestClient(create_app(Auth.from_env({}, allow_no_login=True, rounds=4)))
    assert c.get("/api/session").json() == {"authenticated": True, "noLogin": True}
    assert c.get("/api/config").status_code == 200  # una ruta protegida pasa sin cookie
    assert c.post("/api/login", json={"user": "x", "password": "y"}).status_code == 200


def test_api_con_login_expone_nologin_falso():
    c = TestClient(create_app(Auth("admin", "pw", 1, rounds=4)))
    assert c.get("/api/session").json() == {"authenticated": False, "noLogin": False}
    assert c.get("/api/config").status_code == 401


def test_serve_se_niega_sin_credenciales_en_host_expuesto(monkeypatch, capsys):
    import uvicorn

    llamadas = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: llamadas.append(k))
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 2
    assert llamadas == []
    assert capsys.readouterr().err.strip() == (
        "no se puede arrancar sin usuario ni contraseña en 0.0.0.0: solo se permite en 127.0.0.1. "
        "Define CHECKPOINT_USER y CHECKPOINT_PASSWORD o arranca con --host 127.0.0.1"
    )


def test_serve_host_por_entorno_expuesto_tambien_se_niega(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_HOST", "192.0.2.1")
    assert cli.main(["serve"]) == 2


def test_serve_en_local_sin_credenciales_arranca_y_lo_permite(monkeypatch):
    import uvicorn

    visto = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: visto.append((k["host"], settings.NO_LOGIN_ALLOWED)))
    assert cli.main(["serve"]) == 0
    assert visto == [("127.0.0.1", True)]


def test_serve_con_credenciales_en_host_expuesto_no_activa_sin_login(monkeypatch):
    import uvicorn

    monkeypatch.setenv("CHECKPOINT_USER", "u")
    monkeypatch.setenv("CHECKPOINT_PASSWORD", "p")
    visto = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: visto.append(settings.NO_LOGIN_ALLOWED))
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 0
    assert visto == [False]


def test_app_factory_sin_credenciales_y_sin_permiso_falla(monkeypatch):
    with pytest.raises(RuntimeError):
        Auth.from_env()
