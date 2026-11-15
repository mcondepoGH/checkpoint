"""`POST /api/steam/library` y `refresh_library` contra un hub falso."""

import json

import pytest

import checkpoint_client as hc

KEY = "ckd_" + "k" * 40
SUMMARY = {"associated": [{"appid": 220, "game": "hl2"}], "suggested": 1, "unchanged": 2, "ignored": 3}


def games():
    return [(220, "Half-Life 2"), (730, "Counter-Strike 2")]


def ok_handler(req):
    return 200, SUMMARY, {}


def test_post_library_sends_bearer_and_exact_body(scripthub):
    hub = scripthub(ok_handler)
    r = hc.refresh_library(hub.url, KEY, lambda: games())
    assert r == ("ok", {"found": 2, "associated": 1, "suggested": 1, "unchanged": 2, "ignored": 3})
    (req,) = hub.requests
    assert req.method == "POST" and req.path == "/api/steam/library"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(req.body) == {"games": [{"appid": 220, "name": "Half-Life 2"}, {"appid": 730, "name": "Counter-Strike 2"}]}
    assert KEY not in req.path


def test_not_linked():
    assert hc.refresh_library("", None, lambda: games()) == ("not_linked", {})
    assert hc.refresh_library("http://x", None, lambda: games()) == ("not_linked", {})


def test_no_steam_found_sends_nothing(scripthub):
    hub = scripthub(ok_handler)
    assert hc.refresh_library(hub.url, KEY, lambda: []) == ("no_steam", {})
    assert hub.requests == []


def test_unauthorized(scripthub):
    hub = scripthub(lambda r: (401, {"detail": {"code": "err.auth.invalid", "params": {}}}, {}))
    assert hc.refresh_library(hub.url, KEY, lambda: games())[0] == "unauthorized"
    assert len(hub.requests) == 1  # un 401 no se reintenta


def test_rate_limited_reports_wait(scripthub):
    hub = scripthub(lambda r: (429, {"detail": {"code": "err.main.rate_limited", "params": {}}}, {"Retry-After": "120"}))
    res, data = hc.refresh_library(hub.url, KEY, lambda: games(), sleep=lambda s: None)
    assert res == "rate_limited" and data["wait_s"] == 120
    assert len(hub.requests) == 1  # espera demasiado larga: no se duerme, se avisa


def test_config_changed_retries_once(scripthub):
    calls = []

    def h(req):
        calls.append(1)
        if len(calls) == 1:
            return 409, {"detail": {"code": "err.main.config_changed", "params": {}}}, {}
        return 200, SUMMARY, {}

    hub = scripthub(h)
    assert hc.refresh_library(hub.url, KEY, lambda: games())[0] == "ok"
    assert len(calls) == 2


def test_config_changed_twice_is_error(scripthub):
    hub = scripthub(lambda r: (409, {"detail": {"code": "err.main.config_changed", "params": {}}}, {}))
    assert hc.refresh_library(hub.url, KEY, lambda: games())[0] == "config_changed"
    assert len(hub.requests) == 2


def test_connection_down():
    res = hc.refresh_library("http://127.0.0.1:1", KEY, lambda: games(), sleep=lambda s: None)
    assert res[0] == "connection"
    assert "[POST /api/steam/library]" in res[1]["detail"]  # el detalle dice qué endpoint falló, sin servidor
    assert "127.0.0.1" not in res[1]["detail"]


@pytest.mark.parametrize("status", [400, 413, 422, 409])
def test_other_errors_are_hub_error(scripthub, status):
    hub = scripthub(lambda r: (status, {"detail": {"code": "err.steam.x", "params": {}}}, {}))
    res, data = hc.refresh_library(hub.url, KEY, lambda: games())
    assert res == "hub_error" and data["code"] == "err.steam.x"
    assert data["detail"] == f"HubApiError: estado {status}, código err.steam.x [POST /api/steam/library]"


def test_failure_is_logged_with_status_and_endpoint_without_secrets(scripthub):
    hub = scripthub(lambda r: (500, {"detail": {"code": "err.steam.x", "params": {}}}, {}))
    logs = []
    hc.refresh_library(hub.url, KEY, lambda: games(), sleep=lambda s: None, log=logs.append)
    assert logs and "estado 500" in logs[0] and "POST /api/steam/library" in logs[0]
    assert all(KEY not in m and hub.url not in m for m in logs)
