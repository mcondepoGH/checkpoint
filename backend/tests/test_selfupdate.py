"""Actualización con un clic (services/selfupdate.py + endpoints /api/updates/install). Sin red ni Windows: el abridor
HTTP, el lanzador del instalador y la salida del proceso se inyectan."""

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

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


@pytest.fixture(autouse=True)
def _plataforma_windows(monkeypatch):
    """Los tests de arriba son de Windows; los de Linux (al final) fijan su plataforma con `as_linux`."""
    monkeypatch.setattr(updates, "platform_name", lambda: "windows")
    monkeypatch.setattr(selfupdate, "platform_name", lambda: "windows")


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


def test_start_con_prerelease_rc_llega_a_downloading_y_lanza(tmp_path, monkeypatch):
    name = "Checkpoint-Setup-2.5.0-rc.2.exe"
    base = "https://github.com/o/r/releases/download/v2.5.0-rc.2/"
    assets = [
        {"name": name, "browser_download_url": base + name, "size": len(BODY)},
        {"name": name + ".sha256", "browser_download_url": base + name + ".sha256", "size": 90},
    ]
    rc = release(assets=False, tag="v2.5.0-rc.2", prerelease=True)
    rc["assets"] = assets
    files = {base + name: BODY, base + name + ".sha256": f"{HASH}  {name}\n".encode()}
    up = make_updater(tmp_path, monkeypatch, files=files, rels=[rc])
    monkeypatch.setattr(updates, "installed_version", lambda: "2.5.0-rc.1")
    up.start()
    st = wait(up)
    assert st["state"] == "restarting"
    assert st["version"] == "2.5.0-rc.2" and up.launched and up.launched[0][0].endswith(name)


# =====================================================================================================================
# Linux: instalación nativa (install.sh). El hub descarga el tarball, comprueba su SHA-256, lo extrae con seguridad y
# lanza `install.sh --upgrade` desacoplado; install.sh reemplaza los ficheros y reinicia la unidad de systemd.
# =====================================================================================================================
LNAME = f"checkpoint-{VER}-linux.tar.gz"
LBASE = BASE


def as_linux(monkeypatch):
    monkeypatch.setattr(updates, "platform_name", lambda: "linux")
    monkeypatch.setattr(selfupdate, "platform_name", lambda: "linux")


def make_tar(members=None, *, ver=VER, extra=None) -> bytes:
    """Tarball de mentira con la forma del real: checkpoint-<ver>/{install.sh,VERSION,backend/app/main.py}."""
    root = f"checkpoint-{ver}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:

        def add(name, data=b"", mode=0o644, type_=tarfile.REGTYPE, linkname=""):
            ti = tarfile.TarInfo(name)
            ti.type, ti.mode, ti.linkname = type_, mode, linkname
            ti.size = len(data) if type_ == tarfile.REGTYPE else 0
            tf.addfile(ti, io.BytesIO(data) if type_ == tarfile.REGTYPE else None)

        if members is None:
            add(root, type_=tarfile.DIRTYPE, mode=0o755)
            add(f"{root}/install.sh", b"#!/usr/bin/env bash\necho hola\n", 0o755)
            add(f"{root}/VERSION", ver.encode() + b"\n")
            add(f"{root}/backend/app/main.py", b"print(1)\n")
        for m in extra or []:
            add(**m)
    return buf.getvalue()


def lrelease(ver=VER):
    name = f"checkpoint-{ver}-linux.tar.gz"
    r = release(tag=f"v{ver}")
    r["assets"] = [
        {"name": name, "browser_download_url": LBASE + name},
        {"name": name + ".sha256", "browser_download_url": LBASE + name + ".sha256"},
    ]
    return r


def make_linux(tmp_path, monkeypatch, *, tar=None, supported=True, busy=False, popen=None, systemd_run=None, **kw):
    as_linux(monkeypatch)
    tar = tar if tar is not None else make_tar()
    h = hashlib.sha256(tar).hexdigest()
    files = {LBASE + LNAME: tar, LBASE + LNAME + ".sha256": f"{h}  {LNAME}\n".encode()}
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(updates, "installed_version", lambda: "0.4.2")
    monkeypatch.setattr(selfupdate, "supported", lambda: supported)
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: systemd_run if n == "systemd-run" else None)
    launched, exits = [], []

    def fake_popen(cmd, **kwargs):
        launched.append((cmd, kwargs))

    up = selfupdate.SelfUpdater(
        updates.UpdateChecker(fetch=lambda repo: [lrelease()]),
        busy=lambda: busy,
        opener=FakeOpener(files),
        popen=popen or fake_popen,
        exit_fn=lambda: exits.append(1),
        exit_delay=0,
        **kw,
    )
    up.launched, up.exits = launched, exits
    return up


# ---- supported() en Linux ----
@pytest.fixture
def native(tmp_path, monkeypatch):
    """Instalación nativa de mentira: <base>/<ver>/{.instalado,backend/app/services} y <base>/current -> <ver>."""
    as_linux(monkeypatch)
    root = tmp_path / "checkpoint-app" / "0.4.2"
    (root / "backend" / "app" / "services").mkdir(parents=True)
    (root / ".instalado").write_text("", encoding="utf-8")
    (root.parent / "current").symlink_to("0.4.2")
    monkeypatch.setattr(selfupdate, "app_root", lambda: root)
    monkeypatch.setattr(selfupdate.runtime, "running_in_docker", lambda: False)
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: "/usr/bin/" + n)
    monkeypatch.delenv("SYSTEMCTL", raising=False)
    return root


def test_supported_linux_con_instalacion_nativa(native):
    assert selfupdate.supported() is True


def test_supported_linux_sin_marcador_instalado(native):
    (native / ".instalado").unlink()
    assert selfupdate.supported() is False


def test_supported_linux_sin_enlace_current(native):
    (native.parent / "current").unlink()
    assert selfupdate.supported() is False


def test_supported_linux_current_apunta_a_otra_carpeta_que_la_que_corre(native):
    (native.parent / "0.9.9").mkdir()
    (native.parent / "current").unlink()
    (native.parent / "current").symlink_to("0.9.9")
    assert selfupdate.supported() is False


def test_supported_linux_en_docker_no(native, monkeypatch):
    monkeypatch.setattr(selfupdate.runtime, "running_in_docker", lambda: True)
    assert selfupdate.supported() is False


def test_supported_linux_sin_systemctl_no(native, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: None)
    assert selfupdate.supported() is False


def test_supported_linux_respeta_la_variable_systemctl(native, monkeypatch):
    seen = []
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: seen.append(n) or "/x")
    monkeypatch.setenv("SYSTEMCTL", "/opt/fake/systemctl")
    assert selfupdate.supported() is True and seen == ["/opt/fake/systemctl"]


def test_supported_repo_clonado_linux_no(monkeypatch):
    """Ejecución desde el repositorio (sin .instalado ni current): no soportado, texto manual."""
    as_linux(monkeypatch)
    monkeypatch.setattr(selfupdate.runtime, "running_in_docker", lambda: False)
    assert selfupdate.supported() is False


def test_supported_macos_no(native, monkeypatch):
    monkeypatch.setattr(selfupdate, "platform_name", lambda: "macos")
    assert selfupdate.supported() is False


# ---- flujo en Linux ----
def test_linux_camino_feliz_descarga_verifica_extrae_y_lanza_desacoplado(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_PASSWORD", "secreto")
    monkeypatch.setenv("CHECKPOINT_USER", "yo")
    up = make_linux(tmp_path, monkeypatch)
    up.start()
    st = wait(up)
    assert st["state"] == "restarting" and st["version"] == VER
    folder = tmp_path / "update" / VER / f"checkpoint-{VER}"
    assert (folder / "install.sh").is_file() and (folder / "backend" / "app" / "main.py").is_file()
    ((cmd, kw),) = up.launched
    assert cmd == ["bash", str(folder / "install.sh"), "--upgrade"]
    assert kw["cwd"] == str(folder)
    assert kw["start_new_session"] is True and kw["close_fds"] is True
    assert kw["stdin"] == subprocess.DEVNULL and kw["stderr"] == subprocess.STDOUT
    assert Path(kw["stdout"].name) == tmp_path / "update" / f"upgrade-{VER}.log"
    assert "CHECKPOINT_PASSWORD" not in kw["env"] and "CHECKPOINT_USER" not in kw["env"]
    assert "creationflags" not in kw
    assert up.exits == []  # en Linux no sale: install.sh reinicia la unidad


def test_linux_lleva_el_prefijo_de_la_instalacion_a_install_sh(tmp_path, monkeypatch, native):
    up = make_linux(tmp_path, monkeypatch)
    monkeypatch.setattr(selfupdate, "supported", lambda: True)
    up.start()
    wait(up)
    assert up.launched[0][1]["env"]["CHECKPOINT_INSTALL_PREFIX"] == str(native.parent)


def test_linux_con_systemd_run_lo_lanza_fuera_del_cgroup_del_servicio(tmp_path, monkeypatch, native):
    """Sin esto `systemctl restart` mataría a install.sh (mismo cgroup que el hub) antes de terminar."""
    up = make_linux(tmp_path, monkeypatch, systemd_run="/usr/bin/systemd-run")
    monkeypatch.setattr(selfupdate, "supported", lambda: True)
    up.start()
    wait(up)
    cmd, kw = up.launched[0]
    folder = tmp_path / "update" / VER / f"checkpoint-{VER}"
    assert cmd[:4] == ["/usr/bin/systemd-run", "--user", "--quiet", "--collect"]
    assert f"--working-directory={folder}" in cmd
    assert cmd[-4:] == ["--", "bash", str(folder / "install.sh"), "--upgrade"]
    assert f"--setenv=CHECKPOINT_INSTALL_PREFIX={native.parent}" in cmd
    assert any(c.startswith("--property=StandardOutput=append:") for c in cmd)
    assert not any("PASSWORD" in c for c in cmd)


def test_linux_hash_distinto_no_extrae_ni_lanza(tmp_path, monkeypatch):
    up = make_linux(tmp_path, monkeypatch)
    up._opener.files[LBASE + LNAME + ".sha256"] = (("0" * 64) + f"  {LNAME}\n").encode()
    up.start()
    st = wait(up)
    assert st["error"]["code"] == "err.main.updates.hash_mismatch"
    assert up.launched == [] and not (tmp_path / "update" / VER).exists()
    assert not (tmp_path / "update" / LNAME).exists()


def test_linux_hash_correcto_con_el_nombre_de_otro_fichero_es_error(tmp_path, monkeypatch):
    up = make_linux(tmp_path, monkeypatch)
    h = hashlib.sha256(make_tar()).hexdigest()
    up._opener.files[LBASE + LNAME + ".sha256"] = f"{h}  otro.tar.gz\n".encode()
    up.start()
    assert wait(up)["error"]["code"] == "err.main.updates.hash_mismatch"


def test_linux_tarball_demasiado_grande_se_corta(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate, "MAX_INSTALLER_BYTES", 100)
    up = make_linux(tmp_path, monkeypatch)
    up.start()
    st = wait(up)
    assert st["error"]["code"] == "err.main.updates.download_failed" and up.launched == []


def test_linux_con_sync_en_curso_no_arranca(tmp_path, monkeypatch):
    up = make_linux(tmp_path, monkeypatch, busy=True)
    with pytest.raises(selfupdate.UpdateError) as e:
        up.start()
    assert e.value.code == "err.main.updates.sync_running" and up.launched == []


@pytest.mark.parametrize("kind", ["linux", "macos"])
def test_start_en_entorno_no_soportado_es_install_not_supported(tmp_path, monkeypatch, kind):
    up = make_linux(tmp_path, monkeypatch, supported=False)
    monkeypatch.setattr(selfupdate, "platform_name", lambda: kind)
    with pytest.raises(selfupdate.UpdateError) as e:
        up.start()
    assert e.value.status == 409 and e.value.code == "err.main.updates.install_not_supported"


def test_linux_fallo_al_lanzar_install_sh_es_install_failed_y_no_sale(tmp_path, monkeypatch):
    def boom(cmd, **kw):
        raise OSError("sin bash")

    up = make_linux(tmp_path, monkeypatch, popen=boom)
    up.start()
    st = wait(up)
    assert st["error"]["code"] == "err.main.updates.install_failed" and up.exits == []


def test_linux_si_install_sh_no_reinicia_el_hub_a_tiempo_se_marca_el_error(tmp_path, monkeypatch):
    up = make_linux(tmp_path, monkeypatch, restart_wait=0.05)
    up.start()
    wait(up, states=("restarting",))
    st = wait(up, states=("error",))
    assert st["error"]["code"] == "err.main.updates.install_failed" and "upgrade-" in st["error"]["params"]["reason"]
    assert up.exits == []


def test_linux_tarball_sin_install_sh_es_error(tmp_path, monkeypatch):
    root = f"checkpoint-{VER}"
    tar = make_tar([], extra=[dict(name=f"{root}/VERSION", data=b"1")])
    up = make_linux(tmp_path, monkeypatch, tar=tar)
    up.start()
    st = wait(up)
    assert st["error"]["code"] == "err.main.updates.install_failed" and up.launched == []


def test_api_linux_nativo_marca_instalable_con_el_asset_de_linux(api, monkeypatch):
    as_linux(monkeypatch)
    monkeypatch.setattr(updates, "fetch_releases", lambda repo: [lrelease()])
    login(api)
    monkeypatch.setattr(selfupdate, "supported", lambda: True)
    s = api.get("/api/updates").json()
    assert s["instalable"] is True and s["instalador"] is True
    monkeypatch.setattr(selfupdate, "supported", lambda: False)  # Docker o repo clonado: texto manual
    s = api.get("/api/updates").json()
    assert s["instalable"] is False and s["instalador"] is False
    r = api.post("/api/updates/install")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "err.main.updates.install_not_supported"


# ---- extracción segura ----
def _evil(**m):
    root = f"checkpoint-{VER}"
    base = [
        dict(name=root, type_=tarfile.DIRTYPE, mode=0o755),
        dict(name=f"{root}/install.sh", data=b"#!/bin/sh\n", mode=0o755),
    ]
    return make_tar([], extra=base + [m])


EVIL = {
    "traversal": dict(name=f"checkpoint-{VER}/../../evil.txt", data=b"x"),
    "traversal_inicial": dict(name="../evil.txt", data=b"x"),
    "absoluta": dict(name="/tmp/evil.txt", data=b"x"),
    "otra_raiz": dict(name="otra/evil.txt", data=b"x"),
    "symlink_fuera": dict(name=f"checkpoint-{VER}/link", type_=tarfile.SYMTYPE, linkname="/etc"),
    "symlink_relativo_fuera": dict(name=f"checkpoint-{VER}/link", type_=tarfile.SYMTYPE, linkname="../../x"),
    "symlink_dentro": dict(name=f"checkpoint-{VER}/link", type_=tarfile.SYMTYPE, linkname="install.sh"),
    "hardlink": dict(name=f"checkpoint-{VER}/hl", type_=tarfile.LNKTYPE, linkname=f"checkpoint-{VER}/install.sh"),
    "fifo": dict(name=f"checkpoint-{VER}/fifo", type_=tarfile.FIFOTYPE),
    "dispositivo": dict(name=f"checkpoint-{VER}/dev", type_=tarfile.CHRTYPE),
}


@pytest.mark.parametrize("case", sorted(EVIL))
def test_extraccion_rechaza_miembros_peligrosos(tmp_path, case):
    tgz = tmp_path / "p.tar.gz"
    tgz.write_bytes(_evil(**EVIL[case]))
    dest = tmp_path / "out"
    with pytest.raises(ValueError):
        selfupdate.extract_package(tgz, dest, VER)
    assert not (tmp_path / "evil.txt").exists() and not Path("/tmp/evil.txt").exists()
    assert not dest.exists() or not any(dest.iterdir())  # no se deja nada a medias


def test_extraccion_rechaza_tamano_total_excesivo(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate, "MAX_EXTRACT_BYTES", 10)
    tgz = tmp_path / "p.tar.gz"
    tgz.write_bytes(make_tar())
    with pytest.raises(ValueError, match="tamaño"):
        selfupdate.extract_package(tgz, tmp_path / "out", VER)


def test_extraccion_rechaza_demasiados_miembros(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate, "MAX_EXTRACT_MEMBERS", 2)
    tgz = tmp_path / "p.tar.gz"
    tgz.write_bytes(make_tar())
    with pytest.raises(ValueError, match="miembros"):
        selfupdate.extract_package(tgz, tmp_path / "out", VER)


def test_extraccion_valida_deja_install_sh_ejecutable_y_devuelve_la_carpeta(tmp_path):
    tgz = tmp_path / "p.tar.gz"
    tgz.write_bytes(make_tar())
    folder = selfupdate.extract_package(tgz, tmp_path / "out", VER)
    assert folder == tmp_path / "out" / f"checkpoint-{VER}"
    assert os.access(folder / "install.sh", os.X_OK)


def test_extraccion_no_es_un_tar(tmp_path):
    tgz = tmp_path / "p.tar.gz"
    tgz.write_bytes(b"esto no es un tar")
    with pytest.raises(ValueError):
        selfupdate.extract_package(tgz, tmp_path / "out", VER)


def test_extraccion_borra_restos_de_un_intento_anterior(tmp_path):
    tgz = tmp_path / "p.tar.gz"
    tgz.write_bytes(make_tar())
    dest = tmp_path / "out"
    (dest / "viejo").mkdir(parents=True)
    selfupdate.extract_package(tgz, dest, VER)
    assert not (dest / "viejo").exists()


# ---- extremo a extremo (sin systemd real): build.sh -> actualizador -> install.sh --upgrade --dry-run ----
REPO = Path(__file__).resolve().parents[2]


@pytest.mark.slow
@pytest.mark.skipif(
    shutil.which("bash") is None or not (REPO / "packaging" / "linux" / "build.sh").exists(),
    reason="sin bash o sin packaging/",
)
def test_e2e_tarball_real_de_build_sh_se_extrae_y_install_sh_upgrade_dry_run_lo_entiende(tmp_path, monkeypatch):
    fe = tmp_path / "fe"
    fe.mkdir()
    (fe / "index.html").write_text("<html></html>", encoding="utf-8")
    out = tmp_path / "dist"
    ver = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    subprocess.run(
        ["bash", str(REPO / "packaging/linux/build.sh"), "--no-deck", "--frontend-dir", str(fe), "--out-dir", str(out)],
        check=True,
        capture_output=True,
    )
    name = f"checkpoint-{ver}-linux.tar.gz"
    tar = (out / name).read_bytes()
    assert (out / (name + ".sha256")).read_text(encoding="utf-8").split()[0] == hashlib.sha256(tar).hexdigest()

    # «Instalación» previa: <base>/<ver-vieja>/.instalado + current, y un systemctl falso que registra lo que le piden.
    home = tmp_path / "home"
    base = home / ".local/share/checkpoint-app"
    (base / "0.0.1").mkdir(parents=True)
    (base / "0.0.1/.instalado").write_text("", encoding="utf-8")
    (base / "current").symlink_to("0.0.1")
    (home / ".config/checkpoint").mkdir(parents=True)
    (home / ".config/checkpoint/checkpoint.env").write_text('CHECKPOINT_HOST="127.0.0.1"\n', encoding="utf-8")
    fake = tmp_path / "systemctl"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/systemctl.log"\nexit 0\n', encoding="utf-8")
    fake.chmod(0o755)

    as_linux(monkeypatch)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(updates, "installed_version", lambda: "0.0.1")
    monkeypatch.setattr(selfupdate, "supported", lambda: True)
    monkeypatch.setattr(selfupdate, "app_root", lambda: base / "0.0.1")
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: None)  # sin systemd-run: lanzamiento directo
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SYSTEMCTL", str(fake))
    monkeypatch.setenv("CHECKPOINT_MIN_PYTHON", "3.9")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    procs = []

    def run_dry(cmd, **kw):  # el mismo comando que el real, pero sin tocar nada (--dry-run) y esperando a que acabe
        p = subprocess.Popen([*cmd, "--dry-run"], **kw)
        p.wait(timeout=60)
        procs.append(p)

    r = lrelease(ver)
    base_url = f"https://github.com/o/r/releases/download/v{ver}/"
    r["assets"] = [
        {"name": name, "browser_download_url": base_url + name},
        {"name": name + ".sha256", "browser_download_url": base_url + name + ".sha256"},
    ]
    files = {base_url + name: tar, base_url + name + ".sha256": (out / (name + ".sha256")).read_bytes()}
    up = selfupdate.SelfUpdater(
        updates.UpdateChecker(fetch=lambda repo: [r]),
        busy=lambda: False,
        opener=FakeOpener(files),
        popen=run_dry,
        exit_fn=lambda: None,
        exit_delay=0,
    )
    up.start()
    assert wait(up, timeout=60)["state"] == "restarting"
    assert procs and procs[0].returncode == 0
    log = (tmp_path / "data" / "update" / f"upgrade-{ver}.log").read_text(encoding="utf-8")
    assert "[dry-run]" in log and f"Instalaría Checkpoint {ver}" in log and "restart checkpoint" in log
    assert not (tmp_path / "systemctl.log").exists() or "restart" not in (tmp_path / "systemctl.log").read_text(
        encoding="utf-8"
    )
    assert (base / "0.0.1").exists() and not (base / ver).exists()  # dry-run: nada instalado


def test_espera_reinicio_segun_plataforma(api, monkeypatch):
    login(api)
    assert selfupdate.RESTART_WAIT_WINDOWS == 120 and selfupdate.RESTART_WAIT_LINUX == 300
    monkeypatch.setattr(selfupdate, "platform_name", lambda: "windows")
    assert api.get("/api/updates").json()["espera_reinicio"] == 120
    monkeypatch.setattr(selfupdate, "platform_name", lambda: "linux")
    assert api.get("/api/updates").json()["espera_reinicio"] == 300
