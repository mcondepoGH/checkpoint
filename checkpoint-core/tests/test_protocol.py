"""Compatibilidad por protocolo (enteros) entre un cliente (plugin o CLI) y el hub."""

import pytest

from checkpoint_core.protocol import KEY_PREFIX, compat, parse_protocol


@pytest.mark.parametrize(
    ("own", "hub", "minimum", "res"),
    [
        (1, 1, 1, "ok"),
        (2, 3, 2, "ok"),
        (1, 3, 2, "plugin_outdated"),
        (0, 1, 1, "plugin_outdated"),
        (1, None, 1, "hub_old"),
        (1, 1, None, "hub_old"),
        (None, None, None, "hub_old"),  # el hub viejo manda antes que un protocolo propio desconocido
        (None, 1, 1, "plugin_unknown"),
    ],
)
def test_compat(own, hub, minimum, res):
    assert compat(own, hub, minimum) == res


def test_parse_protocol_only_accepts_non_negative_ints():
    assert parse_protocol(0) == 0 and parse_protocol(3) == 3
    for bad in (None, -1, True, 1.5, "1", [], {}):
        assert parse_protocol(bad) is None


def test_key_prefix():
    assert KEY_PREFIX == "ckd_"
