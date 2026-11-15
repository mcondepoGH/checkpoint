"""Vinculación contra un hub falso por HTTP real (hilo con `http.server`). Sin esperas reales: `sleep` inyectado."""

import asyncio
import json
import os
import stat


from checkpoint_hub import SETTINGS_FILE, Pairing, check_connection, load_settings, save_settings

KEY = "ckd_" + "k" * 40
ACCEPTED = (200, {"status": "accepted", "device": "steam-deck-ab12", "key": KEY}, {})
PENDING = (200, {"status": "pending", "expires_in": 500}, {})


def make(settings_dir, hub_url, logs=None, sleeps=None):
    async def sleep(s):
        if sleeps is not None:
            sleeps.append(s)
        await asyncio.sleep(0)

    p = Pairing(settings_dir, log=(logs.append if logs is not None else lambda _m: None), sleep=sleep)
    p.set_hub_url(hub_url)
    return p


async def finish(p):
    await asyncio.wait_for(p._task, 10)  # noqa: SLF001


def test_pending_then_accepted_saves_key_0600(fakehub, settings_dir):
    fakehub.script = [PENDING, PENDING, ACCEPTED]
    logs, sleeps = [], []

    async def go():
        p = make(settings_dir, fakehub.url, logs, sleeps)
        p.start()
        await asyncio.sleep(0)
        await finish(p)
        return p

    p = asyncio.run(go())
    st = p.state()
    assert st["status"] == "linked" and st["device"] == "steam-deck-ab12"
    assert KEY not in json.dumps(st)
    assert sleeps and all(s == 3.0 for s in sleeps)  # sondeo cada 3 s
    f = os.path.join(settings_dir, SETTINGS_FILE)
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    assert load_settings(settings_dir)["key"] == KEY
    assert not [n for n in os.listdir(settings_dir) if n.startswith(".settings-")]
    # petición de creación: nombre y sistema
    method, path, _h, body = fakehub.requests[0]
    assert (method, path) == ("POST", "/api/pairing/requests")
    assert json.loads(body) == {"name": "Steam Deck", "os": "linux"}
    # secreto: siempre en cabecera, nunca en la URL, y con el id de la solicitud
    polls = [r for r in fakehub.requests if r[0] == "GET"]
    assert len(polls) == 3
    for _m, path, headers, _b in polls:
        assert path == "/api/pairing/requests/rid1"
        assert "SECRET-xyz" not in path
        assert headers["X-Pairing-Secret"] == "SECRET-xyz"
    # logs: ni clave ni secreto
    joined = "\n".join(logs)
    assert KEY not in joined and "SECRET-xyz" not in joined and "123456" not in joined


def test_waiting_state_shows_code_and_countdown(fakehub, settings_dir):
    fakehub.script = [PENDING]

    async def go():
        p = make(settings_dir, fakehub.url)
        p.start()
        for _ in range(5):
            await asyncio.sleep(0.05)
        st = p.state()
        await p.close()
        return st

    st = asyncio.run(go())
    assert st["status"] == "waiting" and st["code"] == "123456" and 0 < st["seconds_left"] <= 600
    assert "secret" not in json.dumps(st) and "SECRET" not in json.dumps(st)


def test_rejected(fakehub, settings_dir):
    fakehub.script = [(200, {"status": "rejected"}, {})]

    async def go():
        p = make(settings_dir, fakehub.url)
        p.start()
        await asyncio.sleep(0)
        await finish(p)
        return p

    p = asyncio.run(go())
    assert p.state()["status"] == "rejected"
    assert "key" not in load_settings(settings_dir)


def test_404_means_expired(fakehub, settings_dir):
    fakehub.script = [(404, {"detail": {"code": "err.pairing.request_unknown", "params": {}}}, {})]

    async def go():
        p = make(settings_dir, fakehub.url)
        p.start()
        await asyncio.sleep(0)
        await finish(p)
        return p

    assert asyncio.run(go()).state()["status"] == "expired"


def test_local_deadline_expires(fakehub, settings_dir):
    fakehub.create = (201, {"id": "r", "code": "000001", "secret": "S", "expires_in": 5}, {})
    fakehub.script = [(200, {"status": "pending"}, {})]  # sin expires_in: manda el reloj local
    now = [0.0]

    async def sleep(s):
        now[0] += s
        await asyncio.sleep(0)

    async def go():
        p = Pairing(settings_dir, sleep=sleep, clock=lambda: now[0])
        p.set_hub_url(fakehub.url)
        p.start()
        await asyncio.sleep(0)
        await finish(p)
        return p

    assert asyncio.run(go()).state()["status"] == "expired"


def test_429_on_poll_waits_retry_after(fakehub, settings_dir):
    fakehub.script = [
        (429, {"detail": {"code": "err.main.too_many_attempts", "params": {}}}, {"Retry-After": "7"}),
        ACCEPTED,
    ]
    sleeps = []

    async def go():
        p = make(settings_dir, fakehub.url, sleeps=sleeps)
        p.start()
        await asyncio.sleep(0)
        await finish(p)
        return p

    assert asyncio.run(go()).state()["status"] == "linked"
    assert sleeps == [3.0, 7.0]


def test_429_on_create_is_error_with_wait(fakehub, settings_dir):
    fakehub.create = (
        429,
        {"detail": {"code": "err.pairing.too_many_requests", "params": {"seconds": 120}}},
        {"Retry-After": "120"},
    )

    async def go():
        p = make(settings_dir, fakehub.url)
        p.start()
        await asyncio.sleep(0)
        await finish(p)
        return p

    st = asyncio.run(go()).state()
    assert st["status"] == "error" and st["error"] == "rate_limited" and st["wait_s"] == 120


def test_network_down_on_create(settings_dir):
    async def go():
        p = make(settings_dir, "http://127.0.0.1:1")  # nadie escucha
        p.start()
        await asyncio.sleep(0)
        await finish(p)
        return p

    st = asyncio.run(go()).state()
    assert st["status"] == "error" and st["error"] == "connection"


def test_network_errors_back_off_then_recover(fakehub, settings_dir):
    """Errores 503 durante el sondeo: espera creciente, sigue esperando (no es un error final) y luego acepta."""
    unavailable = (503, {"detail": {"code": "err.pairing.busy", "params": {}}}, {})
    fakehub.script = [unavailable, unavailable, unavailable, ACCEPTED]
    sleeps = []

    async def go():
        p = make(settings_dir, fakehub.url, sleeps=sleeps)
        p.start()
        await asyncio.sleep(0)
        await finish(p)
        return p

    assert asyncio.run(go()).state()["status"] == "linked"
    assert sleeps == [3.0, 6.0, 12.0, 24.0]


def test_unexpected_accepted_body_is_error(fakehub, settings_dir):
    fakehub.script = [(200, {"status": "accepted", "device": "d", "key": "no-es-clave"}, {})]

    async def go():
        p = make(settings_dir, fakehub.url)
        p.start()
        await asyncio.sleep(0)
        await finish(p)
        return p

    p = asyncio.run(go())
    assert p.state()["error"] == "bad_response"
    assert "key" not in load_settings(settings_dir)


def test_redirect_not_followed_secret_not_forwarded(fakehub, settings_dir):
    other = type(fakehub)()
    try:
        fakehub.redirect_to = other.url + "/api/pairing/requests"

        async def go():
            p = make(settings_dir, fakehub.url)
            p.start()
            await asyncio.sleep(0)
            await finish(p)
            return p

        st = asyncio.run(go()).state()
        assert st["status"] == "error"
        assert other.requests == []
    finally:
        other.stop()


def test_cancel_in_unload_stops_task(fakehub, settings_dir):
    fakehub.script = [PENDING]

    async def go():
        p = make(settings_dir, fakehub.url)
        p.start()
        for _ in range(5):
            await asyncio.sleep(0.02)
        t = p._task  # noqa: SLF001
        await p.close()
        return p, t

    p, t = asyncio.run(go())
    assert t.done() and t.cancelled()
    assert p.state()["status"] == "unlinked"
    n = len(fakehub.requests)
    import time

    time.sleep(0.2)
    assert len(fakehub.requests) == n  # no hay más peticiones tras cancelar


def test_unlink_removes_key_keeps_url(fakehub, settings_dir):
    save_settings(settings_dir, {"hub_url": fakehub.url, "device": "d", "key": KEY})
    p = Pairing(settings_dir)
    assert p.state()["status"] == "linked"
    p.unlink()
    assert p.state()["status"] == "unlinked"
    s = load_settings(settings_dir)
    assert "key" not in s and "device" not in s and s["hub_url"] == fakehub.url


def test_changing_hub_url_drops_old_key(settings_dir):
    save_settings(settings_dir, {"hub_url": "http://a", "device": "d", "key": KEY})
    p = Pairing(settings_dir)
    p.set_hub_url("http://b/")
    assert p.state()["status"] == "unlinked" and p.hub_url == "http://b"
    assert "key" not in load_settings(settings_dir)


def test_state_after_restart_is_linked(settings_dir):
    save_settings(settings_dir, {"hub_url": "http://hub", "device": "deck-1", "key": KEY})
    st = Pairing(settings_dir).state()
    assert st["status"] == "linked" and st["device"] == "deck-1" and "plain_http" not in st
    assert KEY not in json.dumps(st)


def test_settings_file_keeps_0600_when_overwritten(settings_dir):
    save_settings(settings_dir, {"a": 1})
    os.chmod(os.path.join(settings_dir, SETTINGS_FILE), 0o644)
    save_settings(settings_dir, {"key": KEY})
    assert stat.S_IMODE(os.stat(os.path.join(settings_dir, SETTINGS_FILE)).st_mode) == 0o600


# ---- comprobar conexión
def test_ping_ok_with_bearer(fakehub):
    res, data = check_connection(fakehub.url, KEY)
    assert (res, data) == ("ok", {"device": "steam-deck-ab12"})
    m, path, headers, _ = fakehub.requests[-1]
    assert path == "/api/hook/ping" and headers["Authorization"] == f"Bearer {KEY}" and KEY not in path


def test_ping_unauthorized_and_limits(fakehub):
    fakehub.ping = (401, {"detail": {"code": "err.apikey.invalid", "params": {}}}, {})
    assert check_connection(fakehub.url, KEY)[0] == "unauthorized"
    fakehub.ping = (429, {"detail": {"code": "x", "params": {}}}, {"Retry-After": "9"})
    assert check_connection(fakehub.url, KEY) == ("rate_limited", {"wait_s": 9})
    fakehub.ping = (500, None, {})
    assert check_connection(fakehub.url, KEY)[0] == "hub_error"
    assert check_connection("http://127.0.0.1:1", KEY)[0] == "connection"
    assert check_connection(fakehub.url, None)[0] == "not_linked"


# ---- main.py (Plugin) con `decky` falso
def test_plugin_end_to_end_logs_clean(fakehub, fake_decky, caplog, monkeypatch):
    import logging

    import checkpoint_hub

    monkeypatch.setattr(checkpoint_hub, "POLL_S", 0.01)

    fakehub.script = [PENDING, ACCEPTED]
    caplog.set_level(logging.DEBUG)

    async def go():
        import main

        p = main.Plugin()
        await p._main()
        assert (await p.set_hub_url("nada"))["url_error"] == "scheme"
        assert (await p.set_hub_url(fakehub.url + "/"))["ok"]
        assert (await p.start_pairing())["status"] == "waiting"
        await finish(p.pairing)
        st = await p.get_state()
        tc = await p.test_connection()
        await p._unload()
        return st, tc

    st, tc = asyncio.run(go())
    assert st["status"] == "linked" and tc == {
        "result": "ok",
        "device": "steam-deck-ab12",
        "compat": "hub_old",  # el hub falso no anuncia protocolo
        "protocol": None,
        "min_plugin_protocol": None,
        "plugin_protocol": 1,
    }
    assert KEY not in caplog.text and "SECRET-xyz" not in caplog.text
    assert "vinculada al dispositivo" in caplog.text


def test_plugin_unload_cancels_pairing(fakehub, fake_decky):
    fakehub.script = [PENDING]

    async def go():
        import main

        p = main.Plugin()
        await p._main()
        await p.set_hub_url(fakehub.url)
        await p.start_pairing()
        await asyncio.sleep(0.05)
        t = p.pairing._task  # noqa: SLF001
        await p._unload()
        return t

    assert asyncio.run(go()).done()


def test_plugin_start_without_url(fake_decky):
    async def go():
        import main

        p = main.Plugin()
        await p._main()
        return await p.start_pairing()

    assert asyncio.run(go()) == {"ok": False, "url_error": "empty"}
