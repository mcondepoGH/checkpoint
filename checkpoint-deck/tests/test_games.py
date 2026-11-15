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
    p.mkdir(parents=True)
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
        (home / "s").mkdir(exist_ok=True)
        return tools(hub.url, home).create(1, "X", str(home / "s"))

    out = run(422, {"detail": {"code": "err.steam.game_invalid", "params": {"field": "name", "reason": "err.config.name_duplicate"}}})
    assert out["error"] == "game_invalid" and out["error_params"] == {"field": "name", "reason": "err.config.name_duplicate"}
    assert run(401, {"detail": {"code": "err.apikey.invalid", "params": {}}})["error"] == "unauthorized"
    assert run(429, {"detail": {"code": "x", "params": {}}}, {"Retry-After": "90"})["error_params"] == {"wait_s": 90}
    assert run(409, {"detail": {"code": "err.main.config_changed", "params": {}}})["error"] == "config_changed"
    out = run(500, {"detail": {"code": "boom", "params": {}}})
    assert out["error"] == "hub_error" and "500" in out["error_detail"]
    assert tools("http://127.0.0.1:1", home).create(1, "X", str(home / "s"))["error"] == "connection"


def test_create_always_requires_an_existing_directory_and_does_not_call_the_hub(scripthub, home):
    hub = scripthub(lambda r: (200, {"id": "x"}, {}))
    (home / "f").write_text("fichero")
    for p in (home / "no_existe", home / "f"):
        out = tools(hub.url, home).create(1, "X", str(p))
        assert out == {"ok": False, "error": "path_missing", "error_params": {}, "error_detail": None}
    assert hub.requests == [] and not (home / "no_existe").exists()


def test_create_returns_the_join_flags_and_maps_the_join_refusals(scripthub, home):
    body = {"id": "only", "name": "Only", "appid": 7, "path": "/p", "joined": True, "devices": ["a", "b"], "enabled": False}
    (home / "s").mkdir()
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


def _dq7_saves(pfx: Path) -> Path:
    """Guardado sintético con la forma del de Dragon Quest VII (usuario `deck`, steamid ficticio)."""
    saved = pfx / "drive_c/users/deck/Documents/My Games/DRAGON QUEST VII/Steam/76561197960271999/release/Saved"
    (saved / "SaveGames").mkdir(parents=True)
    (saved / "SaveGames" / "slot1.sav").write_bytes(b"x")
    (saved / "Config").mkdir()
    (saved / "Config" / "a.ini").write_text("x")
    return saved / "SaveGames"


def test_suggest_shortcut_for_a_lutris_shortcut_gives_candidates_not_the_whole_prefix(home):
    pfx = _lutris_deck(home, [EMU_SC, LUTRIS_SC])
    saves = _dq7_saves(pfx)
    out = cg.suggest_shortcut(home, 2389644016)
    assert out["path"] == str(saves) and out["candidates"] == [str(saves)] and out["source"] == "lutris"
    assert str(pfx) not in out["candidates"] and out["path"] != str(pfx)
    assert out["browse_start"] == str(pfx / "drive_c/users")


def test_suggest_shortcut_without_candidates_leaves_path_empty_and_browses_users(home):
    pfx = _lutris_deck(home, [LUTRIS_SC])
    (pfx / "drive_c/users/deck/Documents").mkdir(parents=True)
    out = cg.suggest_shortcut(home, 2389644016)
    assert out == {"path": "", "candidates": [], "source": "lutris", "browse_start": str(pfx / "drive_c/users")}


def test_suggest_shortcut_without_drive_c_browses_the_prefix(home):
    pfx = _lutris_deck(home, [LUTRIS_SC])
    out = cg.suggest_shortcut(home, 2389644016)
    assert out["path"] == "" and out["candidates"] == [] and out["browse_start"] == str(pfx)


def test_suggest_shortcut_uses_the_shortcut_name_to_order(home):
    pfx = _lutris_deck(home, [LUTRIS_SC])
    docs = pfx / "drive_c/users/deck/Documents"
    for n in ("Otro", "Fantasma Quest"):
        (docs / n).mkdir(parents=True)
        (docs / n / "f.dat").write_text("x")
    import os

    os.utime(docs / "Otro" / "f.dat", (9_999_999_999, 9_999_999_999))  # el más reciente, pero no coincide
    out = cg.suggest_shortcut(home, 2389644016, name="Fantasma Quest")
    assert out["candidates"][0] == str(docs / "Fantasma Quest")


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
    _dq7_saves(bad)
    import sqlite3

    data = home / ".var/app/net.lutris.Lutris/data/lutris"
    (data / "games" / "dq7-1.yml").write_text(f"game:\n  prefix: {bad}\n")
    con = sqlite3.connect(data / "pga.db")
    con.execute("UPDATE games SET directory = ?", (str(bad),))
    con.commit()
    con.close()
    out = cg.suggest_shortcut(home, 2389644016)
    assert out["path"] == "" and out["candidates"] == []  # el hub rechaza «&»: no se ofrece


# ---- sugerencias: solo lo que existe, se lee y pasa la validación (Steam)
def _cloud(home: Path, appid: int = 9) -> Path:
    d = steam(home) / "userdata/123456" / str(appid) / "remote"
    d.mkdir(parents=True)
    return d


def test_steam_suggestion_requires_a_folder_not_a_file(home):
    acf(steam(home), 9, "Juego", "Juego")
    f = prefix(home, 9) / "AppData/Local/Juego"
    f.parent.mkdir(parents=True)
    f.write_text("no soy una carpeta")
    assert cg.suggest_path(home, 9, "Juego")["candidates"] == []


@pytest.mark.skipif(__import__("os").geteuid() == 0, reason="root ignora los permisos")
def test_steam_suggestion_skips_an_unreadable_folder(home):
    acf(steam(home), 9, "Juego", "Juego")
    d = _cloud(home)
    d.chmod(0)
    try:
        out = cg.suggest_path(home, 9, "Juego")
        assert out["path"] == "" and out["candidates"] == [] and out["source"] == ""
    finally:
        d.chmod(0o755)


def test_steam_suggestion_skips_an_unreadable_folder_simulated(home, monkeypatch):
    import os

    acf(steam(home), 9, "Juego", "Juego")
    d = _cloud(home)
    real = os.scandir

    def deny(p="."):
        if str(p) == str(d):
            raise PermissionError("denegado")
        return real(p)

    monkeypatch.setattr(os, "scandir", deny)
    assert cg.suggest_path(home, 9, "Juego")["candidates"] == []


def test_steam_suggestion_skips_a_symlink_that_points_outside_home(home, tmp_path):
    acf(steam(home), 9, "Juego", "Juego")
    outside = tmp_path / "fuera"
    outside.mkdir()
    remote = steam(home) / "userdata/123456/9/remote"
    remote.parent.mkdir(parents=True)
    remote.symlink_to(outside)
    out = cg.suggest_path(home, 9, "Juego")
    assert out["path"] == "" and out["candidates"] == [] and str(outside) not in str(out)


def test_steam_suggestion_skips_a_protected_folder(home):
    acf(steam(home), 9, "Juego", "Juego")
    d = _cloud(home)
    assert cg.suggest_path(home, 9, "Juego", [d])["candidates"] == []
    assert cg.suggest_path(home, 9, "Juego", [])["candidates"] == [str(d)]


def test_steam_suggestion_writes_nothing(home):
    acf(steam(home), 9, "Juego", "Juego")
    before = sorted(str(p) for p in home.rglob("*"))
    cg.suggest_path(home, 9, "Juego")
    assert sorted(str(p) for p in home.rglob("*")) == before


# ---- «Examinar…» de Steam: lo más cerca de la ruta natural que exista
def test_steam_without_candidates_browses_from_the_deepest_existing_ancestor_of_the_proton_path(home):
    acf(steam(home), 9, "Juego", "Juego")
    pfx = prefix(home, 9)
    (pfx / "AppData/Roaming").mkdir(parents=True)  # la carpeta del juego aún no existe
    out = cg.suggest_path(home, 9, "Juego")
    assert out == {"path": "", "candidates": [], "source": "", "browse_start": str(pfx / "AppData/Roaming")}


def test_steam_browse_start_stops_at_compatdata_when_the_prefix_is_missing(home):
    acf(steam(home), 9, "Juego", "Juego")
    (steam(home) / "steamapps/compatdata/9").mkdir(parents=True)  # compatdata sin pfx
    out = cg.suggest_path(home, 9, "Juego")
    assert out["path"] == "" and out["browse_start"] == str(steam(home) / "steamapps/compatdata/9")


def test_steam_browse_start_follows_the_cloud_path_for_a_native_game(home):
    acf(steam(home), 9, "Juego", "Juego")
    user_app = steam(home) / "userdata/123456/9"
    user_app.mkdir(parents=True)  # `remote` aún sin crear
    out = cg.suggest_path(home, 9, "Juego")
    assert out["path"] == "" and out["browse_start"] == str(user_app)


def test_steam_has_no_browse_start_when_there_is_a_candidate_or_nothing_natural(home):
    acf(steam(home), 5, "Nativo", "Nativo")
    acf(steam(home), 9, "Juego", "Juego")
    assert cg.suggest_path(home, 5, "Nativo") == {"path": "", "candidates": [], "source": ""}  # ni compatdata ni userdata
    _cloud(home)
    assert "browse_start" not in cg.suggest_path(home, 9, "Juego")


# ---- sugerencias de Lutris: lo mismo
def _lutris_with_saves(home):
    pfx = _lutris_deck(home, [LUTRIS_SC])
    return pfx, _dq7_saves(pfx)


def test_lutris_suggestion_skips_a_candidate_that_is_a_file(home):
    pfx = _lutris_deck(home, [LUTRIS_SC])
    docs = pfx / "drive_c/users/deck/Documents/My Games"
    docs.mkdir(parents=True)
    (docs / "Juego").write_text("fichero")
    assert cg.suggest_shortcut(home, 2389644016)["candidates"] == []


def test_lutris_suggestion_skips_a_missing_candidate_but_keeps_the_others(home, monkeypatch):
    import shutil

    import checkpoint_lutris as lu

    pfx = _lutris_deck(home, [LUTRIS_SC])
    docs = pfx / "drive_c/users/deck/Documents"
    for n in ("Uno", "Dos"):
        (docs / n).mkdir(parents=True)
        (docs / n / "f.dat").write_text("x")
    real = lu.find_saves

    def vanish(*a, **k):  # entre el recorrido y la sugerencia desaparece una carpeta
        out = real(*a, **k)
        shutil.rmtree(docs / "Uno")
        return out

    monkeypatch.setattr(lu, "find_saves", vanish)
    out = cg.suggest_shortcut(home, 2389644016)
    assert out["candidates"] == [str(docs / "Dos")] and out["path"] == str(docs / "Dos")


def test_lutris_suggestion_drops_everything_if_the_only_candidate_vanishes(home, monkeypatch):
    import shutil

    import checkpoint_lutris as lu

    _pfx, saves = _lutris_with_saves(home)
    real = lu.find_saves

    def vanish(*a, **k):
        out = real(*a, **k)
        shutil.rmtree(saves)
        return out

    monkeypatch.setattr(lu, "find_saves", vanish)
    out = cg.suggest_shortcut(home, 2389644016)
    assert out["path"] == "" and out["candidates"] == [] and out["source"] == "lutris"


@pytest.mark.skipif(__import__("os").geteuid() == 0, reason="root ignora los permisos")
def test_lutris_suggestion_skips_an_unreadable_candidate(home):
    _pfx, saves = _lutris_with_saves(home)
    saves.chmod(0)
    try:
        assert cg.suggest_shortcut(home, 2389644016)["candidates"] == []
    finally:
        saves.chmod(0o755)


def test_lutris_suggestion_skips_an_unreadable_candidate_simulated(home, monkeypatch):
    import os

    _pfx, saves = _lutris_with_saves(home)
    real = os.access
    monkeypatch.setattr(os, "access", lambda p, m, **k: False if str(p) == str(saves) else real(p, m, **k))
    assert cg.suggest_shortcut(home, 2389644016)["candidates"] == []


def test_lutris_suggestion_skips_a_candidate_symlinked_outside_home(home, tmp_path):
    pfx = _lutris_deck(home, [LUTRIS_SC])
    outside = tmp_path / "fuera"
    (outside / "saves").mkdir(parents=True)
    (outside / "saves" / "a.sav").write_text("x")
    docs = pfx / "drive_c/users/deck/Documents"
    docs.mkdir(parents=True)
    (docs / "Juego").symlink_to(outside / "saves")
    assert cg.suggest_shortcut(home, 2389644016)["candidates"] == []


def test_lutris_suggestion_skips_a_candidate_the_hub_would_reject_and_writes_nothing(home):
    pfx = _lutris_deck(home, [LUTRIS_SC])
    d = pfx / "drive_c/users/deck/Documents/Raro; juego"
    d.mkdir(parents=True)
    (d / "a.sav").write_text("x")
    before = sorted(str(p) for p in home.rglob("*"))
    assert cg.suggest_shortcut(home, 2389644016)["candidates"] == []
    assert sorted(str(p) for p in home.rglob("*")) == before


def test_lutris_browse_start_vanishing_is_dropped(home, monkeypatch):
    import shutil

    import checkpoint_lutris as lu

    pfx = _lutris_deck(home, [LUTRIS_SC])
    (pfx / "drive_c/users/deck/Documents").mkdir(parents=True)
    real = lu.find_saves

    def vanish(*a, **k):
        out = real(*a, **k)
        shutil.rmtree(pfx / "drive_c")
        return out

    monkeypatch.setattr(lu, "find_saves", vanish)
    out = cg.suggest_shortcut(home, 2389644016)
    assert out["browse_start"] == str(pfx)  # el ancestro que sí existe
