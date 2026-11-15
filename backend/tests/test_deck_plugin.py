"""Descarga del zip del plugin de Steam Deck: `GET /api/deck/plugin` (zip), `.sha256` (texto para `sha256sum -c`) e
`info` (JSON). Públicos y de solo lectura; la ruta del zip es fija (`settings.DECK_ZIP`), nunca viene de la petición."""

import hashlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.core import settings
from app.main import create_app
from app.services import deckplugin


def make_zip(path, version="1.2.3", with_package=True, protocol=1):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Checkpoint/main.py", "print('x')\n")
        if with_package:
            z.writestr(
                "Checkpoint/package.json",
                json.dumps({"name": "checkpoint-deck", "version": version, "checkpointProtocol": protocol}),
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
    return buf.getvalue()


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(settings, "DECK_ZIP", tmp_path / "deck" / "Checkpoint.zip")
    app = create_app(Auth("admin", "x" * 12, 1, rounds=4))
    c = TestClient(app)  # sin sesión: los endpoints son públicos
    c.zip = tmp_path / "deck" / "Checkpoint.zip"
    return c


def test_zip_download_matches_sha_and_headers(hub):
    data = make_zip(hub.zip)
    sha = hashlib.sha256(data).hexdigest()
    r = hub.get("/api/deck/plugin")
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["x-checkpoint-plugin-sha256"] == sha
    assert r.headers["x-checkpoint-plugin-version"] == "1.2.3"
    assert 'filename="Checkpoint.zip"' in r.headers["content-disposition"]


def test_info_json(hub):
    data = make_zip(hub.zip)
    r = hub.get("/api/deck/plugin/info")
    assert r.status_code == 200
    assert r.json() == {
        "available": True,
        "version": "1.2.3",
        "protocol": 1,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "filename": "Checkpoint.zip",
    }


def test_sha256_text_works_with_sha256sum(hub):
    data = make_zip(hub.zip)
    r = hub.get("/api/deck/plugin.sha256")
    assert r.status_code == 200
    assert r.text == f"{hashlib.sha256(data).hexdigest()}  Checkpoint.zip\n"
    assert r.headers["content-type"].startswith("text/plain")


def test_missing_zip_is_404_with_code_and_info_not_available(hub):
    for url in ("/api/deck/plugin", "/api/deck/plugin.sha256"):
        r = hub.get(url)
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "err.deck.plugin_missing"
    r = hub.get("/api/deck/plugin/info")
    assert r.status_code == 200 and r.json() == {"available": False}


def test_version_null_when_package_json_missing_or_broken(hub):
    make_zip(hub.zip, with_package=False)
    assert hub.get("/api/deck/plugin/info").json()["version"] is None
    hub.zip.write_bytes(b"no soy un zip")
    r = hub.get("/api/deck/plugin/info").json()
    assert r["available"] is True and r["version"] is None


def test_replaced_zip_is_seen_again(hub):
    make_zip(hub.zip, "1.0.0")
    assert hub.get("/api/deck/plugin/info").json()["version"] == "1.0.0"
    data = make_zip(hub.zip, "2.0.0-longer")
    r = hub.get("/api/deck/plugin/info").json()
    assert r["version"] == "2.0.0-longer" and r["sha256"] == hashlib.sha256(data).hexdigest()


def test_no_path_from_request(hub):
    make_zip(hub.zip)
    for url in ("/api/deck/plugin/../../etc/passwd", "/api/deck/plugin?path=/etc/passwd", "/api/deck/plugin/x"):
        r = hub.get(url)
        assert b"root:" not in r.content
    assert hub.post("/api/deck/plugin").status_code in (404, 405)


def test_directory_at_zip_path_is_not_available(hub):
    hub.zip.mkdir(parents=True)
    assert hub.get("/api/deck/plugin/info").json() == {"available": False}
    assert hub.get("/api/deck/plugin").status_code == 404


def test_service_reads_bytes_once(tmp_path):
    p = tmp_path / "Checkpoint.zip"
    data = make_zip(p)
    got = deckplugin.load(p)
    assert got.data == data and got.sha256 == hashlib.sha256(data).hexdigest()
