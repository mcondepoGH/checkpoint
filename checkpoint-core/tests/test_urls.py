"""URL del hub: `http(s)://host[:puerto]` sin barra final (reglas comunes al plugin de la Deck y al cliente)."""

import pytest

from checkpoint_core.urls import HubUrlError, normalize_hub_url


@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("http://192.168.1.5:8080", "http://192.168.1.5:8080"),
        ("http://192.168.1.5:8080/", "http://192.168.1.5:8080"),
        ("  https://Hub.Casa.LAN/  ", "https://hub.casa.lan"),
        ("  http://hub.local/ ", "http://hub.local"),
        ("https://hub.example.com:443", "https://hub.example.com:443"),
        ("http://hub", "http://hub"),
        ("http://[::1]:9000/", "http://[::1]:9000"),
    ],
)
def test_valid(raw, out):
    assert normalize_hub_url(raw) == out


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", "empty"),
        ("   ", "empty"),
        (None, "empty"),
        ("192.168.1.5:8080", "scheme"),
        ("hub:8088", "scheme"),
        ("ftp://hub", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("http://user:pw@hub", "credentials"),
        ("http://user@hub", "credentials"),
        ("http://hub/api", "path"),
        ("http://hub/?a=1", "path"),
        ("http://hub?x=1", "path"),
        ("http://hub#x", "path"),
        ("http://hub?", "path"),
        ("http://", "invalid"),
        ("http://hub:99999", "invalid"),
        ("http://hub:abc", "invalid"),
        ("http://hu b", "invalid"),
    ],
)
def test_invalid(raw, code):
    with pytest.raises(HubUrlError) as e:
        normalize_hub_url(raw)
    assert e.value.code == code
