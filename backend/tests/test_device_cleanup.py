"""Limpieza de METADATOS al borrar un dispositivo: baseline, staging y resoluciones de ese dispositivo.
Nunca versiones ni hub. Todo en tmp_path con datos sintéticos."""

import copy
import json
from datetime import datetime, timezone

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.core import settings
from app.main import create_app
from app.sync import locking, resolution
from app.sync.baseline import load_baseline, save_baseline
from app.sync.cleanup import purge_device_metadata

H = "a" * 64


def seed(data, game="g1", dev="old"):
    save_baseline(data, game, {dev: H, "keep": H, "hub": H})
    (data / "staging" / game / dev).mkdir(parents=True, exist_ok=True)
    (data / "staging" / game / dev / "f.sav").write_text("x", encoding="utf-8")
    (data / "staging" / game / "keep").mkdir(parents=True, exist_ok=True)
    (data / "staging" / game / "keep" / "f.sav").write_text("x", encoding="utf-8")
    now = datetime.now(timezone.utc)
    resolution.record_conflict(data, game, dev, "both-changed", H, H, now)
    resolution.record_conflict(data, game, "keep", "both-changed", H, H, now)
    (data / "hub" / game).mkdir(parents=True, exist_ok=True)
    (data / "hub" / game / "s.sav").write_text("hub", encoding="utf-8")
    (data / "versions" / game / "2026-01-01_000000" / dev).mkdir(parents=True, exist_ok=True)
    (data / "versions" / game / "2026-01-01_000000" / dev / "s.sav").write_text("v", encoding="utf-8")


def test_quita_solo_metadatos_del_dispositivo(tmp_path):
    seed(tmp_path)
    n = purge_device_metadata(tmp_path, ["old"])
    assert n == {"state": 1, "staging": 1, "resolutions": 1}
    assert load_baseline(tmp_path, "g1") == {"keep": H, "hub": H}
    assert not (tmp_path / "staging/g1/old").exists() and (tmp_path / "staging/g1/keep/f.sav").exists()
    r = resolution.load(tmp_path, "g1")
    assert list(r["conflicts"]) == ["keep"]
    # versiones y hub intactos
    assert (tmp_path / "versions/g1/2026-01-01_000000/old/s.sav").read_text(encoding="utf-8") == "v"
    assert (tmp_path / "hub/g1/s.sav").read_text(encoding="utf-8") == "hub"


def test_sin_datos_no_hace_nada(tmp_path):
    assert purge_device_metadata(tmp_path, ["old"]) == {"state": 0, "staging": 0, "resolutions": 0}
    assert purge_device_metadata(tmp_path, []) == {"state": 0, "staging": 0, "resolutions": 0}
    assert not (tmp_path / "locks").exists()  # no crea locks si no hay nada que limpiar


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "hub", "..", "a\\b"])
def test_ids_no_validos_se_ignoran(tmp_path, bad):
    seed(tmp_path)
    (tmp_path / "staging" / "x").mkdir()
    assert purge_device_metadata(tmp_path, [bad]) == {"state": 0, "staging": 0, "resolutions": 0}
    assert (tmp_path / "staging/x").exists() and (tmp_path / "staging/g1/old").exists()
    assert load_baseline(tmp_path, "g1")["hub"] == H


def test_juego_con_lock_ocupado_se_salta(tmp_path):
    seed(tmp_path)
    seed(tmp_path, "g2")
    h = locking.acquire(tmp_path / "locks" / "g1.lock")
    try:
        n = purge_device_metadata(tmp_path, ["old"])
    finally:
        h.release()
    assert n == {"state": 1, "staging": 1, "resolutions": 1}  # solo g2
    assert "old" in load_baseline(tmp_path, "g1") and "old" not in load_baseline(tmp_path, "g2")
    assert (tmp_path / "staging/g1/old").exists()


def test_baseline_ilegible_no_se_reescribe(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "g1.json").write_text("{no es json", encoding="utf-8")
    purge_device_metadata(tmp_path, ["old"])
    assert (tmp_path / "state" / "g1.json").read_text(encoding="utf-8") == "{no es json"


def test_staging_enlace_simbolico_no_se_sigue(tmp_path):
    outside = tmp_path / "fuera"
    outside.mkdir()
    (outside / "keep.txt").write_text("x", encoding="utf-8")
    (tmp_path / "staging" / "g1").mkdir(parents=True)
    (tmp_path / "staging" / "g1" / "old").symlink_to(outside, target_is_directory=True)
    purge_device_metadata(tmp_path, ["old"])
    assert (outside / "keep.txt").exists()


CFG = {
    "devices": {
        "old": {"name": "Viejo", "host": "192.0.2.10", "user": "u", "os": "linux"},
        "pc": {"name": "PC", "host": "192.0.2.11", "user": "u", "os": "linux"},
    },
    "games": {"g1": {"name": "Juego", "devices": ["pc"], "paths": {"pc": "/p"}}},
}


@pytest.fixture
def cl(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump(CFG), encoding="utf-8")
    c = TestClient(create_app(Auth("admin", "pw-test-1234", 1, rounds=4)))
    assert c.post("/api/login", json={"user": "admin", "password": "pw-test-1234"}).status_code == 200
    return c


def test_guardar_config_sin_el_dispositivo_limpia_metadatos_pero_no_versiones(cl, tmp_path):
    data = tmp_path / "data"
    seed(data)
    got = cl.get("/api/config").json()
    cfg = copy.deepcopy(got["config"])
    cfg["devices"].pop("old")
    r = cl.put("/api/config", json={"config": cfg, "base_version": got["version"]})
    assert r.status_code == 200, r.text
    assert "old" not in load_baseline(data, "g1")
    assert not (data / "staging/g1/old").exists()
    assert (data / "versions/g1/2026-01-01_000000/old/s.sav").exists()
    assert (data / "hub/g1/s.sav").exists()


def test_guardar_sin_borrar_dispositivos_no_toca_nada(cl, tmp_path):
    data = tmp_path / "data"
    seed(data)
    got = cl.get("/api/config").json()
    cfg = copy.deepcopy(got["config"])
    cfg["devices"]["pc"]["name"] = "PC renombrado"
    assert cl.put("/api/config", json={"config": cfg, "base_version": got["version"]}).status_code == 200
    assert "old" in load_baseline(data, "g1") and (data / "staging/g1/old").exists()


def test_restaurar_copia_sin_el_dispositivo_tambien_limpia(cl, tmp_path):
    data = tmp_path / "data"
    seed(data)
    got = cl.get("/api/config").json()
    cfg = copy.deepcopy(got["config"])
    cfg["devices"].pop("old")
    assert cl.put("/api/config", json={"config": cfg, "base_version": got["version"]}).status_code == 200
    seed(data)  # vuelve a haber metadatos de «old» (p. ej. staging tardío)
    got = cl.get("/api/config").json()
    back = cl.get("/api/config/backups").json()
    assert back
    # restaurar la copia anterior TRAE «old» de vuelta: no se limpia nada de lo que existe en la config
    r = cl.post("/api/config/restore", json={"base_version": got["version"], "name": back[0]["name"]})
    assert r.status_code == 200, r.text
    assert "old" in load_baseline(data, "g1")


def test_el_fichero_json_de_estado_conserva_formato(tmp_path):
    seed(tmp_path)
    purge_device_metadata(tmp_path, ["old"])
    raw = json.loads((tmp_path / "state" / "g1.json").read_text(encoding="utf-8"))
    assert set(raw) == {"base", "updated"}
