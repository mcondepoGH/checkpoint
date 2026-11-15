"""Versiones cuyo origen ya no es un dispositivo de la config (borrado o con nombre antiguo): se listan como
«desconocido» y se pueden restaurar al hub. Todo en tmp_path con datos sintéticos."""

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.config.models import parse_config
from app.core import settings
from app.main import create_app
from app.sync.engine import SyncAbort, list_versions, restore_version

CFG = parse_config(
    {
        "devices": {"pc": {"name": "PC", "host": "h1", "user": "u", "os": "linux"}},
        "games": {"g": {"name": "Juego", "devices": ["pc"], "paths": {"pc": "/p"}}},
    }
)
V = "2026-01-01_100000"


def mk(data, source, content="x", game="g", ver=V):
    d = data / "versions" / game / ver / source
    d.mkdir(parents=True)
    (d / "s.sav").write_text(content)


def test_list_marca_origen_desconocido(tmp_path):
    for s in ("pc", "hub", "gone-device", "SteamDeck"):
        mk(tmp_path, s)
    srcs = {s["source"]: s for s in list_versions(tmp_path, "g", {"pc": "PC"})[0]["sources"]}
    assert not srcs["pc"].get("unknown") and not srcs["hub"].get("unknown")
    assert srcs["gone-device"]["unknown"] is True and srcs["gone-device"]["name"] == "gone-device"
    assert srcs["SteamDeck"]["unknown"] is True


def test_list_sin_nombres_no_marca_desconocidos(tmp_path):
    mk(tmp_path, "gone")
    assert "unknown" not in list_versions(tmp_path, "g")[0]["sources"][0]


def test_restaurar_desde_origen_desconocido_copia_al_hub(tmp_path):
    mk(tmp_path, "gone-device", "viejo")
    (tmp_path / "hub" / "g").mkdir(parents=True)
    (tmp_path / "hub" / "g" / "s.sav").write_text("actual")
    msg = restore_version(CFG, "g", V, "gone-device", tmp_path)
    assert msg["code"] == "err.sync.restored" and msg["params"]["source"] == "gone-device"
    assert (tmp_path / "hub" / "g" / "s.sav").read_text() == "viejo"
    # el hub actual se guardó antes como versión nueva
    names = [v["version"] for v in list_versions(tmp_path, "g")]
    assert len(names) == 2
    # y el origen sigue ahí: restaurar no borra la versión
    assert (tmp_path / "versions" / "g" / V / "gone-device" / "s.sav").exists()


def test_restaurar_origen_con_espacios_de_nombre_antiguo(tmp_path):
    mk(tmp_path, "Steam Deck", "deck")
    restore_version(CFG, "g", V, "Steam Deck", tmp_path)
    assert (tmp_path / "hub" / "g" / "s.sav").read_text() == "deck"


@pytest.mark.parametrize("src", ["../x", "a/b", "a\\b", "..", ".", "", "x\x00y"])
def test_origen_inseguro_sigue_siendo_invalido(tmp_path, src):
    mk(tmp_path, "gone")
    with pytest.raises(SyncAbort) as e:
        restore_version(CFG, "g", V, src, tmp_path)
    assert e.value.code == "err.sync.version_invalid"
    assert not (tmp_path / "hub" / "g").exists()


def test_origen_inexistente_es_version_unknown(tmp_path):
    mk(tmp_path, "gone")
    with pytest.raises(SyncAbort) as e:
        restore_version(CFG, "g", V, "otro", tmp_path)
    assert e.value.code == "err.sync.version_unknown"


def test_origen_enlace_simbolico_no_se_restaura(tmp_path):
    out = tmp_path / "fuera"
    out.mkdir()
    (out / "s.sav").write_text("secreto")
    (tmp_path / "versions" / "g" / V).mkdir(parents=True)
    (tmp_path / "versions" / "g" / V / "lnk").symlink_to(out, target_is_directory=True)
    with pytest.raises(SyncAbort) as e:
        restore_version(CFG, "g", V, "lnk", tmp_path)
    assert e.value.code == "err.sync.version_unknown"
    assert not (tmp_path / "hub" / "g").exists()


def test_endpoint_restaura_desconocido_y_lista_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "devices": {"pc": {"name": "PC", "host": "h1", "user": "u", "os": "linux"}},
                "games": {"g": {"name": "Juego", "devices": ["pc"], "paths": {"pc": "/p"}}},
            }
        )
    )
    mk(tmp_path / "data", "gone-device", "viejo")
    c = TestClient(create_app(Auth("admin", "pw-test-1234", 1, rounds=4)))
    assert c.post("/api/login", json={"user": "admin", "password": "pw-test-1234"}).status_code == 200
    s = c.get("/api/versions/g").json()[0]["sources"][0]
    assert s["unknown"] is True and s["source"] == "gone-device"
    r = c.post("/api/versions/g/restore", json={"version": V, "source": "gone-device"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert (tmp_path / "data" / "hub" / "g" / "s.sav").read_text() == "viejo"
