"""Versión semver: validación y comparación (precedencia de semver.org). Compartida por el plugin y el cliente."""

import pytest

from checkpoint_core.version import compare, is_newer, parse_semver


@pytest.mark.parametrize(
    "v", ["0.1.0", "1.2.3", "10.20.30", "1.0.0-rc.1", "1.0.0-alpha", "1.0.0+build.5", "1.0.0-rc.1+b"]
)
def test_parse_valid(v):
    assert parse_semver(v) is not None


@pytest.mark.parametrize(
    "v",
    [
        "",
        "1",
        "1.2",
        "1.2.3.4",
        "01.2.3",
        "1.02.3",
        "v1.2.3",
        "1.2.x",
        "1.2.3-",
        "1.2.3-01",
        " 1.2.3",
        None,
        5,
        "1.0.0-a..b",
        "9" * 70,
    ],
)
def test_parse_invalid(v):
    assert parse_semver(v) is None


def test_parse_returns_numbers_and_pre_release():
    assert parse_semver("1.2.3") == ((1, 2, 3), None)
    assert parse_semver("1.2.3-rc.1+b") == ((1, 2, 3), ("rc", "1"))


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


def test_compare_invalid_raises():
    with pytest.raises(ValueError):
        compare("basura", "1.0.0")


def test_is_newer_false_for_equal_older_or_invalid():
    assert is_newer("0.2.0", "0.1.0")
    assert is_newer("1.0.0", "0.2.9")  # primera versión estable sobre la última 0.2.x
    assert not is_newer("0.1.0", "0.1.0")
    assert not is_newer("0.0.9", "0.1.0")
    assert not is_newer("1.0.0-rc.1", "1.0.0")
    assert not is_newer("basura", "0.1.0")  # versión remota no válida: no se ofrece
    assert not is_newer("0.2.0", "basura")  # local ilegible: no se ofrece nada a ciegas
