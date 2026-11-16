"""Juegos instalados (Steam y Lutris) y usuario de Wine: bibliotecas, appmanifest, compatdata, yml y Flatpak frente a nativo.

Todo SINTÉTICO en tmp_path. Lutris nativo no está verificado en una Deck real."""

import os

import pytest

import checkpoint_installed as ci
from savefix import lutris_db, lutris_yml, steam_game, steam_home, write

FP = ".var/app/net.lutris.Lutris/data/lutris"
NAT = ".local/share/lutris"


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home" / "deck"
    h.mkdir(parents=True)
    return h


def test_steam_internal_and_sd_libraries_with_compatdata_next_to_the_game(home, tmp_path):
    sd = tmp_path / "run/media/mmcblk0p1"
    root = steam_home(home, sd)
    steam_game(root, 413150, "Stardew Valley")
    pfx_sd = steam_game(sd, 730, "Counter", installdir="cs")
    (root / "steamapps/compatdata/730/pfx").mkdir(parents=True)  # compatdata en la interna: NO es la de este juego
    games = {g.id: g for g in ci.steam_games(home)}
    assert set(games) == {413150, 730}
    sv, cs = games[413150], games[730]
    assert sv.install == str(root / "steamapps/common/StardewValley")
    assert sv.prefix == str(root / "steamapps/compatdata/413150/pfx")
    assert cs.install == str(sd / "steamapps/common/cs")
    assert cs.prefix == str(pfx_sd)  # la compatdata de la biblioteca del juego (la SD)
    assert cs.prefix != str(root / "steamapps/compatdata/730/pfx")


def test_steam_without_prefix_or_install_dir(home):
    root = steam_home(home)
    steam_game(root, 5, "Nativo", pfx=False)
    (root / "steamapps/common/Nativo").rmdir()
    g = ci.steam_games(home)[0]
    assert g.prefix is None and g.install is None


def test_steam_userdata_glob_over_users(home):
    root = steam_home(home)
    steam_game(root, 9, "Nube")
    (root / "userdata/111/9/remote").mkdir(parents=True)
    (root / "userdata/222/9").mkdir(parents=True)
    (root / "userdata/222/10").mkdir(parents=True)
    g = ci.steam_games(home)[0]
    assert g.userdata == [str(root / "userdata/111/9"), str(root / "userdata/222/9")]


def test_wine_user_symlink_is_resolved_and_public_excluded(tmp_path):
    users = tmp_path / "pfx/drive_c/users"
    (users / "steamuser").mkdir(parents=True)
    (users / "Public").mkdir()
    os.symlink("steamuser", users / "deck")
    assert ci.wine_users(str(tmp_path / "pfx")) == [str(users / "steamuser")]


def test_wine_user_real_name_other_than_steamuser_and_fallback(tmp_path):
    users = tmp_path / "a/drive_c/users"
    (users / "deck").mkdir(parents=True)
    (users / "steamuser").mkdir()
    assert ci.wine_users(str(tmp_path / "a")) == [str(users / "steamuser"), str(users / "deck")]
    assert ci.wine_users(str(tmp_path / "vacio")) == [str(tmp_path / "vacio/drive_c/users/steamuser")]


def make_lutris(home, base, exe_kind="file"):
    pfx = home / "Games/ff6/pfx"
    (pfx / "drive_c").mkdir(parents=True)
    game = home / "Games/ff6/game"
    game.mkdir(parents=True)
    exe = {"file": write(game / "ff6.exe"), "dir": game, "missing": game / "nada.exe"}[exe_kind]
    lutris_db(
        home / base,
        [
            {"id": 1, "name": "Final Fantasy VI", "slug": "final-fantasy-vi", "service": "steam", "service_id": "382330",
             "directory": str(game), "configpath": "ff6-1"},
            {"id": 2, "name": "Borrado", "slug": "borrado", "installed": 0, "configpath": "b"},
        ],
    )  # fmt: skip
    cfg = home / base / "games" if "var/app" in base else home / ".config/lutris/games"
    lutris_yml(cfg, "ff6-1", prefix=pfx, exe=exe)
    return pfx, game, exe


def test_lutris_flatpak_reads_yml_and_skips_uninstalled(home):
    pfx, game, exe = make_lutris(home, FP)
    games = ci.lutris_games(home)
    assert [g.id for g in games] == [1]
    g = games[0]
    assert (g.prefix, g.install, g.steam_appid, g.slug, g.flatpak) == (str(pfx), str(game), 382330, "final-fantasy-vi", True)


def test_lutris_native_when_no_flatpak_and_flatpak_wins_when_both(home):
    pfx, game, _ = make_lutris(home, NAT)
    g = ci.lutris_games(home)[0]
    assert g.flatpak is False and g.prefix == str(pfx)
    lutris_db(home / FP, [{"id": 7, "name": "Otro", "slug": "otro", "configpath": "o"}])
    assert [x.id for x in ci.lutris_games(home)] == [7]


def test_lutris_exe_directory_or_missing_falls_back_to_directory_column_then_drive_c(home):
    pfx, game, exe = make_lutris(home, FP, "dir")
    assert ci.lutris_games(home)[0].install == str(game)  # exe es carpeta: `directory` de la base
    pfx2 = home / "Games/p2"
    (pfx2 / "drive_c").mkdir(parents=True)
    lutris_db(home / FP, [{"id": 3, "name": "Sin dir", "slug": "s", "directory": "/no/existe", "configpath": "s3"}])
    lutris_yml(home / FP / "games", "s3", prefix=pfx2, exe=home / "nada.exe")
    assert ci.lutris_games(home)[0].install == str(pfx2 / "drive_c")  # exe inexistente y directory inexistente


def test_lutris_exe_file_gives_its_dirname(home):
    _, game, exe = make_lutris(home, FP, "file")
    assert ci.lutris_games(home)[0].install == os.path.dirname(str(exe))


def test_lutris_game_without_prefix_is_native_and_slug_falls_back_to_yml(home):
    lutris_db(home / FP, [{"id": 4, "name": "Linux", "slug": None, "runner": "linux", "configpath": "l4"}])
    lutris_yml(home / FP / "games", "l4", prefix=None, slug="linux-game")
    g = ci.lutris_games(home)[0]
    assert g.prefix is None and g.slug == "linux-game"


def test_lutris_database_is_opened_read_only(home):
    make_lutris(home, FP)
    ci.lutris_games(home)
    assert not list((home / FP).glob("pga.db-*"))  # sin -journal ni -wal
