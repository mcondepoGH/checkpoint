"""Appid de Steam por dispositivo (`steam_appids`): modelo, validación, unicidad por dispositivo, `GET /api/games` con
key de dispositivo y de usuario, y round-trip por `PUT /api/config`."""

import copy

import yaml

from app.config.models import Config, parse_config, validate_config
from app.config.store import parse_text
from test_steam import bearer, cfg_games, hub  # noqa: F401  (hub es una fixture)

DEV = {"name": "PC", "host": "h", "user": "u", "os": "linux"}
DECK = {"name": "Deck", "http": True, "os": "linux"}


def cfg_with(**games):
    """Dos dispositivos (`pc`, `deck`); cada juego, por defecto, solo en `pc`."""
    return {
        "devices": {"pc": DEV, "deck": DECK},
        "games": {
            gid: {"name": gid.upper(), "devices": ["pc"], "paths": {"pc": "/p/" + gid}, **g} for gid, g in games.items()
        },
    }


def both(**kw):
    return {"devices": ["pc", "deck"], "paths": {"pc": "/p", "deck": "/d"}, **kw}


# ---- modelo ----
def test_default_is_none_and_valid_map_is_kept():
    c = parse_config(cfg_with(a={}, b=both(steam_appids={"pc": 11, "deck": 3_000_000_001})))
    assert c.games["a"].steam_appids is None
    assert c.games["b"].steam_appids == {"pc": 11, "deck": 3_000_000_001}


def test_effective_appid_prefers_the_device_entry_over_the_general():
    g = parse_config(cfg_with(a=both(steam_appid=5, steam_appids={"deck": 9}))).games["a"]
    assert g.effective_appid("deck") == 9 and g.effective_appid("pc") == 5
    assert parse_config(cfg_with(a={})).games["a"].effective_appid("pc") is None


def test_empty_or_absent_map_is_not_written_and_a_full_one_is():
    c = parse_config(cfg_with(a={}, b={"steam_appids": {}}, c=both(steam_appids={"deck": 9})))
    d = c.model_dump(exclude_none=True)["games"]
    assert "steam_appids" not in d["a"] and "steam_appids" not in d["b"] and d["c"]["steam_appids"] == {"deck": 9}


def test_invalid_values_are_rejected():
    for bad in (0, -1, "5", 1.5, True, None):
        c, errs = validate_config(cfg_with(a={"steam_appids": {"pc": bad}}))
        assert c is None
        assert errs["games.a.steam_appids"] == {"code": "err.config.steam_appid_invalid", "params": {}}


def test_keys_must_be_config_devices_of_the_game():
    _, errs = validate_config(cfg_with(a={"steam_appids": {"nope": 5}}, b={"steam_appids": {"deck": 6}}))
    assert errs["games.a.steam_appids.nope"] == {
        "code": "err.config.steam_appids_device_unknown",
        "params": {"id": "nope"},
    }
    assert errs["games.b.steam_appids.deck"] == {
        "code": "err.config.steam_appids_device_not_in_game",
        "params": {"id": "deck"},
    }


def test_yaml_round_trip(tmp_path):
    text = yaml.safe_dump(cfg_with(a=both(steam_appid=1, steam_appids={"deck": 9}), b={}))
    c, err = parse_text(text)
    assert err is None and isinstance(c, Config)
    again, err2 = parse_text(yaml.safe_dump(c.model_dump(exclude_none=True)))
    assert err2 is None and again.games["a"].steam_appids == {"deck": 9} and again.games["b"].steam_appids is None


# ---- unicidad por dispositivo ----
def test_same_appid_on_different_devices_is_fine_for_different_games():
    c, errs = validate_config(
        cfg_with(
            a={"devices": ["pc"], "paths": {"pc": "/a"}, "steam_appids": {"pc": 7}},
            b={"devices": ["deck"], "paths": {"deck": "/b"}, "steam_appids": {"deck": 7}},
        )
    )
    assert errs == {} and isinstance(c, Config)


def test_same_game_may_have_different_appids_per_device_and_even_the_general_of_other_game_in_another_device():
    data = cfg_with(
        a=both(steam_appid=1, steam_appids={"deck": 2}),
        b={"devices": ["deck"], "paths": {"deck": "/b"}, "steam_appid": 3},
    )
    assert validate_config(data)[1] == {}


def test_effective_appid_must_be_unique_in_a_device():
    # `b` usa en `pc` el appid que `a` tiene por dispositivo
    a = {"steam_appids": {"pc": 7}}
    b = {"steam_appids": {"pc": 7}}
    _, errs = validate_config(cfg_with(a=a, b=b))
    assert errs == {"games.b.steam_appids.pc": {"code": "err.config.steam_appid_duplicate", "params": {"other": "A"}}}


def test_per_device_entry_colliding_with_a_general_appid_of_another_game_in_that_device():
    _, errs = validate_config(cfg_with(a={"steam_appid": 7}, b={"steam_appids": {"pc": 7}}))
    assert errs["games.b.steam_appids.pc"]["code"] == "err.config.steam_appid_duplicate"
    # y al revés: el general llega después del de dispositivo
    _, errs = validate_config(cfg_with(a={"steam_appids": {"pc": 7}}, b={"steam_appid": 7}))
    assert errs["games.b.steam_appid"] == {"code": "err.config.steam_appid_duplicate", "params": {"other": "A"}}


def test_general_duplicate_between_games_keeps_its_single_error():
    _, errs = validate_config(cfg_with(a={"steam_appid": 440}, b={"steam_appid": 440}))
    assert errs == {"games.b.steam_appid": {"code": "err.config.steam_appid_duplicate", "params": {"other": "A"}}}


def test_a_device_entry_that_overrides_the_general_frees_the_shared_appid_in_that_device():
    # `a` y `b` en `pc` con el mismo general es duplicado, pero si `b` lo cambia en `pc` ya no choca en `pc`
    # (el general sigue siendo único entre juegos, así que se prueba con generales distintos)
    data = cfg_with(a={"steam_appid": 1}, b={"steam_appid": 2, "steam_appids": {"pc": 1}})
    _, errs = validate_config(data)
    assert list(errs) == ["games.b.steam_appids.pc"]  # `a` sigue teniendo 1 efectivo en `pc`


# ---- GET /api/games ----
def put_map(hub, gid, mapping, general=None):
    snap = hub.ctx.store.snapshot()
    data = snap.cfg.model_dump(exclude_none=True)
    data["games"][gid]["steam_appids"] = mapping
    if general is not None:
        data["games"][gid]["steam_appid"] = general
    cfg, errors = validate_config(data)
    assert not errors, errors
    hub.ctx.store.save(snap.version, cfg)


def games(hub, key):
    return {g["id"]: g for g in hub.anon.get("/api/games", headers=bearer(key)).json()}


def test_games_with_a_device_key_resolve_the_effective_appid_without_leaking_the_map(hub):
    put_map(hub, "g1", {"deck": 2389644016, "pc": 3928137182}, general=555)
    d = games(hub, hub.key)
    assert d["g1"]["steam_appid"] == 2389644016 and "steam_appids" not in d["g1"]
    assert "3928137182" not in str(d)  # el appid de otro dispositivo no sale
    assert d["hades"]["steam_appid"] is None  # sin mapa ni general
    assert d["haspid"]["steam_appid"] == 111  # solo general


def test_games_with_a_device_key_fall_back_to_the_general_when_the_device_has_no_entry(hub):
    put_map(hub, "g1", {"pc": 3928137182}, general=555)
    assert games(hub, hub.key)["g1"]["steam_appid"] == 555


def test_games_with_a_user_key_have_the_general_and_the_map(hub):
    put_map(hub, "g1", {"deck": 2389644016, "pc": 3928137182}, general=555)
    d = games(hub, hub.ukey)
    assert d["g1"]["steam_appid"] == 555 and d["g1"]["steam_appids"] == {"deck": 2389644016, "pc": 3928137182}
    assert "steam_appids" not in d["hades"] and "path" not in d["g1"]


# ---- PUT /api/config conserva el campo ----
def test_put_config_keeps_steam_appids_round_trip(hub):
    got = hub.session.get("/api/config").json()
    cfg = copy.deepcopy(got["config"])
    cfg["games"]["g1"]["steam_appid"] = 555
    cfg["games"]["g1"]["steam_appids"] = {"deck": 2389644016, "pc": 3928137182}
    r = hub.session.put("/api/config", json={"base_version": got["version"], "config": cfg})
    assert r.status_code == 200, r.text
    assert r.json()["config"]["games"]["g1"]["steam_appids"] == {"deck": 2389644016, "pc": 3928137182}
    assert cfg_games(hub)["g1"]["steam_appids"] == {"deck": 2389644016, "pc": 3928137182}
    # el siguiente guardado, con lo que devuelve GET, no lo pierde
    again = hub.session.get("/api/config").json()
    r = hub.session.put("/api/config", json={"base_version": again["version"], "config": again["config"]})
    assert r.status_code == 200 and cfg_games(hub)["g1"]["steam_appids"] == {"deck": 2389644016, "pc": 3928137182}


def test_put_config_rejects_a_bad_device_key(hub):
    got = hub.session.get("/api/config").json()
    cfg = copy.deepcopy(got["config"])
    cfg["games"]["hades"]["steam_appids"] = {"pc": 5}  # `pc` no está en los dispositivos de Hades
    r = hub.session.put("/api/config", json={"base_version": got["version"], "config": cfg})
    assert r.status_code == 422
    assert r.json()["errors"]["games.hades.steam_appids.pc"]["code"] == "err.config.steam_appids_device_not_in_game"
