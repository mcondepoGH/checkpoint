import pytest
from conftest import KEY, sha

from checkpoint_client import hubclient as hc
from checkpoint_client.hub import HubNetworkError


def client(fakehub, **kw):
    return hc.HubClient(fakehub.url, KEY, sleep=lambda s: None, **kw)


def test_get_games_keeps_path_and_process(fakehub):
    fakehub.games = [
        {
            "id": "g1",
            "name": "Uno",
            "enabled": True,
            "steam_appid": 1,
            "status": None,
            "path": "/x",
            "process": "uno.exe",
        },
        {"id": "g2", "name": "Dos", "enabled": True, "steam_appid": None, "status": None, "path": "", "process": None},
        {"sin": "id"},
    ]
    games = client(fakehub).get_games()
    assert [g["id"] for g in games] == ["g1", "g2"]
    assert games[0]["path"] == "/x" and games[0]["process"] == "uno.exe"
    assert games[1]["path"] is None and games[1]["process"] is None
    assert fakehub.requests[0][2]["Authorization"] == f"Bearer {KEY}"


def test_unauthorized_is_hub_api_error_without_key(fakehub):
    fakehub.key = "ckd_otra"
    with pytest.raises(hc.HubApiError) as e:
        client(fakehub).get_games()
    assert e.value.status == 401 and KEY not in str(e.value) and e.value.endpoint == "GET /api/games"


def test_retries_5xx_then_gives_up(fakehub, monkeypatch):
    fakehub.games = []
    seen = []
    monkeypatch.setattr(
        hc,
        "request_json",
        lambda *a, **k: seen.append(1) or __import__("checkpoint_client.hub").hub.HubResponse(500, None, {}),
    )
    with pytest.raises(hc.HubApiError) as e:
        client(fakehub, retries=2).get_games()
    assert e.value.status == 500 and len(seen) == 3


def test_long_retry_after_is_not_waited(fakehub, monkeypatch):
    from checkpoint_client.hub import HubResponse

    monkeypatch.setattr(hc, "request_json", lambda *a, **k: HubResponse(429, None, {"retry-after": "600"}))
    with pytest.raises(hc.HubApiError) as e:
        client(fakehub).get_games()
    assert e.value.status == 429 and e.value.wait_s == 600


def test_network_error_after_retries():
    c = hc.HubClient("http://127.0.0.1:1", KEY, sleep=lambda s: None, retries=1)
    with pytest.raises(HubNetworkError):
        c.get_games()


def test_upload_commit_and_fingerprint(fakehub, tmp_path):
    data = b"x" * 1000
    f = tmp_path / "a.sav"
    f.write_bytes(data)
    c = client(fakehub)
    out = c.upload_file("g1", "a.sav", f, len(data), sha(data))
    assert out["received"] == 1000
    manifest = [{"path": "a.sav", "sha256": sha(data), "size": 1000, "mtime": 1}]
    assert c.commit("g1", None, manifest) == {"outcome": "ok"}
    assert fakehub.files["g1"] == {"a.sav": data}
    assert c.fingerprint("g1", manifest)["action"] == "none"


def test_upload_rejects_file_over_limit(fakehub, tmp_path):
    f = tmp_path / "big"
    f.write_bytes(b"")
    with pytest.raises(hc.FileTooLarge):
        client(fakehub).upload_file("g1", "big", f, hc.MAX_FILE_BYTES + 1, "0" * 64)
    assert fakehub.requests == []


def test_upload_resumes_from_hub_received(fakehub, tmp_path):
    data = bytes(range(256)) * 8
    f = tmp_path / "a.sav"
    f.write_bytes(data)
    fakehub.staging["g1"] = {"a.sav": data[:700]}  # el hub ya tiene 700 bytes de un intento anterior
    out = client(fakehub).upload_file("g1", "a.sav", f, len(data), sha(data))
    assert out["received"] == len(data) and fakehub.staging["g1"]["a.sav"] == data


def test_download_file_and_resume(fakehub, tmp_path):
    data = b"hola mundo" * 100
    fakehub.files["g1"] = {"d/a.sav": data}
    dest = tmp_path / "a.sav"
    assert client(fakehub).download_file("g1", "d/a.sav", dest) == len(data)
    assert dest.read_bytes() == data
    dest.write_bytes(data[:300])  # trozo previo: se pide con Range y se completa
    assert client(fakehub).download_file("g1", "d/a.sav", dest, offset=300) == len(data)
    assert dest.read_bytes() == data
    assert any(r[2].get("Range") == "bytes=300-" for r in fakehub.requests)


def test_download_missing_file_is_404(fakehub, tmp_path):
    with pytest.raises(hc.HubApiError) as e:
        client(fakehub).download_file("g1", "no.sav", tmp_path / "x")
    assert e.value.status == 404


def test_set_resolution_closed_opened(fakehub):
    c = client(fakehub)
    assert c.set_resolution("g1", "hub", {"hub": "a", "device": "b"}) == {"ok": True}
    assert c.closed("g1", {"state": "ok"}) == {"ok": True}
    assert c.opened("g1") == {"ok": True}
    assert [e[0] for e in fakehub.events] == ["closed", "opened"]
