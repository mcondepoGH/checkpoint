"""Integración de punta a punta contra el hub REAL del repositorio (uvicorn en un hilo, sockets de verdad).

Se omite sola si no están las dependencias del backend. Para ejecutarla con el entorno del hub:
    <venv-del-hub>/bin/python -m pytest -m integration checkpoint-deck/tests
Flujo: el plugin pide vinculación -> el usuario (con sesión) acepta en el hub -> el plugin recoge la clave ->
`ping` con esa clave devuelve el dispositivo."""

import asyncio
import copy
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path[:0] = [str(BACKEND), str(BACKEND / "tests")]

try:
    import httpx
    import uvicorn

    from app.api.auth import Auth
    from app.core import settings
    from app.main import create_app
    from test_hook_fingerprint import PW, Env
except Exception as e:  # pragma: no cover - depende del entorno
    pytest.skip(f"hub real no disponible: {e!r}", allow_module_level=True)

from checkpoint_hub import Pairing, check_connection  # noqa: E402

pytestmark = pytest.mark.integration

CFG = {
    "devices": {"pc": {"name": "PC", "host": "192.0.2.10", "user": "u", "os": "linux"}},
    "games": {},
}


@pytest.fixture
def real_hub(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    Env(tmp_path, copy.deepcopy(CFG))
    app = create_app(Auth("admin", PW, 1, rounds=4))
    s = socket.socket()  # el socket se entrega ya enlazado a uvicorn: sin la carrera de cerrar el puerto y reabrirlo
    s.bind(("127.0.0.1", 0))
    s.listen(128)
    port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=lambda: server.run(sockets=[s]), daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)
    s.close()


def test_pair_accept_collect_key_ping(real_hub, tmp_path, monkeypatch):
    import checkpoint_hub

    monkeypatch.setattr(checkpoint_hub, "POLL_S", 0.05)
    sdir = str(tmp_path / "deck-settings")
    admin = httpx.Client(base_url=real_hub)
    assert admin.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200

    async def go():
        p = Pairing(sdir)
        p.set_hub_url(real_hub + "/")
        p.start()
        for _ in range(100):  # espera a que salga el código
            await asyncio.sleep(0.05)
            if p.state().get("code"):
                break
        st = p.state()
        assert st["status"] == "waiting" and len(st["code"]) == 6
        pend = admin.get("/api/pairing/pending").json()
        assert [x["code"] for x in pend] == [st["code"]] and pend[0]["name"] == "Steam Deck"
        r = admin.post(
            f"/api/pairing/pending/{pend[0]['id']}/accept",
            json={"code": st["code"]},
            headers={"Origin": real_hub},
        )
        assert r.status_code == 200, r.text
        await asyncio.wait_for(p._task, 10)  # noqa: SLF001
        return p

    p = asyncio.run(go())
    st = p.state()
    assert st["status"] == "linked" and st["device"].startswith("steam-deck-")
    key = p.key()
    assert key.startswith("ckd_")
    res, data = check_connection(real_hub, key)
    assert res == "ok" and data["device"] == st["device"]
    assert check_connection(real_hub, "ckd_mala")[0] == "unauthorized"
    # Compatibilidad por protocolo contra el hub REAL (backend/app/core/protocol.py)
    res, data = check_connection(real_hub, key, plugin_protocol=1)
    assert res == "ok" and data["compat"] == "ok" and data["protocol"] == 1 and data["min_plugin_protocol"] == 1
    assert check_connection(real_hub, key, plugin_protocol=0)[1]["compat"] == "plugin_outdated"  # 0 < min 1


def test_rejected_by_user(real_hub, tmp_path, monkeypatch):
    import checkpoint_hub

    monkeypatch.setattr(checkpoint_hub, "POLL_S", 0.05)
    admin = httpx.Client(base_url=real_hub)
    admin.post("/api/login", json={"user": "admin", "password": PW})

    async def go():
        p = Pairing(str(tmp_path / "s"))
        p.set_hub_url(real_hub)
        p.start()
        for _ in range(100):
            await asyncio.sleep(0.05)
            if p.state().get("code"):
                break
        rid = admin.get("/api/pairing/pending").json()[0]["id"]
        assert admin.post(f"/api/pairing/pending/{rid}/reject", headers={"Origin": real_hub}).status_code == 200
        await asyncio.wait_for(p._task, 10)  # noqa: SLF001
        return p.state()

    assert asyncio.run(go())["status"] == "rejected"


def test_update_check_against_real_hub(real_hub, tmp_path, monkeypatch):
    """info pública del hub real -> aviso de versión nueva (solo lectura: nada se descarga ni se instala)."""
    import checkpoint_update as upd
    from test_update import make_zip

    zp = tmp_path / "deck" / "Checkpoint.zip"
    zp.parent.mkdir()
    zp.write_bytes(make_zip("0.2.0", 1))
    monkeypatch.setattr(settings, "DECK_ZIP", zp)
    info = upd.fetch_info(real_hub)
    assert info["version"] == "0.2.0" and info["protocol"] == 1 and len(info["sha256"]) == 64
    ev = upd.evaluate(info, "0.1.0", 1, 1)
    assert ev["state"] == "available" and ev["reason"] is None and "can_install" not in ev
    assert upd.evaluate(info, "0.2.0", 1, 1)["state"] == "up_to_date"
