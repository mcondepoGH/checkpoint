"""Resolución de conflictos de datos de dispositivos `http`: el hub registra el conflicto (por juego y dispositivo),
la web o el propio dispositivo dejan una «resolución pendiente» y `fingerprint`/`commit` la honran."""

from datetime import timedelta

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.core import settings
from app.main import create_app
from app.sync import locking
from app.sync.engine import fingerprint, list_versions, load_baseline, save_baseline
from app.sync.fingerprint import fingerprint_from_manifest
from test_hook_fingerprint import PW, Env, entry

CFG = {
    "devices": {
        "deck": {"name": "Steam Deck", "http": True, "os": "linux"},
        "tab": {"name": "Tablet", "http": True, "os": "linux"},
        "pc": {"name": "PC", "host": "192.0.2.10", "user": "u", "os": "linux"},
    },
    "games": {
        "g1": {"name": "Mi Juego", "devices": ["deck", "tab"], "paths": {"deck": "/d", "tab": "/t"}},
        "g3": {"name": "Con PC", "devices": ["deck", "pc"], "paths": {"deck": "/d3", "pc": "/p3"}},
        "g2": {"name": "Otro", "devices": ["deck", "tab"], "paths": {"deck": "/d2", "tab": "/t2"}},
    },
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    e = Env(tmp_path, CFG)
    c = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
    assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    c.keys = {d: c.post(f"/api/devices/{d}/apikey").json()["key"] for d in ("deck", "tab")}
    c.ukey = c.post("/api/profile/apikey").json()["key"]
    c.env = e
    return c


def anon(c):
    return TestClient(c.app)


def H(c, dev="deck"):
    return {"Authorization": f"Bearer {c.keys[dev]}"}


def fp(c, manifest, game="g1", dev="deck"):
    return anon(c).post(f"/api/hook/{game}/fingerprint", json=manifest, headers=H(c, dev))


def hub_dir(c, game="g1"):
    return c.env.data / "hub" / game


def write_hub(c, content, game="g1"):
    d = hub_dir(c, game)
    d.mkdir(parents=True, exist_ok=True)
    (d / "s.sav").write_text(content, encoding="utf-8")


def base_all(c, content="base", game="g1"):
    h = fingerprint_from_manifest([entry("s.sav", content)]).hash
    save_baseline(c.env.data, game, {"deck": h, "tab": h, "pc": h, "hub": h})


def conflict(c, hub="hub nuevo", dev="deck", dev_content="dev nuevo", game="g1"):
    """Crea un conflicto real (ambos cambiaron sobre la misma base) y lo registra con un fingerprint."""
    write_hub(c, hub, game)
    base_all(c, game=game)
    r = fp(c, [entry("s.sav", dev_content, 2000)], game, dev)
    assert r.json()["action"] == "conflict" and r.json()["reason"] == "both-changed", r.text
    return r.json()


def pending(c):
    return c.get("/api/watches").json()


def expect_of(j):
    return {"hub": j["hub"]["hash"], "device": j["device_state"]["hash"]}


def session_put(c, body, game="g1"):
    return c.put(f"/api/sync/{game}/resolution", json=body)


def hook_put(c, body, game="g1", dev="deck", q=""):
    return anon(c).put(f"/api/hook/{game}/resolution{q}", json=body, headers=H(c, dev))


def code(r):
    return r.json()["detail"]["code"]


# ---- registro del conflicto ----
def test_conflict_is_recorded_without_paths_or_names(client):
    j = conflict(client)
    (c,) = pending(client)["conflicts"]
    assert c["game"] == "g1" and c["device"] == "deck" and c["reason"] == "both-changed"
    assert c["hub"] == j["hub"]["hash"] and c["device_hash"] == j["device_state"]["hash"] and c["at"].endswith("Z")
    assert set(c) == {"game", "device", "reason", "hub", "device_hash", "at"}
    assert pending(client)["resolutions"] == []


def test_conflict_record_survives_restart_on_disk(client):
    conflict(client)
    other = TestClient(create_app(Auth("admin", PW, 1, rounds=4)))
    other.post("/api/login", json={"user": "admin", "password": PW})
    assert len(other.get("/api/watches").json()["conflicts"]) == 1


def test_conflict_is_replaced_not_duplicated(client):
    conflict(client)
    conflict(client, dev_content="otro cambio")
    (c,) = pending(client)["conflicts"]
    assert c["device_hash"] == fingerprint_from_manifest([entry("s.sav", "otro cambio", 2000)]).hash


def test_other_game_or_device_does_not_see_each_others_conflict(client):
    conflict(client)
    assert [c["game"] for c in pending(client)["conflicts"]] == ["g1"]
    # el otro dispositivo, mismo juego, sin cambios sobre la base: baja, no hay conflicto suyo
    r = fp(client, [entry("s.sav", "base")], "g1", "tab")
    assert r.json()["action"] == "download"
    assert [(c["game"], c["device"]) for c in pending(client)["conflicts"]] == [("g1", "deck")]


# ---- resolver: el hub gana ----
def test_resolution_hub_via_session_downloads_then_clears(client):
    j = conflict(client)
    r = session_put(client, {"device": "deck", "winner": "hub", "expect": expect_of(j)})
    assert r.status_code == 200, r.text
    assert r.json()["winner"] == "hub" and r.json()["by"] == "web" and r.json()["device"] == "deck"
    (p,) = pending(client)["resolutions"]
    assert (p["game"], p["device"], p["winner"], p["by"]) == ("g1", "deck", "hub", "web")
    j2 = fp(client, [entry("s.sav", "dev nuevo", 2000)]).json()
    assert j2["action"] == "download" and j2["reason"] == "resolution"
    # el dispositivo baja el hub: ahora son iguales -> `none`, baseline fijada y todo limpio
    j3 = fp(client, [entry("s.sav", "hub nuevo")]).json()
    assert j3["action"] == "none" and j3["reason"] == "same"
    h = fingerprint(hub_dir(client)).hash
    assert load_baseline(client.env.data, "g1")["deck"] == h
    assert pending(client)["conflicts"] == [] and pending(client)["resolutions"] == []


def test_resolution_hub_with_manifest_flag_returns_hub_manifest(client):
    j = conflict(client)
    session_put(client, {"device": "deck", "winner": "hub", "expect": expect_of(j)})
    r = anon(client).post(
        "/api/hook/g1/fingerprint?manifest=1", json=[entry("s.sav", "dev nuevo", 2000)], headers=H(client)
    )
    assert r.json()["action"] == "download" and [m["path"] for m in r.json()["hub_manifest"]] == ["s.sav"]


# ---- resolver: el dispositivo gana ----
def upload(c, content=b"dev nuevo", dev="deck", game="g1"):
    import hashlib

    q = {"path": "s.sav", "size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "offset": 0}
    assert anon(c).put(f"/api/hook/{game}/files", params=q, content=content, headers=H(c, dev)).status_code == 200


def commit(c, expect, manifest, dev="deck", game="g1"):
    return anon(c).post(f"/api/hook/{game}/commit", json={"expect": expect, "manifest": manifest}, headers=H(c, dev))


def test_resolution_device_via_device_key_uploads_and_commit_keeps_previous_version(client):
    j = conflict(client)
    r = hook_put(client, {"device": "deck", "winner": "device", "expect": expect_of(j)}, q="?device=deck")
    assert r.status_code == 200, r.text
    assert r.json()["winner"] == "device" and r.json()["by"] == "device"
    j2 = fp(client, [entry("s.sav", "dev nuevo", 2000)]).json()
    assert j2["action"] == "upload" and j2["reason"] == "resolution"
    upload(client)
    man = [entry("s.sav", "dev nuevo", 2000)]
    r = commit(client, j["hub"]["hash"], man)
    assert r.status_code == 200 and r.json()["outcome"] == "ok", r.text
    assert (hub_dir(client) / "s.sav").read_text(encoding="utf-8") == "dev nuevo"
    (v,) = list_versions(client.env.data, "g1")  # la copia previa del hub
    assert (client.env.data / "versions" / "g1" / v["version"] / "hub" / "s.sav").read_text(
        encoding="utf-8"
    ) == "hub nuevo"
    h = fingerprint(hub_dir(client)).hash
    b = load_baseline(client.env.data, "g1")
    assert b["deck"] == h and b["hub"] == h
    assert pending(client) == {**pending(client), "conflicts": [], "resolutions": []}


def test_hook_resolution_body_device_must_match_key(client):
    j = conflict(client)
    r = hook_put(client, {"device": "tab", "winner": "device", "expect": expect_of(j)})
    assert r.status_code == 403 and code(r) == "err.apikey.device_mismatch"
    r = hook_put(client, {"winner": "device", "expect": expect_of(j)}, q="?device=Tablet")
    assert r.status_code == 403
    assert hook_put(client, {"winner": "device", "expect": expect_of(j)}).status_code == 200  # sin device: el de la key


# ---- commit forzado ----
def test_forced_commit_without_resolution_is_rejected(client):
    j = conflict(client)
    upload(client)
    r = commit(client, j["hub"]["hash"], [entry("s.sav", "dev nuevo", 2000)])
    assert r.status_code == 409 and code(r) == "err.hook.commit_rejected"
    assert (hub_dir(client) / "s.sav").read_text(encoding="utf-8") == "hub nuevo" and list_versions(
        client.env.data, "g1"
    ) == []


def test_forced_commit_with_hub_resolution_is_rejected(client):
    j = conflict(client)
    session_put(client, {"device": "deck", "winner": "hub", "expect": expect_of(j)})
    upload(client)
    r = commit(client, j["hub"]["hash"], [entry("s.sav", "dev nuevo", 2000)])
    assert r.status_code == 409 and code(r) == "err.hook.commit_rejected"
    assert (hub_dir(client) / "s.sav").read_text(encoding="utf-8") == "hub nuevo"


def test_forced_commit_with_other_manifest_than_resolved_is_rejected(client):
    j = conflict(client)
    session_put(client, {"device": "deck", "winner": "device", "expect": expect_of(j)})
    upload(client, b"otra cosa")
    r = commit(client, j["hub"]["hash"], [entry("s.sav", "otra cosa", 3000)])
    assert r.status_code == 409 and code(r) == "err.hook.commit_rejected"
    assert r.json()["detail"]["params"] == {"reason": "resolution_stale"}
    assert (hub_dir(client) / "s.sav").read_text(encoding="utf-8") == "hub nuevo"


def test_resolution_of_another_device_does_not_authorize_commit(client):
    # deck y tab en conflicto; solo tab tiene resolución: el commit de deck sigue rechazado
    j = conflict(client)
    conflict(client, dev="tab", dev_content="tab nuevo")
    jt = fp(client, [entry("s.sav", "tab nuevo", 2000)], "g1", "tab").json()
    session_put(client, {"device": "tab", "winner": "device", "expect": expect_of(jt)})
    upload(client)
    r = commit(client, j["hub"]["hash"], [entry("s.sav", "dev nuevo", 2000)])
    assert r.status_code == 409 and code(r) == "err.hook.commit_rejected"
    assert len(pending(client)["resolutions"]) == 1 and pending(client)["resolutions"][0]["device"] == "tab"


# ---- obsoleta, caducada, cancelada ----
def test_stale_resolution_gives_conflict_again_and_is_discarded(client):
    j = conflict(client)
    session_put(client, {"device": "deck", "winner": "hub", "expect": expect_of(j)})
    write_hub(client, "hub cambió otra vez")
    r = fp(client, [entry("s.sav", "dev nuevo", 2000)]).json()
    assert r["action"] == "conflict" and r["reason"] == "resolution_stale"
    p = pending(client)
    assert p["resolutions"] == [] and len(p["conflicts"]) == 1
    assert p["conflicts"][0]["hub"] == fingerprint(hub_dir(client)).hash  # conflicto actualizado a las huellas nuevas
    assert fp(client, [entry("s.sav", "dev nuevo", 2000)]).json()["reason"] == "both-changed"


def test_stale_when_device_changed_again(client):
    j = conflict(client)
    session_put(client, {"device": "deck", "winner": "device", "expect": expect_of(j)})
    r = fp(client, [entry("s.sav", "dev otra vez", 2500)]).json()
    assert r["action"] == "conflict" and r["reason"] == "resolution_stale"


def test_expired_resolution_is_ignored_and_not_listed(client):
    j = conflict(client)
    session_put(client, {"device": "deck", "winner": "hub", "expect": expect_of(j)})
    sch = client.app.state.ctx.scheduler
    clock = sch.clock
    sch.clock = lambda: clock() + timedelta(seconds=settings.HOOK_RESOLUTION_TTL + 1)
    assert pending(client)["resolutions"] == []
    r = fp(client, [entry("s.sav", "dev nuevo", 2000)]).json()
    assert r["action"] == "conflict" and r["reason"] == "both-changed"


def test_cancel_removes_the_pending_resolution_only(client):
    j = conflict(client)
    session_put(client, {"device": "deck", "winner": "hub", "expect": expect_of(j)})
    r = client.delete("/api/sync/g1/resolution", params={"device": "deck"})
    assert r.status_code == 200 and r.json() == {"game": "g1", "device": "deck", "cancelled": True}
    p = pending(client)
    assert p["resolutions"] == [] and len(p["conflicts"]) == 1
    assert fp(client, [entry("s.sav", "dev nuevo", 2000)]).json()["action"] == "conflict"
    assert client.delete("/api/sync/g1/resolution", params={"device": "deck"}).json()["cancelled"] is False


def test_natural_resolution_clears_records(client):
    """Si el conflicto desaparece solo (p. ej. el dispositivo vuelve a la base), no queda nada pendiente."""
    j = conflict(client)
    session_put(client, {"device": "deck", "winner": "hub", "expect": expect_of(j)})
    write_hub(client, "base")  # el hub vuelve a la base
    r = fp(client, [entry("s.sav", "dev nuevo", 2000)]).json()
    assert r["action"] == "upload"
    p = pending(client)
    assert p["conflicts"] == [] and p["resolutions"] == []


# ---- validación y errores ----
def test_put_without_registered_conflict_is_409(client):
    write_hub(client, "x")
    h = fingerprint(hub_dir(client)).hash
    r = session_put(client, {"device": "deck", "winner": "hub", "expect": {"hub": h, "device": h}})
    assert r.status_code == 409 and code(r) == "err.resolution.no_conflict"


def test_put_with_expect_different_from_record_is_409_stale(client):
    j = conflict(client)
    bad = {"hub": "0" * 64, "device": j["device_state"]["hash"]}
    r = session_put(client, {"device": "deck", "winner": "hub", "expect": bad})
    assert r.status_code == 409 and code(r) == "err.resolution.stale"
    assert pending(client)["resolutions"] == []


@pytest.mark.parametrize(
    "mut",
    [
        {"winner": "newest"},
        {"winner": "device:deck"},
        {"winner": None},
        {"winner": 1},
        {"expect": None},
        {"expect": {"hub": "xyz", "device": "0" * 64}},
        {"expect": {"hub": "A" * 64, "device": "0" * 64}},
        {"expect": {"hub": "0" * 64}},
        {"expect": {"hub": "0" * 64, "device": "0" * 64, "extra": 1}},
        {"expect": {"hub": 5, "device": "0" * 64}},
        {"extra": 1},
        {"device": 5},
    ],
)
def test_invalid_body_is_422(client, mut):
    j = conflict(client)
    body = {"device": "deck", "winner": "hub", "expect": expect_of(j), **mut}
    r = session_put(client, body)
    assert r.status_code == 422 and code(r) == "err.resolution.invalid", r.text
    assert pending(client)["resolutions"] == []


def test_body_too_big_or_not_json(client):
    conflict(client)
    assert client.put("/api/sync/g1/resolution", content=b"x" * 5000).status_code == 400
    assert client.put("/api/sync/g1/resolution", json=[1]).status_code == 400
    assert hook_put(client, {"winner": "hub", "pad": "x" * 5000}).status_code == 400


def test_device_must_be_http_and_in_game(client):
    j = conflict(client)
    assert session_put(client, {"device": "pc", "winner": "hub", "expect": expect_of(j)}, "g3").status_code == 400
    assert session_put(client, {"device": "nope", "winner": "hub", "expect": expect_of(j)}).status_code == 404
    assert session_put(client, {"winner": "hub", "expect": expect_of(j)}).status_code == 400  # ambiguo: deck y tab
    assert session_put(client, {"device": "deck", "winner": "hub", "expect": expect_of(j)}, "zzz").status_code == 404


def test_hook_resolution_keys_and_session(client):
    j = conflict(client)
    body = {"winner": "device", "expect": expect_of(j)}
    assert anon(client).put("/api/hook/g1/resolution", json=body).status_code == 401  # sin key (la cookie no vale)
    assert (
        anon(client)
        .put("/api/hook/g1/resolution", json=body, headers={"Authorization": f"Bearer {client.ukey}"})
        .status_code
        == 401
    )
    assert client.put("/api/sync/g1/resolution", json=body).status_code == 400  # sesión: falta `device` y hay dos
    assert anon(client).put("/api/sync/g1/resolution", json=body).status_code == 401
    assert anon(client).delete("/api/sync/g1/resolution?device=deck").status_code == 401
    assert hook_put(client, body, game="g2").status_code == 409  # g2 existe y lo incluye, pero no hay conflicto allí
    assert hook_put(client, body, game="zzz").status_code == 404


def test_device_key_cannot_touch_game_without_it(client, tmp_path):
    j = conflict(client)
    # g1 no incluye ningún dispositivo ajeno; comprobamos que un juego inexistente para esa key es 404 sin filtrar
    r = hook_put(client, {"winner": "hub", "expect": expect_of(j)}, game="no-existe")
    assert r.status_code == 404 and code(r) == "err.main.game_unknown"


def test_resolution_while_lock_busy_is_409(client):
    j = conflict(client)
    h = locking.acquire(client.env.data / "locks" / "g1.lock")
    try:
        r = session_put(client, {"device": "deck", "winner": "hub", "expect": expect_of(j)})
        assert r.status_code == 409 and code(r) == "err.main.run_in_progress"
        r = fp(client, [entry("s.sav", "dev nuevo", 2000)])  # registrar el conflicto también pide el lock
        assert r.status_code == 409 and code(r) == "err.main.run_in_progress"
    finally:
        h.release()
    assert pending(client)["resolutions"] == []


def test_resolution_for_disabled_game_is_409(client):
    j = conflict(client)
    cfg = yaml.safe_load(client.env.tmp.joinpath("config", "config.yaml").read_text(encoding="utf-8"))
    cfg["games"]["g1"]["enabled"] = False
    client.env.tmp.joinpath("config", "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    r = session_put(client, {"device": "deck", "winner": "hub", "expect": expect_of(j)})
    assert r.status_code == 409 and code(r) == "err.sync.game_disabled"


def test_resolution_for_an_empty_winner_side_is_409(client):
    from app.sync import resolution

    now = client.app.state.ctx.scheduler.clock()
    resolution.record_conflict(client.env.data, "g1", "deck", "inconsistent", None, "a" * 64, now)
    r = session_put(client, {"device": "deck", "winner": "hub", "expect": {"hub": None, "device": "a" * 64}})
    assert r.status_code == 409 and code(r) == "err.resolution.side_empty"
    r = session_put(client, {"device": "deck", "winner": "device", "expect": {"hub": None, "device": "a" * 64}})
    assert r.status_code == 200


def test_damaged_records_file_is_ignored(client):
    (client.env.data / "resolutions").mkdir(parents=True)
    (client.env.data / "resolutions" / "g1.json").write_text(
        '{"conflicts": {"deck": {"reason": 1}}, "resolutions": 5}', encoding="utf-8"
    )
    assert pending(client)["conflicts"] == [] and pending(client)["resolutions"] == []
    (client.env.data / "resolutions" / "g1.json").write_text("no json", encoding="utf-8")
    assert pending(client)["conflicts"] == []
