"""Autoarranque en Windows con una Tarea Programada «al iniciar sesión» (services/autostart.py). Todo con mocks:
`schtasks` no existe en Linux, así que se inyecta el ejecutor de comandos."""

import subprocess

import pytest
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.core import settings
from app.main import create_app
from app.services import autostart


class FakeRun:
    """Sustituto de subprocess.run: guarda las llamadas y devuelve el CompletedProcess programado."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls, self.result = [], (returncode, stdout, stderr)

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, self.result[0], self.result[1], self.result[2])


@pytest.fixture
def win(monkeypatch):
    """Windows con el hub congelado (instalador)."""
    monkeypatch.setattr(autostart, "platform_name", lambda: "windows")
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", r"C:\Users\ana\AppData\Local\Programs\Checkpoint\checkpoint.exe")
    monkeypatch.setattr(autostart, "current_user", lambda: r"PC\ana")


def test_supported_solo_windows_con_instalador(monkeypatch, win):
    assert autostart.supported() is True
    monkeypatch.setattr(autostart, "platform_name", lambda: "linux")
    assert autostart.supported() is False
    monkeypatch.setattr(autostart, "platform_name", lambda: "windows")
    monkeypatch.delattr(autostart.sys, "frozen")
    assert autostart.supported() is False


def test_task_xml_dispara_al_iniciar_sesion_del_usuario_sin_privilegios(win):
    xml = autostart.task_xml(r"C:\Program Files\Checkpoint\checkpoint.exe", r"PC\ana")
    assert "<LogonTrigger>" in xml and r"<UserId>PC\ana</UserId>" in xml
    assert "<RunLevel>LeastPrivilege</RunLevel>" in xml
    assert r"<Command>C:\Program Files\Checkpoint\checkpoint.exe</Command>" in xml
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in xml  # sin límite de tiempo: el hub no termina


def test_task_xml_escapa_caracteres_especiales():
    xml = autostart.task_xml(r"C:\a&b\c.exe", r"PC\a<b")
    assert "a&amp;b" in xml and "a&lt;b" in xml


def test_is_enabled_consulta_la_tarea(win):
    run = FakeRun(0)
    assert autostart.is_enabled(run=run) is True
    assert run.calls[0][0][:2] == ["schtasks", "/Query"] and "Checkpoint" in run.calls[0][0]
    assert autostart.is_enabled(run=FakeRun(1)) is False


def test_is_enabled_false_si_no_soportado(monkeypatch):
    monkeypatch.setattr(autostart, "platform_name", lambda: "linux")
    run = FakeRun(0)
    assert autostart.is_enabled(run=run) is False and run.calls == []


def test_enable_crea_la_tarea_desde_un_xml_temporal(win):
    run = FakeRun(0)
    autostart.enable(run=run)
    cmd = run.calls[0][0]
    assert cmd[:2] == ["schtasks", "/Create"] and "/XML" in cmd and "/F" in cmd and "Checkpoint" in cmd


def test_enable_error_de_schtasks(win):
    with pytest.raises(autostart.AutostartError) as e:
        autostart.enable(run=FakeRun(1, stderr="Acceso denegado\n"))
    assert e.value.code == "err.main.autostart.create_failed" and e.value.reason == "Acceso denegado"


def test_disable_borra_la_tarea_y_es_idempotente(win):
    run = FakeRun(0)
    autostart.disable(run=run)
    assert run.calls[0][0][:2] == ["schtasks", "/Delete"] and "/F" in run.calls[0][0]
    # La tarea no existía: no es error.
    autostart.disable(run=FakeRun(1, stderr="ERROR: The system cannot find the file specified."), exists=lambda: False)


def test_disable_error_real(win):
    with pytest.raises(autostart.AutostartError) as e:
        autostart.disable(run=FakeRun(1, stderr="boom"), exists=lambda: True)
    assert e.value.code == "err.main.autostart.remove_failed"


def test_no_soportado_lanza(monkeypatch):
    monkeypatch.setattr(autostart, "platform_name", lambda: "linux")
    for fn in (autostart.enable, autostart.disable):
        with pytest.raises(autostart.AutostartError) as e:
            fn(run=FakeRun())
        assert e.value.code == "err.main.autostart.not_supported"


def test_schtasks_ausente_es_error_controlado(win):
    def boom(cmd, **kw):
        raise FileNotFoundError("schtasks")

    with pytest.raises(autostart.AutostartError):
        autostart.enable(run=boom)
    assert autostart.is_enabled(run=boom) is False


# ---- endpoints ----
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    c = TestClient(create_app(Auth("admin", "pw", 1, rounds=4)))
    return c


def _login(c):
    assert c.post("/api/login", json={"user": "admin", "password": "pw"}).status_code == 200


def test_endpoints_requieren_sesion(api):
    assert api.get("/api/autostart").status_code == 401
    assert api.put("/api/autostart", json={"enabled": True}).status_code == 401


def test_get_fuera_de_windows(api, monkeypatch):
    monkeypatch.setattr(autostart, "platform_name", lambda: "linux")
    _login(api)
    assert api.get("/api/autostart").json() == {"supported": False, "enabled": False}
    r = api.put("/api/autostart", json={"enabled": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "err.main.autostart.not_supported"


def test_put_activa_y_desactiva(api, monkeypatch, win):
    state = {"on": False}
    monkeypatch.setattr(autostart, "is_enabled", lambda run=None: state["on"])
    monkeypatch.setattr(autostart, "enable", lambda run=None: state.update(on=True))
    monkeypatch.setattr(autostart, "disable", lambda run=None, exists=None: state.update(on=False))
    _login(api)
    assert api.get("/api/autostart").json() == {"supported": True, "enabled": False}
    assert api.put("/api/autostart", json={"enabled": True}).json() == {"supported": True, "enabled": True}
    assert api.put("/api/autostart", json={"enabled": False}).json() == {"supported": True, "enabled": False}
    assert api.put("/api/autostart", json={"enabled": "si"}).status_code == 422


def test_put_error_de_schtasks_es_500_con_motivo(api, monkeypatch, win):
    def fail(run=None):
        raise autostart.AutostartError("err.main.autostart.create_failed", "Acceso denegado")

    monkeypatch.setattr(autostart, "enable", fail)
    monkeypatch.setattr(autostart, "is_enabled", lambda run=None: False)
    _login(api)
    r = api.put("/api/autostart", json={"enabled": True})
    assert r.status_code == 500
    assert r.json()["detail"] == {"code": "err.main.autostart.create_failed", "params": {"reason": "Acceso denegado"}}
