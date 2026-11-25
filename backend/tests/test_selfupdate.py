"""Actualización con un clic (services/selfupdate.py + endpoints /api/updates/install). Sin red ni Windows: el abridor
HTTP, el lanzador del instalador y la salida del proceso se inyectan."""

import hashlib
import io
import time

import pytest
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.core import settings, updates
from app.main import create_app
from app.services import selfupdate
from app.services.runs import RunRegistry

from test_api import PW, login

VER = "0.5.0"
NAME = f"Checkpoint-Setup-{VER}.exe"
BODY = b"MZ-instalador-falso" * 100
HASH = hashlib.sha256(BODY).hexdigest()
BASE = "https://github.com/o/r/releases/download/v0.5.0/"


def release(assets=True, tag="v0.5.0", **kw):
    r = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "body": "notas",
        "html_url": f"https://github.com/o/r/releases/tag/{tag}",
        **kw,
    }
    if assets:
        r["assets"] = [
            {"name": NAME, "browser_download_url": BASE + NAME, "size": len(BODY)},
            {"name": NAME + ".sha256", "browser_download_url": BASE + NAME + ".sha256", "size": 90},
        ]
    return r


# ---- pick_latest: el instalador publicado ----
def test_pick_latest_incluye_el_instalador_con_su_hash():
    latest = updates.pick_latest([release()])
    assert latest["installer"] == {"name": NAME, "url": BASE + NAME, "sha256_url": BASE + NAME + ".sha256"}


def test_pick_latest_sin_assets_o_incompletos_no_hay_instalador():
    assert updates.pick_latest([release(assets=False)])["installer"] is None
    r = release()
    r["assets"] = r["assets"][:1]  # falta el hash: no se ofrece
    assert updates.pick_latest([r])["installer"] is None
    r = release()
    r["assets"][0]["name"] = "Checkpoint-Setup-9.9.9.exe"  # otra versión
    assert updates.pick_latest([r])["installer"] is None


@pytest.mark.parametrize(
    "bad",
    [
        "http://github.com/x.exe",
        "https://evil.example/x.exe",
        "https://github.com.evil.example/x.exe",
        "ftp://github.com/x",
    ],
)
def test_pick_latest_rechaza_urls_que_no_son_de_github(bad):
    r = release()
    r["assets"][0]["browser_download_url"] = bad
    assert updates.pick_latest([r])["installer"] is None


# ---- hash ----
def test_parse_sha256():
    assert selfupdate.parse_sha256(f"{HASH}  {NAME}\n", NAME) == HASH
    assert selfupdate.parse_sha256(f"{HASH.upper()} *{NAME}", NAME) == HASH
    assert selfupdate.parse_sha256(HASH, NAME) == HASH  # solo el hash
    assert selfupdate.parse_sha256(f"{HASH}  otro.exe", NAME) is None
    assert selfupdate.parse_sha256("no es un hash", NAME) is None
    assert selfupdate.parse_sha256("", NAME) is None


# ---- descarga ----
class FakeOpener:
    def __init__(self, files):
        self.files, self.urls = files, []

    def open(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        self.urls.append(url)
        if url not in self.files:
            raise OSError("404")
        return _Resp(self.files[url])


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def make_updater(tmp_path, monkeypatch, *, files=None, busy=False, supported=True, popen=None, rels=None):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(updates, "installed_version", lambda: "0.4.2")
    checker = updates.UpdateChecker(fetch=lambda repo: rels or [release()])
    monkeypatch.setattr(selfupdate, "supported", lambda: supported)
    files = files if files is not None else {BASE + NAME: BODY, BASE + NAME + ".sha256": f"{HASH}  {NAME}\n".encode()}
    launched, exits = [], []
    up = selfupdate.SelfUpdater(
        checker,
        busy=lambda: busy,
        opener=FakeOpener(files),
        popen=popen or (lambda cmd, **kw: launched.append(cmd)),
        exit_fn=lambda: exits.append(1),
        exit_delay=0,
    )
    up.launched, up.exits = launched, exits
    return up


def wait(up, states=("restarting", "error"), timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if up.status()["state"] in states:
            return up.status()
        time.sleep(0.01)
    raise AssertionError(up.status())


def test_camino_feliz_descarga_verifica_lanza_y_sale(tmp_path, monkeypatch):
    up = make_updater(tmp_path, monkeypatch)
    assert up.status()["state"] == "idle"
    up.start()
    st = wait(up)
    assert st["state"] == "restarting" and st["version"] == VER
    cmd = up.launched[0]
    assert cmd[0].endswith(NAME) and "/VERYSILENT" in cmd and "/SUPPRESSMSGBOXES" in cmd and "/NORESTART" in cmd
    assert (tmp_path / "update" / NAME).read_bytes() == BODY
    for _ in range(100):
        if up.exits:
            break
        time.sleep(0.01)
    assert up.exits == [1]


def test_hash_distinto_no_instala_nada_y_borra_la_descarga(tmp_path, monkeypatch):
    files = {BASE + NAME: BODY + b"x", BASE + NAME + ".sha256": f"{HASH}  {NAME}".encode()}
    up = make_updater(tmp_path, monkeypatch, files=files)
    up.start()
    st = wait(up)
    assert st["state"] == "error" and st["error"]["code"] == "err.main.updates.hash_mismatch"
    assert up.launched == [] and up.exits == []
    assert not (tmp_path / "update" / NAME).exists()


def test_hash_ilegible_tambien_es_error_de_hash(tmp_path, monkeypatch):
    files = {BASE + NAME: BODY, BASE + NAME + ".sha256": b"basura"}
    up = make_updater(tmp_path, monkeypatch, files=files)
    up.start()
    assert wait(up)["error"]["code"] == "err.main.updates.hash_mismatch"
    assert up.launched == []


def test_fallo_de_red_es_download_failed_con_motivo(tmp_path, monkeypatch):
    up = make_updater(tmp_path, monkeypatch, files={})
    up.start()
    st = wait(up)
    assert st["error"]["code"] == "err.main.updates.download_failed" and "reason" in st["error"]["params"]


def test_instalador_demasiado_grande(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate, "MAX_INSTALLER_BYTES", 10)
    up = make_updater(tmp_path, monkeypatch)
    up.start()
    assert wait(up)["error"]["code"] == "err.main.updates.download_failed"
    assert not (tmp_path / "update" / NAME).exists()


def test_fallo_al_lanzar_el_instalador_mantiene_la_version(tmp_path, monkeypatch):
    def boom(cmd, **kw):
        raise OSError("acceso denegado")

    up = make_updater(tmp_path, monkeypatch, popen=boom)
    up.start()
    st = wait(up)
    assert (
        st["error"]["code"] == "err.main.updates.install_failed"
        and "acceso denegado" in st["error"]["params"]["reason"]
    )
    assert up.exits == []


def test_rechaza_sin_instalador_de_windows(tmp_path, monkeypatch):
    up = make_updater(tmp_path, monkeypatch, supported=False)
    with pytest.raises(selfupdate.UpdateError) as e:
        up.start()
    assert e.value.status == 409 and e.value.code == "err.main.updates.install_not_supported"


def test_rechaza_con_sync_en_curso(tmp_path, monkeypatch):
    up = make_updater(tmp_path, monkeypatch, busy=True)
    with pytest.raises(selfupdate.UpdateError) as e:
        up.start()
    assert e.value.status == 409 and e.value.code == "err.main.updates.sync_running"
    assert up.status()["state"] == "idle"


def test_rechaza_sin_version_nueva_ni_instalador_publicado(tmp_path, monkeypatch):
    up = make_updater(tmp_path, monkeypatch, rels=[release(assets=False)])
    with pytest.raises(selfupdate.UpdateError) as e:
        up.start()
    assert e.value.code == "err.main.updates.install_failed"
    up = make_updater(tmp_path, monkeypatch, rels=[release(tag="v0.4.2")])
    with pytest.raises(selfupdate.UpdateError):
        up.start()


def test_no_arranca_dos_a_la_vez(tmp_path, monkeypatch):
    gate = []
    up = make_updater(tmp_path, monkeypatch, popen=lambda cmd, **kw: gate.append(1))
    up.start()
    with pytest.raises(selfupdate.UpdateError) as e:
        up.start()
    assert e.value.status == 409
    wait(up)


def test_hay_sync_mira_scheduler_y_runs():
    reg = RunRegistry()

    class S:
        current = None

    assert selfupdate.sync_running(S(), reg) is False
    S.current = "juego"
    assert selfupdate.sync_running(S(), reg) is True
    S.current = None
    reg.create("g", False)
    assert selfupdate.sync_running(S(), reg) is True


# ---- endpoints ----
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(updates, "installed_version", lambda: "0.4.2")
    monkeypatch.setattr(updates, "fetch_releases", lambda repo: [release()])
    return TestClient(create_app(Auth("admin", PW, 1, rounds=4)))


def test_endpoints_requieren_sesion(api):
    assert api.post("/api/updates/install").status_code == 401
    assert api.get("/api/updates/install").status_code == 401


def test_estado_marca_instalable_solo_con_instalador_de_windows(api, monkeypatch):
    login(api)
    monkeypatch.setattr(selfupdate, "supported", lambda: False)
    st = api.get("/api/updates").json()
    assert st["instalable"] is False and st["instalador"] is False
    monkeypatch.setattr(selfupdate, "supported", lambda: True)
    s = api.get("/api/updates").json()
    assert s["instalable"] is True and s["hay_actualizacion"] is True
    monkeypatch.setattr(updates, "fetch_releases", lambda repo: [release(assets=False)])
    api.app.state.ctx.checker.clock = lambda: time.time() + 1000  # pasa el límite entre comprobaciones forzadas
    assert api.get("/api/updates?refresh=1").json()["instalable"] is False


def test_post_fuera_de_windows_es_409(api, monkeypatch):
    login(api)
    monkeypatch.setattr(selfupdate, "supported", lambda: False)
    r = api.post("/api/updates/install")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "err.main.updates.install_not_supported"


def test_post_arranca_y_get_informa(api, monkeypatch):
    login(api)
    monkeypatch.setattr(selfupdate, "supported", lambda: True)
    started = []
    monkeypatch.setattr(selfupdate.SelfUpdater, "_work", lambda self, inst: started.append(inst["name"]))
    r = api.post("/api/updates/install")
    assert r.status_code == 200 and r.json()["state"] == "downloading" and r.json()["version"] == VER
    for _ in range(100):
        if started:
            break
        time.sleep(0.01)
    assert started == [NAME]
    assert api.get("/api/updates/install").json()["state"] in ("downloading", "idle", "error", "restarting")


def test_instalar_es_solo_con_sesion_y_sin_parametros_del_cliente(api, monkeypatch):
    """El cliente no elige URL ni versión: el servidor usa solo lo que él mismo comprobó en GitHub."""
    login(api)
    monkeypatch.setattr(selfupdate, "supported", lambda: True)
    seen = []
    monkeypatch.setattr(selfupdate.SelfUpdater, "_work", lambda self, inst: seen.append(inst["url"]))
    api.post("/api/updates/install", json={"url": "https://evil.example/x.exe", "version": "9.9.9"})
    for _ in range(100):
        if seen:
            break
        time.sleep(0.01)
    assert seen == [BASE + NAME]
