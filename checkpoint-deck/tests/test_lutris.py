"""Carpeta sugerida para un atajo de Lutris: LaunchOptions -> pga.db -> .yml -> prefijo.

Todo SINTÉTICO (pga.db y .yml creados en tmp_path, usuario ficticio `deck`). Modelado sobre lo verificado en una Deck real
con Lutris Flatpak. Lutris NATIVO (~/.local/share/lutris, ~/.config/lutris): no verificado en una Deck real."""

import os
import sqlite3
from pathlib import Path

import pytest

import checkpoint_lutris as lu

FLATPAK = ".var/app/net.lutris.Lutris/data/lutris"
NATIVE = ".local/share/lutris"
LAUNCH = "run net.lutris.Lutris lutris:rungameid/1"


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home" / "deck"
    h.mkdir(parents=True)
    return h


def make_db(data: Path, rows=((1, "Juego", "wine", "/prefix", "juego-123"),)) -> Path:
    data.mkdir(parents=True, exist_ok=True)
    db = data / "pga.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT, runner TEXT, directory TEXT, configpath TEXT)")
    con.executemany("INSERT INTO games VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return db


def make_yml(gamesdir: Path, configpath: str, prefix, exe="/x/game.exe", quote="") -> None:
    gamesdir.mkdir(parents=True, exist_ok=True)
    lines = ["game:", "  args: ''", f"  exe: {quote}{exe}{quote}"]
    if prefix is not None:
        lines.append(f"  prefix: {quote}{prefix}{quote}")
    lines += ["game_slug: juego", "name: Juego", "system: {}"]
    (gamesdir / f"{configpath}.yml").write_text("\n".join(lines) + "\n")


def setup_flatpak(home, prefix_name="pfx", yml_prefix="auto", directory="auto"):
    pfx = home / "Games" / prefix_name
    pfx.mkdir(parents=True, exist_ok=True)
    data = home / FLATPAK
    make_db(data, ((1, "Juego", "wine", str(pfx) if directory == "auto" else directory, "juego-123"),))
    make_yml(data / "games", "juego-123", str(pfx) if yml_prefix == "auto" else yml_prefix)
    return pfx


# ---- LaunchOptions
@pytest.mark.parametrize(
    "opts,expected",
    [
        ("run net.lutris.Lutris lutris:rungameid/1", 1),
        ("lutris:rungameid/42", 42),
        ("  run net.lutris.Lutris lutris:rungameid/7  ", 7),
        ('"lutris:rungameid/9"', None),
        ("lutris:rungameid/abc", None),
        ("lutris:rungameid/", None),
        ("lutris:rungameid/-3", None),
        ("lutris:rungameid/12abc", None),
        ("lutris:dragon-quest-vii", None),
        ("", None),
        ("--fullscreen", None),
        (None, None),
    ],
)
def test_parse_game_id(opts, expected):
    assert lu.parse_game_id(opts) == expected


def test_parse_game_id_rejects_absurdly_long_ids():
    assert lu.parse_game_id("lutris:rungameid/" + "9" * 30) is None


# ---- sugerencia
def test_flatpak_suggests_the_prefix(home):
    pfx = setup_flatpak(home)
    assert lu.find_prefix(home, LAUNCH) == str(pfx)


def test_native_data_dir_is_supported(home):
    pfx = home / "Games" / "nat"
    pfx.mkdir(parents=True)
    make_db(home / NATIVE, ((1, "J", "wine", str(pfx), "j-1"),))
    make_yml(home / NATIVE / "games", "j-1", str(pfx))
    assert lu.find_prefix(home, LAUNCH) == str(pfx)


def test_native_old_layout_yml_in_config_dir(home):
    pfx = home / "Games" / "old"
    pfx.mkdir(parents=True)
    make_db(home / NATIVE, ((1, "J", "wine", "/nonexistent-dir", "j-1"),))
    make_yml(home / ".config/lutris/games", "j-1", str(pfx))
    assert lu.find_prefix(home, LAUNCH) == str(pfx)


def test_flatpak_wins_over_native(home):
    pfx = setup_flatpak(home)
    other = home / "Games" / "other"
    other.mkdir()
    make_db(home / NATIVE, ((1, "J", "wine", str(other), "j-1"),))
    assert lu.find_prefix(home, LAUNCH) == str(pfx)


def test_falls_back_to_directory_when_yml_missing(home):
    pfx = home / "Games" / "pfx"
    pfx.mkdir(parents=True)
    make_db(home / FLATPAK, ((1, "J", "wine", str(pfx), "j-1"),))  # sin games/
    assert lu.find_prefix(home, LAUNCH) == str(pfx)


def test_falls_back_to_directory_when_yml_has_no_prefix(home):
    pfx = setup_flatpak(home, yml_prefix=None)
    assert lu.find_prefix(home, LAUNCH) == str(pfx)


def test_falls_back_to_directory_when_prefix_does_not_exist(home):
    pfx = setup_flatpak(home, yml_prefix=str(home / "Games" / "gone"))
    assert lu.find_prefix(home, LAUNCH) == str(pfx)


def test_prefix_wins_over_directory_when_both_exist(home):
    a = home / "Games" / "a"
    a.mkdir(parents=True)
    pfx = setup_flatpak(home, yml_prefix=str(a))
    assert pfx != a and lu.find_prefix(home, LAUNCH) == str(a)


def test_nothing_exists_gives_empty(home):
    setup_flatpak(home, yml_prefix=str(home / "g1"), directory=str(home / "g2"))
    assert lu.find_prefix(home, LAUNCH) == ""


def test_yml_quoted_values(home):
    pfx = home / "Games" / "it's here"
    pfx.mkdir(parents=True)
    data = home / FLATPAK
    make_db(data, ((1, "J", "wine", "/nope", "j-1"),))
    (data / "games").mkdir()
    (data / "games" / "j-1.yml").write_text("game:\n  exe: 'x'\n  prefix: '" + str(pfx).replace("'", "''") + "'\nname: J\n")
    assert lu.find_prefix(home, LAUNCH) == str(pfx)
    (data / "games" / "j-1.yml").write_text('game:\n  prefix: "' + str(pfx) + '"\n')
    assert lu.find_prefix(home, LAUNCH) == str(pfx)


def test_yml_prefix_outside_game_section_is_ignored(home):
    pfx = home / "Games" / "pfx"
    pfx.mkdir(parents=True)
    other = home / "Games" / "other"
    other.mkdir()
    data = home / FLATPAK
    make_db(data, ((1, "J", "wine", str(pfx), "j-1"),))
    (data / "games").mkdir()
    (data / "games" / "j-1.yml").write_text(f"wine:\n  prefix: {other}\ngame:\n  exe: x\nsystem:\n  prefix: {other}\n")
    assert lu.find_prefix(home, LAUNCH) == str(pfx)


def test_row_selected_by_game_id(home):
    a, b = home / "Games" / "a", home / "Games" / "b"
    a.mkdir(parents=True)
    b.mkdir()
    make_db(home / FLATPAK, ((1, "A", "wine", str(a), "a"), (2, "B", "wine", str(b), "b")))
    assert lu.find_prefix(home, "lutris:rungameid/2") == str(b)
    assert lu.find_prefix(home, "lutris:rungameid/3") == ""


# ---- no Lutris
@pytest.mark.parametrize("opts", ["", "--fullscreen", "lutris:slug-sin-id", "run net.lutris.Lutris lutris:rungameid/x", None])
def test_non_lutris_gives_empty(home, opts):
    setup_flatpak(home)
    assert lu.find_prefix(home, opts) == ""


# ---- robustez
def test_missing_db_gives_empty_and_creates_nothing(home):
    assert lu.find_prefix(home, LAUNCH) == ""
    assert not (home / FLATPAK).exists() and not (home / NATIVE).exists()


def test_corrupt_db_gives_empty(home):
    d = home / FLATPAK
    d.mkdir(parents=True)
    (d / "pga.db").write_bytes(b"esto no es sqlite" * 50)
    assert lu.find_prefix(home, LAUNCH) == ""


def test_empty_file_db_gives_empty(home):
    d = home / FLATPAK
    d.mkdir(parents=True)
    (d / "pga.db").write_bytes(b"")
    assert lu.find_prefix(home, LAUNCH) == ""
    assert (d / "pga.db").stat().st_size == 0  # no escribe


def test_db_without_games_table_gives_empty(home):
    d = home / FLATPAK
    d.mkdir(parents=True)
    sqlite3.connect(d / "pga.db").execute("CREATE TABLE otra (x)").connection.commit()
    assert lu.find_prefix(home, LAUNCH) == ""


def test_locked_db_gives_empty(home):
    pfx = setup_flatpak(home)
    con = sqlite3.connect(home / FLATPAK / "pga.db", isolation_level=None)
    con.execute("BEGIN EXCLUSIVE")
    try:
        assert lu.find_prefix(home, LAUNCH) in ("", str(pfx))  # sin excepción, con o sin lock
    finally:
        con.execute("ROLLBACK")
        con.close()


def test_does_not_write_to_the_db_or_leave_journal(home):
    setup_flatpak(home)
    d = home / FLATPAK
    before = {p.name: p.read_bytes() for p in d.iterdir() if p.is_file()}
    mtime = (d / "pga.db").stat().st_mtime_ns
    lu.find_prefix(home, LAUNCH)
    after = {p.name: p.read_bytes() for p in d.iterdir() if p.is_file()}
    assert before == after and (d / "pga.db").stat().st_mtime_ns == mtime
    assert not list(d.glob("*-journal")) and not list(d.glob("*-wal")) and not list(d.glob("*-shm"))


def test_db_opened_read_only(home, monkeypatch):
    setup_flatpak(home)
    seen = []
    real = sqlite3.connect

    def spy(target, *a, **kw):
        seen.append((str(target), kw.get("uri")))
        return real(target, *a, **kw)

    monkeypatch.setattr(lu.sqlite3, "connect", spy)
    lu.find_prefix(home, LAUNCH)
    assert seen and all("mode=ro" in t and uri is True for t, uri in seen)


def test_db_path_with_special_chars_still_opens(home):
    h = home / "my dir#1?x"
    h.mkdir()
    pfx = setup_flatpak(h)
    assert lu.find_prefix(h, LAUNCH) == str(pfx)


def test_huge_yml_is_ignored(home):
    pfx = home / "Games" / "pfx"
    pfx.mkdir(parents=True)
    data = home / FLATPAK
    make_db(data, ((1, "J", "wine", str(pfx), "j-1"),))
    (data / "games").mkdir()
    (data / "games" / "j-1.yml").write_text("game:\n  prefix: /x\n" + "#" * (lu.MAX_YML + 10))
    assert lu.find_prefix(home, LAUNCH) == str(pfx)


@pytest.mark.parametrize("cfg", ["../../evil", "a/b", "..", "", None, 5])
def test_configpath_with_traversal_is_not_followed(home, cfg):
    pfx = home / "Games" / "pfx"
    pfx.mkdir(parents=True)
    data = home / FLATPAK
    make_db(data, ((1, "J", "wine", str(pfx), cfg),))
    evil = home / "evil.yml"
    evil.write_text("game:\n  prefix: /etc\n")
    assert lu.find_prefix(home, LAUNCH) == str(pfx)


# ---- validación de la ruta
def test_prefix_outside_home_is_rejected(home, tmp_path):
    outside = tmp_path / "otro" / "pfx"
    outside.mkdir(parents=True)
    setup_flatpak(home, yml_prefix=str(outside), directory=str(outside))
    assert lu.find_prefix(home, LAUNCH) == ""


def test_system_or_forbidden_prefix_is_rejected(home):
    setup_flatpak(home, yml_prefix="/etc", directory=str(home))
    assert lu.find_prefix(home, LAUNCH) == ""


def test_relative_prefix_is_rejected(home):
    setup_flatpak(home, yml_prefix="Games/pfx", directory="Games/pfx")
    assert lu.find_prefix(home, LAUNCH) == ""


def test_dotdot_prefix_is_rejected(home):
    (home / "Games" / "pfx").mkdir(parents=True)
    setup_flatpak(home, yml_prefix=f"{home}/Games/../Games/pfx", directory="/nope")
    assert lu.find_prefix(home, LAUNCH) == ""


def test_symlink_prefix_is_rejected(home):
    real = home / "Games" / "real"
    real.mkdir(parents=True)
    link = home / "Games" / "link"
    link.symlink_to(real)
    setup_flatpak(home, yml_prefix=str(link), directory="/nope")
    assert lu.find_prefix(home, LAUNCH) == ""


def test_protected_dirs_are_respected(home):
    pfx = setup_flatpak(home)
    assert lu.find_prefix(home, LAUNCH, protected=[pfx]) == ""


def test_accept_filter_can_reject_a_candidate(home):
    pfx = setup_flatpak(home)
    assert lu.find_prefix(home, LAUNCH, accept=lambda s: False) == ""
    assert lu.find_prefix(home, LAUNCH, accept=lambda s: s == str(pfx)) == str(pfx)


def test_log_has_no_paths_or_user_names(home):
    pfx = setup_flatpak(home)
    (home / FLATPAK / "pga.db").write_bytes(b"corrupta" * 40)
    logs = []
    assert lu.find_prefix(home, LAUNCH, log=logs.append) == ""
    assert all(str(home) not in m and "deck" not in m and str(pfx) not in m for m in logs)


# ---------------------------------------------------------------- candidatos de carpeta de guardado
DQ7_ID = "76561197960271999"  # steamid ficticio


def put(path: Path, content: bytes = b"x", mtime=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def users(pfx: Path, user: str = "deck") -> Path:
    return pfx / "drive_c/users" / user


def dq7(pfx: Path, user: str = "deck") -> Path:
    """Prefijo modelado sobre Dragon Quest VII Reimagined (la carpeta de guardado real del hub del usuario)."""
    saved = users(pfx, user) / f"Documents/My Games/DRAGON QUEST VII/Steam/{DQ7_ID}/release/Saved"
    put(saved / "SaveGames" / "slot1.sav")
    put(saved / "SaveGames" / "slot2.sav")
    put(saved / "Config" / "GameUserSettings.ini")
    put(saved / "Logs" / "game.log")
    return saved / "SaveGames"


def saves(home, **kw):
    return lu.find_saves(home, LAUNCH, **kw)


def test_dq7_first_candidate_is_the_savegames_folder_not_the_prefix(home):
    pfx = setup_flatpak(home, prefix_name="dragon-quest-vii-reimagined")
    saved = dq7(pfx)
    out = saves(home)
    assert out["prefix"] == str(pfx)
    assert out["candidates"] == [str(saved)]  # ni el prefijo, ni la carpeta del juego, ni Config ni Logs
    assert str(pfx) not in out["candidates"]
    assert out["browse_start"] == str(pfx / "drive_c/users")


def test_name_match_with_a_game_whose_folder_differs_from_the_slug(home):
    """«DRAGON QUEST VII» frente al nombre/slug «dragon-quest-vii-reimagined»: coincide (reimagined no cuenta)."""
    assert lu.similarity("DRAGON QUEST VII", ["Dragon Quest VII Reimagined", "dragon-quest-vii-reimagined"]) >= lu.MIN_SIMILARITY
    assert lu.similarity("Hollow Knight", ["Dragon Quest VII Reimagined"]) == 0.0
    assert lu.similarity("DragonQuestVII", ["dragon quest vii"]) == 1.0  # CamelCase
    assert lu.similarity("Ñandú Édition", ["nandu"]) == 1.0  # acentos y palabras vacías


def test_appdata_local_game_with_saved_savegames(home):
    pfx = setup_flatpak(home)
    s = put(users(pfx) / "AppData/Local/MiJuego/Saved/SaveGames/a.sav").parent
    assert saves(home)["candidates"] == [str(s)]


def test_appdata_locallow_dev_game(home):
    pfx = setup_flatpak(home)
    g = put(users(pfx) / "AppData/LocalLow/Estudio/Juego/save1.dat").parent
    assert saves(home)["candidates"] == [str(g)]


def test_saved_games_roaming_and_documents_folders(home):
    pfx = setup_flatpak(home)
    a = put(users(pfx) / "Saved Games/Uno/s.sav").parent
    b = put(users(pfx) / "AppData/Roaming/Dos/s.sav").parent
    c = put(users(pfx) / "Documents/Tres/s.sav").parent
    assert set(saves(home)["candidates"]) == {str(a), str(b), str(c)}


def test_my_games_itself_is_not_a_candidate(home):
    pfx = setup_flatpak(home)
    put(users(pfx) / "Documents/My Games/J/x.sav")
    out = saves(home)["candidates"]
    assert str(users(pfx) / "Documents/My Games") not in out and out == [str(users(pfx) / "Documents/My Games/J")]


def test_save_names_are_case_insensitive_and_preferred_to_the_game_folder(home):
    pfx = setup_flatpak(home)
    g = users(pfx) / "Documents/Juego"
    put(g / "SAVEDATA/a.bin")
    put(g / "readme.txt")
    put(g / "a/b/c/Save/s.dat")
    out = saves(home)["candidates"]
    assert set(out) == {str(g / "SAVEDATA"), str(g / "a/b/c/Save")} and str(g) not in out


def test_save_folder_deeper_than_six_levels_is_not_found(home):
    pfx = setup_flatpak(home)
    g = users(pfx) / "Documents/Juego"
    deep = g / "1/2/3/4/5/6/Saves"
    put(deep / "a.sav")
    put(g / "x.cfg")
    assert saves(home)["candidates"] == [str(g)]  # sin SaveGames a la vista: la carpeta del juego, que sí tiene ficheros
    ok = g / "1/2/3/4/5/Saves"  # a profundidad 6
    put(ok / "a.sav")
    assert str(ok) in saves(home)["candidates"]


@pytest.mark.parametrize(
    "noise",
    ["Documents/Microsoft", "AppData/Local/Microsoft", "AppData/Local/Wine", "AppData/Local/Temp", "AppData/Local/Packages",
     "AppData/Roaming/Microsoft", "AppData/Local/Programs", "AppData/Local/Windows", "AppData/Local/INetCache",
     "AppData/Local/CrashPad", "AppData/Local/Cache", "AppData/Local/Logs", "AppData/LocalLow/Microsoft/x", "AppData/LocalLow/Unity/y"],
)
def test_wine_and_windows_noise_is_filtered(home, noise):
    pfx = setup_flatpak(home)
    put(users(pfx) / noise / "f.dat")
    assert saves(home)["candidates"] == []


def test_empty_and_file_less_folders_are_excluded(home):
    pfx = setup_flatpak(home)
    (users(pfx) / "Documents/Vacia").mkdir(parents=True)
    (users(pfx) / "Documents/SoloCarpetas/a/b").mkdir(parents=True)
    (users(pfx) / "Documents/Juego/Saves").mkdir(parents=True)  # SaveGames vacía: sin ficheros no es un guardado
    assert saves(home)["candidates"] == []


def test_empty_savegames_falls_back_to_nothing_but_a_populated_sibling_wins(home):
    pfx = setup_flatpak(home)
    g = users(pfx) / "Documents/Juego"
    (g / "Saves").mkdir(parents=True)
    put(g / "Save/a.sav")
    assert saves(home)["candidates"] == [str(g / "Save")]


def test_prefix_without_saves_gives_no_candidates_and_browses_users(home):
    pfx = setup_flatpak(home)
    users(pfx, "deck").mkdir(parents=True)
    out = saves(home)
    assert out["candidates"] == [] and out["prefix"] == str(pfx) and out["browse_start"] == str(pfx / "drive_c/users")


def test_prefix_without_drive_c_browses_the_prefix(home):
    pfx = setup_flatpak(home)
    out = saves(home)
    assert out["candidates"] == [] and out["browse_start"] == str(pfx)


def test_missing_prefix_gives_nothing(home):
    setup_flatpak(home, yml_prefix=str(home / "g1"), directory=str(home / "g2"))
    assert saves(home) == {"prefix": "", "candidates": [], "browse_start": ""}


def test_not_a_lutris_shortcut_gives_nothing(home):
    pfx = setup_flatpak(home)
    dq7(pfx)
    assert lu.find_saves(home, "--fullscreen") == {"prefix": "", "candidates": [], "browse_start": ""}
    assert lu.find_saves(home, None)["candidates"] == []


@pytest.mark.parametrize("user", ["deck", "steamuser"])
def test_wine_user_is_discovered(home, user):
    pfx = setup_flatpak(home)
    saved = dq7(pfx, user)
    assert saves(home)["candidates"] == [str(saved)]


def test_several_users_are_searched_and_public_is_not(home):
    pfx = setup_flatpak(home)
    a = dq7(pfx, "deck")
    b = put(users(pfx, "steamuser") / "Documents/Otro/s.sav").parent
    put(users(pfx, "Public") / "Documents/Compartido/s.sav")
    assert set(saves(home)["candidates"]) == {str(a), str(b)}


def test_symlink_pointing_outside_home_is_rejected(home, tmp_path):
    pfx = setup_flatpak(home)
    outside = tmp_path / "fuera" / "Juego"
    put(outside / "s.sav")
    (users(pfx) / "Documents").mkdir(parents=True)
    (users(pfx) / "Documents/Enlace").symlink_to(outside)
    g = users(pfx) / "Documents/Real"
    put(g / "x.dat")
    (g / "SaveGames").symlink_to(outside)
    out = saves(home)["candidates"]
    assert all(str(tmp_path / "fuera") not in c for c in out) and out == [str(g)]


def test_symlinked_documents_folder_is_not_followed(home, tmp_path):
    pfx = setup_flatpak(home)
    real = home / "Documents"  # dentro de ~ pero fuera del prefijo
    put(real / "Juego/s.sav")
    users(pfx).mkdir(parents=True)
    (users(pfx) / "Documents").symlink_to(real)
    assert saves(home)["candidates"] == []


def test_candidates_never_leave_the_prefix_or_hit_protected_dirs(home):
    pfx = setup_flatpak(home)
    a = put(users(pfx) / "Documents/A/s.sav").parent
    b = put(users(pfx) / "Documents/B/s.sav").parent
    assert set(saves(home)["candidates"]) == {str(a), str(b)}
    # una carpeta protegida dentro del prefijo (o el prefijo mismo) invalida la sugerencia, como en la sincronización
    assert saves(home, protected=[b])["candidates"] == [] and saves(home, protected=[pfx])["prefix"] == ""
    assert all(c.startswith(str(pfx) + "/") for c in saves(home)["candidates"])


def test_accept_filter_applies_to_candidates_only(home):
    pfx = setup_flatpak(home, prefix_name="pfx &x")
    put(users(pfx) / "Documents/A/s.sav")
    out = saves(home, accept=lambda s: "&" not in s)
    assert out["prefix"] == str(pfx) and out["candidates"] == []


def test_limit_of_eight_candidates(home):
    pfx = setup_flatpak(home)
    for i in range(12):
        put(users(pfx) / f"Documents/Juego{i:02d}/s.sav", mtime=1_000_000 + i)
    out = saves(home)["candidates"]
    assert len(out) == lu.MAX_CANDIDATES == 8
    assert out[0].endswith("Juego11")  # los más recientes


def test_order_name_match_first_then_most_recent(home):
    pfx = setup_flatpak(home)
    d = users(pfx) / "Documents"
    old_match = put(d / "My Games/Dragon Quest VII/s.sav", mtime=1_000).parent
    new_other = put(d / "Zeta/s.sav", mtime=9_000_000).parent
    mid_other = put(d / "Alfa/s.sav", mtime=5_000_000).parent
    pfx_name = "Dragon Quest VII Reimagined"
    con = sqlite3.connect(home / FLATPAK / "pga.db")
    con.execute("UPDATE games SET name = ?", (pfx_name,))
    con.commit()
    con.close()
    assert saves(home)["candidates"] == [str(old_match), str(new_other), str(mid_other)]


def test_order_by_mtime_only_when_nothing_matches(home):
    pfx = setup_flatpak(home)
    d = users(pfx) / "Documents"
    a = put(d / "A/s.sav", mtime=100).parent
    b = put(d / "B/s.sav", mtime=300).parent
    c = put(d / "C/s.sav", mtime=200).parent
    assert saves(home)["candidates"] == [str(b), str(c), str(a)]


def test_name_from_the_slug_column_and_the_shortcut_name(home):
    pfx = setup_flatpak(home)
    d = users(pfx) / "Documents"
    put(d / "Nuevo/s.sav", mtime=9_000_000)
    target = put(d / "Hollow Knight/s.sav", mtime=10).parent
    con = sqlite3.connect(home / FLATPAK / "pga.db")
    con.execute("ALTER TABLE games ADD COLUMN slug TEXT")
    con.execute("UPDATE games SET slug = 'hollow-knight-edition'")
    con.commit()
    con.close()
    assert saves(home)["candidates"][0] == str(target)
    con = sqlite3.connect(home / FLATPAK / "pga.db")
    con.execute("UPDATE games SET slug = 'otro'")
    con.commit()
    con.close()
    assert saves(home)["candidates"][0] != str(target)
    assert saves(home, name="Hollow Knight")["candidates"][0] == str(target)  # nombre del atajo


def test_nested_candidates_keep_the_most_specific(home):
    pfx = setup_flatpak(home)
    g = users(pfx) / "Documents/Juego"
    put(g / "Saves/a.sav")
    put(g / "Saves/Profile/Save/b.sav")  # no se entra en una carpeta de guardado ya hallada: solo Saves
    assert saves(home)["candidates"] == [str(g / "Saves")]


def test_nested_candidates_prefer_ancestor_with_more_own_files():
    a = {"path": "/x/A", "files": 20, "mtime": 0, "score": 0}
    b = {"path": "/x/A/B", "files": 3, "mtime": 0, "score": 0}
    assert [c["path"] for c in lu._prune_nested([a, b])] == ["/x/A"]
    a2 = {"path": "/x/A", "files": 5, "mtime": 0, "score": 0}
    assert [c["path"] for c in lu._prune_nested([a2, b])] == ["/x/A/B"]


def test_walk_limits_stop_the_search(home, monkeypatch):
    pfx = setup_flatpak(home)
    for i in range(30):
        put(users(pfx) / f"Documents/J{i:02d}/s.sav")
    monkeypatch.setattr(lu, "MAX_DIRS", 5)
    assert len(saves(home)["candidates"]) < 30
    monkeypatch.setattr(lu, "MAX_DIRS", 3000)
    monkeypatch.setattr(lu, "MAX_SECONDS", -1.0)  # tiempo ya agotado: sin candidatos, sin colgarse
    assert saves(home)["candidates"] == []


def test_entries_per_folder_are_capped(home, monkeypatch):
    pfx = setup_flatpak(home)
    for i in range(20):
        put(users(pfx) / f"Documents/J{i:02d}/s.sav")
    monkeypatch.setattr(lu, "MAX_ENTRIES", 4)
    assert len(saves(home)["candidates"]) <= 4


def test_unexpected_error_gives_no_candidates_without_raising(home, monkeypatch):
    pfx = setup_flatpak(home)
    put(users(pfx) / "Documents/J/s.sav")
    monkeypatch.setattr(lu, "_game_folders", lambda *a, **k: 1 / 0)
    logs = []
    out = saves(home, log=logs.append)
    assert out["candidates"] == [] and out["prefix"] == str(pfx) and all(str(home) not in m for m in logs)


def test_search_writes_nothing(home):
    pfx = setup_flatpak(home)
    dq7(pfx)

    def snapshot(root):
        return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size if p.is_file() else 0) for p in sorted(root.rglob("*"))}

    before = snapshot(home)
    saves(home)
    assert snapshot(home) == before
