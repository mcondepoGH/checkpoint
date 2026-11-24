"""Versión propia del plugin y protocolo, leídos del package.json en ejecución (la comparación semver se prueba en checkpoint-core)."""

import json

import pytest

from checkpoint_core.version import parse_semver
from checkpoint_version import plugin_dir, read_version


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
