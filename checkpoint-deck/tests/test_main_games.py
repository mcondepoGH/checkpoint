"""`Plugin` (main.py, con `decky` falso) y un hub falso: buscar juegos, lista con interruptores, configurar los que no
están en el hub y desactivar uno (un juego desactivado no sincroniza al abrir ni al cerrar)."""

import asyncio
import json
from pathlib import Path

from test_main_library import KEY, make_plugin, settled

LIBRARY_OK = {"associated": [], "suggested": 0, "unchanged": 1, "ignored": 2}


class State:
    """Hub de juguete con estado: los juegos que ya tiene y lo que se le pide."""

    def __init__(self):
        self.games = [{"id": "hl2", "name": "Half-Life 2", "enabled": True, "steam_appid": 220, "path": "/x/hl2"}]
        self.fail_create = None
        self.join = None  # respuesta del hub al unirse a un juego existente (cuerpo 200)

    def handle(self, req):
        if req.path == "/api/steam/library":
            return 200, LIBRARY_OK, {}
        if req.path == "/api/games":
            return 200, [dict(g) for g in self.games], {}
        if req.path == "/api/steam/games" and req.method == "POST":
            if self.fail_create:
                return self.fail_create
            b = json.loads(req.body)
            if self.join:
                self.games.append({"id": self.join["id"], "name": self.join["name"], "enabled": self.join.get("enabled", True), "steam_appid": b["appid"], "path": b["path"]})
                return 200, self.join, {}
            g = {"id": b["name"].lower().replace(" ", "-"), "name": b["name"], "enabled": True, "steam_appid": b["appid"], "path": b["path"]}
            self.games.append(g)
            return 200, {"id": g["id"], "name": g["name"], "appid": b["appid"], "path": b["path"]}, {}
        if req.path.startswith("/api/steam/games/") and req.path.endswith("/enabled"):
            gid = req.path.split("/")[4]
            for g in self.games:
                if g["id"] == gid:
                    g["enabled"] = json.loads(req.body)["enabled"]
                    return 200, {"game": gid, "enabled": g["enabled"]}, {}
            return 404, {"detail": {"code": "err.steam.game_unknown", "params": {}}}, {}
        return 404, {"detail": {"code": "err.nope", "params": {}}}, {}


def setup(fake_decky, scripthub, tmp_path, monkeypatch):
    st = State()
    hub = scripthub(st.handle)
    return st, hub, make_plugin(fake_decky, hub.url, tmp_path, monkeypatch)


def test_search_lists_hub_games_with_toggle_state_and_the_unconfigured_ones(fake_decky, scripthub, tmp_path, monkeypatch):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)

    async def go():
        await p._main()
        await p.refresh_library()
        s = await settled(p)
        await p._unload()
        return s

    s = asyncio.run(go())
    assert [(g["id"], g["enabled"]) for g in s["games"]] == [("hl2", True)]
    assert sorted(u["appid"] for u in s["unconfigured"]) == [730, 1245620]  # 220 ya está en el hub
    assert all("path" not in g for g in s["games"])


def test_suggest_game_uses_what_is_on_disk(fake_decky, scripthub, tmp_path, monkeypatch):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    save = Path(tmp_path / "card/steamapps/compatdata/730/pfx/drive_c/users/steamuser/AppData/Local/Counter-Strike 2")

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        none = await p.suggest_game(1245620)
        save.mkdir(parents=True)
        found = await p.suggest_game(730)
        unknown = await p.suggest_game(99999)
        await p._unload()
        return none, found, unknown

    none, found, unknown = asyncio.run(go())
    assert none["ok"] and none["path"] == "" and none["name"]  # el nombre sale de lo que encontró Steam
    assert found["ok"] and found["path"] == str(save) and found["name"] == "Counter-Strike 2" and found["candidates"] == [str(save)]
    assert unknown["ok"] is False and unknown["error"] == "unknown_game"  # solo se sugiere para un juego sin configurar


def test_suggest_game_gives_the_home_where_the_folder_picker_starts_when_nothing_is_detected(fake_decky, scripthub, tmp_path, monkeypatch):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        out = await p.suggest_game(1245620)
        await p._unload()
        return out

    out = asyncio.run(go())
    assert out["path"] == "" and out["home"] == str(Path.home())  # el selector abre en el home de la Deck


def test_configure_game_creates_it_and_moves_it_to_the_list(fake_decky, scripthub, tmp_path, monkeypatch, caplog):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    save = tmp_path / "deckhome" / "saves" / "cs2"
    save.mkdir(parents=True)

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        r = await p.configure_game(730, "Counter-Strike 2", str(save))
        s = await p.get_sync_state()
        await p._unload()
        return r, s

    r, s = asyncio.run(go())
    assert r["ok"] and r["game"] == {"id": "counter-strike-2", "name": "Counter-Strike 2", "appid": 730}
    post = next(q for q in hub.requests if q.method == "POST" and q.path == "/api/steam/games")
    assert json.loads(post.body) == {"appid": 730, "name": "Counter-Strike 2", "path": str(save)}
    assert post.headers["authorization"] == f"Bearer {KEY}"
    assert [g["id"] for g in s["games"]] == ["hl2", "counter-strike-2"]
    assert [u["appid"] for u in s["unconfigured"]] == [1245620]
    assert KEY not in caplog.text


def test_configure_game_only_for_an_unconfigured_game_and_reports_hub_errors(fake_decky, scripthub, tmp_path, monkeypatch):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    st.fail_create = (422, {"detail": {"code": "err.steam.game_invalid", "params": {"field": "name", "reason": "err.config.name_duplicate"}}}, {})
    (tmp_path / "deckhome" / "s").mkdir(parents=True)
    ok_path = str(tmp_path / "deckhome" / "s")

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        taken = await p.configure_game(730, "Dup", ok_path)
        stranger = await p.configure_game(555555, "No instalado", ok_path)
        bad = await p.configure_game(730, "X", "/etc")
        s = await p.get_sync_state()
        await p._unload()
        return taken, stranger, bad, s

    taken, stranger, bad, s = asyncio.run(go())
    assert taken["ok"] is False and taken["error"] == "game_invalid" and taken["error_params"]["field"] == "name"
    assert stranger["ok"] is False and stranger["error"] == "unknown_game"
    assert bad["error"] == "path_forbidden"
    assert [g["id"] for g in s["games"]] == ["hl2"] and len(s["unconfigured"]) == 2  # nada cambió


def test_configure_and_toggle_need_a_link_and_a_current_plugin(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:1", tmp_path, monkeypatch, with_key=False)

    async def go():
        await p._main()
        a = await p.configure_game(1, "X", "/p")
        b = await p.set_game_enabled("g", False)
        p._compat = "plugin_outdated"
        c = await p.set_game_enabled("g", False)
        await p._unload()
        return a, b, c

    a, b, c = asyncio.run(go())
    assert a["error"] == "not_linked"
    assert b["error"] == "not_linked" and c["error"] == "plugin_outdated"


def test_disabling_a_game_stops_the_automatic_sync_on_open_and_close(fake_decky, scripthub, tmp_path, monkeypatch):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)

    def syncs():
        return [q.path for q in hub.requests if "/api/hook/" in q.path]

    async def wait_idle():
        for _ in range(100):
            await asyncio.sleep(0.02)

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        off = await p.set_game_enabled("hl2", False)
        s = await p.get_sync_state()
        await p.game_event(220, True)
        await wait_idle()
        await p.game_event(220, False)
        await wait_idle()
        await p._unload()
        return off, s

    off, s = asyncio.run(go())
    assert off == {"ok": True, "game": "hl2", "enabled": False}
    assert (s["games"][0]["enabled"], s["games"][0]["state"]) == (False, "disabled")
    assert st.games[0]["enabled"] is False and syncs() == []  # ni fingerprint, ni commit, ni aviso de cierre


def test_enabling_it_again_syncs_on_open(fake_decky, scripthub, tmp_path, monkeypatch):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    st.games[0]["enabled"] = False

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        on = await p.set_game_enabled("hl2", True)
        s = await p.get_sync_state()
        await p.game_event(220, True)
        for _ in range(100):
            await asyncio.sleep(0.02)
        await p._unload()
        return on, s

    on, s = asyncio.run(go())
    assert on["enabled"] is True and s["games"][0]["enabled"] is True
    assert any("/api/hook/hl2/fingerprint" in q.path for q in hub.requests)  # vuelve a intentar sincronizar


def test_configure_game_joined_moves_it_to_the_list_and_flags_the_join(fake_decky, scripthub, tmp_path, monkeypatch):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    save = tmp_path / "deckhome" / "saves" / "cs2"
    save.mkdir(parents=True)
    st.join = {"id": "cs2-hub", "name": "Counter-Strike 2 (hub)", "appid": 730, "path": str(save), "joined": True, "devices": ["pc", "deck"], "enabled": True}

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        r = await p.configure_game(730, "Counter-Strike 2", str(save))
        s = await p.get_sync_state()
        await p._unload()
        return r, s

    r, s = asyncio.run(go())
    assert r == {"ok": True, "game": {"id": "cs2-hub", "name": "Counter-Strike 2 (hub)", "appid": 730, "joined": True}}
    assert [g["id"] for g in s["games"]] == ["hl2", "cs2-hub"] and [u["appid"] for u in s["unconfigured"]] == [1245620]


def test_configure_game_a_new_game_is_not_flagged_as_joined(fake_decky, scripthub, tmp_path, monkeypatch):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        r = await p.configure_game(730, "Counter-Strike 2", str(tmp_path / "deckhome" / "saves" / "cs2"))
        await p._unload()
        return r

    (tmp_path / "deckhome" / "saves" / "cs2").mkdir(parents=True)
    assert "joined" not in asyncio.run(go())["game"]


def test_configure_game_joined_a_disabled_game_stays_disabled_in_the_list(fake_decky, scripthub, tmp_path, monkeypatch):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    save = tmp_path / "deckhome" / "saves" / "cs2"
    save.mkdir(parents=True)
    st.join = {"id": "cs2-hub", "name": "CS2", "appid": 730, "path": str(save), "joined": True, "devices": ["pc", "deck"], "enabled": False}

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        await p.configure_game(730, "Counter-Strike 2", str(save))
        s = await p.get_sync_state()
        await p._unload()
        return s

    row = next(g for g in asyncio.run(go())["games"] if g["id"] == "cs2-hub")
    assert row["enabled"] is False and row["state"] == "disabled"


def test_configure_game_join_refusals_keep_the_game_unconfigured(fake_decky, scripthub, tmp_path, monkeypatch):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    (tmp_path / "deckhome" / "s").mkdir(parents=True)
    ok_path = str(tmp_path / "deckhome" / "s")

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        out = {}
        for reason in ("err.steam.no_free_slot", "err.steam.appid_mismatch", "err.steam.appid_in_use"):
            st.fail_create = (422, {"detail": {"code": "err.steam.game_invalid", "params": {"field": "name", "reason": reason}}}, {})
            out[reason] = await p.configure_game(730, "Dup", ok_path)
        s = await p.get_sync_state()
        await p._unload()
        return out, s

    out, s = asyncio.run(go())
    for reason, r in out.items():
        assert r["ok"] is False and r["error"] == "game_invalid" and r["error_params"] == {"field": "name", "reason": reason}
    assert [g["id"] for g in s["games"]] == ["hl2"] and len(s["unconfigured"]) == 2


def test_shortcut_shows_as_unconfigured_with_origin_and_can_be_created_in_the_hub(fake_decky, scripthub, tmp_path, monkeypatch):
    """Atajo de Steam (fichero sintético) con appid por encima de 2**31-1: sale en «sin configurar» marcado y se crea en el hub."""
    import struct

    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    cfg = tmp_path / "deckhome/.local/share/Steam/userdata/111/config"
    cfg.mkdir(parents=True)
    body = b"\x02appid\x00" + struct.pack("<I", 3_000_000_001) + b"\x01AppName\x00Lutris Juego\x00"
    (cfg / "shortcuts.vdf").write_bytes(b"\x00shortcuts\x00\x000\x00" + body + b"\x08\x08\x08")
    sent = []

    async def go():
        await p._main()
        await p.refresh_library()
        s = await settled(p)
        sent.append(await p.suggest_game(3_000_000_001))
        await p._unload()
        return s

    s = asyncio.run(go())
    assert {"appid": 3_000_000_001, "name": "Lutris Juego", "source": "shortcut"} in s["unconfigured"]
    assert all("source" not in u for u in s["unconfigured"] if u["appid"] != 3_000_000_001)
    assert sent[0]["ok"] is True and sent[0]["name"] == "Lutris Juego" and sent[0]["path"] == ""  # sin ruta detectada: la pide la interfaz


def test_suggest_game_gives_lutris_candidates_for_a_lutris_shortcut_and_nothing_for_other_shortcuts(fake_decky, scripthub, tmp_path, monkeypatch):
    """Atajos sintéticos: uno de Lutris (Flatpak, pga.db y .yml sintéticos en el home falso) y uno de emulador."""
    import sqlite3
    import struct

    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    home = tmp_path / "deckhome"
    cfg = home / ".local/share/Steam/userdata/111/config"
    cfg.mkdir(parents=True)

    def entry(i, appid, name, exe, opts):
        e = b"\x02appid\x00" + struct.pack("<I", appid) + b"\x01AppName\x00" + name.encode() + b"\x00"
        e += b"\x01Exe\x00" + exe.encode() + b"\x00" + b"\x01LaunchOptions\x00" + opts.encode() + b"\x00"
        return b"\x00" + str(i).encode() + b"\x00" + e + b"\x08"

    raw = b"\x00shortcuts\x00" + entry(0, 3_000_000_001, "Lutris Juego", '"/usr/bin/flatpak"', "run net.lutris.Lutris lutris:rungameid/1")
    raw += entry(1, 3_000_000_002, "Emulador", '"/home/deck/bin/cemu.sh"', "") + b"\x08\x08"
    (cfg / "shortcuts.vdf").write_bytes(raw)
    pfx = home / "Games" / "juego"
    pfx.mkdir(parents=True)
    data = home / ".var/app/net.lutris.Lutris/data/lutris"
    (data / "games").mkdir(parents=True)
    con = sqlite3.connect(data / "pga.db")
    con.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT, directory TEXT, configpath TEXT)")
    con.execute("INSERT INTO games VALUES (1, 'J', ?, 'j-1')", (str(pfx),))
    con.commit()
    con.close()
    (data / "games" / "j-1.yml").write_text(f"game:\n  prefix: {pfx}\n")
    saves = pfx / "drive_c/users/deck/Documents/My Games/Juego/Saves"
    saves.mkdir(parents=True)
    (saves / "a.sav").write_bytes(b"x")

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        out = (await p.suggest_game(3_000_000_001), await p.suggest_game(3_000_000_002), await p.suggest_game(1245620))
        out += (await p.picker_start(out[0]["browse_start"]),)
        await p._unload()
        return out

    lutris, emu, steam_game, picker = asyncio.run(go())
    assert lutris["ok"] and lutris["path"] == str(saves) and lutris["source"] == "lutris" and lutris["candidates"] == [str(saves)]
    assert lutris["path"] != str(pfx)  # el prefijo entero ya no se sugiere
    assert lutris["browse_start"] == str(pfx / "drive_c/users") and picker["path"] == lutris["browse_start"]
    assert emu["ok"] and emu["path"] == "" and emu["source"] == "" and emu["home"] == str(home)
    assert steam_game["source"] != "lutris" and steam_game["path"] == ""


def test_configure_game_refuses_a_suggested_folder_that_vanished_and_does_not_call_the_hub(fake_decky, scripthub, tmp_path, monkeypatch, caplog):
    import shutil

    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    save = Path(tmp_path / "card/steamapps/compatdata/730/pfx/drive_c/users/steamuser/AppData/Local/Counter-Strike 2")

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        save.mkdir(parents=True)
        sug = await p.suggest_game(730)
        shutil.rmtree(save)  # desaparece entre sugerir y guardar
        r = await p.configure_game(730, "Counter-Strike 2", sug["path"])
        s = await p.get_sync_state()
        await p._unload()
        return sug, r, s

    sug, r, s = asyncio.run(go())
    assert sug["path"] == str(save)
    assert r["ok"] is False and r["error"] == "path_vanished"
    assert not [q for q in hub.requests if q.method == "POST" and q.path == "/api/steam/games"]
    assert 730 in [u["appid"] for u in s["unconfigured"]] and [g["id"] for g in s["games"]] == ["hl2"]  # no queda a medias
    assert str(save) not in caplog.text and "tmp" not in " ".join(m for m in caplog.messages if "crear juego" in m)


def test_configure_game_refuses_a_suggested_folder_that_became_a_file(fake_decky, scripthub, tmp_path, monkeypatch):
    import shutil

    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    save = Path(tmp_path / "card/steamapps/compatdata/730/pfx/drive_c/users/steamuser/AppData/Local/Counter-Strike 2")

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        save.mkdir(parents=True)
        sug = await p.suggest_game(730)
        shutil.rmtree(save)
        save.write_text("ahora soy un fichero")
        r = await p.configure_game(730, "Counter-Strike 2", sug["path"])
        await p._unload()
        return r

    r = asyncio.run(go())
    assert r["ok"] is False and r["error"] == "path_vanished"
    assert not [q for q in hub.requests if q.method == "POST" and q.path == "/api/steam/games"]


def _post_games(hub):
    return [q for q in hub.requests if q.method == "POST" and q.path == "/api/steam/games"]


def test_configure_game_refuses_a_typed_folder_that_does_not_exist_and_does_not_call_the_hub(fake_decky, scripthub, tmp_path, monkeypatch, caplog):
    _, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    nueva = tmp_path / "deckhome" / "saves" / "nueva"  # escrita a mano, nunca ofrecida

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        r = await p.configure_game(730, "Counter-Strike 2", str(nueva))
        s = await p.get_sync_state()
        await p._unload()
        return r, s

    r, s = asyncio.run(go())
    assert r["ok"] is False and r["error"] == "path_missing"
    assert _post_games(hub) == [] and not nueva.exists()  # ni se llama al hub ni se crea la carpeta
    assert 730 in [u["appid"] for u in s["unconfigured"]] and [g["id"] for g in s["games"]] == ["hl2"]
    assert str(nueva) not in caplog.text and "tmp" not in " ".join(m for m in caplog.messages if "crear juego" in m)


def test_configure_game_refuses_a_typed_path_that_is_a_file(fake_decky, scripthub, tmp_path, monkeypatch):
    _, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    fichero = tmp_path / "deckhome" / "saves" / "fichero"
    fichero.parent.mkdir(parents=True)
    fichero.write_text("no soy una carpeta")

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        r = await p.configure_game(730, "Counter-Strike 2", str(fichero))
        await p._unload()
        return r

    r = asyncio.run(go())
    assert r["ok"] is False and r["error"] == "path_missing" and _post_games(hub) == []


def test_configure_game_accepts_a_typed_or_browsed_folder_that_exists(fake_decky, scripthub, tmp_path, monkeypatch):
    _, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    elegida = tmp_path / "deckhome" / "saves" / "elegida"  # escrita o elegida con Examinar: no pasó por suggest_game
    elegida.mkdir(parents=True)

    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        r = await p.configure_game(730, "Counter-Strike 2", str(elegida))
        await p._unload()
        return r

    assert asyncio.run(go())["ok"] is True
    assert json.loads(_post_games(hub)[0].body)["path"] == str(elegida)
