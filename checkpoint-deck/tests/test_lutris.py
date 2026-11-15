"""Carpeta sugerida para un atajo de Lutris: LaunchOptions -> pga.db -> .yml -> prefijo.

Todo SINTÉTICO (pga.db y .yml creados en tmp_path, usuario ficticio `deck`). Modelado sobre lo verificado en una Deck real
con Lutris Flatpak. Lutris NATIVO (~/.local/share/lutris, ~/.config/lutris): no verificado en una Deck real."""

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
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)


def test_native_data_dir_is_supported(home):
    pfx = home / "Games" / "nat"
    pfx.mkdir(parents=True)
    make_db(home / NATIVE, ((1, "J", "wine", str(pfx), "j-1"),))
    make_yml(home / NATIVE / "games", "j-1", str(pfx))
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)


def test_native_old_layout_yml_in_config_dir(home):
    pfx = home / "Games" / "old"
    pfx.mkdir(parents=True)
    make_db(home / NATIVE, ((1, "J", "wine", "/nonexistent-dir", "j-1"),))
    make_yml(home / ".config/lutris/games", "j-1", str(pfx))
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)


def test_flatpak_wins_over_native(home):
    pfx = setup_flatpak(home)
    other = home / "Games" / "other"
    other.mkdir()
    make_db(home / NATIVE, ((1, "J", "wine", str(other), "j-1"),))
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)


def test_falls_back_to_directory_when_yml_missing(home):
    pfx = home / "Games" / "pfx"
    pfx.mkdir(parents=True)
    make_db(home / FLATPAK, ((1, "J", "wine", str(pfx), "j-1"),))  # sin games/
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)


def test_falls_back_to_directory_when_yml_has_no_prefix(home):
    pfx = setup_flatpak(home, yml_prefix=None)
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)


def test_falls_back_to_directory_when_prefix_does_not_exist(home):
    pfx = setup_flatpak(home, yml_prefix=str(home / "Games" / "gone"))
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)


def test_prefix_wins_over_directory_when_both_exist(home):
    a = home / "Games" / "a"
    a.mkdir(parents=True)
    pfx = setup_flatpak(home, yml_prefix=str(a))
    assert pfx != a and lu.suggest_prefix(home, LAUNCH) == str(a)


def test_nothing_exists_gives_empty(home):
    setup_flatpak(home, yml_prefix=str(home / "g1"), directory=str(home / "g2"))
    assert lu.suggest_prefix(home, LAUNCH) == ""


def test_yml_quoted_values(home):
    pfx = home / "Games" / "it's here"
    pfx.mkdir(parents=True)
    data = home / FLATPAK
    make_db(data, ((1, "J", "wine", "/nope", "j-1"),))
    (data / "games").mkdir()
    (data / "games" / "j-1.yml").write_text("game:\n  exe: 'x'\n  prefix: '" + str(pfx).replace("'", "''") + "'\nname: J\n")
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)
    (data / "games" / "j-1.yml").write_text('game:\n  prefix: "' + str(pfx) + '"\n')
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)


def test_yml_prefix_outside_game_section_is_ignored(home):
    pfx = home / "Games" / "pfx"
    pfx.mkdir(parents=True)
    other = home / "Games" / "other"
    other.mkdir()
    data = home / FLATPAK
    make_db(data, ((1, "J", "wine", str(pfx), "j-1"),))
    (data / "games").mkdir()
    (data / "games" / "j-1.yml").write_text(f"wine:\n  prefix: {other}\ngame:\n  exe: x\nsystem:\n  prefix: {other}\n")
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)


def test_row_selected_by_game_id(home):
    a, b = home / "Games" / "a", home / "Games" / "b"
    a.mkdir(parents=True)
    b.mkdir()
    make_db(home / FLATPAK, ((1, "A", "wine", str(a), "a"), (2, "B", "wine", str(b), "b")))
    assert lu.suggest_prefix(home, "lutris:rungameid/2") == str(b)
    assert lu.suggest_prefix(home, "lutris:rungameid/3") == ""


# ---- no Lutris
@pytest.mark.parametrize("opts", ["", "--fullscreen", "lutris:slug-sin-id", "run net.lutris.Lutris lutris:rungameid/x", None])
def test_non_lutris_gives_empty(home, opts):
    setup_flatpak(home)
    assert lu.suggest_prefix(home, opts) == ""


# ---- robustez
def test_missing_db_gives_empty_and_creates_nothing(home):
    assert lu.suggest_prefix(home, LAUNCH) == ""
    assert not (home / FLATPAK).exists() and not (home / NATIVE).exists()


def test_corrupt_db_gives_empty(home):
    d = home / FLATPAK
    d.mkdir(parents=True)
    (d / "pga.db").write_bytes(b"esto no es sqlite" * 50)
    assert lu.suggest_prefix(home, LAUNCH) == ""


def test_empty_file_db_gives_empty(home):
    d = home / FLATPAK
    d.mkdir(parents=True)
    (d / "pga.db").write_bytes(b"")
    assert lu.suggest_prefix(home, LAUNCH) == ""
    assert (d / "pga.db").stat().st_size == 0  # no escribe


def test_db_without_games_table_gives_empty(home):
    d = home / FLATPAK
    d.mkdir(parents=True)
    sqlite3.connect(d / "pga.db").execute("CREATE TABLE otra (x)").connection.commit()
    assert lu.suggest_prefix(home, LAUNCH) == ""


def test_locked_db_gives_empty(home):
    pfx = setup_flatpak(home)
    con = sqlite3.connect(home / FLATPAK / "pga.db", isolation_level=None)
    con.execute("BEGIN EXCLUSIVE")
    try:
        assert lu.suggest_prefix(home, LAUNCH) in ("", str(pfx))  # sin excepción, con o sin lock
    finally:
        con.execute("ROLLBACK")
        con.close()


def test_does_not_write_to_the_db_or_leave_journal(home):
    setup_flatpak(home)
    d = home / FLATPAK
    before = {p.name: p.read_bytes() for p in d.iterdir() if p.is_file()}
    mtime = (d / "pga.db").stat().st_mtime_ns
    lu.suggest_prefix(home, LAUNCH)
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
    lu.suggest_prefix(home, LAUNCH)
    assert seen and all("mode=ro" in t and uri is True for t, uri in seen)


def test_db_path_with_special_chars_still_opens(home):
    h = home / "my dir#1?x"
    h.mkdir()
    pfx = setup_flatpak(h)
    assert lu.suggest_prefix(h, LAUNCH) == str(pfx)


def test_huge_yml_is_ignored(home):
    pfx = home / "Games" / "pfx"
    pfx.mkdir(parents=True)
    data = home / FLATPAK
    make_db(data, ((1, "J", "wine", str(pfx), "j-1"),))
    (data / "games").mkdir()
    (data / "games" / "j-1.yml").write_text("game:\n  prefix: /x\n" + "#" * (lu.MAX_YML + 10))
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)


@pytest.mark.parametrize("cfg", ["../../evil", "a/b", "..", "", None, 5])
def test_configpath_with_traversal_is_not_followed(home, cfg):
    pfx = home / "Games" / "pfx"
    pfx.mkdir(parents=True)
    data = home / FLATPAK
    make_db(data, ((1, "J", "wine", str(pfx), cfg),))
    evil = home / "evil.yml"
    evil.write_text("game:\n  prefix: /etc\n")
    assert lu.suggest_prefix(home, LAUNCH) == str(pfx)


# ---- validación de la ruta
def test_prefix_outside_home_is_rejected(home, tmp_path):
    outside = tmp_path / "otro" / "pfx"
    outside.mkdir(parents=True)
    setup_flatpak(home, yml_prefix=str(outside), directory=str(outside))
    assert lu.suggest_prefix(home, LAUNCH) == ""


def test_system_or_forbidden_prefix_is_rejected(home):
    setup_flatpak(home, yml_prefix="/etc", directory=str(home))
    assert lu.suggest_prefix(home, LAUNCH) == ""


def test_relative_prefix_is_rejected(home):
    setup_flatpak(home, yml_prefix="Games/pfx", directory="Games/pfx")
    assert lu.suggest_prefix(home, LAUNCH) == ""


def test_dotdot_prefix_is_rejected(home):
    (home / "Games" / "pfx").mkdir(parents=True)
    setup_flatpak(home, yml_prefix=f"{home}/Games/../Games/pfx", directory="/nope")
    assert lu.suggest_prefix(home, LAUNCH) == ""


def test_symlink_prefix_is_rejected(home):
    real = home / "Games" / "real"
    real.mkdir(parents=True)
    link = home / "Games" / "link"
    link.symlink_to(real)
    setup_flatpak(home, yml_prefix=str(link), directory="/nope")
    assert lu.suggest_prefix(home, LAUNCH) == ""


def test_protected_dirs_are_respected(home):
    pfx = setup_flatpak(home)
    assert lu.suggest_prefix(home, LAUNCH, protected=[pfx]) == ""


def test_accept_filter_can_reject_a_candidate(home):
    pfx = setup_flatpak(home)
    assert lu.suggest_prefix(home, LAUNCH, accept=lambda s: False) == ""
    assert lu.suggest_prefix(home, LAUNCH, accept=lambda s: s == str(pfx)) == str(pfx)


def test_log_has_no_paths_or_user_names(home):
    pfx = setup_flatpak(home)
    (home / FLATPAK / "pga.db").write_bytes(b"corrupta" * 40)
    logs = []
    assert lu.suggest_prefix(home, LAUNCH, log=logs.append) == ""
    assert all(str(home) not in m and "deck" not in m and str(pfx) not in m for m in logs)
