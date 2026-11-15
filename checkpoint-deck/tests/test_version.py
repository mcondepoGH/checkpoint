"""Versión propia del plugin (semver) y protocolo, leídos del package.json en ejecución; comparación de versiones."""

import json

import pytest

from checkpoint_version import compare, is_newer, parse_semver, plugin_dir, read_version


@pytest.mark.parametrize("v", ["0.1.0", "1.2.3", "10.20.30", "1.0.0-rc.1", "1.0.0-alpha", "1.0.0+build.5", "1.0.0-rc.1+b"])
def test_parse_valid(v):
    assert parse_semver(v) is not None


@pytest.mark.parametrize(
    "v", ["", "1", "1.2", "1.2.3.4", "01.2.3", "1.02.3", "v1.2.3", "1.2.x", "1.2.3-", "1.2.3-01", " 1.2.3", None, 5, "1.0.0-a..b", "9" * 70]
)
def test_parse_invalid(v):
    assert parse_semver(v) is None


@pytest.mark.parametrize(
    "a,b,res",
    [
        ("0.1.0", "0.1.0", 0),
        ("0.1.0", "0.1.1", -1),
        ("0.2.0", "0.1.9", 1),
        ("1.0.0", "0.99.99", 1),
        ("0.10.0", "0.9.0", 1),  # numérico, no de texto
        ("1.0.0-rc.1", "1.0.0", -1),  # una pre-release es menor que su release
        ("1.0.0", "1.0.0-rc.1", 1),
        ("1.0.0-alpha", "1.0.0-beta", -1),
        ("1.0.0-rc.2", "1.0.0-rc.10", -1),  # identificador numérico: numérico
        ("1.0.0-1", "1.0.0-a", -1),  # numérico < alfanumérico
        ("1.0.0-rc", "1.0.0-rc.1", -1),  # menos campos < más campos
        ("1.0.0+a", "1.0.0+b", 0),  # los metadatos de build no cuentan
    ],
)
def test_compare(a, b, res):
    assert compare(a, b) == res
    assert compare(b, a) == -res


def test_is_newer_false_for_equal_older_or_invalid():
    assert is_newer("0.2.0", "0.1.0")
    assert is_newer("1.0.0", "0.2.9")  # primera versión estable sobre la última 0.2.x
    assert not is_newer("0.1.0", "0.1.0")
    assert not is_newer("0.0.9", "0.1.0")
    assert not is_newer("1.0.0-rc.1", "1.0.0")
    assert not is_newer("basura", "0.1.0")  # versión remota no válida: no se ofrece
    assert not is_newer("0.2.0", "basura")  # local ilegible: no se ofrece nada a ciegas


def test_read_version(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"version": "0.3.1", "checkpointProtocol": 1}))
    assert read_version(tmp_path) == {"version": "0.3.1", "protocol": 1}


@pytest.mark.parametrize("content", [None, "no es json", "[]", '{"version": 3}', '{"version":"x","checkpointProtocol":"1"}'])
def test_read_version_unreadable_gives_none(tmp_path, content):
    if content is not None:
        (tmp_path / "package.json").write_text(content)
    assert read_version(tmp_path) == {"version": None, "protocol": None}


def test_read_version_bool_protocol_is_not_int(tmp_path):
    (tmp_path / "package.json").write_text('{"version":"1.0.0","checkpointProtocol":true}')
    assert read_version(tmp_path)["protocol"] is None


def test_plugin_dir_prefers_decky_value(tmp_path):
    class D:
        DECKY_PLUGIN_DIR = str(tmp_path / "plug")

    assert plugin_dir(D) == tmp_path / "plug"


def test_plugin_dir_falls_back_next_to_main():
    class D:  # sin DECKY_PLUGIN_DIR
        pass

    d = plugin_dir(D)
    assert (d / "main.py").is_file() and (d / "package.json").is_file()


def test_real_package_json_is_semver_with_protocol():
    """El package.json REAL del plugin: versión propia semver (arranca en 0.1.0) y protocolo entero declarado."""
    from checkpoint_version import PLUGIN_ROOT

    v = read_version(PLUGIN_ROOT)
    assert parse_semver(v["version"]) is not None
    assert v["protocol"] == 1
