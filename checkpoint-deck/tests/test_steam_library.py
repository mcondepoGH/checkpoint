"""Biblioteca de Steam: parser de VDF/ACF, descubrimiento de bibliotecas y lectura de `appmanifest_*.acf`."""

import shutil
from pathlib import Path

import pytest

import checkpoint_steam as sl

FIX = Path(__file__).parent / "fixtures" / "steam"


@pytest.fixture
def deck(tmp_path):
    """Copia de la fixture con las rutas de `libraryfolders.vdf` apuntando a la copia."""
    root = tmp_path / "deck"
    shutil.copytree(FIX, root)
    vdf = root / "home/.local/share/Steam/steamapps/libraryfolders.vdf"
    vdf.write_text(vdf.read_text().replace("@HOME@", str(root / "home")).replace("@ROOT@", str(root)))
    return root


# ---- parser
def test_parse_basic_nested():
    d = sl.parse_vdf('"a" { "b" "c" "d" { "e" "f" } }')
    assert d == {"a": {"b": "c", "d": {"e": "f"}}}


def test_parse_escapes_comments_and_blank_lines():
    d = sl.parse_vdf('// hola\n\n"k"\t"a \\"q\\" \\\\ \\n"  // fin\n')
    assert d == {"k": 'a "q" \\ \n'}


def test_parse_bom_and_unquoted():
    assert sl.parse_vdf('﻿"k" v\nw "x"') == {"k": "v", "w": "x"}


def test_parse_keys_lowercased():
    assert sl.parse_vdf('"AppID" "5"') == {"appid": "5"}


@pytest.mark.parametrize("bad", ['"a" {', '"a" "b" }', '"a', '{ "a" "b" }', '"a"', ""])
def test_parse_errors_raise(bad):
    with pytest.raises(sl.VdfError):
        sl.parse_vdf(bad)


def test_parse_depth_limit():
    with pytest.raises(sl.VdfError):
        sl.parse_vdf('"a" {' * 100 + "}" * 100)


# ---- descubrimiento
def test_roots_found_in_home(deck):
    roots = sl.find_steam_roots(deck / "home")
    assert roots == [deck / "home/.local/share/Steam"]


def test_roots_dedup_symlink(deck):
    (deck / "home/.steam").mkdir()
    (deck / "home/.steam/steam").symlink_to(deck / "home/.local/share/Steam")
    assert len(sl.find_steam_roots(deck / "home")) == 1


def test_library_dirs_include_extra_and_skip_missing(deck):
    dirs = sl.library_dirs(deck / "home/.local/share/Steam")
    assert dirs == [
        deck / "home/.local/share/Steam/steamapps",
        deck / "card/steamapps",
        deck / "empty/steamapps",
    ]


def test_library_dirs_without_vdf_uses_root(tmp_path):
    (tmp_path / "steamapps").mkdir()
    assert sl.library_dirs(tmp_path) == [tmp_path / "steamapps"]


def test_library_dirs_corrupt_vdf_falls_back_to_root(tmp_path):
    (tmp_path / "steamapps").mkdir()
    (tmp_path / "steamapps/libraryfolders.vdf").write_text('"x" {')
    assert sl.library_dirs(tmp_path) == [tmp_path / "steamapps"]


# ---- lectura
def test_scan_root_reads_all_libraries(deck):
    games = sl.scan_steam_root(deck / "home/.local/share/Steam")
    assert dict(games) == {
        220: "Half-Life 2",  # la primera biblioteca gana el duplicado
        1245620: 'ELDEN RING "Shadow" \\ Ñandú',  # con BOM y escapes
        730: "Counter-Strike 2",
    }
    # descartados: sin nombre (555), truncado (999), appid 0


def test_scan_never_returns_more_than_appid_and_name(deck):
    for g in sl.scan_steam_root(deck / "home/.local/share/Steam"):
        assert isinstance(g[0], int) and isinstance(g[1], str) and len(g) == 2


def test_scan_cap(tmp_path):
    apps = tmp_path / "steamapps"
    apps.mkdir()
    for i in range(1, 12):
        (apps / f"appmanifest_{i}.acf").write_text(f'"AppState" {{ "appid" "{i}" "name" "G{i}" }}')
    assert len(sl.scan_steam_root(tmp_path, limit=5)) == 5


def test_scan_name_trimmed_and_cut_to_200(tmp_path):
    apps = tmp_path / "steamapps"
    apps.mkdir()
    (apps / "appmanifest_1.acf").write_text('"AppState" { "appid" "1" "name" "  ' + "x" * 300 + '  " }')
    ((_, name),) = sl.scan_steam_root(tmp_path)
    assert name == "x" * 200


def test_scan_appid_in_filename_must_match_content(tmp_path):
    apps = tmp_path / "steamapps"
    apps.mkdir()
    (apps / "appmanifest_7.acf").write_text('"AppState" { "appid" "8" "name" "Otro" }')
    assert sl.scan_steam_root(tmp_path) == [(8, "Otro")]


def test_scan_appid_invalid_values(tmp_path):
    apps = tmp_path / "steamapps"
    apps.mkdir()
    for i, v in enumerate(["-3", "abc", "1.5", "", "99999999999999999999"]):
        (apps / f"appmanifest_{i + 1}.acf").write_text('"AppState" { "appid" "%s" "name" "N" }' % v)
    assert sl.scan_steam_root(tmp_path) == []


def test_scan_ignores_unreadable_and_huge(tmp_path):
    apps = tmp_path / "steamapps"
    apps.mkdir()
    (apps / "appmanifest_1.acf").write_bytes(b"\xff\xfe\x00bad")
    (apps / "appmanifest_2.acf").write_text('"AppState" { "appid" "2" "name" "' + "a" * 300_000 + '" }')
    (apps / "appmanifest_3.acf").write_text('"AppState" { "appid" "3" "name" "Bien" }')
    assert sl.scan_steam_root(tmp_path) == [(3, "Bien")]


def test_scan_all_dedups_across_roots_and_sorted_by_appid(deck):
    games = sl.scan_library(deck / "home")
    assert [a for a, _ in games] == [220, 730, 1245620]


def test_scan_all_no_steam(tmp_path):
    assert sl.scan_library(tmp_path) == []


def test_unreadable_extra_library_does_not_break_scan(tmp_path):
    """Regresión: en Python 3.11 `is_dir()` de una carpeta sin permiso lanzaba PermissionError y tumbaba el escaneo."""
    import os

    import pytest

    if os.geteuid() == 0:
        pytest.skip("root ignora los permisos")
    root = tmp_path / "home" / ".local/share/Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps" / "appmanifest_10.acf").write_text('"AppState" { "appid" "10" "name" "Uno" }')
    sd = tmp_path / "sd"
    (sd / "steamapps").mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(f'"libraryfolders" {{ "0" {{ "path" "{sd}" }} }}')
    sd.chmod(0)
    logs = []
    try:
        assert sl.scan_library(tmp_path / "home", log=logs.append) == [(10, "Uno")]
    finally:
        sd.chmod(0o755)
    assert any("se omite" in m and str(sd) in m for m in logs)
