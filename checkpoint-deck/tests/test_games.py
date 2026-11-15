"""Configurar juegos desde el plugin: ruta sugerida, crear un juego en el hub y activar o desactivar uno."""

import json
from pathlib import Path

import pytest

import checkpoint_client as hc
import checkpoint_games as cg

KEY = "ckd_" + "k" * 40


def acf(root: Path, appid: int, name: str, installdir: str, lib: str = "") -> None:
    d = root / lib / "steamapps" if lib else root / "steamapps"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"appmanifest_{appid}.acf").write_text(
        f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"installdir"\t\t"{installdir}"\n}}\n'
    )


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    (h / ".local/share/Steam").mkdir(parents=True)
    return h


def steam(home: Path) -> Path:
    return home / ".local/share/Steam"


def prefix(home: Path, appid: int) -> Path:
    return steam(home) / "steamapps/compatdata" / str(appid) / "pfx/drive_c/users/steamuser"


# ---- find_game / suggest_path
def test_find_game_reads_installdir_from_its_manifest(home):
    acf(steam(home), 504230, "Celeste", "Celeste")
    g = cg.find_game(home, 504230)
    assert g and g["installdir"] == "Celeste" and g["steamapps"] == steam(home) / "steamapps"
    assert cg.find_game(home, 1) is None


def test_suggest_prefers_the_proton_save_folder_that_exists(home):
    acf(steam(home), 504230, "Celeste", "Celeste")
    (prefix(home, 504230) / "AppData/Local/Celeste").mkdir(parents=True)
    (prefix(home, 504230) / "AppData/Roaming/OtroJuego").mkdir(parents=True)  # no es de este juego
    out = cg.suggest_path(home, 504230, "Celeste")
    assert out["path"] == str(prefix(home, 504230) / "AppData/Local/Celeste")
    assert out["candidates"] == [out["path"]] and out["source"] == "proton"


def test_suggest_uses_the_installdir_name_and_strips_trademarks(home):
    acf(steam(home), 7, "Hollow Knight™", "Hollow Knight")
    (prefix(home, 7) / "AppData/LocalLow/Team Cherry").mkdir(parents=True)
    (prefix(home, 7) / "AppData/Roaming/Hollow Knight").mkdir(parents=True)
    out = cg.suggest_path(home, 7, "Hollow Knight™")
    assert out["candidates"] == [str(prefix(home, 7) / "AppData/Roaming/Hollow Knight")]


def test_suggest_adds_steam_cloud_folder_after_proton(home):
    acf(steam(home), 9, "Juego", "Juego")
    (prefix(home, 9) / "Documents/My Games/Juego").mkdir(parents=True)
    (steam(home) / "userdata/123456/9/remote").mkdir(parents=True)
    out = cg.suggest_path(home, 9, "Juego")
    assert out["candidates"] == [
        str(prefix(home, 9) / "Documents/My Games/Juego"),
        str(steam(home) / "userdata/123456/9/remote"),
    ]
    assert out["source"] == "proton"


def test_suggest_cloud_only(home):
    acf(steam(home), 9, "Juego", "Juego")
    (steam(home) / "userdata/123456/9/remote").mkdir(parents=True)
    out = cg.suggest_path(home, 9, "Juego")
    assert out["path"] == str(steam(home) / "userdata/123456/9/remote") and out["source"] == "cloud"


def test_suggest_nothing_found_leaves_the_path_empty(home):
    acf(steam(home), 5, "Nativo", "Nativo")
    assert cg.suggest_path(home, 5, "Nativo") == {"path": "", "candidates": [], "source": ""}
    assert cg.suggest_path(home, 77, "No instalado") == {"path": "", "candidates": [], "source": ""}


def test_suggest_skips_paths_the_hub_would_reject(home):
    acf(steam(home), 5, "Juego; raro", "Juego; raro")
    (prefix(home, 5) / "AppData/Local/Juego; raro").mkdir(parents=True)  # `;` no vale en rutas del hub
    assert cg.suggest_path(home, 5, "Juego; raro")["candidates"] == []


def test_suggest_in_a_library_on_the_sd_card(home, tmp_path):
    card = tmp_path / "card"
    acf(card, 11, "En SD", "En SD")
    (steam(home) / "steamapps").mkdir(parents=True)
    (steam(home) / "steamapps/libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{steam(home)}"\n\t}}\n\t"1"\n\t{{\n\t\t"path"\t\t"{card}"\n\t}}\n}}\n'
    )
    pfx = card / "steamapps/compatdata/11/pfx/drive_c/users/steamuser/AppData/Roaming/En SD"
    pfx.mkdir(parents=True)
    assert cg.suggest_path(home, 11, "En SD")["path"] == str(pfx)


# ---- herramientas de Steam que no son juegos
def test_steam_tools_are_not_games():
    for n in ("Proton 9.0 (Beta)", "Proton Experimental", "Steam Linux Runtime 3.0 (sniper)", "Steamworks Common Redistributables"):
        assert cg.is_tool(n), n
    for n in ("Celeste", "Protonmail Simulator", "Half-Life 2"):
        assert not cg.is_tool(n), n


# ---- cliente del hub
def test_client_create_game_and_set_enabled(scripthub):
    def h(req):
        if req.path == "/api/steam/games":
            return 200, {"id": "celeste", "name": "Celeste", "appid": 504230, "path": "/p"}, {}
        return 200, {"game": "celeste", "enabled": False}, {}

    hub = scripthub(h)
    c = hc.HubClient(hub.url, KEY)
    assert c.create_game(504230, "Celeste", "/p")["id"] == "celeste"
    assert c.set_game_enabled("celeste", False) == {"game": "celeste", "enabled": False}
    a, b = hub.requests
    assert (a.method, a.path, json.loads(a.body)) == ("POST", "/api/steam/games", {"appid": 504230, "name": "Celeste", "path": "/p"})
    assert (b.method, b.path, json.loads(b.body)) == ("PUT", "/api/steam/games/celeste/enabled", {"enabled": False})
    assert a.headers["authorization"] == f"Bearer {KEY}" == b.headers["authorization"]


def test_client_set_enabled_quotes_the_game_id(scripthub):
    hub = scripthub(lambda r: (200, {"game": "a b/c", "enabled": True}, {}))
    hc.HubClient(hub.url, KEY).set_game_enabled("a b/c", True)
    assert hub.requests[0].path == "/api/steam/games/a%20b%2Fc/enabled"


def test_client_rejects_a_strange_answer(scripthub):
    hub = scripthub(lambda r: (200, ["no"], {}))
    c = hc.HubClient(hub.url, KEY)
    with pytest.raises(hc.HubApiError):
        c.create_game(1, "X", "/p")
    with pytest.raises(hc.HubApiError):
        c.set_game_enabled("x", True)


# ---- GameTools (lógica de main.py)
def tools(hub_url, home):
    return cg.GameTools(hub_url, KEY, home=home, protected=[])


def test_create_ok(scripthub, home):
    hub = scripthub(lambda r: (200, {"id": "celeste", "name": "Celeste", "appid": 504230, "path": "/home/x/p"}, {}))
    p = home / "saves/Celeste"
    out = tools(hub.url, home).create(504230, "Celeste", str(p))
    assert out == {"ok": True, "game": {"id": "celeste", "name": "Celeste", "appid": 504230, "path": "/home/x/p"}}
    assert json.loads(hub.requests[0].body)["path"] == str(p)


@pytest.mark.parametrize("bad", ["", "relativa", "/", "/etc", "/home/deck/../etc"])
def test_create_refuses_a_path_the_deck_would_not_accept_before_calling_the_hub(scripthub, home, bad):
    hub = scripthub(lambda r: (200, {}, {}))
    out = tools(hub.url, home).create(1, "X", bad)
    assert out["ok"] is False and out["error"] == "path_forbidden" and hub.requests == []


def test_create_maps_hub_errors(scripthub, home):
    def run(status, body, headers=None):
        hub = scripthub(lambda r: (status, body, headers or {}))
        return tools(hub.url, home).create(1, "X", str(home / "s"))

    out = run(422, {"detail": {"code": "err.steam.game_invalid", "params": {"field": "name", "reason": "err.config.name_duplicate"}}})
    assert out["error"] == "game_invalid" and out["error_params"] == {"field": "name", "reason": "err.config.name_duplicate"}
    assert run(401, {"detail": {"code": "err.apikey.invalid", "params": {}}})["error"] == "unauthorized"
    assert run(429, {"detail": {"code": "x", "params": {}}}, {"Retry-After": "90"})["error_params"] == {"wait_s": 90}
    assert run(409, {"detail": {"code": "err.main.config_changed", "params": {}}})["error"] == "config_changed"
    out = run(500, {"detail": {"code": "boom", "params": {}}})
    assert out["error"] == "hub_error" and "500" in out["error_detail"]
    assert tools("http://127.0.0.1:1", home).create(1, "X", str(home / "s"))["error"] == "connection"


def test_create_returns_the_join_flags_and_maps_the_join_refusals(scripthub, home):
    body = {"id": "only", "name": "Only", "appid": 7, "path": "/p", "joined": True, "devices": ["a", "b"], "enabled": False}
    hub = scripthub(lambda r: (200, body, {}))
    assert tools(hub.url, home).create(7, "only", str(home / "s")) == {"ok": True, "game": body}
    for reason in ("err.steam.no_free_slot", "err.steam.appid_mismatch", "err.steam.appid_in_use"):
        hub = scripthub(lambda r, reason=reason: (422, {"detail": {"code": "err.steam.game_invalid", "params": {"field": "name", "reason": reason, "other": "Secreto"}}}, {}))
        out = tools(hub.url, home).create(7, "only", str(home / "s"))
        assert out["error"] == "game_invalid" and out["error_params"] == {"field": "name", "reason": reason}


def test_set_enabled_ok_and_errors(scripthub, home):
    hub = scripthub(lambda r: (200, {"game": "g", "enabled": False}, {}))
    assert tools(hub.url, home).set_enabled("g", False) == {"ok": True, "game": "g", "enabled": False}
    hub = scripthub(lambda r: (404, {"detail": {"code": "err.steam.game_unknown", "params": {}}}, {}))
    assert tools(hub.url, home).set_enabled("g", False)["error"] == "unknown_game"
    assert tools("http://127.0.0.1:1", home).set_enabled("g", True)["error"] == "connection"


# ---- suggest_shortcut (atajos de Lutris)
def _shortcut_vdf(entries):
    import struct

    def s(k, v):
        return b"\x01" + k.encode() + b"\x00" + v.encode() + b"\x00"

    body = b""
    for i, (appid, name, exe, opts) in enumerate(entries):
        e = b"\x02appid\x00" + struct.pack("<I", appid) + s("AppName", name) + s("Exe", exe) + s("LaunchOptions", opts)
        body += b"\x00" + str(i).encode() + b"\x00" + e + b"\x08"
    return b"\x00shortcuts\x00" + body + b"\x08\x08"


def _lutris_deck(home: Path, entries):
    import sqlite3

    (steam(home) / "steamapps").mkdir(parents=True, exist_ok=True)  # así se reconoce la raíz de Steam
    cfg = steam(home) / "userdata/111/config"
    cfg.mkdir(parents=True)
    (cfg / "shortcuts.vdf").write_bytes(_shortcut_vdf(entries))
    pfx = home / "Games" / "dq7"
    pfx.mkdir(parents=True)
    data = home / ".var/app/net.lutris.Lutris/data/lutris"
    (data / "games").mkdir(parents=True)
    con = sqlite3.connect(data / "pga.db")
    con.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT, directory TEXT, configpath TEXT)")
    con.execute("INSERT INTO games VALUES (1, 'DQ7', ?, 'dq7-1')", (str(pfx),))
    con.commit()
    con.close()
    (data / "games" / "dq7-1.yml").write_text(f"game:\n  exe: /x/DQ7R.exe\n  prefix: {pfx}\nname: DQ7\n")
    return pfx


LUTRIS_SC = (2389644016, "DQ7", '"/usr/bin/flatpak"', "run net.lutris.Lutris lutris:rungameid/1")
EMU_SC = (3000000002, "PS2", '"/home/deck/bin/pcsx2-qt.sh"', "")


def test_suggest_shortcut_for_a_lutris_shortcut_gives_its_prefix(home):
    pfx = _lutris_deck(home, [EMU_SC, LUTRIS_SC])
    out = cg.suggest_shortcut(home, 2389644016)
    assert out == {"path": str(pfx), "candidates": [str(pfx)], "source": "lutris"}


def test_suggest_shortcut_for_an_emulator_shortcut_is_empty(home):
    _lutris_deck(home, [EMU_SC, LUTRIS_SC])
    assert cg.suggest_shortcut(home, 3000000002) == {"path": "", "candidates": [], "source": ""}


def test_suggest_shortcut_unknown_appid_or_no_steam_is_empty(home, tmp_path):
    _lutris_deck(home, [LUTRIS_SC])
    empty = {"path": "", "candidates": [], "source": ""}
    assert cg.suggest_shortcut(home, 12345) == empty
    assert cg.suggest_shortcut(tmp_path / "otro", 2389644016) == empty


def test_suggest_shortcut_drops_a_path_the_hub_would_reject(home):
    pfx = _lutris_deck(home, [LUTRIS_SC])
    bad = home / "Games" / "dq7 &x"
    pfx.rename(bad)
    import sqlite3

    data = home / ".var/app/net.lutris.Lutris/data/lutris"
    (data / "games" / "dq7-1.yml").write_text(f"game:\n  prefix: {bad}\n")
    con = sqlite3.connect(data / "pga.db")
    con.execute("UPDATE games SET directory = ?", (str(bad),))
    con.commit()
    con.close()
    assert cg.suggest_shortcut(home, 2389644016)["path"] == ""
