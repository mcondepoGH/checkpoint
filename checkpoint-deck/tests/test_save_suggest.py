"""Resolvedor y emparejado de rutas de guardado: manifiesto, raíces, existencia, mtime, `x`, carpeta frente a glob, orden de casado.

Todo SINTÉTICO en tmp_path (HOME de pruebas, usuario `deck`)."""

import asyncio
import json
import os
import time

import pytest

import checkpoint_installed as ci
import checkpoint_savepaths as sp
import checkpoint_savesuggest as ss
from checkpoint_savemanifest import ManifestStore, SaveManifest, SaveManifestError
from savefix import lutris_db, lutris_yml, manifest, mgame, rule, steam_game, steam_home, write

FP = ".var/app/net.lutris.Lutris/data/lutris"


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home" / "deck"
    h.mkdir(parents=True)
    return h


def M(*games):
    return SaveManifest.from_bytes(manifest(*games))


def one(m, home, source, ident):
    return ss.suggest_one(m, home, source, ident)


# ---- manifiesto
def test_manifest_indexes_and_drops_malformed_entries():
    m = SaveManifest.from_bytes(
        manifest(
            mgame("A", steam=1, lutris="a-slug", paths=[rule("home", "x")]),
            mgame("B", slug="b-s", paths=[rule("home", "../fuera"), rule("rara", "x"), rule("xdgData", "ok")]),
            mgame("Sin rutas", steam=3),
            {"n": 5},
        )
    )
    assert [g["n"] for g in m.games] == ["A", "B"]
    assert m.by_steam[1]["n"] == "A" and m.by_lutris["a-slug"]["n"] == "A" and m.by_slug["b-s"]["n"] == "B"
    assert [p["p"] for p in m.by_slug["b-s"]["paths"]] == ["ok"]
    assert m.by_name["a"]["n"] == "A"


@pytest.mark.parametrize("raw", [b"no json", b'{"v": 2, "games": []}', b"[]", b'{"v": 1}'])
def test_manifest_rejects_bad_schema(raw):
    with pytest.raises(SaveManifestError):
        SaveManifest.from_bytes(raw)


def test_store_is_lazy_cached_and_reloads_on_change(tmp_path):
    st = ManifestStore(tmp_path)
    assert st.get() is None  # sin fichero
    f = tmp_path / "save_manifest.json"
    f.write_bytes(manifest(mgame("A", steam=1, paths=[rule("home", "x")])))
    first = st.get()
    assert first is st.get()  # cacheado
    f.write_bytes(manifest(mgame("A", steam=1, paths=[rule("home", "x")]), mgame("B", steam=2, paths=[rule("home", "y")])))
    os.utime(f, (time.time() + 5, time.time() + 5))
    assert len(st.get().games) == 2
    f.write_text("basura")
    os.utime(f, (time.time() + 9, time.time() + 9))
    assert st.get() is None  # inválido: sin sugerencias, sin excepción


def test_store_accepts_bytes_and_custom_path_without_writing(tmp_path):
    st = ManifestStore(tmp_path)
    st.set_bytes(manifest(mgame("A", steam=1, paths=[rule("home", "x")]), src="mem"))
    assert st.get().src == "mem" and not (tmp_path / "save_manifest.json").exists()
    other = tmp_path / "otro.json"
    other.write_bytes(manifest(mgame("B", steam=2, paths=[rule("home", "y")]), src="otro"))
    st.set_path(other)
    assert st.get().src == "otro"


# ---- Stardew: xdgConfig (nativo) y pfxRoaming (Proton)
STARDEW = mgame(
    "Stardew Valley", steam=413150,
    paths=[rule("pfxRoaming", "StardewValley/Saves"), rule("xdgConfig", "StardewValley/Saves", "linux")],
)  # fmt: skip


def test_stardew_proton_uses_pfx_roaming(home):
    root = steam_home(home)
    pfx = steam_game(root, 413150, "Stardew Valley")
    save = write(pfx / "drive_c/users/steamuser/AppData/Roaming/StardewValley/Saves/Farm_123/Farm_123", "s")
    write(home / ".config/StardewValley/Saves/Nativo/Nativo", "no debe salir")  # regla de Linux: no aplica con prefijo
    r = one(M(STARDEW), home, "steam", 413150)
    assert r["state"] == "found" and r["confidence"] == "high" and r["needs_confirmation"] is True
    assert [p["path"] for p in r["paths"]] == [str(pfx / "drive_c/users/steamuser/AppData/Roaming/StardewValley/Saves")]
    assert r["paths"][0]["rule"] == "pfxRoaming:StardewValley/Saves" and r["paths"][0]["files"] == 1
    assert save.exists()


def test_stardew_native_uses_xdg_config(home):
    root = steam_home(home)
    steam_game(root, 413150, "Stardew Valley", pfx=False)
    write(home / ".config/StardewValley/Saves/Farm/Farm", "s")
    r = one(M(STARDEW), home, "steam", 413150)
    assert [p["path"] for p in r["paths"]] == [str(home / ".config/StardewValley/Saves")]


def test_not_found_yet_lists_candidates_when_nothing_exists(home):
    root = steam_home(home)
    pfx = steam_game(root, 413150, "Stardew Valley")
    r = one(M(STARDEW), home, "steam", 413150)
    assert r["state"] == "not_found_yet"
    assert [(p["path"], p["exists"]) for p in r["paths"]] == [(str(pfx / "drive_c/users/steamuser/AppData/Roaming/StardewValley/Saves"), False)]


def test_wine_user_deck_symlink_to_steamuser_resolves_once(home):
    root = steam_home(home)
    pfx = steam_game(root, 413150, "Stardew Valley")
    os.symlink("steamuser", pfx / "drive_c/users/deck")
    write(pfx / "drive_c/users/steamuser/AppData/Roaming/StardewValley/Saves/a", "s")
    assert len(one(M(STARDEW), home, "steam", 413150)["paths"]) == 1


# ---- existencia, mtime, tamaño
def test_only_existing_paths_sorted_by_mtime_desc_with_size_and_files(home):
    root = steam_home(home)
    pfx = steam_game(root, 1, "Juego")
    u = pfx / "drive_c/users/steamuser"
    write(u / "Documents/My Games/J/old.sav", "aaaa", mtime=1_000_000)
    write(u / "Documents/My Games/J/old2.sav", "bb", mtime=1_000_100)
    write(u / "AppData/Roaming/J/new.sav", "c" * 10, mtime=2_000_000)
    m = M(mgame("Juego", steam=1, paths=[rule("pfxDocs", "My Games/J"), rule("pfxRoaming", "J"), rule("pfxLocal", "J")]))
    r = one(m, home, "steam", 1)
    assert [p["rule"] for p in r["paths"]] == ["pfxRoaming:J", "pfxDocs:My Games/J"]  # pfxLocal no existe: fuera
    assert [p["mtime"] for p in r["paths"]] == [2_000_000, 1_000_100]
    assert (r["paths"][1]["size"], r["paths"][1]["files"], r["paths"][0]["size"]) == (6, 2, 10)


def test_measure_depth_and_count_are_bounded_and_contents_are_not_read(tmp_path, monkeypatch):
    d = tmp_path / "d"
    for i in range(sp.MAX_SCAN + 50):
        write(d / f"f{i // 300}" / f"{i}.sav", "x")
    write(d / "a/b/c/d/profundo.sav", "x")
    opened = []
    monkeypatch.setattr("builtins.open", lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(AssertionError("no se lee")))
    m = sp.measure(str(d))
    assert m["truncated"] is True and m["files"] <= sp.MAX_SCAN and not opened
    shallow = tmp_path / "s"
    write(shallow / "a/b/c/d/x.sav", "x")
    write(shallow / "a/b/ok.sav", "x")
    out = sp.measure(str(shallow))
    assert out["files"] == 1 and out["truncated"] is True  # el nivel 4 no se recorre


def test_steam_autocloud_metadata_is_ignored_when_measuring(tmp_path):
    d = tmp_path / "Saves"
    write(d / "Farm_1/Farm_1", "x" * 100, mtime=1_000_000)
    write(d / "Farm_1/SaveGameInfo", "y" * 50, mtime=1_000_100)
    write(d / "steam_autocloud.vdf", "z" * 52, mtime=2_000_000)
    m = sp.measure(str(d))
    assert (m["size"], m["files"], m["mtime"]) == (150, 2, 1_000_100)


def test_measure_only_metadata_folder_is_empty_with_folder_mtime(tmp_path):
    d = tmp_path / "Saves"
    write(d / "steam_autocloud.vdf", "z" * 52, mtime=2_000_000)
    os.utime(d, (1_500_000, 1_500_000))
    m = sp.measure(str(d))
    assert (m["size"], m["files"], m["mtime"]) == (0, 0, 1_500_000)


def test_ignored_names_are_exact_and_case_sensitive(tmp_path):
    d = tmp_path / "d"
    write(d / "a.sav", "x", mtime=1_000_000)
    write(d / "Steam_Autocloud.vdf", "x", mtime=1_000_001)
    write(d / "steam_autocloud.vdf.bak", "x", mtime=1_000_002)
    write(d / "otro.vdf", "x", mtime=1_000_003)
    m = sp.measure(str(d))
    assert m["files"] == 4 and m["mtime"] == 1_000_003
    assert sp.measure(str(d / "a.sav"))["files"] == 1


def test_symlinks_are_not_followed(tmp_path):
    d = tmp_path / "d"
    write(d / "a.sav", "x")
    (tmp_path / "otro").mkdir()
    write(tmp_path / "otro/b.sav", "x")
    os.symlink(tmp_path / "otro", d / "enlace")
    assert sp.measure(str(d))["files"] == 1


# ---- x: exclusiones
def test_x_patterns_do_not_count_toward_size_files_or_mtime(home):
    root = steam_home(home)
    steam_game(root, 2, "Juego", pfx=False)
    write(home / ".config/J/save1.dat", "12345", mtime=1_000_000)
    write(home / ".config/J/debug.log", "x" * 100, mtime=9_000_000)
    write(home / ".config/J/logs/a.txt", "x" * 100, mtime=9_000_000)
    write(home / ".config/J/crash_1.dmp", "x", mtime=9_000_000)
    m = M(mgame("Juego", steam=2, paths=[rule("xdgConfig", "J", "linux", x=["*.log", "logs", "crash*"])]))
    p = one(m, home, "steam", 2)["paths"][0]
    assert (p["size"], p["files"], p["mtime"]) == (5, 1, 1_000_000)


# ---- carpeta preferida al glob
def test_folder_preferred_over_file_glob_when_both_present(home):
    root = steam_home(home)
    steam_game(root, 3, "Juego", pfx=False)
    write(home / ".config/J/Saves/slot1.sav")
    m = M(mgame("Juego", steam=3, paths=[rule("xdgConfig", "J/Saves/*.sav", "linux"), rule("xdgConfig", "J/Saves", "linux")]))
    r = one(m, home, "steam", 3)
    assert [p["path"] for p in r["paths"]] == [str(home / ".config/J/Saves")]


def test_file_glob_alone_is_grouped_and_dir_glob_expands_per_folder(home):
    root = steam_home(home)
    steam_game(root, 3, "Juego", pfx=False)
    write(home / ".config/J/slot1.sav", "aa", mtime=5)
    write(home / ".config/J/slot2.sav", "bbb", mtime=7)
    write(home / ".config/P/uno/x", "x")
    write(home / ".config/P/dos/y", "y")
    m = M(mgame("Juego", steam=3, paths=[rule("xdgConfig", "J/*.sav", "linux"), rule("xdgConfig", "P/*", "linux")]))
    r = one(m, home, "steam", 3)
    byrule = {}
    for p in r["paths"]:
        byrule.setdefault(p["rule"], []).append(p)
    g = byrule["xdgConfig:J/*.sav"]
    assert len(g) == 1 and g[0]["path"].endswith("J/*.sav") and (g[0]["files"], g[0]["size"], g[0]["mtime"]) == (2, 5, 7)
    assert sorted(os.path.basename(p["path"]) for p in byrule["xdgConfig:P/*"]) == ["dos", "uno"]


# ---- raíces
def test_roots_install_xdgdata_home_progdata_and_steamcloud_in_paths(home):
    root = steam_home(home)
    pfx = steam_game(root, 4, "Juego")
    u = pfx / "drive_c/users/steamuser"
    write(root / "steamapps/common/Juego/saves/s.sav")
    write(home / ".local/share/J/x")
    write(home / "Juego/y")
    write(pfx / "drive_c/ProgramData/J/z")
    write(u / "AppData/LocalLow/Dev/J/l")
    write(u / "AppData/Local/J/l")
    write(u / "Saved Games/J/l")
    write(root / "userdata/111/4/remote/cloud.sav")
    m = M(
        mgame(
            "Juego", steam=4,
            paths=[
                rule("install", "saves"), rule("xdgData", "J", "linux"), rule("home", "Juego", "linux"), rule("pfxProgData", "J"),
                rule("pfxLocalLow", "Dev/J"), rule("pfxLocal", "J"), rule("pfxSaved", "J"), rule("steamCloud", "remote", "linux"),
            ],
        )
    )  # fmt: skip
    r = one(m, home, "steam", 4)
    rules = sorted(p["rule"] for p in r["paths"])
    assert rules == sorted(["install:saves", "pfxProgData:J", "pfxLocalLow:Dev/J", "pfxLocal:J", "pfxSaved:J", "steamCloud:remote"])  # linux no aplica con prefijo
    assert str(root / "userdata/111/4/remote") in [p["path"] for p in r["paths"]]
    assert "cloud" not in r


def test_steamcloud_only_game_is_found(home):
    root = steam_home(home)
    steam_game(root, 631510, "DMC HD", pfx=False)
    write(root / "userdata/111/631510/remote/dmc1.sav", mtime=1_000_000)
    write(root / "userdata/111/631510/remote/options.sav", mtime=1_000_005)
    write(root / "userdata/111/631510/remote.checkpoint-backup/x.sav")  # hermana: no se sugiere
    r = one(M(mgame("DMC", steam=631510, paths=[rule("steamCloud", "remote", "linux")])), home, "steam", 631510)
    assert r["state"] == "found"
    assert [(p["path"], p["files"], p["exists"]) for p in r["paths"]] == [(str(root / "userdata/111/631510/remote"), 2, True)]
    assert r["paths"][0]["rule"] == "steamCloud:remote" and set(r["paths"][0]) >= {"mtime", "size", "truncated"}


def test_steamcloud_and_local_path_sorted_by_mtime(home):
    root = steam_home(home)
    steam_game(root, 8, "J", pfx=False)
    write(home / ".local/share/J/a.sav", mtime=1_000_000)
    write(root / "userdata/111/8/remote/b.sav", mtime=2_000_000)
    m = M(mgame("J", steam=8, paths=[rule("xdgData", "J", "linux"), rule("steamCloud", "remote", "linux")]))
    r = one(m, home, "steam", 8)
    assert [p["rule"] for p in r["paths"]] == ["steamCloud:remote", "xdgData:J"]
    write(home / ".local/share/J/a.sav", mtime=3_000_000)
    assert [p["rule"] for p in one(m, home, "steam", 8)["paths"]] == ["xdgData:J", "steamCloud:remote"]


def test_nothing_exists_gives_not_found_yet_with_candidates(home):
    root = steam_home(home)
    steam_game(root, 9, "J", pfx=False)
    (root / "userdata/111/9").mkdir(parents=True)  # appid sin `remote`
    m = M(mgame("J", steam=9, paths=[rule("xdgData", "J", "linux"), rule("steamCloud", "remote", "linux")]))
    r = one(m, home, "steam", 9)
    assert r["state"] == "not_found_yet"
    assert {p["rule"] for p in r["paths"]} == {"xdgData:J", "steamCloud:remote"} and not any(p["exists"] for p in r["paths"])


def test_steamcloud_several_accounts_one_entry_each_capped(home):
    root = steam_home(home)
    steam_game(root, 7, "J", pfx=False)
    for i in range(12):
        write(root / f"userdata/{100 + i}/7/remote/s.sav", mtime=1_000_000 + i)
    write(root / "userdata/999/7/otra/s.sav")  # cuenta sin `remote`: no sale
    r = one(M(mgame("J", steam=7, paths=[rule("steamCloud", "remote", "linux")])), home, "steam", 7)
    assert r["state"] == "found" and len(r["paths"]) == sp.MAX_DIR_MATCHES
    assert all(p["path"].endswith("/7/remote") for p in r["paths"])
    mt = [p["mtime"] for p in r["paths"]]
    assert mt == sorted(mt, reverse=True)


def test_home_is_the_real_home_not_hardcoded(tmp_path):
    other = tmp_path / "otro_home"
    g = ci.InstalledGame("steam", 1, "J")
    assert sp.base_dirs(g, other)["home"] == [str(other)]
    assert sp.base_dirs(g, other)["xdgConfig"] == [str(other / ".config")]


# ---- casado en orden
def lutris_game(home, row, prefix=None):
    pfx = home / "Games/p"
    (pfx / "drive_c/users/steamuser").mkdir(parents=True, exist_ok=True)
    lutris_db(home / FP, [row])
    lutris_yml(home / FP / "games", row["configpath"], prefix=prefix or pfx, exe=home / "nada.exe", slug=row.get("slug") or "")
    return pfx


def test_match_order_lutris_steam_service_then_slug_then_secondary(home):
    pfx = lutris_game(home, {"id": 1, "name": "FF VI", "slug": "ff-vi", "service": "steam", "service_id": "382330", "configpath": "c1"})
    write(pfx / "drive_c/users/steamuser/AppData/Roaming/A/s", "s")
    write(pfx / "drive_c/users/steamuser/AppData/Roaming/B/s", "s")
    write(pfx / "drive_c/users/steamuser/AppData/Roaming/C/s", "s")
    m = M(
        mgame("Por steam", steam=382330, paths=[rule("pfxRoaming", "A")]),
        mgame("Por slug", lutris="ff-vi", paths=[rule("pfxRoaming", "B")]),
        mgame("Por nombre", slug="ff-vi", paths=[rule("pfxRoaming", "C")]),
    )
    r = one(m, home, "lutris", 1)
    assert (r["manifest_name"], r["match"], r["confidence"]) == ("Por steam", {"by": "lutris_service_steam", "id": 382330}, "high")
    # sin service steam: gana el slug de `lutris` (alta) sobre el slug derivado y el nombre (dudosas)
    lutris_game(home, {"id": 1, "name": "FF VI", "slug": "ff-vi", "configpath": "c1"})
    r = one(m, home, "lutris", 1)
    assert (r["manifest_name"], r["match"]["by"], r["confidence"]) == ("Por slug", "lutris_slug", "high")
    m2 = M(mgame("Por nombre", slug="ff-vi", paths=[rule("pfxRoaming", "C")]))
    r = one(m2, home, "lutris", 1)
    assert (r["match"]["by"], r["confidence"], r["needs_confirmation"]) == ("slug_derived", "doubtful", True)
    m3 = M(mgame("ff vi", paths=[rule("pfxRoaming", "C")]))
    r = one(m3, home, "lutris", 1)
    assert (r["match"]["by"], r["confidence"]) == ("name", "doubtful")


def test_steam_appid_match_and_no_match_returns_none(home):
    root = steam_home(home)
    steam_game(root, 77, "Algo")
    assert one(M(mgame("Otro", steam=1, paths=[rule("home", "x")])), home, "steam", 77) is None
    assert one(M(mgame("Otro", steam=77, paths=[rule("home", "x")])), home, "steam", 77)["match"] == {"by": "steam_appid", "id": 77}


def test_lutris_wine_game_uses_prefix_install_and_never_a_guessed_prefix(home):
    pfx = lutris_game(home, {"id": 2, "name": "Magicka 2", "slug": "magicka-2", "configpath": "c2"})
    write(pfx / "drive_c/users/steamuser/Documents/Paradox Interactive/Magicka 2/Saves/s.sav", "s")
    m = M(mgame("Magicka 2", lutris="magicka-2", paths=[rule("pfxDocs", "Paradox Interactive/Magicka 2/Saves")]))
    r = one(m, home, "lutris", "magicka-2")
    assert r["state"] == "found" and r["paths"][0]["path"].startswith(str(pfx))
    other = home / "Games/magicka-2"  # carpeta con el nombre del juego: no se usa si no es el prefijo del yml
    write(other / "drive_c/users/steamuser/Documents/Paradox Interactive/Magicka 2/Saves/s.sav", "s")
    assert [p["path"] for p in one(m, home, "lutris", 2)["paths"]] == [r["paths"][0]["path"]]


def test_lutris_native_flatpak_also_looks_under_flatpak_xdg(home):
    lutris_db(home / FP, [{"id": 5, "name": "Linux", "slug": "linux-g", "runner": "linux", "configpath": "c5"}])
    lutris_yml(home / FP / "games", "c5", prefix=None)
    write(home / ".var/app/net.lutris.Lutris/config/Linux/s.sav")
    m = M(mgame("Linux", lutris="linux-g", paths=[rule("xdgConfig", "Linux", "linux")]))
    r = one(m, home, "lutris", "linux-g")
    assert [p["path"] for p in r["paths"]] == [str(home / ".var/app/net.lutris.Lutris/config/Linux")]


# ---- suggest_all, callables de Plugin
def test_suggest_all_covers_steam_and_lutris_and_skips_unmatched(home):
    root = steam_home(home)
    pfx = steam_game(root, 413150, "Stardew Valley")
    write(pfx / "drive_c/users/steamuser/AppData/Roaming/StardewValley/Saves/a")
    steam_game(root, 999, "Sin manifiesto")
    lutris_game(home, {"id": 1, "name": "Magicka 2", "slug": "magicka-2", "configpath": "c1"})
    m = M(STARDEW, mgame("Magicka 2", lutris="magicka-2", paths=[rule("pfxDocs", "M")]))
    out = ss.suggest_all(m, home)
    assert [(g["source"], g["id"], g["state"]) for g in out] == [("steam", 413150, "found"), ("lutris", 1, "not_found_yet")]


def test_plugin_callables(fake_decky, tmp_path, monkeypatch):
    home = tmp_path / "h"
    root = steam_home(home)
    pfx = steam_game(root, 413150, "Stardew Valley")
    write(pfx / "drive_c/users/steamuser/AppData/Roaming/StardewValley/Saves/a")
    monkeypatch.setenv("HOME", str(home))
    import main

    p = main.Plugin()
    p.saves = ss.SaveSuggester(fake_decky.DECKY_PLUGIN_SETTINGS_DIR)
    assert asyncio.run(p.suggest_saves()) == {"ok": False, "error": "no_manifest"}
    os.makedirs(fake_decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
    with open(os.path.join(fake_decky.DECKY_PLUGIN_SETTINGS_DIR, "save_manifest.json"), "wb") as f:
        f.write(manifest(STARDEW, src="t@1"))
    out = asyncio.run(p.suggest_saves())
    assert out["ok"] and out["manifest"] == "t@1" and out["games"][0]["id"] == 413150
    json.dumps(out)  # serializable para la interfaz
    assert asyncio.run(p.suggest_saves_for("steam", 413150))["game"]["state"] == "found"
    assert asyncio.run(p.suggest_saves_for("steam", 1))["error"] == "no_match"
    assert asyncio.run(p.suggest_saves_for("gog", 1))["error"] == "bad_args"


# ---- rutas dudosas (`d: true`, heurística LÖVE)
def test_move_or_die_love_found_doubtful(home):
    root = steam_home(home)
    steam_game(root, 323850, "Move or Die", pfx=False)
    base = home / ".local/share/love/Move Or Die"
    write(base / "PartyData", "p")
    write(base / "inventory", "i")
    write(base / "Levels/a", "l")
    write(base / "startup.ini", "c")
    m = M(mgame("Move or Die", steam=323850, paths=[rule("xdgData", "love/Move Or Die", "linux", d_=True)]))
    r = one(m, home, "steam", 323850)
    assert r["state"] == "found" and r["confidence"] == "doubtful" and r["needs_confirmation"] is True
    assert [p["path"] for p in r["paths"]] == [str(base)] and r["paths"][0]["doubtful"] is True


def test_doubtful_solo_baja_si_todas_las_existentes_lo_son(home):
    root = steam_home(home)
    steam_game(root, 7, "Mix", pfx=False)
    write(home / ".local/share/love/Mix/a", "x")
    dud = rule("xdgData", "love/Mix", "linux", d_=True)
    r = one(M(mgame("Mix", steam=7, paths=[dud])), home, "steam", 7)
    assert r["confidence"] == "doubtful"
    write(home / ".config/Mix/s", "x")
    r = one(M(mgame("Mix", steam=7, paths=[dud, rule("xdgConfig", "Mix", "linux")])), home, "steam", 7)
    assert r["confidence"] == "high" and {p["doubtful"] for p in r["paths"]} == {True, False}
    # la normal no existe, solo la dudosa: baja
    r = one(M(mgame("Mix", steam=7, paths=[dud, rule("xdgConfig", "Otra", "linux")])), home, "steam", 7)
    assert r["confidence"] == "doubtful"


def test_ruta_normal_no_es_dudosa_y_not_found_conserva_confianza(home):
    root = steam_home(home)
    steam_game(root, 8, "N", pfx=False)
    r = one(M(mgame("N", steam=8, paths=[rule("xdgData", "love/N", "linux", d_=True)])), home, "steam", 8)
    assert r["state"] == "not_found_yet" and r["confidence"] == "high" and r["paths"][0]["doubtful"] is True
    write(home / ".config/N/s", "x")
    r = one(M(mgame("N", steam=8, paths=[rule("xdgConfig", "N", "linux")])), home, "steam", 8)
    assert r["paths"][0]["doubtful"] is False and r["confidence"] == "high"


def test_doubtful_ignora_metadatos_de_steam(home):
    root = steam_home(home)
    steam_game(root, 9, "M", pfx=False)
    write(home / ".local/share/love/M/steam_autocloud.vdf", "meta")
    r = one(M(mgame("M", steam=9, paths=[rule("xdgData", "love/M", "linux", d_=True)])), home, "steam", 9)
    assert r["paths"][0]["files"] == 0 and r["paths"][0]["doubtful"] is True


# ---- dos ubicaciones por defecto: ajustes (prioridad) y empaquetado en el plugin (solo lectura)
def _put(d, name, steam=1):
    d.mkdir(parents=True, exist_ok=True)
    f = d / "save_manifest.json"
    f.write_bytes(manifest(mgame(name, steam=steam, paths=[rule("home", "x")]), src=name))
    return f


def test_store_uses_bundled_when_settings_has_none(tmp_path):
    bundled = _put(tmp_path / "plugin/data", "empaquetado")
    st = ManifestStore(tmp_path / "ajustes", bundled_dir=tmp_path / "plugin/data")
    assert st.get().src == "empaquetado" and st.used == bundled


def test_store_settings_wins_over_bundled_and_falls_back_when_removed_or_invalid(tmp_path):
    bundled = _put(tmp_path / "plugin/data", "empaquetado")
    settings = _put(tmp_path / "ajustes", "ajustes")
    logs = []
    st = ManifestStore(tmp_path / "ajustes", logs.append, bundled_dir=tmp_path / "plugin/data")
    assert st.get().src == "ajustes" and st.used == settings
    settings.write_text("basura")  # inválido: cae al empaquetado
    os.utime(settings, (time.time() + 5, time.time() + 5))
    assert st.get().src == "empaquetado" and st.used == bundled and logs
    settings.unlink()
    assert st.get().src == "empaquetado"
    _put(tmp_path / "ajustes", "ajustes2")  # vuelve a existir: gana otra vez
    assert st.get().src == "ajustes2"


def test_store_bundled_is_never_written_and_set_path_overrides_both(tmp_path):
    bundled = _put(tmp_path / "plugin/data", "empaquetado")
    before = bundled.read_bytes()
    st = ManifestStore(tmp_path / "ajustes", bundled_dir=tmp_path / "plugin/data")
    st.set_bytes(manifest(mgame("M", steam=3, paths=[rule("home", "x")]), src="mem"))
    assert st.get().src == "mem"
    other = _put(tmp_path / "otro", "otro")
    st.set_path(other)
    assert st.get().src == "otro" and st.used == other
    st.set_path(tmp_path / "no-existe.json")
    assert st.get() is None  # una ruta explícita no cae al empaquetado
    assert bundled.read_bytes() == before and not (tmp_path / "ajustes").exists()


def test_plugin_reads_the_manifest_bundled_in_its_data_folder(fake_decky, tmp_path, monkeypatch):
    home = tmp_path / "h"
    root = steam_home(home)
    pfx = steam_game(root, 413150, "Stardew Valley")
    write(pfx / "drive_c/users/steamuser/AppData/Roaming/StardewValley/Saves/a")
    monkeypatch.setenv("HOME", str(home))
    plugin = tmp_path / "plugin"
    fake_decky.DECKY_PLUGIN_DIR = str(plugin)
    (plugin / "data").mkdir(parents=True)
    (plugin / "data/save_manifest.json").write_bytes(manifest(STARDEW, src="bundled@1"))
    import main

    p = main.Plugin()
    asyncio.run(p._main())
    try:
        out = asyncio.run(p.suggest_saves())
        assert out["ok"] and out["manifest"] == "bundled@1" and out["games"][0]["id"] == 413150
    finally:
        asyncio.run(p._unload())
