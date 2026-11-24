"""Integración de punta a punta contra el hub REAL del repositorio (uvicorn en un hilo, sockets de verdad).

Se omite sola si no están las dependencias del backend. Ejemplo con el entorno del hub (sirve Python 3.11 o superior):
    PYTHONPATH=checkpoint-client/src <venv-del-hub>/bin/python -m pytest -m integration checkpoint-client/tests
Flujo: `checkpoint-client link` (el usuario acepta en el hub con sesión) -> `games` (con `path` y `process`) -> `sync` (subir,
bajar, conflicto y resolución) -> `run`."""

import copy
import os
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
    from app.core import settings as hub_settings
    from app.main import create_app
    from app.sync import fingerprint as hub_fp
    from test_hook_fingerprint import PW, Env
except Exception as e:  # pragma: no cover - depende del entorno
    pytest.skip(f"hub real no disponible: {e!r}", allow_module_level=True)

from checkpoint_client import cli, hub, settings, texts  # noqa: E402
from checkpoint_client import manifest as lm  # noqa: E402

pytestmark = pytest.mark.integration

CFG = {"devices": {"pc": {"name": "PC", "host": "192.0.2.10", "user": "u", "os": "linux"}}, "games": {}}
GAME = "g1"


@pytest.fixture
def real_hub(tmp_path, monkeypatch):
    monkeypatch.setattr(hub_settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(hub_settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(hub_settings, "STATIC_DIR", tmp_path / "static")
    Env(tmp_path, copy.deepcopy(CFG))
    app = create_app(Auth("admin", PW, 1, rounds=4))
    s = socket.socket()
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


@pytest.fixture
def world(real_hub, tmp_path, home, monkeypatch, capsys):
    monkeypatch.setattr(hub, "POLL_S", 0.05)

    class World:
        url = real_hub
        hubdir = tmp_path / "data" / "hub" / GAME
        save = home / "Games" / "g1"

        def __init__(self):
            self.admin = httpx.Client(base_url=real_hub)
            assert self.admin.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200

        def run(self, *argv):
            code = cli.main(list(argv))
            cap = capsys.readouterr()
            return code, cap.out, cap.err

        def link(self):
            """`checkpoint-client link` en un hilo; el usuario acepta la solicitud pendiente en el hub."""
            out = {}
            t = threading.Thread(target=lambda: out.update(r=cli.main(["link", real_hub, "--name", "Mi PC"])))
            t.start()
            for _ in range(200):
                pend = self.admin.get("/api/pairing/pending").json()
                if pend:
                    break
                time.sleep(0.05)
            assert pend and pend[0]["name"] == "Mi PC"
            r = self.admin.post(
                f"/api/pairing/pending/{pend[0]['id']}/accept",
                json={"code": pend[0]["code"]},
                headers={"Origin": real_hub},
            )
            assert r.status_code == 200, r.text
            t.join(15)
            assert out["r"] == 0
            return pend[0]["code"], r.json()["device"]

        def set_game(self, device, process="mijuego"):
            snap = self.admin.get("/api/config").json()
            cfg = snap["config"]
            cfg.setdefault("games", {})[GAME] = {
                "name": "Mi Juego",
                "devices": [device],
                "enabled": True,
                "paths": {device: str(self.save)},
                "process": process,
            }
            r = self.admin.put("/api/config", json={"base_version": snap["version"], "config": cfg})
            assert r.status_code == 200, r.text

    return World()


def put(root: Path, rel: str, data: bytes, mtime: int = 1_700_000_000):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    os.utime(p, (mtime, mtime))


def tree(root: Path):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_link_games_sync_and_conflict_against_real_hub(world, capsys):
    code, device = world.link()
    out = capsys.readouterr().out
    assert texts.LINK_CODE.format(code=texts.spaced_code(code)) in out
    assert texts.LINK_DONE.format(device=device, where="fichero") in out
    key = settings.load_settings(settings.config_dir())["key"]
    assert key.startswith("ckd_") and key not in out
    code_, out, err = world.run("status")
    assert code_ == 0, err
    assert f"{texts.STATUS_KEYS['protocol']}: 1" in out and device in out
    world.set_game(device)
    code_, out, _ = world.run("games")
    assert out.splitlines() == [f"{GAME}\tMi Juego\t{world.save}\t-"]
    # El hub devuelve `path` y `process` con la key de dispositivo (lo que el cliente necesita)
    from checkpoint_client.hubclient import HubClient

    (g,) = HubClient(world.url, key).get_games()
    assert g["path"] == str(world.save) and g["process"] == "mijuego"
    # subir
    put(world.save, "slot1/save.dat", b"datos")
    put(world.save, "it's & a: ñ.sav", b"x")
    code_, out, err = world.run("sync", GAME)
    assert code_ == 0, err
    assert texts.SYNC_UPLOADED.format(game="Mi Juego", n=2) in out
    assert tree(world.hubdir) == tree(world.save)
    assert world.run("sync", GAME)[1].strip() == texts.SYNC_UP_TO_DATE.format(game="Mi Juego")
    assert world.run("games", "--check")[1].strip() == texts.SYNC_UP_TO_DATE.format(game="Mi Juego")
    # bajar: el hub cambia
    put(world.hubdir, "slot1/save.dat", b"nuevo en el hub", 1_700_000_100)
    put(world.hubdir, "it's & a: ñ.sav", b"x", 1_700_000_000)
    assert world.run("sync", GAME, "--dry-run")[1].strip() == texts.CHECK_DOWNLOAD.format(game="Mi Juego")
    code_, out, err = world.run("sync", GAME)
    assert code_ == 0, err
    assert tree(world.save) == tree(world.hubdir)
    assert tree(Path(str(world.save) + ".checkpoint-backup"))["slot1/save.dat"] == b"datos"
    # conflicto: cambian los dos lados
    put(world.hubdir, "slot1/save.dat", b"hub otra vez", 1_700_000_200)
    put(world.save, "slot1/save.dat", b"local otra vez", 1_700_000_300)
    before = (tree(world.save), tree(world.hubdir))
    code_, out, err = world.run("sync", GAME)
    assert code_ == 3 and texts.SYNC_CONFLICT.format(game="Mi Juego") in err
    assert (tree(world.save), tree(world.hubdir)) == before
    # resolver a favor de este equipo
    code_, out, err = world.run("sync", GAME, "--resolve", "device")
    assert code_ == 0, err
    assert tree(world.hubdir)["slot1/save.dat"] == b"local otra vez"


def test_run_against_real_hub(world, capsys):
    import sys as _sys

    _, device = world.link()
    world.set_game(device)
    put(world.hubdir, "slot.sav", b"nivel1", 1_700_000_000)
    script = (
        f"import pathlib;s=pathlib.Path({str(world.save)!r});assert (s/'slot.sav').read_bytes()==b'nivel1';"
        "(s/'slot.sav').write_bytes(b'nivel2')"
    )
    code, out, err = world.run("run", GAME, "--", _sys.executable, "-c", script)
    assert code == 0, err
    assert tree(world.hubdir)["slot.sav"] == b"nivel2"
    assert texts.SYNC_DOWNLOADED.format(game="Mi Juego", n=1, path=world.save) in out
    assert texts.SYNC_UPLOADED.format(game="Mi Juego", n=1) in out


def test_wrong_key_is_rejected_by_real_hub(world):
    world.link()
    s = settings.load_settings(settings.config_dir())
    settings.save_settings(settings.config_dir(), {**s, "key": "ckd_" + "x" * 40})
    code, _, err = world.run("games")
    assert code == 1 and texts.ERR_UNAUTHORIZED in err


# ---- equivalencia del manifiesto con el `fingerprint` del hub real
def _fixtures(base: Path):
    d1 = base / "simple"
    put(d1, "a/b.sav", b"hola", 1234)
    put(d1, "c.sav", b"")
    d2 = base / "enlaces"
    put(d2, "real.sav", b"real")
    (d2 / "enlace.sav").symlink_to(d2 / "real.sav")
    os.mkfifo(d2 / "tuberia")
    (d2 / "vacia").mkdir()
    d3 = base / "orden"
    for rel in ["a.txt", "a/b", "a-b", "a b", "a+b/c", "A/B", "a/b.c", "a/c/d", "a0"]:
        put(d3, rel, rel.encode())
    d4 = base / "grande"
    put(d4, "big.bin", os.urandom(2_500_000))
    return [d1, d2, d3, d4]


def test_manifest_equivalence_with_hub_fingerprint(tmp_path):
    for d in _fixtures(tmp_path):
        mine = hub_fp.fingerprint_from_manifest(lm.build_manifest(d))
        assert mine == hub_fp.fingerprint(d), d.name
        assert hub_fp.dir_manifest(d) == lm.build_manifest(d), d.name
