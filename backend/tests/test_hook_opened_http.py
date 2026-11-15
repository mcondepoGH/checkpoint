"""POST /api/hook/{game}/opened con key de DISPOSITIVO (`ckd_`): un dispositivo `http` avisa de que abre el juego. No
sincroniza ni vigila: marca «jugando» (en memoria, con caducidad) y deja `hook_opened` en el historial. El cuerpo opcional
`{"result": {...}}` lleva el resultado de la sync local del plugin; `closed` acepta el mismo cuerpo y limpia «jugando»."""

from datetime import timedelta

from fastapi.testclient import TestClient

from app.core import settings
from app.users import history
from test_hook_fingerprint import PW, Env, client, code, env  # noqa: F401 (fixtures)


def post(c, ev, body=None, game="g1", device="deck", headers=None, raw=None):
    h = {"Authorization": f"Bearer {c.key}"} if headers is None else headers
    url = f"/api/hook/{game}/{ev}" + (f"?device={device}" if device else "")
    kw = {"content": raw, "headers": {**h, "Content-Type": "application/json"}} if raw is not None else {"headers": h}
    if body is not None:
        kw["json"] = body
    return TestClient(c.app).post(url, **kw)


def opened(c, **kw):
    return post(c, "opened", **kw)


def closed(c, **kw):
    return post(c, "closed", **kw)


def entries(trigger):
    return [e for e in history.read() if e["trigger"] == trigger]


def view(c):
    return c.get("/api/watches").json()


def test_opened_with_device_key_marks_playing_without_sync(client):
    e = client.env
    e.write_hub("base")
    e.baseline()
    before = sorted(str(p.relative_to(e.data)) for p in e.data.rglob("*") if "history" not in str(p))
    r = opened(client)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["game"] == "g1" and j["device"] == "deck" and j["recorded"] is True and j["outcome"] == "ok"
    assert j["playing"] is True and j["expires"]
    after = sorted(str(p.relative_to(e.data)) for p in e.data.rglob("*") if "history" not in str(p))
    assert before == after  # ni sync ni línea base ni run
    (en,) = entries("hook_opened")
    assert en["device"] == "deck" and en["result"] == "ok" and en["games"]["g1"]["name"] == "Mi Juego"
    assert client.app.state.watcher.list() == []  # no se vigila
    (p,) = view(client)["playing"]
    assert p["game"] == "g1" and p["device"] == "deck" and p["since"] and p["expires"] and "result" not in p


def test_result_is_stored_and_exposed(client):
    r = opened(client, body={"result": {"state": "uploaded"}})
    assert r.status_code == 200, r.text
    (en,) = entries("hook_opened")
    assert en["games"]["g1"]["code"] == "hook.sync.uploaded" and en["code"] == "hook.sync.uploaded"
    (p,) = view(client)["playing"]
    assert p["result"] == {"state": "uploaded"}


def test_error_result_keeps_reason_code(client):
    assert opened(client, body={"result": {"state": "error", "code": "connection"}}).status_code == 200
    (en,) = entries("hook_opened")
    assert en["result"] == "error" and en["games"]["g1"]["params"] == {"reason": "connection"}
    assert view(client)["playing"][0]["result"] == {"state": "error", "code": "connection"}


def test_unknown_error_code_is_dropped_not_rejected(client):
    assert opened(client, body={"result": {"state": "error", "code": "/home/deck/saves"}}).status_code == 200
    assert view(client)["playing"][0]["result"] == {"state": "error"}
    assert "saves" not in str(entries("hook_opened"))
    assert entries("hook_opened")[0]["games"]["g1"]["params"] == {"reason": "unknown"}


def test_states_map_to_history_result(client):
    for state, want in [("up_to_date", "ok"), ("downloaded", "ok"), ("conflict", "conflict"), ("no_path", "skipped"),
                        ("missing_dir", "skipped"), ("error", "error")]:  # fmt: skip
        opened(client, body={"result": {"state": state}})
        assert entries("hook_opened")[0]["result"] == want, state


def test_closed_clears_playing_and_keeps_result(client):
    opened(client, body={"result": {"state": "downloaded"}})
    assert len(view(client)["playing"]) == 1
    r = closed(client, body={"result": {"state": "uploaded"}})
    assert r.status_code == 200 and r.json()["outcome"] == "ok"
    v = view(client)
    assert v["playing"] == []
    (res,) = v["results"]
    assert (
        res["game"] == "g1"
        and res["device"] == "deck"
        and res["state"] == "uploaded"
        and res["trigger"] == "hook_closed"
    )
    assert entries("hook_closed")[0]["games"]["g1"]["code"] == "hook.sync.uploaded"


def test_closed_without_body_still_works_and_clears(client):
    opened(client)
    assert closed(client).status_code == 200
    assert view(client)["playing"] == []
    assert entries("hook_closed")[0]["result"] == "ok" and "code" not in entries("hook_closed")[0]


def test_last_result_per_game_and_device_is_the_newest(client):
    opened(client, body={"result": {"state": "downloaded"}})
    closed(client, body={"result": {"state": "up_to_date"}})
    (res,) = view(client)["results"]
    assert res["state"] == "up_to_date"


def test_invalid_result_is_400(client):
    bad = [
        {"result": {"state": "hackeado"}},
        {"result": {"state": 3}},
        {"result": "uploaded"},
        {"result": {}},
        {"result": {"state": "uploaded", "path": "/home/deck/x"}},  # campos no previstos: rutas, ficheros...
        {"result": {"state": "uploaded", "code": 7}},
    ]
    for ev in (opened, closed):
        for b in bad:
            r = ev(client, body=b)
            assert r.status_code == 400 and code(r) == "err.hook.result_invalid", (b, r.text)
    assert entries("hook_opened") == [] and entries("hook_closed") == []
    assert view(client)["playing"] == []


def test_oversized_body_is_400(client):
    big = {"result": {"state": "uploaded"}, "pad": "x" * 5000}
    r = opened(client, body=big)
    assert r.status_code == 400 and code(r) == "err.hook.result_invalid"


def test_no_body_or_unknown_body_is_current_behaviour(client):
    for kw in ({"raw": b""}, {"raw": b"no es json"}, {"body": {"otra": 1}}, {"body": [1, 2]}):
        assert opened(client, **kw).status_code == 200, kw
        assert closed(client, **kw).status_code == 200, kw
    assert all("code" not in e for e in entries("hook_opened"))


def test_playing_expires(client):
    opened(client)
    assert len(view(client)["playing"]) == 1
    clock = client.app.state.ctx.scheduler.clock
    client.app.state.ctx.scheduler.clock = lambda: clock() + timedelta(seconds=settings.HOOK_PLAYING_TTL + 1)
    assert view(client)["playing"] == []
    assert closed(client).status_code == 200  # cerrar tras caducar no falla


def test_reopen_refreshes_instead_of_duplicating(client):
    opened(client)
    opened(client)
    assert len(view(client)["playing"]) == 1


def test_disabled_game_is_skipped_and_not_playing(env, client):
    import yaml

    p = env.tmp / "config" / "config.yaml"
    d = yaml.safe_load(p.read_text())
    d["games"]["g1"]["enabled"] = False
    p.write_text(yaml.safe_dump(d, allow_unicode=True))
    r = opened(client)
    assert r.status_code == 200 and r.json()["outcome"] == "skipped" and r.json()["code"] == "err.sync.game_disabled"
    assert view(client)["playing"] == []
    assert entries("hook_opened")[0]["result"] == "skipped"


def test_auth_401_and_429(client):
    for h in ({}, {"Authorization": "Bearer ckd_" + "x" * 43}):
        r = opened(client, headers=h)
        assert r.status_code == 401 and code(r) == "err.apikey.invalid"
    assert TestClient(client.app).post("/api/hook/g1/opened?device=deck").status_code == 401  # cookie sola no vale
    r = opened(client)  # tercer fallo ya contado: bloqueo por IP, como el resto de hooks
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert entries("hook_opened") == []


def test_scope_403_404(client):
    r = opened(client, device="pc")
    assert r.status_code == 403 and code(r) == "err.apikey.device_mismatch"
    r = opened(client, game="nope")
    assert r.status_code == 404 and code(r) == "err.main.game_unknown"
    assert entries("hook_opened") == [] and view(client)["playing"] == []


def test_user_key_behaviour_unchanged(client):
    h = {"Authorization": f"Bearer {client.ukey}"}
    r = opened(client, headers=h, body={"result": {"state": "uploaded"}})
    assert r.status_code == 400 and code(r) == "err.hook.device_push_only"  # el cuerpo se ignora con key de usuario
    assert view(client)["playing"] == []
    assert entries("hook_opened") == []


def test_other_device_never_leaks_into_my_playing(client):
    opened(client)
    # La key de usuario no ve el estado de otros por /api/hook/watches (sigue siendo solo vigilancias) y el
    # estado de «jugando» solo sale en la vista de sesión.
    r = TestClient(client.app).get("/api/hook/watches", headers={"Authorization": f"Bearer {client.ukey}"})
    assert r.status_code == 200 and r.json() == []
