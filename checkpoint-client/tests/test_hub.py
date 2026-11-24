import pytest
from conftest import KEY

from checkpoint_client import hub

PENDING = (200, {"status": "pending", "expires_in": 500}, {})
ACCEPTED = (200, {"status": "accepted", "key": KEY, "device": "pc-ab12"}, {})


# ---- URL
@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("http://192.168.1.10:8088", "http://192.168.1.10:8088"),
        ("  http://hub.local/ ", "http://hub.local"),
        ("https://hub.example.com:443", "https://hub.example.com:443"),
        ("http://[::1]:8088", "http://[::1]:8088"),
    ],
)
def test_normalize_hub_url_ok(raw, out):
    assert hub.normalize_hub_url(raw) == out


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", "empty"),
        (None, "empty"),
        ("ftp://h", "scheme"),
        ("hub:8088", "scheme"),
        ("http://u:p@h", "credentials"),
        ("http://h/api", "path"),
        ("http://h?x=1", "path"),
        ("http://h:99999", "invalid"),
        ("http://h a", "invalid"),
    ],
)
def test_normalize_hub_url_rejects(raw, code):
    with pytest.raises(hub.HubUrlError) as e:
        hub.normalize_hub_url(raw)
    assert e.value.code == code


# ---- nombre del equipo
def test_device_name_rules():
    assert hub.normalize_device_name("  Mi PC ") == "Mi PC"
    for raw, code in [("", "empty"), ("a  b", "spaces"), ("x" * 65, "too_long"), ("a/b", "slash"), ("..", "dots")]:
        with pytest.raises(hub.DeviceNameError) as e:
            hub.normalize_device_name(raw)
        assert e.value.code == code
    assert hub.normalize_device_name("x" * 64) == "x" * 64


def test_default_device_name_is_valid_and_bounded(monkeypatch):
    monkeypatch.setattr("socket.gethostname", lambda: "mi-portatil")
    assert hub.default_device_name() == "mi-portatil"
    monkeypatch.setattr("socket.gethostname", lambda: "x" * 100)
    assert hub.default_device_name() == "x" * 64
    monkeypatch.setattr("socket.gethostname", lambda: "")
    assert hub.default_device_name() == hub.DEVICE_NAME


# ---- redacción
def test_redact_hides_keys_and_secrets():
    text = f"fallo con {KEY} y ck_otra-1 y SECRET-xyz"
    out = hub.redact(text, "SECRET-xyz")
    assert KEY not in out and "ck_otra-1" not in out and "SECRET-xyz" not in out


def test_describe_error_has_no_key():
    e = ValueError(f"clave {KEY}")
    assert KEY not in hub.describe_error(e)


# ---- HTTP
def test_request_json_does_not_follow_redirects(fakehub):
    fakehub.redirect_to = "http://127.0.0.1:9/robado"
    r = hub.create_pairing(fakehub.url, "pc")
    assert r.status == 307
    assert len(fakehub.requests) == 1


def test_request_json_network_error_has_no_url():
    with pytest.raises(hub.HubNetworkError) as e:
        hub.request_json("GET", "http://127.0.0.1:1/api/x")
    assert "127.0.0.1" not in str(e.value)


# ---- vinculación
def pair(fakehub, **kw):
    codes = []
    out = hub.pair(fakehub.url, "pc", on_code=codes.append, sleep=lambda s: None, poll_s=0, **kw)
    return out, codes


def test_pair_accepted_returns_device_and_key(fakehub):
    fakehub.script = [PENDING, ACCEPTED]
    (device, key), codes = pair(fakehub)
    assert (device, key) == ("pc-ab12", KEY)
    assert codes == ["123456"]
    method, path, headers, body = fakehub.requests[0]
    assert (method, path) == ("POST", "/api/pairing/requests")
    assert b'"os": "linux"' in body and b'"name": "pc"' in body
    # El secreto viaja solo en la cabecera al consultar
    assert fakehub.requests[1][2]["X-Pairing-Secret"] == "SECRET-xyz"


@pytest.mark.parametrize(
    ("script", "code"),
    [
        ([(200, {"status": "rejected"}, {})], "rejected"),
        ([(404, {"detail": {"code": "x"}}, {})], "expired"),
        ([(200, {"status": "accepted", "key": "ck_mala", "device": "d"}, {})], "bad_response"),
        ([(200, {"status": "raro"}, {})], "bad_response"),
        ([(400, {"detail": {"code": "x"}}, {})], "hub_error"),
    ],
)
def test_pair_failures(fakehub, script, code):
    fakehub.script = script
    with pytest.raises(hub.PairingError) as e:
        pair(fakehub)
    assert e.value.code == code


def test_pair_expires_by_clock(fakehub):
    fakehub.create = (201, {"id": "r", "code": "111111", "secret": "S", "expires_in": 10}, {})
    fakehub.script = [(200, {"status": "pending"}, {})]
    t = [0.0]

    def sleep(s):
        t[0] += 6

    with pytest.raises(hub.PairingError) as e:
        hub.pair(fakehub.url, "pc", sleep=sleep, clock=lambda: t[0], poll_s=1)
    assert e.value.code == "expired"


@pytest.mark.parametrize(
    ("create", "code", "wait"),
    [
        ((429, {"detail": {"code": "x"}}, {"Retry-After": "7"}), "rate_limited", 7),
        ((503, {"detail": {"code": "x"}}, {"Retry-After": "3"}), "busy", 3),
        ((400, {"detail": {"code": "err.pairing.name_invalid"}}, {}), "name_invalid", 0),
        ((201, {"id": "r"}, {}), "bad_response", 0),
        ((500, None, {}), "hub_error", 0),
    ],
)
def test_pair_create_errors(fakehub, create, code, wait):
    fakehub.create = create
    with pytest.raises(hub.PairingError) as e:
        pair(fakehub)
    assert (e.value.code, e.value.wait_s) == (code, wait)


def test_pair_connection_error():
    with pytest.raises(hub.PairingError) as e:
        hub.pair("http://127.0.0.1:1", "pc", sleep=lambda s: None)
    assert e.value.code == "connection"


def test_pair_retries_network_hiccup_while_polling(fakehub, monkeypatch):
    fakehub.script = [ACCEPTED]
    real = hub.poll_pairing
    calls = []

    def flaky(*a):
        calls.append(1)
        if len(calls) == 1:
            raise hub.HubNetworkError("URLError")
        return real(*a)

    monkeypatch.setattr(hub, "poll_pairing", flaky)
    (device, _), _ = pair(fakehub)
    assert device == "pc-ab12" and len(calls) == 2


# ---- conexión
def test_check_connection_ok_with_compat(fakehub):
    res, data = hub.check_connection(fakehub.url, KEY, client_protocol=1)
    assert res == "ok" and data["device"] == "pc-ab12" and data["compat"] == "ok"
    assert fakehub.requests[0][2]["Authorization"] == f"Bearer {KEY}"


def test_check_connection_outdated_client(fakehub):
    fakehub.ping = (200, {"ok": True, "device": "d", "protocol": 3, "min_plugin_protocol": 2}, {})
    res, data = hub.check_connection(fakehub.url, KEY, client_protocol=1)
    assert res == "ok" and data["compat"] == "plugin_outdated" and data["min_plugin_protocol"] == 2


def test_check_connection_old_hub_without_protocol(fakehub):
    fakehub.ping = (200, {"ok": True, "device": "d"}, {})
    assert hub.check_connection(fakehub.url, KEY, client_protocol=1)[1]["compat"] == "hub_old"


@pytest.mark.parametrize(
    ("ping", "res"),
    [
        ((401, {}, {}), "unauthorized"),
        ((429, {}, {"Retry-After": "5"}), "rate_limited"),
        ((500, None, {}), "hub_error"),
    ],
)
def test_check_connection_errors(fakehub, ping, res):
    fakehub.ping = ping
    assert hub.check_connection(fakehub.url, KEY, client_protocol=1)[0] == res


def test_check_connection_unreachable_and_not_linked():
    assert hub.check_connection("http://127.0.0.1:1", KEY, client_protocol=1)[0] == "connection"
    assert hub.check_connection("", None, client_protocol=1)[0] == "not_linked"
