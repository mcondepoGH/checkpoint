"""Atajos de Steam (juegos que no son de Steam, p. ej. Lutris): lector de `shortcuts.vdf` (VDF binario).

Los ficheros de estos tests son SINTÉTICOS: se construyen aquí byte a byte según el formato público del VDF binario.
No son capturas de una Deck real (formato real y ids en una Deck: no verificado)."""

import struct
import zlib

import pytest

import checkpoint_shortcuts as sc


def s(key, val):
    return b"\x01" + key.encode() + b"\x00" + val.encode() + b"\x00"


def i(key, val):
    return b"\x02" + key.encode() + b"\x00" + struct.pack("<I", val)


def d(key, body):
    return b"\x00" + key.encode() + b"\x00" + body + b"\x08"


def entry(idx, appid=None, name="Juego", exe='"/usr/bin/lutris"', start='"/home/deck"', extra=b""):
    body = b""
    if appid is not None:
        body += i("appid", appid)
    body += s("AppName", name) + s("Exe", exe) + s("StartDir", start) + extra
    body += d("tags", s("0", "favorito"))  # subdiccionario: el lector lo salta sin romperse
    return d(str(idx), body)


def vdf(*entries):
    return d("shortcuts", b"".join(entries)) + b"\x08"


def put(home, user, data):
    p = home / ".local/share/Steam/userdata" / user / "config"
    p.mkdir(parents=True)
    (p / "shortcuts.vdf").write_bytes(data)
    return home / ".local/share/Steam"


# ---- parser
def test_parse_returns_name_appid_exe_startdir():
    out = sc.parse_shortcuts(vdf(entry(0, appid=3000000001, name="Mi Juego")))
    assert out == [sc.Shortcut(3000000001, "Mi Juego", '"/usr/bin/lutris"', '"/home/deck"')]


def test_parse_appid_is_unsigned_up_to_2_pow_32():
    out = sc.parse_shortcuts(vdf(entry(0, appid=2**32 - 1)))
    assert out[0].appid == 2**32 - 1


def test_parse_keys_case_insensitive():
    raw = d("shortcuts", d("0", i("AppID", 3000000002) + s("appname", "X") + s("EXE", "e"))) + b"\x08"
    assert sc.parse_shortcuts(raw) == [sc.Shortcut(3000000002, "X", "e", "")]


def test_parse_many_entries_in_order():
    out = sc.parse_shortcuts(vdf(entry(0, 3000000001, "A"), entry(1, 3000000002, "B")))
    assert [x.name for x in out] == ["A", "B"]


def test_parse_entry_without_appid_has_appid_none():
    assert sc.parse_shortcuts(vdf(entry(0, None, "Sin id")))[0].appid is None


def test_parse_unicode_name():
    assert sc.parse_shortcuts(vdf(entry(0, 3000000001, "Ñandú ★")))[0].name == "Ñandú ★"


def test_parse_skips_unknown_value_types_of_known_size():
    extra = b"\x07big\x00" + struct.pack("<Q", 5) + b"\x03fl\x00" + struct.pack("<f", 1.5)
    assert sc.parse_shortcuts(vdf(entry(0, 3000000001, extra=extra)))[0].appid == 3000000001


@pytest.mark.parametrize(
    "bad",
    [b"", b"\x00", b"\x00shortcuts\x00", b"\x09junk\x00", b"\xff" * 50, vdf(entry(0, 3000000001))[:-7], b"\x01k\x00v"],
)
def test_parse_corrupt_raises(bad):
    with pytest.raises(sc.ShortcutsError):
        sc.parse_shortcuts(bad)


def test_parse_depth_limit():
    raw = b"".join(b"\x00a\x00" for _ in range(100)) + b"\x08" * 100
    with pytest.raises(sc.ShortcutsError):
        sc.parse_shortcuts(raw)


def test_parse_no_shortcuts_key_is_empty():
    assert sc.parse_shortcuts(d("otra", b"") + b"\x08") == []


# ---- id derivado (no verificado)
def test_derive_appid_formula_is_crc32_or_high_bit():
    exe, name = '"/usr/bin/lutris"', "Mi Juego"
    assert sc.derive_appid(exe, name) == (zlib.crc32((exe + name).encode()) | 0x80000000)
    assert sc.derive_appid(exe, name) >= 2**31


# ---- escaneo
def test_scan_reads_all_steam_users_and_dedups(tmp_path):
    root = put(tmp_path, "111", vdf(entry(0, 3000000001, "A"), entry(1, 3000000002, "B")))
    put(tmp_path, "222", vdf(entry(0, 3000000002, "B repetido"), entry(1, 3000000003, "C")))
    assert sc.scan_shortcuts(root) == [(3000000001, "A"), (3000000002, "B"), (3000000003, "C")]


def test_scan_no_userdata_or_no_file_is_empty(tmp_path):
    assert sc.scan_shortcuts(tmp_path / "nada") == []
    (tmp_path / "userdata/111/config").mkdir(parents=True)
    assert sc.scan_shortcuts(tmp_path) == []


def test_scan_corrupt_file_is_skipped_and_logged_without_breaking_others(tmp_path):
    root = put(tmp_path, "111", b"basura")
    put(tmp_path, "222", vdf(entry(0, 3000000005, "Bueno")))
    logs = []
    assert sc.scan_shortcuts(root, log=logs.append) == [(3000000005, "Bueno")]
    assert len(logs) == 1 and "111" not in logs[0]  # sin steamid en el log


def test_scan_ignores_invalid_ids_and_names(tmp_path):
    raw = vdf(
        entry(0, 0, "Cero"),
        entry(1, 3000000001, "   "),
        entry(2, None, "Sin id"),
        entry(3, 3000000002, "Bueno  "),
    )
    root = put(tmp_path, "111", raw)
    logs = []
    assert sc.scan_shortcuts(root, log=logs.append) == [(3000000002, "Bueno")]
    assert any("no trae appid" in m for m in logs)


def test_scan_name_cut_to_200(tmp_path):
    root = put(tmp_path, "111", vdf(entry(0, 3000000001, "x" * 500)))
    assert len(sc.scan_shortcuts(root)[0][1]) == 200


def test_scan_derives_missing_appid_only_when_asked(tmp_path):
    root = put(tmp_path, "111", vdf(entry(0, None, "Sin id")))
    assert sc.scan_shortcuts(root) == []
    got = sc.scan_shortcuts(root, derive_missing=True)
    assert got == [(sc.derive_appid('"/usr/bin/lutris"', "Sin id"), "Sin id")]


def test_scan_huge_file_is_ignored(tmp_path):
    root = put(tmp_path, "111", b"\x00" * (sc.MAX_FILE + 10))
    assert sc.scan_shortcuts(root) == []


def test_scan_limit(tmp_path):
    root = put(tmp_path, "111", vdf(*[entry(n, 3000000000 + n, f"J{n}") for n in range(10)]))
    assert len(sc.scan_shortcuts(root, limit=3)) == 3


def test_scan_non_numeric_user_folders_ignored(tmp_path):
    root = put(tmp_path, "abc", vdf(entry(0, 3000000001, "A")))
    assert sc.scan_shortcuts(root) == []


# ---- LaunchOptions (para sugerir carpeta en los atajos de Lutris)
def test_parse_keeps_launch_options():
    out = sc.parse_shortcuts(vdf(entry(0, appid=3000000001, name="L", extra=s("LaunchOptions", "run net.lutris.Lutris lutris:rungameid/1"))))
    assert out[0].launch_options == "run net.lutris.Lutris lutris:rungameid/1"
    assert sc.parse_shortcuts(vdf(entry(0, appid=3000000001)))[0].launch_options == ""


def test_find_launch_options_looks_up_by_appid_in_every_user(tmp_path):
    root = put(tmp_path, "111", vdf(entry(0, appid=3000000001, name="A", extra=s("LaunchOptions", "lutris:rungameid/1"))))
    put(tmp_path, "222", vdf(entry(0, appid=3000000002, name="B", extra=s("LaunchOptions", "otra"))))
    assert sc.find_launch_options(root, 3000000001) == "lutris:rungameid/1"
    assert sc.find_launch_options(root, 3000000002) == "otra"
    assert sc.find_launch_options(root, 3000000009) is None


def test_find_launch_options_ignores_broken_files(tmp_path):
    root = put(tmp_path, "111", b"\x00basura")
    assert sc.find_launch_options(root, 3000000001) is None
    assert sc.find_launch_options(tmp_path / "nada", 1) is None
