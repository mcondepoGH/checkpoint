"""Nombre visible del dispositivo: las mismas reglas que `name_error` del hub."""

import pytest

from checkpoint_core.names import NAME_MAX, DeviceNameError, normalize_device_name


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (None, "empty"),
        (5, "empty"),
        ("", "empty"),
        ("   ", "empty"),
        ("a" * 65, "too_long"),
        ("a/b", "slash"),
        ("a\\b", "slash"),
        ("a  b", "spaces"),
        ("a\x00b", "control"),
        ("a\tb", "control"),
        ("a b", "control"),
        ("a b", "control"),
        ("...", "dots"),
        ("..", "dots"),
    ],
)
def test_invalid(raw, code):
    with pytest.raises(DeviceNameError) as e:
        normalize_device_name(raw)
    assert e.value.code == code


def test_valid_edge_names():
    assert NAME_MAX == 64
    assert normalize_device_name("  Mi PC ") == "Mi PC"
    assert normalize_device_name("a" * 64) == "a" * 64
    assert normalize_device_name("Deck 🎮") == "Deck 🎮"
    assert normalize_device_name("a.b") == "a.b"
    assert normalize_device_name("👨‍👩‍👧") == "👨‍👩‍👧"  # unión de emojis compuestos (U+200D)
