import bcrypt
import pytest
from fastapi.testclient import TestClient

from app.core import settings
from app.api.auth import Auth
from app.main import create_app
from app.core.redact import redact

PW = "correct horse"
CFG = {
    "devices": {
        "a": {"name": "Equipo a", "host": "10.0.0.1", "user": "u", "os": "linux"},
        "b": {"name": "Equipo b", "host": "10.0.0.2", "user": "u", "os": "windows"},
    },
    "games": {},
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "static").mkdir()
    (tmp_path / "static/index.html").write_text("<html>app</html>", encoding="utf-8")
    t = [1000.0]
    a = Auth("admin", PW, 1, clock=lambda: t[0], rounds=4)
    c = TestClient(create_app(a))
    c.clock, c.sauth = t, a
    return c


def login(c, pw=PW, user="admin"):
    return c.post("/api/login", json={"user": user, "password": pw})


def test_api_requires_session(client):
    for m, p in [
        ("get", "/api/config"),
        ("put", "/api/config"),
        ("get", "/api/status"),
        ("post", "/api/sync/x"),
        ("get", "/api/versions/x"),
        ("get", "/api/runs/x/stream"),
        ("post", "/api/devices/test"),
        ("post", "/api/config/validate"),
        ("post", "/api/config/diff"),
        ("post", "/api/config/yaml"),
        ("get", "/api/config/events"),
        ("get", "/api/config/backups"),
        ("post", "/api/config/restore"),
    ]:
        assert getattr(client, m)(p).status_code == 401, p
    assert client.get("/").status_code == 200  # solo shell de login


def test_login_cookie_flags_and_config_roundtrip(client):
    r = login(client)
    assert r.status_code == 200
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "max-age=3600" in sc
    v0 = client.get("/api/config").json()["version"]
    r = client.put("/api/config", json={"config": CFG, "base_version": v0})
    assert r.status_code == 200 and r.json()["changed"] is True
    got = client.get("/api/config").json()
    assert got["config"]["devices"]["a"]["host"] == "10.0.0.1" and got["error"] is None
    bad = {"devices": {"a": {"name": "Equipo a", "host": "x y", "user": "u", "os": "linux"}}}
    r = client.put("/api/config", json={"config": bad, "base_version": got["version"]})
    assert r.status_code == 422 and "devices.a.host" in r.json()["errors"]
    assert client.get("/api/config").json()["config"]["devices"]["a"]["host"] == "10.0.0.1"  # intacto


def test_session_expires(client):
    login(client)
    client.clock[0] += 3601
    assert client.get("/api/config").status_code == 401


def test_bad_password_and_backoff(client):
    assert login(client, "no").status_code == 401
    assert login(client, "no").status_code == 401
    assert login(client, "no").status_code == 401  # 3er fallo => bloqueo 5 s
    r = login(client)  # correcta pero bloqueada
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    client.clock[0] += 6
    assert login(client).status_code == 200
    # tras éxito se resetea
    assert client.sauth.wait_time("testclient") == 0


def test_backoff_grows(client):
    waits = []
    for _ in range(5):
        login(client, "no")
        waits.append(client.sauth.wait_time("testclient"))
        client.clock[0] += waits[-1]
    assert waits[2] < waits[3] < waits[4]


def test_foreign_origin_blocked(client):
    login(client)
    r = client.put("/api/config", json={"config": CFG, "base_version": "x"}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403


def test_redact():
    assert "REDACTED" in redact("password=hunter2")
    assert "hunter2" not in redact("token: hunter2")
    assert "REDACTED" in redact("x " + bcrypt.hashpw(PW.encode(), bcrypt.gensalt(4)).decode())


def test_scheduler_endpoints(client):
    assert client.get("/api/scheduler").status_code == 401
    assert client.put("/api/scheduler", json={}).status_code == 401
    login(client)
    g = client.get("/api/scheduler").json()
    assert g["enabled"] is False and g["next_run"] is None and g["last_run"] is None
    r = client.put("/api/scheduler", json={"enabled": True, "interval_hours": 6})
    assert r.status_code == 200 and r.json()["next_run"] and r.json()["interval_hours"] == 6.0
    r = client.put("/api/scheduler", json={"interval_hours": 0.1})
    assert r.status_code == 422 and "interval_hours" in r.json()["errors"]
    assert client.get("/api/scheduler").json()["interval_hours"] == 6.0


def test_scheduler_history_endpoint(client):
    from datetime import datetime, timezone
    from app.users import history

    assert client.get("/api/scheduler/history").status_code == 401
    login(client)
    assert client.get("/api/scheduler/history").json() == {"entries": []}
    now = datetime.now(timezone.utc)
    for i in range(205):
        trig = "manual" if i == 204 else "scheduled"
        history.append(
            history.make_entry(now, 0.5, trig, "ok", {"g": {"result": "ok", "message": ""}}, f"e{i}"), now=now
        )
    assert len(client.get("/api/scheduler/history").json()["entries"]) == 200
    r = client.get("/api/scheduler/history?limit=200").json()["entries"]
    assert len(r) == 200 and r[0]["message"] == "e204" and r[0]["trigger"] == "manual"
    assert r[1]["trigger"] == "scheduled"
    assert client.get("/api/scheduler/history?limit=3").json()["entries"][2]["message"] == "e202"
    for bad in ("0", "201", "1000", "-1", "abc"):
        assert client.get(f"/api/scheduler/history?limit={bad}").status_code == 422, bad


def test_versions_limit_endpoint(client, tmp_path):
    login(client)
    cfg = dict(
        CFG,
        max_versions=7,
        games={"g": {"name": "Juego g", "devices": ["a", "b"], "paths": {"a": "/x/y", "b": "C:/z"}}},
    )
    client.sauth  # noqa
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    import yaml

    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (tmp_path / "data" / "versions" / "g" / "2026-01-01_100000" / "a").mkdir(parents=True)
    r = client.get("/api/versions/g/limit")
    assert r.status_code == 200 and r.json() == {
        "max": 7,
        "count": 1,
        "override": False,
        "latest": "2026-01-01_100000",
        "current": None,  # el hub no tiene datos de este juego
    }
    # `latest` es la más reciente por orden cronológico (con sufijo -n numérico), aunque count no cambie al rotar
    for v in ("2026-01-01_100000-2", "2026-01-01_100000-10", "2025-12-31_235959", "no-version"):
        (tmp_path / "data" / "versions" / "g" / v / "a").mkdir(parents=True)
    assert client.get("/api/versions/g/limit").json()["latest"] == "2026-01-01_100000-10"
    assert client.get("/api/versions/nope/limit").status_code == 404


def test_versions_limit_latest_is_null_without_versions(client, tmp_path):
    login(client)
    cfg = dict(CFG, games={"g": {"name": "Juego g", "devices": ["a", "b"], "paths": {"a": "/x/y", "b": "C:/z"}}})
    import yaml

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    assert client.get("/api/versions/g/limit").json()["latest"] is None


def test_versions_limit_current_is_the_hub_state(client, tmp_path):
    """`current` = estado actual del hub (solo stat, sin hashes): id barato, fecha, ficheros y tamaño; None si está vacío."""
    import os
    import yaml

    login(client)
    cfg = dict(CFG, games={"g": {"name": "Juego g", "devices": ["a", "b"], "paths": {"a": "/x/y", "b": "C:/z"}}})
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    hub = tmp_path / "data" / "hub" / "g"
    hub.mkdir(parents=True)
    assert client.get("/api/versions/g/limit").json()["current"] is None  # carpeta vacía = sin datos
    (hub / "sub").mkdir()
    (hub / "a.sav").write_bytes(b"12345")
    (hub / "sub" / "b.sav").write_bytes(b"678")
    os.utime(hub / "a.sav", (1_700_000_000, 1_700_000_000))
    os.utime(hub / "sub" / "b.sav", (1_700_000_100, 1_700_000_100))
    cur = client.get("/api/versions/g/limit").json()["current"]
    assert set(cur) == {"id", "mtime", "files", "size"}
    assert cur["files"] == 2 and cur["size"] == 8 and cur["mtime"] == _fmt_local(1_700_000_100)
    first_id = cur["id"]
    os.utime(hub / "a.sav", (1_700_000_500, 1_700_000_500))  # cambia el contenido del hub: cambia el id
    assert client.get("/api/versions/g/limit").json()["current"]["id"] != first_id
    # el listado de versiones sigue siendo una lista (compatibilidad): `current` no va ahí
    assert client.get("/api/versions/g").json() == []


def _fmt_local(ts):
    from datetime import datetime

    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def test_spa_cache_headers(client, tmp_path):
    (tmp_path / "static/assets").mkdir()
    (tmp_path / "static/assets/app-abc123.js").write_text("x", encoding="utf-8")
    (tmp_path / "static/favicon.svg").write_text("<svg/>", encoding="utf-8")
    for p in ("/", "/index.html", "/ruta/spa"):
        r = client.get(p)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", p
    r = client.get("/assets/app-abc123.js")
    assert "immutable" in r.headers["cache-control"] and "max-age=31536000" in r.headers["cache-control"]
    assert client.get("/favicon.svg").headers["cache-control"] == "no-cache"


def test_deck_plugin_info_exposes_checkpoint_protocol(client, tmp_path, monkeypatch):
    """`info` del zip lleva `protocol` (el `checkpointProtocol` del package.json del plugin) o null si no lo declara."""
    import io
    import json
    import zipfile

    from app.services import deckplugin

    def zip_with(pkg):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Checkpoint/package.json", json.dumps(pkg))
        return buf.getvalue()

    z = tmp_path / "deck" / "Checkpoint.zip"
    z.parent.mkdir()
    monkeypatch.setattr(settings, "DECK_ZIP", z)
    z.write_bytes(zip_with({"version": "0.1.0", "checkpointProtocol": 1}))
    j = client.get("/api/deck/plugin/info").json()
    assert j["version"] == "0.1.0" and j["protocol"] == 1
    deckplugin._cache.clear()
    z.write_bytes(zip_with({"version": "0.1.0", "checkpointProtocol": "x"}))
    assert client.get("/api/deck/plugin/info").json()["protocol"] is None
    deckplugin._cache.clear()
    z.write_bytes(zip_with({"version": "0.1.0"}))
    assert client.get("/api/deck/plugin/info").json()["protocol"] is None
