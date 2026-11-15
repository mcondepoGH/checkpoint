"""Asociación automática de juegos de Steam desde la Deck: `POST /api/steam/library` (solo key `ckd_`), coincidencia
por nombre normalizado, sugerencias en memoria, descartes recordados en disco y la API de sesión de la web."""

import copy
import json
import logging

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.config.models import validate_config
from app.core import settings
from app.main import create_app
from app.services import steam
from test_hook_fingerprint import PW, Env

CFG = {
    "devices": {
        "pc": {"name": "PC", "host": "192.0.2.10", "user": "u", "os": "linux"},
        "deck": {"name": "Steam Deck", "http": True, "os": "linux"},
        "deck2": {"name": "Otra Deck", "http": True, "os": "linux"},
    },
    "games": {
        "g1": {"name": "Mi Juego", "devices": ["deck", "pc"], "paths": {"deck": "/d", "pc": "/p"}},
        "hades": {"name": "Hades", "devices": ["deck"], "paths": {"deck": "/h"}},
        "witcher": {"name": "The Witcher 3: Wild Hunt", "devices": ["deck"], "paths": {"deck": "/w"}},
        "dup1": {"name": "Dup Game", "devices": ["deck"], "paths": {"deck": "/a"}},
        "dup2": {"name": "Dup-Game", "devices": ["deck"], "paths": {"deck": "/b"}},
        "haspid": {"name": "Has Appid", "devices": ["deck"], "paths": {"deck": "/c"}, "steam_appid": 111},
        "usedby": {"name": "Other Pid", "devices": ["pc"], "paths": {"pc": "/e"}, "steam_appid": 222},
        "only2": {"name": "Only Other", "devices": ["deck2"], "paths": {"deck2": "/f"}},
        "off": {"name": "Disabled Game", "devices": ["deck"], "paths": {"deck": "/g"}, "enabled": False},
        "portal": {"name": "Portal", "devices": ["deck"], "paths": {"deck": "/p1"}},
    },
}


class Hub:
    pass


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    Env(tmp_path, copy.deepcopy(CFG))
    h = Hub()
    h.tmp = tmp_path
    h.clock = [1000.0]
    h.auth = Auth("admin", PW, 1, clock=lambda: h.clock[0], rounds=4)
    h.app = create_app(h.auth)
    h.ctx = h.app.state.ctx
    h.session = TestClient(h.app)
    assert h.session.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    h.anon = TestClient(h.app)
    h.key = h.session.post("/api/devices/deck/apikey").json()["key"]
    h.key2 = h.session.post("/api/devices/deck2/apikey").json()["key"]
    h.ukey = h.session.post("/api/profile/apikey").json()["key"]
    return h


def bearer(k):
    return {"Authorization": f"Bearer {k}"}


def lib(hub, games, key=None, **kw):
    body = {"games": [{"appid": a, "name": n} for a, n in games]}
    return hub.anon.post("/api/steam/library", json=body, headers=bearer(key or hub.key), **kw)


def code(r):
    return r.json()["detail"]["code"]


def cfg_games(hub):
    return yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())["games"]


def sugg(hub):
    return hub.session.get("/api/steam/suggestions").json()


# ---- normalización (función pura) ----
@pytest.mark.parametrize(
    "raw,want",
    [
        ("The Witcher® 3: Wild Hunt™", "the witcher 3 wild hunt"),
        ("  Café   Ñandú ", "cafe nandu"),
        ("Dark Souls™ III © FromSoftware", "dark souls iii fromsoftware"),
        ("Half-Life 2: Episode One", "half life 2 episode one"),
        ("Tom & Jerry", "tom and jerry"),
        ("ＨＡＤＥＳ", "hades"),
        ("!!!", ""),
    ],
)
def test_normalize(raw, want):
    assert steam.normalize(raw) == want


def test_similar_threshold_is_documented_and_deterministic():
    assert steam.SIMILARITY == 0.85
    assert steam.similar("the witcher 3 wild hunt", "the witcher 3 wild hunt goty")
    assert not steam.similar("hades", "hades ii")
    assert not steam.similar("", "")


# ---- endpoint de la Deck: auth y forma ----
def test_user_key_and_session_and_anonymous_are_401(hub):
    for headers in (bearer(hub.ukey), {}, bearer("ckd_" + "A" * 43), bearer("basura")):
        r = hub.anon.post("/api/steam/library", json={"games": []}, headers=headers)
        assert r.status_code == 401 and code(r) == "err.apikey.invalid"
        hub.auth.hook_fails.clear()  # cada intento cuenta; aquí se comprueba cada uno por separado
    r = hub.session.post("/api/steam/library", json={"games": []})  # cookie de sesión no vale
    assert r.status_code == 401 and code(r) == "err.apikey.invalid"


def test_failures_count_and_block_429(hub):
    for _ in range(3):
        hub.anon.post("/api/steam/library", json={"games": []}, headers=bearer(hub.ukey))
    r = hub.anon.post("/api/steam/library", json={"games": []}, headers=bearer(hub.key))
    assert r.status_code == 429 and "retry-after" in r.headers


def test_response_shape_and_no_store(hub):
    r = lib(hub, [(1, "Hades")])
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"associated": [{"appid": 1, "game": "hades"}], "suggested": 0, "unchanged": 0, "ignored": 0}


def test_body_validation(hub):
    def post(body):
        return hub.anon.post("/api/steam/library", json=body, headers=bearer(hub.key))

    for bad in ([], {"games": "x"}, {"games": [], "x": 1}, {}):
        r = post(bad)
        assert r.status_code in (400, 422), bad
    for entry in (
        {"appid": 0, "name": "A"},
        {"appid": -3, "name": "A"},
        {"appid": True, "name": "A"},
        {"appid": "5", "name": "A"},
        {"appid": 1.5, "name": "A"},
        {"appid": 5, "name": ""},
        {"appid": 5, "name": 7},
        {"appid": 5, "name": "x" * (steam.MAX_NAME + 1)},
        {"appid": 5, "name": "A", "extra": 1},
        {"appid": 5},
        "texto",
    ):
        r = post({"games": [entry]})
        assert r.status_code == 422 and code(r) == "err.steam.entry_invalid", entry
    assert post({"games": [{"appid": 5, "name": "x" * steam.MAX_NAME}]}).status_code == 200


def test_list_cap_and_body_cap(hub):
    ok = [{"appid": i + 1, "name": f"n{i}"} for i in range(steam.MAX_GAMES)]
    assert hub.anon.post("/api/steam/library", json={"games": ok}, headers=bearer(hub.key)).status_code == 200
    r = hub.anon.post(
        "/api/steam/library", json={"games": ok + [{"appid": 99999, "name": "z"}]}, headers=bearer(hub.key)
    )
    assert r.status_code == 413 and code(r) == "err.steam.too_many_games"
    big = hub.anon.post(
        "/api/steam/library", content=b'{"games": [' + b" " * (steam.MAX_BODY + 1) + b"]}", headers=bearer(hub.key)
    )
    assert big.status_code == 413 and code(big) == "err.steam.body_too_large"


def test_not_json_is_400(hub):
    r = hub.anon.post("/api/steam/library", content=b"no json", headers=bearer(hub.key))
    assert r.status_code == 400 and code(r) == "err.main.json_body_required"


# ---- coincidencia automática ----
def test_exact_unique_match_associates_and_writes_valid_config(hub):
    r = lib(hub, [(1145360, "HADES™"), (292030, "The Witcher® 3: Wild Hunt")])
    assert r.status_code == 200
    j = r.json()
    assert sorted(j["associated"], key=lambda a: a["appid"]) == [
        {"appid": 292030, "game": "witcher"},
        {"appid": 1145360, "game": "hades"},
    ]
    games = cfg_games(hub)
    assert games["hades"]["steam_appid"] == 1145360 and games["witcher"]["steam_appid"] == 292030
    assert validate_config(yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text()))[1] == {}
    # visible en GET /api/games
    g = {x["id"]: x for x in hub.anon.get("/api/games", headers=bearer(hub.key)).json()}
    assert g["hades"]["steam_appid"] == 1145360


def test_game_with_other_appid_is_never_overwritten_nor_suggested(hub):
    j = lib(hub, [(999, "Has Appid")]).json()
    assert j == {"associated": [], "suggested": 0, "unchanged": 0, "ignored": 1}
    assert cfg_games(hub)["haspid"]["steam_appid"] == 111 and sugg(hub) == []


def test_same_appid_is_idempotent(hub):
    before = (hub.tmp / "config" / "config.yaml").read_text()
    j = lib(hub, [(111, "Has Appid")]).json()
    assert j == {"associated": [], "suggested": 0, "unchanged": 1, "ignored": 0}
    assert (hub.tmp / "config" / "config.yaml").read_text() == before


def test_second_call_is_idempotent_after_associating(hub):
    assert lib(hub, [(1, "Hades")]).json()["associated"]
    j = lib(hub, [(1, "Hades")]).json()
    assert j == {"associated": [], "suggested": 0, "unchanged": 1, "ignored": 0}


def test_appid_already_used_by_other_game_does_not_associate(hub):
    j = lib(hub, [(222, "Hades")]).json()
    assert j == {"associated": [], "suggested": 0, "unchanged": 0, "ignored": 1}
    assert "steam_appid" not in cfg_games(hub)["hades"] and sugg(hub) == []


def test_two_hub_games_same_normalized_name_become_suggestions(hub):
    j = lib(hub, [(5, "Dup Game")]).json()
    assert j["associated"] == [] and j["suggested"] == 1
    s = sugg(hub)
    assert {(x["game"], x["appid"]) for x in s} == {("dup1", 5), ("dup2", 5)}
    assert "steam_appid" not in cfg_games(hub)["dup1"]


def test_two_steam_entries_same_name_become_suggestions(hub):
    j = lib(hub, [(7, "Hades"), (8, "Hades")]).json()
    assert j["associated"] == [] and j["suggested"] == 2
    assert {(x["game"], x["appid"]) for x in sugg(hub)} == {("hades", 7), ("hades", 8)}


def test_similar_name_is_a_suggestion_not_an_association(hub):
    j = lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")]).json()
    assert j["associated"] == [] and j["suggested"] == 1
    (s,) = sugg(hub)
    assert s["game"] == "witcher" and s["appid"] == 9 and s["steam_name"] == "The Witcher 3 Wild Hunt GOTY"
    assert "steam_appid" not in cfg_games(hub)["witcher"]


def test_not_similar_is_ignored(hub):
    assert lib(hub, [(3, "Totally Different Title"), (4, "Hades II")]).json() == {
        "associated": [],
        "suggested": 0,
        "unchanged": 0,
        "ignored": 2,
    }


def test_exact_match_entry_is_not_also_similar_to_other_game(hub):
    lib(hub, [(10, "Portal")])  # exacta con "portal"; no debe proponerse además a otros
    assert sugg(hub) == []


def test_scope_other_device_and_disabled_games_ignored(hub):
    j = lib(hub, [(20, "Only Other"), (21, "Disabled Game"), (22, "Other Pid")]).json()
    assert j == {"associated": [], "suggested": 0, "unchanged": 0, "ignored": 3}
    g = cfg_games(hub)
    assert "steam_appid" not in g["only2"] and "steam_appid" not in g["off"]
    assert sugg(hub) == []


def test_other_device_key_only_touches_its_games(hub):
    j = lib(hub, [(20, "Only Other"), (1, "Hades")], key=hub.key2).json()
    assert j["associated"] == [{"appid": 20, "game": "only2"}] and j["ignored"] == 1


def test_response_never_leaks_other_games(hub):
    r = lib(hub, [(222, "Other Pid"), (20, "Only Other"), (1, "Hades")])
    for secreto in ("only2", "usedby", "Only Other", "Other Pid", "pc"):
        assert secreto not in r.text


def test_duplicate_appids_in_list_count_once(hub):
    j = lib(hub, [(1, "Hades"), (1, "Hades")]).json()
    assert j["associated"] == [{"appid": 1, "game": "hades"}] and j["ignored"] == 0


def test_two_steam_entries_same_name_one_unused_still_ambiguous_not_auto(hub):
    assert lib(hub, [(1, "Hades"), (2, "hades")]).json()["associated"] == []


def test_config_changed_is_retried(hub, monkeypatch):
    real = hub.ctx.store.save
    calls = []

    def flaky(version, cfg):
        calls.append(1)
        if len(calls) == 1:
            from app.config.store import Conflict

            raise Conflict("x")
        return real(version, cfg)

    monkeypatch.setattr(hub.ctx.store, "save", flaky)
    assert lib(hub, [(1, "Hades")]).json()["associated"] == [{"appid": 1, "game": "hades"}]
    assert len(calls) == 2


def test_config_changed_exhausted_is_409(hub, monkeypatch):
    from app.config.store import Conflict

    def always(version, cfg):
        raise Conflict("x")

    monkeypatch.setattr(hub.ctx.store, "save", always)
    r = lib(hub, [(1, "Hades")])
    assert r.status_code == 409 and code(r) == "err.main.config_changed"


# ---- sugerencias: API de sesión ----
def test_suggestion_shape_and_no_store(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    r = hub.session.get("/api/steam/suggestions")
    assert r.headers["cache-control"] == "no-store"
    (s,) = r.json()
    assert set(s) == {"id", "appid", "steam_name", "game", "game_name", "device", "device_name"}
    assert s["game_name"] == "The Witcher 3: Wild Hunt" and s["device"] == "deck" and s["device_name"] == "Steam Deck"


def test_suggestions_resent_do_not_duplicate(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    assert len(sugg(hub)) == 1


def test_session_endpoints_need_session_and_origin(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    sid = sugg(hub)[0]["id"]
    for method, url in (
        ("get", "/api/steam/suggestions"),
        ("post", f"/api/steam/suggestions/{sid}/accept"),
        ("post", f"/api/steam/suggestions/{sid}/dismiss"),
        ("get", "/api/steam/dismissed"),
        ("delete", "/api/steam/dismissed/x"),
    ):
        r = getattr(hub.anon, method)(url)
        assert r.status_code == 401 and code(r) == "err.main.session_required", url
        r = getattr(hub.anon, method)(url, headers=bearer(hub.key))  # clave de dispositivo no vale
        assert r.status_code == 401, url
        r = getattr(hub.anon, method)(url, headers=bearer(hub.ukey))
        assert r.status_code == 401, url
    for method, url in (
        ("post", f"/api/steam/suggestions/{sid}/accept"),
        ("post", f"/api/steam/suggestions/{sid}/dismiss"),
        ("delete", "/api/steam/dismissed/x"),
    ):
        r = getattr(hub.session, method)(url, headers={"Origin": "http://evil.example"})
        assert r.status_code == 403 and code(r) == "err.main.origin_forbidden", url
    assert len(sugg(hub)) == 1  # nada se aplicó


def test_accept_writes_appid(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    sid = sugg(hub)[0]["id"]
    r = hub.session.post(f"/api/steam/suggestions/{sid}/accept")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"id": sid, "appid": 9, "game": "witcher", "name": "The Witcher 3: Wild Hunt"}
    assert cfg_games(hub)["witcher"]["steam_appid"] == 9
    assert sugg(hub) == []
    assert hub.session.post(f"/api/steam/suggestions/{sid}/accept").status_code == 404


def test_accept_unknown_is_404(hub):
    r = hub.session.post("/api/steam/suggestions/nope/accept")
    assert r.status_code == 404 and code(r) == "err.steam.suggestion_unknown"


def test_accept_removes_rival_suggestions_of_same_game_or_appid(hub):
    lib(hub, [(7, "Hades"), (8, "Hades")])
    a = next(s for s in sugg(hub) if s["appid"] == 7)
    assert hub.session.post(f"/api/steam/suggestions/{a['id']}/accept").status_code == 200
    assert sugg(hub) == []


def test_accept_409_when_game_got_an_appid_meanwhile(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    sid = sugg(hub)[0]["id"]
    cfg = yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())
    cfg["games"]["witcher"]["steam_appid"] = 55
    (hub.tmp / "config" / "config.yaml").write_text(yaml.safe_dump(cfg))
    r = hub.session.post(f"/api/steam/suggestions/{sid}/accept")
    assert r.status_code == 409 and code(r) == "err.steam.game_has_appid"
    assert cfg_games(hub)["witcher"]["steam_appid"] == 55


def test_accept_409_when_appid_in_use_meanwhile(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    sid = sugg(hub)[0]["id"]
    cfg = yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())
    cfg["games"]["hades"]["steam_appid"] = 9
    (hub.tmp / "config" / "config.yaml").write_text(yaml.safe_dump(cfg))
    r = hub.session.post(f"/api/steam/suggestions/{sid}/accept")
    assert r.status_code == 409 and code(r) == "err.steam.appid_in_use"
    assert "steam_appid" not in cfg_games(hub)["witcher"]


def test_accept_404_when_game_removed(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    sid = sugg(hub)[0]["id"]
    cfg = yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())
    del cfg["games"]["witcher"]
    (hub.tmp / "config" / "config.yaml").write_text(yaml.safe_dump(cfg))
    r = hub.session.post(f"/api/steam/suggestions/{sid}/accept")
    assert r.status_code == 404 and code(r) == "err.steam.game_unknown"


def test_accept_config_changed_retries_then_409(hub, monkeypatch):
    from app.config.store import Conflict

    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    sid = sugg(hub)[0]["id"]
    real = hub.ctx.store.save
    n = []

    def flaky(v, c):
        n.append(1)
        if len(n) == 1:
            raise Conflict("x")
        return real(v, c)

    monkeypatch.setattr(hub.ctx.store, "save", flaky)
    assert hub.session.post(f"/api/steam/suggestions/{sid}/accept").status_code == 200

    lib(hub, [(10, "Hades Remastered Edit")])  # nueva sugerencia no coincide: usamos otra
    lib(hub, [(7, "Hades"), (8, "Hades")])
    sid = sugg(hub)[0]["id"]

    def always(v, c):
        raise Conflict("x")

    monkeypatch.setattr(hub.ctx.store, "save", always)
    r = hub.session.post(f"/api/steam/suggestions/{sid}/accept")
    assert r.status_code == 409 and code(r) == "err.main.config_changed"
    assert any(s["id"] == sid for s in sugg(hub))  # sigue pendiente: se puede reintentar


def test_suggestion_stale_after_game_gets_appid_is_hidden(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    cfg = yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())
    cfg["games"]["witcher"]["steam_appid"] = 55
    (hub.tmp / "config" / "config.yaml").write_text(yaml.safe_dump(cfg))
    assert sugg(hub) == []


# ---- descartes ----
def dismissed_file(hub):
    return hub.tmp / "data" / "state" / "_steam" / "dismissed.json"


def test_dismiss_is_remembered_and_not_proposed_again(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    sid = sugg(hub)[0]["id"]
    r = hub.session.post(f"/api/steam/suggestions/{sid}/dismiss")
    assert r.status_code == 200 and r.json()["appid"] == 9 and r.json()["game"] == "witcher"
    assert sugg(hub) == []
    j = lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")]).json()
    assert j["suggested"] == 0 and j["ignored"] == 1 and sugg(hub) == []
    (d,) = hub.session.get("/api/steam/dismissed").json()
    assert set(d) == {"id", "appid", "steam_name", "game", "game_name"}
    assert d["game_name"] == "The Witcher 3: Wild Hunt"
    assert hub.session.post(f"/api/steam/suggestions/{sid}/dismiss").status_code == 404


def test_dismiss_survives_service_restart_and_has_no_secrets(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    hub.session.post(f"/api/steam/suggestions/{sugg(hub)[0]['id']}/dismiss")
    raw = dismissed_file(hub).read_text()
    assert json.loads(raw)
    assert hub.key not in raw and "ckd_" not in raw and "ck_" not in raw
    app2 = create_app(hub.auth)
    c2 = TestClient(app2)
    assert c2.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    assert len(c2.get("/api/steam/dismissed").json()) == 1
    c2.post(
        "/api/steam/library",
        json={"games": [{"appid": 9, "name": "The Witcher 3 Wild Hunt GOTY"}]},
        headers=bearer(hub.key),
    )
    assert c2.get("/api/steam/suggestions").json() == []


def test_forget_dismissal_allows_proposing_again(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    hub.session.post(f"/api/steam/suggestions/{sugg(hub)[0]['id']}/dismiss")
    did = hub.session.get("/api/steam/dismissed").json()[0]["id"]
    r = hub.session.delete(f"/api/steam/dismissed/{did}")
    assert r.status_code == 200 and r.json() == {"id": did, "forgotten": True}
    assert hub.session.get("/api/steam/dismissed").json() == []
    assert hub.session.delete(f"/api/steam/dismissed/{did}").status_code == 404
    assert lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")]).json()["suggested"] == 1


def test_dismiss_only_blocks_that_pair(hub):
    lib(hub, [(7, "Hades"), (8, "Hades")])
    a = next(s for s in sugg(hub) if s["appid"] == 7)
    hub.session.post(f"/api/steam/suggestions/{a['id']}/dismiss")
    assert [s["appid"] for s in sugg(hub)] == [8]


def test_corrupt_dismissed_file_is_empty_not_a_crash(hub):
    dismissed_file(hub).parent.mkdir(parents=True)
    dismissed_file(hub).write_text("{no json")
    assert hub.session.get("/api/steam/dismissed").json() == []
    assert lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")]).json()["suggested"] == 1


def test_dismissed_cap_drops_oldest(hub, monkeypatch):
    monkeypatch.setattr(steam, "MAX_DISMISSED", 2)
    monkeypatch.setattr(steam, "MAX_SUGGESTIONS", 50)
    for appid in (1, 2, 3):
        lib(hub, [(appid, "Hades"), (appid + 100, "Hades")])
        for s in sugg(hub):
            hub.session.post(f"/api/steam/suggestions/{s['id']}/dismiss")
    assert len(hub.session.get("/api/steam/dismissed").json()) == 2


def test_purge_forgets_dismissals_of_removed_games(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    hub.session.post(f"/api/steam/suggestions/{sugg(hub)[0]['id']}/dismiss")
    cfg = yaml.safe_load((hub.tmp / "config" / "config.yaml").read_text())
    del cfg["games"]["witcher"]
    (hub.tmp / "config" / "config.yaml").write_text(yaml.safe_dump(cfg))
    hub.ctx.steam.purge()
    assert hub.session.get("/api/steam/dismissed").json() == []


# ---- topes y caducidad de sugerencias ----
def test_suggestion_caps_total_and_per_device(hub, monkeypatch):
    monkeypatch.setattr(steam, "MAX_SUGGESTIONS", 3)
    monkeypatch.setattr(steam, "MAX_PER_DEVICE", 2)
    lib(hub, [(1, "Dup Game"), (2, "Hades"), (3, "Hades")])
    assert len(sugg(hub)) == 2  # tope por dispositivo
    r = lib(hub, [(1, "Dup Game"), (2, "Hades"), (3, "Hades")], key=hub.key2)
    assert r.status_code == 200 and len(sugg(hub)) == 2  # deck2 no tiene esos juegos


def test_total_cap(hub, monkeypatch):
    monkeypatch.setattr(steam, "MAX_SUGGESTIONS", 1)
    lib(hub, [(2, "Hades"), (3, "Hades")])
    assert len(sugg(hub)) == 1


def test_suggestions_expire_and_purge(hub):
    lib(hub, [(9, "The Witcher 3 Wild Hunt GOTY")])
    hub.ctx.steam._clock = lambda: 1000.0 + steam.TTL_S + 1  # el reloj de la sesión no se toca
    assert sugg(hub) == []
    assert hub.ctx.steam._sugg == {}


def test_purge_registered_in_scheduler_maintenance(hub):
    assert hub.ctx.steam.purge in hub.ctx.scheduler.maintenance


# ---- logs ----
def test_no_secrets_in_logs(hub, caplog):
    caplog.set_level(logging.DEBUG)
    lib(hub, [(1, "Hades"), (9, "The Witcher 3 Wild Hunt GOTY")])
    lib(hub, [(1, "Hades")], key=hub.ukey)
    text = caplog.text
    assert hub.key not in text and hub.ukey not in text
