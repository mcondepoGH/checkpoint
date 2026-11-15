"""Juegos desde la Deck con su key `ckd_`: `POST /api/steam/games` (crear con appid, nombre y ruta) y
`PUT /api/steam/games/{game}/enabled` (activar o desactivar uno de SUS juegos)."""

import logging

from test_steam import bearer, cfg_games, code, hub  # noqa: F401  (hub es una fixture)

PATH = "/home/deck/.local/share/Steam/steamapps/compatdata/4000/pfx/drive_c/users/steamuser/AppData/Roaming/Celeste"


def create(hub, body, key=None, **kw):
    return hub.anon.post("/api/steam/games", json=body, headers=bearer(key or hub.key), **kw)


def toggle(hub, game, enabled, key=None, body=None):
    return hub.anon.put(
        f"/api/steam/games/{game}/enabled",
        json={"enabled": enabled} if body is None else body,
        headers=bearer(key or hub.key),
    )


def good(**kw):
    return {"appid": 504230, "name": "Celeste", "path": PATH, **kw}


# ---- crear ----
def test_create_game_writes_a_game_for_that_device_only(hub):
    r = create(hub, good())
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"id": "celeste", "name": "Celeste", "appid": 504230, "path": PATH}
    g = cfg_games(hub)["celeste"]
    assert g["devices"] == ["deck"] and g["paths"] == {"deck": PATH} and g["steam_appid"] == 504230
    assert "enabled" not in g  # activo (el valor por defecto no se escribe)
    # queda en `GET /api/games` de esa Deck, y no en el de la otra
    ids = [x["id"] for x in hub.anon.get("/api/games", headers=bearer(hub.key)).json()]
    assert "celeste" in ids
    assert "celeste" not in [x["id"] for x in hub.anon.get("/api/games", headers=bearer(hub.key2)).json()]


def test_create_game_needs_a_device_key(hub):
    for h in ({}, bearer(hub.ukey)):  # sin key o con la de usuario (pocos intentos: los fallos cuentan para el 429)
        r = hub.anon.post("/api/steam/games", json=good(), headers=h)
        assert r.status_code == 401 and code(r) == "err.apikey.invalid"
    assert "celeste" not in cfg_games(hub)


def test_create_game_session_cookie_is_not_enough(hub):
    assert hub.session.post("/api/steam/games", json=good()).status_code == 401
    assert "celeste" not in cfg_games(hub)


def test_create_game_id_is_a_slug_and_never_collides(hub):
    assert create(hub, good(name="G1", appid=9001)).json()["id"] == "g1-9001"  # el id "g1" ya existe (otro nombre)
    assert create(hub, good(name="Ñandú: The Game", appid=9002)).json()["id"] == "nandu-the-game"
    assert create(hub, good(name="日本語", appid=9003)).json()["id"] == "steam-9003"  # nada aprovechable


def test_create_game_rejects_a_taken_name_or_appid_without_leaking_others(hub):
    r = create(hub, good(name="hades"))  # mismo nombre sin importar mayúsculas
    assert r.status_code == 422 and code(r) == "err.steam.game_invalid"
    assert r.json()["detail"]["params"] == {"field": "name", "reason": "err.config.name_duplicate"}
    r = create(hub, good(appid=222))  # lo usa «Other Pid», que ni siquiera es de esta Deck
    assert code(r) == "err.steam.game_invalid"
    assert r.json()["detail"]["params"] == {"field": "appid", "reason": "err.config.steam_appid_duplicate"}
    assert "Other Pid" not in r.text and "Hades" not in r.text


def test_create_game_validates_name_and_path_like_the_config(hub):
    cases = [
        (good(name="A/B"), "name", "err.config.name_slash"),
        (good(path="relativa/ruta"), "path", "err.config.path_absolute"),
        (good(path="/home/deck/a;rm -rf"), "path", "err.config.path_chars"),
        (good(path="/home/deck/../etc"), "path", "err.config.path_dotdot"),
        (good(path="/"), "path", "err.config.path_root"),
    ]
    for body, field, reason in cases:
        r = create(hub, body)
        assert r.status_code == 422, body
        assert r.json()["detail"]["params"] == {"field": field, "reason": reason}, body
    assert set(cfg_games(hub)) == set(cfg_games_before(hub))


def cfg_games_before(hub):
    return ["g1", "hades", "witcher", "dup1", "dup2", "haspid", "usedby", "only2", "off", "portal"]


def test_create_game_body_shape(hub):
    for body in (
        {},
        {"appid": 1, "name": "X"},  # falta la ruta
        {**good(), "extra": 1},
        good(appid=0),
        good(appid=True),
        good(appid="5"),
        good(name=""),
        good(name="x" * 201),
        good(path=""),
        good(path=5),
    ):
        r = create(hub, body)
        assert r.status_code == 422 and code(r) == "err.steam.game_body_invalid", body
    for raw in (b"no json", b"[1]"):
        assert hub.anon.post("/api/steam/games", content=raw, headers=bearer(hub.key)).status_code == 400


def test_create_game_too_large_body(hub):
    r = hub.anon.post(
        "/api/steam/games",
        content=b'{"name": "' + b"x" * 9000 + b'"}',
        headers={**bearer(hub.key), "content-length": "9030"},
    )
    assert r.status_code == 413 and code(r) == "err.steam.body_too_large"


def test_create_game_keeps_the_rest_of_the_config(hub):
    before = cfg_games(hub)
    assert create(hub, good()).status_code == 200
    after = cfg_games(hub)
    assert {k: v for k, v in after.items() if k != "celeste"} == before


def test_create_game_then_library_reports_it_as_unchanged(hub):
    create(hub, good())
    r = hub.anon.post(
        "/api/steam/library", json={"games": [{"appid": 504230, "name": "Celeste"}]}, headers=bearer(hub.key)
    )
    assert r.json()["unchanged"] == 1 and r.json()["associated"] == []


# ---- activar / desactivar ----
def test_toggle_disables_and_enables_a_device_game(hub):
    r = toggle(hub, "hades", False)
    assert r.status_code == 200 and r.json() == {"game": "hades", "enabled": False}
    assert cfg_games(hub)["hades"]["enabled"] is False
    row = next(x for x in hub.anon.get("/api/games", headers=bearer(hub.key)).json() if x["id"] == "hades")
    assert row["enabled"] is False
    r = toggle(hub, "hades", True)
    assert r.json() == {"game": "hades", "enabled": True}
    assert cfg_games(hub)["hades"].get("enabled", True) is True


def test_toggle_is_idempotent_and_touches_nothing_else(hub):
    before = cfg_games(hub)
    assert toggle(hub, "hades", True).status_code == 200  # ya estaba activo
    assert cfg_games(hub) == before
    toggle(hub, "off", False)
    assert cfg_games(hub) == before  # «off» ya estaba desactivado


def test_toggle_only_for_games_of_that_device(hub):
    for game in ("only2", "usedby", "nope"):  # de otra Deck, de otro dispositivo, inexistente: el mismo 404
        r = toggle(hub, game, False)
        assert r.status_code == 404 and code(r) == "err.steam.game_unknown", game
    assert cfg_games(hub)["only2"].get("enabled", True) is True


def test_toggle_needs_a_device_key(hub):
    assert hub.session.put("/api/steam/games/hades/enabled", json={"enabled": False}).status_code == 401
    for h in ({}, bearer(hub.ukey)):
        r = hub.anon.put("/api/steam/games/hades/enabled", json={"enabled": False}, headers=h)
        assert r.status_code == 401
    assert cfg_games(hub)["hades"].get("enabled", True) is True


def test_toggle_body_shape(hub):
    for body in ({}, {"enabled": "no"}, {"enabled": 1}, {"enabled": None}, {"enabled": True, "x": 1}):
        r = toggle(hub, "hades", None, body=body)
        assert r.status_code == 422 and code(r) == "err.steam.game_body_invalid", body


def test_no_secrets_in_logs_of_the_new_endpoints(hub, caplog):
    caplog.set_level(logging.DEBUG)
    create(hub, good())
    toggle(hub, "hades", False)
    create(hub, good(), key=hub.ukey)
    assert hub.key not in caplog.text and hub.ukey not in caplog.text and PATH not in caplog.text


# ---- unirse a un juego existente (mismo nombre normalizado, hueco libre) ----
def join_cfg(hub, **games):
    """Sustituye o añade juegos en la config guardada (misma vía que `PUT /api/config`: `ConfigStore.save`)."""
    from app.config.models import validate_config

    snap = hub.ctx.store.snapshot()
    data = snap.cfg.model_dump(exclude_none=True)
    data["games"].update(games)
    cfg, errors = validate_config(data)
    assert not errors, errors
    hub.ctx.store.save(snap.version, cfg)


def test_create_joins_an_existing_game_with_a_free_slot(hub):
    # «Mi Juego» tiene deck+pc; usamos «Only Other» (solo deck2) desde la clave de «deck»
    r = create(hub, {"appid": 777, "name": "only  OTHER™", "path": "/home/deck/only"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    b = r.json()
    assert b["joined"] is True and b["id"] == "only2" and b["name"] == "Only Other" and b["appid"] == 777
    assert b["devices"] == ["deck2", "deck"] and b["path"] == "/home/deck/only" and b["enabled"] is True
    g = cfg_games(hub)
    assert g["only2"]["devices"] == ["deck2", "deck"]
    assert g["only2"]["paths"] == {"deck2": "/f", "deck": "/home/deck/only"} and g["only2"]["steam_appid"] == 777
    assert set(g) == set(cfg_games_before(hub))  # no se creó ningún juego


def test_join_keeps_the_game_appid_when_it_already_has_the_same(hub):
    join_cfg(hub, only2={"name": "Only Other", "devices": ["deck2"], "paths": {"deck2": "/f"}, "steam_appid": 777})
    r = create(hub, {"appid": 777, "name": "Only Other", "path": "/home/deck/only"})
    assert r.status_code == 200 and r.json()["joined"] is True
    assert cfg_games(hub)["only2"]["steam_appid"] == 777


def test_join_a_disabled_game_joins_but_does_not_enable_it(hub):
    join_cfg(hub, only2={"name": "Only Other", "devices": ["deck2"], "paths": {"deck2": "/f"}, "enabled": False})
    r = create(hub, {"appid": 777, "name": "Only Other", "path": "/home/deck/only"})
    assert r.status_code == 200 and r.json()["joined"] is True and r.json()["enabled"] is False
    assert cfg_games(hub)["only2"]["enabled"] is False


def test_join_second_attempt_is_idempotent(hub):
    body = {"appid": 777, "name": "Only Other", "path": "/home/deck/only"}
    assert create(hub, body).json()["joined"] is True
    before = cfg_games(hub)
    r = create(hub, {**body, "path": "/home/deck/otra"})  # la ruta guardada no se cambia
    assert r.status_code == 200 and r.json()["joined"] is False and r.json()["id"] == "only2"
    assert r.json()["path"] == "/home/deck/only" and r.json()["devices"] == ["deck2", "deck"]
    assert cfg_games(hub) == before


def test_join_refuses_without_a_free_slot(hub):
    r = create(hub, {"appid": 777, "name": "mi juego", "path": "/x/y"}, key=hub.key2)  # deck+pc: lleno
    assert r.status_code == 422 and code(r) == "err.steam.game_invalid"
    assert r.json()["detail"]["params"] == {"field": "name", "reason": "err.steam.no_free_slot"}
    assert cfg_games(hub)["g1"]["devices"] == ["deck", "pc"] and "Mi Juego" not in r.text


def test_join_refuses_a_different_appid(hub):
    r = create(hub, {"appid": 333, "name": "Has Appid", "path": "/x/y"}, key=hub.key2)  # el juego tiene 111
    assert r.status_code == 422
    assert r.json()["detail"]["params"] == {"field": "name", "reason": "err.steam.appid_mismatch"}
    assert cfg_games(hub)["haspid"]["devices"] == ["deck"]


def test_join_refuses_an_appid_used_by_another_game(hub):
    r = create(hub, {"appid": 222, "name": "Only Other", "path": "/x/y"})  # 222 es de «Other Pid»
    assert r.status_code == 422
    assert r.json()["detail"]["params"] == {"field": "name", "reason": "err.steam.appid_in_use"}
    assert "Other Pid" not in r.text and cfg_games(hub)["only2"]["devices"] == ["deck2"]


def test_join_device_already_in_the_game_with_other_appid_keeps_name_duplicate(hub):
    r = create(hub, good(name="hades"))
    assert r.status_code == 422
    assert r.json()["detail"]["params"] == {"field": "name", "reason": "err.config.name_duplicate"}


def test_join_ambiguous_name_is_not_joined(hub):
    r = create(hub, {"appid": 777, "name": "dup game", "path": "/x/y"}, key=hub.key2)  # dup1 y dup2 coinciden
    assert r.status_code == 422
    assert r.json()["detail"]["params"] == {"field": "name", "reason": "err.config.name_duplicate"}


def test_join_validates_the_path_like_a_creation(hub):
    for bad, reason in (("relativa", "err.config.path_absolute"), ("/a/../b", "err.config.path_dotdot")):
        r = create(hub, {"appid": 777, "name": "Only Other", "path": bad})
        assert r.status_code == 422
        assert r.json()["detail"]["params"] == {"field": "path", "reason": reason}
    assert cfg_games(hub)["only2"]["devices"] == ["deck2"]


def test_join_adds_only_the_device_of_the_key_and_touches_nothing_else(hub):
    before = cfg_games(hub)
    assert create(hub, {"appid": 777, "name": "Only Other", "path": "/p/q"}, key=hub.key).status_code == 200
    after = cfg_games(hub)
    assert {k: v for k, v in after.items() if k != "only2"} == {k: v for k, v in before.items() if k != "only2"}
    assert after["only2"]["paths"]["deck2"] == "/f"


def test_join_needs_a_device_key(hub):
    r = hub.anon.post("/api/steam/games", json=good(name="Only Other"), headers=bearer(hub.ukey))
    assert r.status_code == 401 and cfg_games(hub)["only2"]["devices"] == ["deck2"]


def test_join_retries_on_a_config_race(hub, monkeypatch):
    from app.config.store import Conflict, ConfigStore

    real, calls = ConfigStore.save, []

    def flaky(self, version, cfg):
        calls.append(1)
        if len(calls) == 1:
            raise Conflict("v")
        return real(self, version, cfg)

    monkeypatch.setattr(ConfigStore, "save", flaky)
    r = create(hub, {"appid": 777, "name": "Only Other", "path": "/p/q"})
    assert r.status_code == 200 and r.json()["joined"] is True and len(calls) == 2


def test_put_config_is_not_affected_by_the_join_rules(hub):
    from app.config.models import validate_config

    data = hub.ctx.store.snapshot().cfg.model_dump(exclude_none=True)
    data["games"]["twin"] = {"name": "only other", "devices": ["deck"], "paths": {"deck": "/z"}}
    _, errors = validate_config(data)
    assert (
        errors["games.twin.name"]["code"] == "err.config.name_duplicate"
    )  # la config sigue rechazando el nombre repetido
