"""Cliente del hub (`HubClient`) contra un hub falso: juegos, fingerprint, descarga con Range, subida reanudable, commit,
reintentos y que la clave no aparezca nunca."""

import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

import checkpoint_client as hc
from checkpoint_hub import HubNetworkError

KEY = "ckd_secretisima123"
NOSLEEP = []


def client(hub, sleeps=None):
    s = [] if sleeps is None else sleeps
    return hc.HubClient(hub.url, KEY, sleep=s.append), s


def err(status, code, params=None, headers=None):
    return status, {"detail": {"code": code, "params": params or {}}}, headers or {}


# ---- get_games
def test_get_games(scripthub):
    games = [{"id": "g1", "name": "Juego", "enabled": True, "steam_appid": 5, "status": None, "path": "/home/deck/x"}]
    hub = scripthub(lambda r: (200, games, {}))
    c, _ = client(hub)
    assert c.get_games() == games
    assert hub.requests[0].method == "GET" and hub.requests[0].path == "/api/games"
    assert hub.requests[0].headers["authorization"] == f"Bearer {KEY}"


def test_get_games_drops_malformed_items(scripthub):
    good = {"id": "g1", "name": "J", "enabled": True, "steam_appid": None, "status": None, "path": None}
    hub = scripthub(lambda r: (200, [good, {"id": 3}, "x", {**good, "id": "g2", "path": 7}], {}))
    c, _ = client(hub)
    assert [g["id"] for g in c.get_games()] == ["g1", "g2"]
    assert c.get_games()[1]["path"] is None  # una ruta que no es texto = sin ruta


# ---- fingerprint
def test_fingerprint_posts_manifest_and_flag(scripthub):
    hub = scripthub(lambda r: (200, {"action": "none", "reason": "same", "hub": {"hash": None}}, {}))
    c, _ = client(hub)
    m = [{"path": "a", "sha256": "0" * 64, "size": 1, "mtime": 2}]
    assert c.fingerprint("mi juego/ñ", m)["action"] == "none"
    assert c.fingerprint("g", m, with_manifest=True)
    r1, r2 = hub.requests
    assert r1.path == "/api/hook/mi%20juego%2F%C3%B1/fingerprint" and json.loads(r1.body) == m
    assert r2.path == "/api/hook/g/fingerprint?manifest=1"


# ---- commit
def test_commit(scripthub):
    hub = scripthub(lambda r: (200, {"outcome": "ok"}, {}))
    c, _ = client(hub)
    assert c.commit("g", "abc", [])["outcome"] == "ok"
    assert json.loads(hub.requests[0].body) == {"expect": "abc", "manifest": []}
    c.commit("g", None, [])
    assert json.loads(hub.requests[1].body)["expect"] is None


@pytest.mark.parametrize("code,status", [("err.hook.hub_changed", 409), ("err.hook.upload_incomplete", 422)])
def test_commit_errors_carry_code(scripthub, code, status):
    hub = scripthub(lambda r: err(status, code, {"missing": 2}))
    c, _ = client(hub)
    with pytest.raises(hc.HubApiError) as e:
        c.commit("g", "x", [])
    assert e.value.status == status and e.value.code == code and e.value.params == {"missing": 2}
    assert len(hub.requests) == 1  # un 4xx no se reintenta


# ---- reintentos
def test_401_not_retried_and_message_has_no_secret(scripthub):
    hub = scripthub(lambda r: err(401, "err.auth.invalid"))
    c, sleeps = client(hub)
    with pytest.raises(hc.HubApiError) as e:
        c.get_games()
    assert e.value.status == 401 and sleeps == [] and len(hub.requests) == 1
    assert KEY not in str(e.value) and hub.url not in str(e.value)


def test_429_waits_retry_after_then_succeeds(scripthub):
    n = []

    def h(r):
        n.append(1)
        return err(429, "err.main.rate_limited", headers={"Retry-After": "7"}) if len(n) == 1 else (200, [], {})

    hub = scripthub(h)
    c, sleeps = client(hub)
    assert c.get_games() == []
    assert sleeps == [7.0]


def test_429_too_long_raises_without_sleeping(scripthub):
    hub = scripthub(lambda r: err(429, "x", headers={"Retry-After": "600"}))
    c, sleeps = client(hub)
    with pytest.raises(hc.HubApiError) as e:
        c.get_games()
    assert e.value.status == 429 and e.value.wait_s == 600 and sleeps == []


def test_5xx_backoff_grows_then_gives_up(scripthub):
    hub = scripthub(lambda r: (503, b"", {}))
    c, sleeps = client(hub)
    with pytest.raises(hc.HubApiError) as e:
        c.get_games()
    assert e.value.status == 503 and sleeps == [1.0, 2.0, 4.0] and len(hub.requests) == 4


def test_network_down_retries_then_raises():
    c = hc.HubClient("http://127.0.0.1:1", KEY, sleep=(s := []).append)
    with pytest.raises(HubNetworkError) as e:
        c.get_games()
    assert s == [1.0, 2.0, 4.0]
    assert KEY not in str(e.value) and "127.0.0.1" not in str(e.value)


def test_no_redirect_followed(scripthub):
    other = scripthub(lambda r: (200, [], {}))
    hub = scripthub(lambda r: (307, b"", {"Location": other.url + "/api/games"}))
    c, _ = client(hub)
    with pytest.raises(hc.HubApiError) as e:
        c.get_games()
    assert e.value.status == 307 and other.requests == []


# ---- descarga
DATA = bytes(range(256)) * 100


def serve_file(req):
    rng = req.headers.get("range")
    if rng:
        start = int(rng.split("=")[1].split("-")[0])
        return 206, DATA[start:], {"Content-Range": f"bytes {start}-{len(DATA) - 1}/{len(DATA)}"}
    return 200, DATA, {}


def test_download_full(scripthub, tmp_path):
    hub = scripthub(serve_file)
    c, _ = client(hub)
    dest = tmp_path / "out"
    assert c.download_file("g", "a b/ñ'&:.sav", dest) == len(DATA)
    assert dest.read_bytes() == DATA
    r = hub.requests[0]
    assert "range" not in r.headers
    assert parse_qs(urlsplit(r.path).query) == {"path": ["a b/ñ'&:.sav"]}
    assert " " not in r.path and "'" not in r.path and "&:" not in r.path


def test_download_resumes_with_range(scripthub, tmp_path):
    hub = scripthub(serve_file)
    c, _ = client(hub)
    dest = tmp_path / "out"
    dest.write_bytes(DATA[:1000])
    assert c.download_file("g", "x", dest, offset=1000) == len(DATA)
    assert hub.requests[0].headers["range"] == "bytes=1000-"
    assert dest.read_bytes() == DATA


def test_download_server_ignores_range_restarts(scripthub, tmp_path):
    hub = scripthub(lambda r: (200, DATA, {}))
    c, _ = client(hub)
    dest = tmp_path / "out"
    dest.write_bytes(b"basura" * 10)
    c.download_file("g", "x", dest, offset=60)
    assert dest.read_bytes() == DATA


def test_download_bad_content_range_is_error(scripthub, tmp_path):
    hub = scripthub(lambda r: (206, DATA[10:], {"Content-Range": f"bytes 10-{len(DATA) - 1}/{len(DATA)}"}))
    c, _ = client(hub)
    dest = tmp_path / "out"
    dest.write_bytes(b"x" * 5)
    with pytest.raises(hc.HubApiError) as e:
        c.download_file("g", "x", dest, offset=5)
    assert e.value.code == "bad_response"


def test_download_416_restarts_from_zero(scripthub, tmp_path):
    def h(r):
        if r.headers.get("range"):
            return err(416, "err.hook.range_invalid", headers={"Content-Range": f"bytes */{len(DATA)}"})
        return 200, DATA, {}

    hub = scripthub(h)
    c, _ = client(hub)
    dest = tmp_path / "out"
    dest.write_bytes(b"x" * 99999)
    assert c.download_file("g", "x", dest, offset=99999) == len(DATA)
    assert dest.read_bytes() == DATA


def test_download_cut_connection_resumes(scripthub, tmp_path):
    calls = []

    def h(r):
        calls.append(r.headers.get("range"))
        if len(calls) == 1:
            raise hub.Drop(DATA[:777])
        return serve_file(r)

    hub = scripthub(h)
    c, sleeps = client(hub)
    dest = tmp_path / "out"
    assert c.download_file("g", "x", dest) == len(DATA)
    assert dest.read_bytes() == DATA
    assert calls == [None, "bytes=777-"] and sleeps == [1.0]


def test_download_404(scripthub, tmp_path):
    hub = scripthub(lambda r: err(404, "err.hook.file_unknown"))
    c, _ = client(hub)
    with pytest.raises(hc.HubApiError) as e:
        c.download_file("g", "x", tmp_path / "o")
    assert e.value.code == "err.hook.file_unknown"


# ---- subida
class Receiver:
    """Hub falso de subida: acumula el cuerpo; `cut_after` corta la conexión tras N bytes la primera vez."""

    def __init__(self, size, cut_after=None):
        self.have = b""
        self.size = size
        self.cut_after = cut_after
        self.offsets = []

    def __call__(self, req):
        q = parse_qs(urlsplit(req.path).query)
        off = int(q["offset"][0])
        self.offsets.append(off)
        if off != len(self.have):
            return err(409, "err.hook.upload_offset_mismatch", {"received": len(self.have)})
        if self.cut_after is not None:
            self.have += req.body[: self.cut_after]
            self.cut_after = None
            raise ScriptHubDrop()
        self.have += req.body
        done = len(self.have) == self.size
        return 200, {"received": len(self.have), "size": self.size, "complete": done}, {}


def ScriptHubDrop():
    from conftest import ScriptHub

    return ScriptHub.Drop()


def mkfile(tmp_path, data):
    p = tmp_path / "f.bin"
    p.write_bytes(data)
    return p, hashlib.sha256(data).hexdigest()


def test_upload_streams_whole_file(scripthub, tmp_path):
    data = b"0123456789" * 50_000
    p, sha = mkfile(tmp_path, data)
    rx = Receiver(len(data))
    hub = scripthub(rx)
    c, _ = client(hub)
    out = c.upload_file("g", "a b/ñ.sav", p, len(data), sha)
    assert out["complete"] and rx.have == data
    r = hub.requests[0]
    q = parse_qs(urlsplit(r.path).query)
    assert q == {"path": ["a b/ñ.sav"], "size": [str(len(data))], "sha256": [sha], "offset": ["0"]}
    assert r.method == "PUT" and r.headers["content-length"] == str(len(data))
    assert KEY not in r.path


def test_upload_empty_file(scripthub, tmp_path):
    p, sha = mkfile(tmp_path, b"")
    rx = Receiver(0)
    hub = scripthub(rx)
    c, _ = client(hub)
    assert c.upload_file("g", "v", p, 0, sha)["complete"]


def test_upload_resumes_after_connection_cut(scripthub, tmp_path):
    data = bytes(range(256)) * 1000
    p, sha = mkfile(tmp_path, data)
    rx = Receiver(len(data), cut_after=100_000)
    hub = scripthub(rx)
    c, sleeps = client(hub)
    assert c.upload_file("g", "x", p, len(data), sha)["complete"]
    assert rx.have == data
    assert rx.offsets[0] == 0 and 100_000 in rx.offsets[1:] and sleeps == [1.0]


def test_upload_409_mismatch_adopts_received(scripthub, tmp_path):
    data = b"abcdefghij" * 100
    p, sha = mkfile(tmp_path, data)
    rx = Receiver(len(data))
    rx.have = data[:300]  # el hub ya tenía 300 bytes de un intento anterior
    hub = scripthub(rx)
    c, _ = client(hub)
    assert c.upload_file("g", "x", p, len(data), sha)["complete"]
    assert rx.offsets == [0, 300] and rx.have == data


def test_upload_gives_up_after_repeated_mismatch(scripthub, tmp_path):
    p, sha = mkfile(tmp_path, b"x" * 100)
    hub = scripthub(lambda r: err(409, "err.hook.upload_offset_mismatch", {"received": 5}))
    c, _ = client(hub)
    with pytest.raises(hc.HubApiError):
        c.upload_file("g", "x", p, 100, sha)
    assert len(hub.requests) <= 8


def test_upload_too_large_is_refused_without_request(scripthub, tmp_path):
    hub = scripthub(lambda r: (200, {}, {}))
    c, _ = client(hub)
    p, sha = mkfile(tmp_path, b"x")
    with pytest.raises(hc.FileTooLarge):
        c.upload_file("g", "x", p, hc.MAX_FILE_BYTES + 1, sha)
    assert hub.requests == []


def test_upload_429_waits(scripthub, tmp_path):
    n = []
    p, sha = mkfile(tmp_path, b"hola")
    rx = Receiver(4)

    def h(r):
        n.append(1)
        return err(429, "x", headers={"Retry-After": "3"}) if len(n) == 1 else rx(r)

    hub = scripthub(h)
    c, sleeps = client(hub)
    assert c.upload_file("g", "x", p, 4, sha)["complete"] and sleeps == [3.0]


def test_upload_401_not_retried(scripthub, tmp_path):
    p, sha = mkfile(tmp_path, b"hola")
    hub = scripthub(lambda r: err(401, "err.auth.invalid"))
    c, sleeps = client(hub)
    with pytest.raises(hc.HubApiError) as e:
        c.upload_file("g", "x", p, 4, sha)
    assert e.value.status == 401 and sleeps == []


def test_upload_413_too_large_from_hub(scripthub, tmp_path):
    p, sha = mkfile(tmp_path, b"hola")
    hub = scripthub(lambda r: err(413, "err.hook.file_too_large", {"max_mb": 512}))
    c, _ = client(hub)
    with pytest.raises(hc.HubApiError) as e:
        c.upload_file("g", "x", p, 4, sha)
    assert e.value.code == "err.hook.file_too_large"


def test_upload_network_down(tmp_path):
    p, sha = mkfile(tmp_path, b"hola")
    c = hc.HubClient("http://127.0.0.1:1", KEY, sleep=lambda s: None)
    with pytest.raises(HubNetworkError):
        c.upload_file("g", "x", p, 4, sha)


# ---- aviso de cierre
def test_closed_posts_to_the_game_without_body(scripthub):
    hub = scripthub(lambda r: (200, {"game": "g 1", "device": "d", "recorded": True, "outcome": "ok"}, {}))
    c, _ = client(hub)
    assert c.closed("g 1")["outcome"] == "ok"
    r = hub.requests[0]
    assert r.method == "POST" and r.path == "/api/hook/g%201/closed"
    assert r.headers["authorization"] == f"Bearer {KEY}"


def test_closed_409_is_api_error_with_code(scripthub):
    hub = scripthub(lambda r: err(409, "err.main.run_in_progress"))
    c, _ = client(hub)
    with pytest.raises(hc.HubApiError) as e:
        c.closed("g1")
    assert e.value.status == 409 and e.value.code == "err.main.run_in_progress"


def test_closed_rejects_non_object_response(scripthub):
    hub = scripthub(lambda r: (200, [1], {}))
    c, _ = client(hub)
    with pytest.raises(hc.HubApiError):
        c.closed("g1")


# ---- aviso de apertura y resultado de la sync local
def test_opened_posts_result_once_without_retries(scripthub):
    hub = scripthub(lambda r: err(503, "err.main.unavailable"))
    c, sleeps = client(hub)
    with pytest.raises(hc.HubApiError):
        c.opened("g 1", {"state": "uploaded"})
    assert len(hub.requests) == 1 and sleeps == []  # un solo intento: nunca se reintenta ni se espera
    r = hub.requests[0]
    assert r.method == "POST" and r.path == "/api/hook/g%201/opened"
    assert json.loads(r.body) == {"result": {"state": "uploaded"}}
    assert r.headers["authorization"] == f"Bearer {KEY}"


def test_opened_network_error_is_not_retried(scripthub):
    hub = scripthub(lambda r: (200, {}, {}))
    c, sleeps = client(hub)
    hub.stop()
    with pytest.raises(HubNetworkError):
        c.opened("g1", {"state": "up_to_date"})
    assert sleeps == []


def test_opened_without_result_sends_no_body_and_returns_object(scripthub):
    hub = scripthub(lambda r: (200, {"recorded": True, "playing": True}, {}))
    c, _ = client(hub)
    assert c.opened("g1")["playing"] is True
    assert hub.requests[0].body == b""


def test_opened_rejects_non_object_response(scripthub):
    hub = scripthub(lambda r: (200, [1], {}))
    c, _ = client(hub)
    with pytest.raises(hc.HubApiError):
        c.opened("g1")


def test_closed_sends_result_when_given(scripthub):
    hub = scripthub(lambda r: (200, {"outcome": "ok"}, {}))
    c, _ = client(hub)
    c.closed("g1", {"state": "error", "code": "connection"})
    assert json.loads(hub.requests[0].body) == {"result": {"state": "error", "code": "connection"}}


def test_set_resolution_sends_winner_and_expect_with_the_device_key(scripthub):
    import json

    hub = scripthub(lambda r: (200, {"game": "g1", "device": "deck", "winner": "hub", "by": "device", "expires": "x"}, {}))
    c = hc.HubClient(hub.url, "ckd_secret", sleep=lambda s: None)
    out = c.set_resolution("g 1", "hub", {"hub": "a" * 64, "device": None})
    assert out["winner"] == "hub"
    (q,) = hub.requests
    assert (q.method, q.path) == ("PUT", "/api/hook/g%201/resolution")
    assert q.headers["authorization"] == "Bearer ckd_secret"
    assert json.loads(q.body) == {"winner": "hub", "expect": {"hub": "a" * 64, "device": None}}


def test_set_resolution_rejects_a_non_object_answer(scripthub):
    import pytest

    hub = scripthub(lambda r: (200, ["no"], {}))
    c = hc.HubClient(hub.url, "ckd_secret", sleep=lambda s: None)
    with pytest.raises(hc.HubApiError):
        c.set_resolution("g1", "device", {"hub": None, "device": None})
