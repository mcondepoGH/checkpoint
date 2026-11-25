"""API con «Este equipo»: modos native y docker, test de carpeta, sync y conflicto por API."""

import json
import os
import sys

import pytest
import yaml
from fastapi.testclient import TestClient

from app.core import settings
from app.api.auth import Auth
from app.main import create_app
from app.sync.transport import LocalDeviceTransport
from fakes import LocalTransport

PW = "correct horse"
USUARIO = "Zx9-usuario-no-en-rutas-7q"  # centinela: no puede aparecer en rutas del SO (p. ej. "runneradmin")
PC, LAP = "pc-1a2b3c4d", "laptop-5e6f7a8b"
# El dispositivo local es esta máquina: su `os` y sus rutas (con «/», como las guarda la config) dependen del SO.
SO = "windows" if sys.platform == "win32" else "linux"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(settings, "SSH_KEY", str(tmp_path / "keys" / "k"))
    monkeypatch.setattr(settings, "KNOWN_HOSTS", str(tmp_path / "keys" / "kh"))
    (tmp_path / "static").mkdir()
    (tmp_path / "static/index.html").write_text("<html>app</html>", encoding="utf-8")
    c = TestClient(create_app(Auth(USUARIO, PW, 1, rounds=4)))
    assert c.post("/api/login", json={"user": USUARIO, "password": PW}).status_code == 200
    c.tmp = tmp_path
    return c


def cfg(tmp, **local):
    return {
        "devices": {
            PC: {"name": "PC", "local": True, "os": SO, **local},
            LAP: {"name": "Laptop", "host": "192.0.2.10", "user": "usuario", "os": "linux"},
        },
        "games": {
            "g1": {
                "name": "Juego",
                "devices": [PC, LAP],
                "paths": {PC: (tmp / "pc saves").as_posix(), LAP: "/home/usuario/g"},
            }
        },
    }


def put_config(c, data):
    v = c.get("/api/config").json()["version"]
    return c.put("/api/config", json={"config": data, "base_version": v})


# ---- runtime expuesto ----
def test_config_expone_runtime_native(client):
    j = client.get("/api/config").json()
    assert j["runtime"] == "native" and j["platform"] in ("linux", "windows", "macos")


def test_config_expone_runtime_docker(client, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    assert client.get("/api/config").json()["runtime"] == "docker"


def test_runtime_requiere_sesion(client):
    anon = TestClient(client.app)
    assert anon.get("/api/config").status_code == 401


def test_nada_sensible_en_config(client):
    put_config(client, cfg(client.tmp))
    txt = client.get("/api/config").text
    for secreto in (PW, USUARIO, str(settings.SSH_KEY), "known_hosts", "id_ed25519"):
        assert secreto not in txt
    assert set(client.get("/api/config").json()) == {"version", "config", "error", "runtime", "platform"}


# ---- guardar config ----
def test_guardar_local_ok_en_native(client):
    r = put_config(client, cfg(client.tmp))
    assert r.status_code == 200 and r.json()["changed"] is True
    saved = client.get("/api/config").json()["config"]["devices"][PC]
    assert saved == {"name": "PC", "local": True, "os": SO}
    txt = settings.CONFIG_PATH.read_text(encoding="utf-8")
    assert "local: true" in txt
    assert yaml.safe_load(txt)["devices"][LAP]["host"] == "192.0.2.10"


def test_guardar_local_en_docker_422_con_mensaje(client, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    r = put_config(client, cfg(client.tmp))
    assert r.status_code == 422
    assert r.json()["errors"][f"devices.{PC}.local"]["code"] == "err.config.local_docker"
    assert not settings.CONFIG_PATH.exists() or "local" not in settings.CONFIG_PATH.read_text(encoding="utf-8")


def test_validate_en_vivo_docker_y_native(client, monkeypatch):
    j = client.post("/api/config/validate", json={"config": cfg(client.tmp)}).json()
    assert j == {"ok": True, "errors": {}}
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    j = client.post("/api/config/validate", json={"config": cfg(client.tmp)}).json()
    assert not j["ok"] and f"devices.{PC}.local" in j["errors"]


def test_dos_locales_422(client):
    d = cfg(client.tmp)
    d["devices"][LAP] = {"name": "Otro", "local": True, "os": SO}
    r = put_config(client, d)
    assert r.status_code == 422 and f"devices.{LAP}.local" in r.json()["errors"]


def test_local_con_host_422(client):
    r = put_config(client, cfg(client.tmp, host="192.0.2.5"))
    assert r.status_code == 422 and f"devices.{PC}.host" in r.json()["errors"]


def test_diff_y_yaml_con_local(client):
    base = cfg(client.tmp)
    r = client.post("/api/config/diff", json={"config": base}).json()["diff"]
    assert PC in r["devices"]["added"]
    put_config(client, base)
    base["devices"][PC]["name"] = "Sobremesa"
    d = client.post("/api/config/diff", json={"config": base}).json()["diff"]
    assert d["devices"]["changed"][PC] == {"name": {"old": "PC", "new": "Sobremesa"}}
    y = client.post("/api/config/yaml", json={"config": base}).json()["yaml"]
    assert "Sobremesa" in y and "local: true" in y


def test_config_con_local_ya_en_fichero_y_docker_se_ve_el_error(client, monkeypatch):
    put_config(client, cfg(client.tmp))
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    settings.CONFIG_PATH.write_text(
        settings.CONFIG_PATH.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )  # fuerza recarga
    j = client.get("/api/config").json()
    assert j["error"]["params"]["causes"][0]["code"] == "err.config.local_docker" and j["runtime"] == "docker"


# ---- /api/devices/test ----
def test_test_local_sin_ruta(client):
    r = client.post("/api/devices/test", json={"device": {"local": True, "os": SO}}).json()
    assert r["ok"] and r["code"] == "err.transport.local_info"


def test_test_local_no_toca_ssh(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe usar SSH")

    monkeypatch.setattr("app.services.devices.get_transport", boom)
    monkeypatch.setattr("app.core.bootstrap.ensure_host_key", boom)
    monkeypatch.setattr("app.sync.transport.base._run", boom)
    r = client.post(
        "/api/devices/test", json={"device": {"local": True, "os": SO}, "paths": [client.tmp.as_posix()]}
    ).json()
    assert r["ok"]


def test_test_local_ruta_ok_inexistente_creable_y_fichero(client):
    t = client.tmp
    ok = client.post("/api/devices/test", json={"device": {"local": True, "os": SO}, "paths": [t.as_posix()]}).json()
    assert ok["ok"] and ok["code"] == "err.transport.folder_ok"
    nueva = client.post(
        "/api/devices/test", json={"device": {"local": True, "os": SO}, "paths": [(t / "a" / "b").as_posix()]}
    ).json()
    assert nueva["ok"] and nueva["code"] == "err.transport.folder_will_be_created"
    (t / "f").write_text("x", encoding="utf-8")
    f = client.post(
        "/api/devices/test", json={"device": {"local": True, "os": SO}, "paths": [(t / "f").as_posix()]}
    ).json()
    assert not f["ok"] and f["code"] == "err.transport.not_a_folder_short"


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="los permisos POSIX no se pueden provocar en Windows ni como root",
)
def test_test_local_ruta_ilegible_y_no_escribible(client):
    t = client.tmp
    (t / "ni").mkdir()
    (t / "ni").chmod(0)
    (t / "ro").mkdir()
    (t / "ro").chmod(0o555)
    try:
        a = client.post(
            "/api/devices/test", json={"device": {"local": True, "os": SO}, "paths": [(t / "ni").as_posix()]}
        ).json()
        b = client.post(
            "/api/devices/test", json={"device": {"local": True, "os": SO}, "paths": [(t / "ro").as_posix()]}
        ).json()
        c = client.post(
            "/api/devices/test", json={"device": {"local": True, "os": SO}, "paths": [(t / "ro" / "x").as_posix()]}
        ).json()
    finally:
        (t / "ni").chmod(0o755)
        (t / "ro").chmod(0o755)
    assert not a["ok"] and a["code"] == "err.transport.unreadable"
    assert not b["ok"] and b["code"] == "err.transport.not_writable"
    assert not c["ok"] and c["code"] == "err.transport.cannot_create_no_permission"


# normalize_path: en windows toda ruta sin unidad es path_windows; en linux se distingue relativa de «..»
INVALIDAS = (
    ["err.config.path_windows"] * 2 if SO == "windows" else ["err.config.path_absolute", "err.config.path_dotdot"]
)


def test_test_local_varias_rutas_y_rutas_invalidas(client):
    t = client.tmp
    r = client.post(
        "/api/devices/test", json={"device": {"local": True, "os": SO}, "paths": [t.as_posix(), "relativa", "/a/../b"]}
    ).json()
    assert (
        not r["ok"]
        and r["message"].count("\n") == 2
        and [x.get("code") for x in r["results"]] == ["err.transport.folder_ok", *INVALIDAS]
    )
    r = client.post("/api/devices/test", json={"device": {"local": True, "os": SO}, "paths": "x"}).json()
    assert not r["ok"]
    r = client.post("/api/devices/test", json={"device": {"local": True, "os": SO}, "paths": [1]}).json()
    assert not r["ok"]


def test_test_local_con_host_es_invalido(client):
    r = client.post("/api/devices/test", json={"device": {"local": True, "os": SO, "host": "192.0.2.1"}}).json()
    assert not r["ok"] and r["params"]["causes"][0]["path"] == "host"


def test_test_local_en_docker_rechazado(client, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    r = client.post("/api/devices/test", json={"device": {"local": True, "os": SO}}).json()
    assert not r["ok"] and r["code"] == "err.config.local_docker"


def test_test_remoto_sigue_igual(client, monkeypatch):
    monkeypatch.setattr("app.core.bootstrap.ensure_host_key", lambda h, p: False)

    class T:
        def __init__(self, d):
            pass

        def check(self):
            return None

    monkeypatch.setattr("app.services.devices.get_transport", lambda d: T(d))
    r = client.post("/api/devices/test", json={"device": {"host": "192.0.2.1", "user": "u", "os": "linux"}}).json()
    assert r["ok"] and r["code"] == "err.transport.connection_ok" and r["first_use"] is False


# ---- sync, conflicto y resolución por API ----
@pytest.fixture
def papi(client, monkeypatch):
    t = client.tmp
    put_config(client, cfg(t))
    roots = {"192.0.2.10": t / "laptop"}
    orig = LocalDeviceTransport

    def gt(dev):
        return orig(dev) if dev.local else LocalTransport(roots[dev.host])

    monkeypatch.setattr("app.sync.engine.get_transport", gt)
    (t / "pc saves").mkdir()
    (t / "laptop/home/usuario/g").mkdir(parents=True)
    return client


def wait_run(c, run_id):
    r = c.get(f"/api/runs/{run_id}/stream")
    done = [ln for ln in r.text.split("\n\n") if ln.startswith("event: done")]
    return json.loads(done[0].split("data: ", 1)[1])


def w(path, content, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_sync_por_api_con_local(papi):
    t = papi.tmp
    w(t / "pc saves/s.sav", "pc1", 1000)
    st = wait_run(papi, papi.post("/api/sync/g1", json={}).json()["run_id"])
    assert st["result"] == "ok" and st["winner"] == PC
    assert (t / "laptop/home/usuario/g/s.sav").read_text(encoding="utf-8") == "pc1"
    assert (t / "data/hub/g1/s.sav").read_text(encoding="utf-8") == "pc1"
    assert papi.get("/api/status").json()["g1"]["result"] == "ok"


def test_conflicto_y_resolucion_por_api_con_local(papi):
    t = papi.tmp
    w(t / "pc saves/s.sav", "pc1", 1000)
    wait_run(papi, papi.post("/api/sync/g1", json={}).json()["run_id"])
    w(t / "pc saves/s.sav", "pc2", 2000)
    w(t / "laptop/home/usuario/g/s.sav", "lap2", 3000)
    st = wait_run(papi, papi.post("/api/sync/g1", json={}).json()["run_id"])
    assert st["result"] == "conflict"
    sides = {s["id"]: s for s in st["conflict"]["sides"]}
    assert set(sides) == {PC, LAP} and sides[PC]["name"] == "PC" and "hash" in sides[PC]
    assert (t / "pc saves/s.sav").read_text(encoding="utf-8") == "pc2"  # nada tocado
    expect = {k: v["hash"] for k, v in sides.items()}
    r = papi.post("/api/sync/g1", json={"resolution": f"device:{PC}", "expect": expect})
    st = wait_run(papi, r.json()["run_id"])
    assert st["result"] == "ok" and st["winner"] == PC
    assert (t / "laptop/home/usuario/g/s.sav").read_text(encoding="utf-8") == "pc2"
    # el perdedor quedó versionado y la API de versiones lo muestra con el nombre actual
    vs = papi.get("/api/versions/g1").json()
    assert vs and any(s["name"] == "Laptop" for v in vs for s in v["sources"])
    lim = papi.get("/api/versions/g1/limit").json()
    assert lim["count"] == 1


def test_resolucion_por_nombre_del_local_via_api(papi):
    t = papi.tmp
    w(t / "pc saves/s.sav", "pc1", 1000)
    w(t / "laptop/home/usuario/g/s.sav", "lap1", 1500)
    st = wait_run(papi, papi.post("/api/sync/g1", json={}).json()["run_id"])
    assert st["result"] == "conflict" and st["conflict"]["reason"] == "no-baseline"
    st = wait_run(papi, papi.post("/api/sync/g1", json={"resolution": "device:PC"}).json()["run_id"])
    assert st["winner"] == PC


def test_sync_por_api_en_docker_con_local_no_arranca(papi, monkeypatch):
    """Un config con local en Docker queda inválido: la API se niega a sincronizar (500 con el motivo)."""
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")
    settings.CONFIG_PATH.write_text(settings.CONFIG_PATH.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    r = papi.post("/api/sync/g1", json={})
    assert (
        r.status_code == 500
        and r.json()["detail"]["params"]["cause"]["params"]["causes"][0]["code"] == "err.config.local_docker"
    )


def test_remoto_offline_via_api_con_local(papi, monkeypatch):
    t = papi.tmp

    def gt(dev):
        return LocalDeviceTransport(dev) if dev.local else LocalTransport(t / "laptop", down=True)

    monkeypatch.setattr("app.sync.engine.get_transport", gt)
    w(t / "pc saves/s.sav", "pc1", 1000)
    st = wait_run(papi, papi.post("/api/sync/g1", json={}).json()["run_id"])
    assert st["result"] == "ok" and st["offline"] == [LAP]
    assert (t / "data/hub/g1/s.sav").read_text(encoding="utf-8") == "pc1"


# ---- CLI serve ----
def test_cli_serve_exige_credenciales(monkeypatch, capsys):
    from app import cli

    for k in ("CHECKPOINT_USER", "CHECKPOINT_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    # Host local: arranca sin login (ver test_no_login.py); con host expuesto se niega.
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 2
    assert "CHECKPOINT_USER" in capsys.readouterr().err


def test_cli_serve_llama_a_uvicorn(monkeypatch, capsys):
    import uvicorn
    from app import cli

    monkeypatch.setenv("CHECKPOINT_USER", "u")
    monkeypatch.setenv("CHECKPOINT_PASSWORD", "p")
    llamadas = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: llamadas.append((a, k)))
    assert cli.main(["serve"]) == 0
    from app.main import app_factory

    # Objeto y no cadena "app.main:app_factory": PyInstaller no ve imports por cadena (el hub congelado no arrancaba).
    assert llamadas == [((app_factory,), {"factory": True, "host": "127.0.0.1", "port": 8088, "server_header": False})]
    monkeypatch.setenv("CHECKPOINT_HOST", "0.0.0.0")
    monkeypatch.setenv("CHECKPOINT_PORT", "9001")
    cli.main(["serve"])
    assert llamadas[1][1]["host"] == "0.0.0.0" and llamadas[1][1]["port"] == 9001
    cli.main(["serve", "--host", "192.0.2.1", "--port", "7000"])
    assert llamadas[2][1]["host"] == "192.0.2.1" and llamadas[2][1]["port"] == 7000
    err = capsys.readouterr().err
    assert "native" in err and "password" not in err.lower() and "p@" not in err
    assert cli.main(["serve", "--port", "70000"]) == 2
