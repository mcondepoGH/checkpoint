"""Consulta a lutris.net del appid de Steam (`lutris_api_steam`): caché, negativos, errores, cuota por llamada y casado.

Sin red real: `fetch` falso o un servidor HTTP local. Todo SINTÉTICO en tmp_path."""

import json
import os
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import checkpoint_lutris_api as la
import checkpoint_savesuggest as ss
from checkpoint_savemanifest import SaveManifest
from savefix import lutris_db, manifest, mgame, rule

FP = ".var/app/net.lutris.Lutris/data/lutris"
DQ = {"steamid": 2499860}  # forma real verificada: `steamid` entero


class Fake:
    def __init__(self, table=None, default=(404, {"detail": "No Game matches the given query."})):
        self.table, self.default, self.urls = table or {}, default, []

    def __call__(self, url):
        self.urls.append(url)
        r = self.table.get(url.rsplit("/", 1)[1], self.default)
        if isinstance(r, Exception):
            raise r
        return r


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


def api(tmp_path, fake, **kw):
    sleeps = kw.pop("sleeps", [])
    return la.LutrisSteamLookup(str(tmp_path), fetch=fake, sleep=sleeps.append, **kw)


def cache(tmp_path):
    return json.loads((tmp_path / la.CACHE_FILE).read_text())


def test_success_is_cached_and_second_call_does_not_ask(tmp_path):
    f = Fake({"dragon-quest-vii-reimagined": (200, DQ)})
    a = api(tmp_path, f, clock=Clock())
    assert a.lookup_steam_id("dragon-quest-vii-reimagined") == 2499860
    assert f.urls == ["https://lutris.net/api/games/dragon-quest-vii-reimagined"] and a.requests == 1
    assert cache(tmp_path) == {"dragon-quest-vii-reimagined": {"steamid": 2499860, "checked_at": Clock.t}}
    assert oct(os.stat(tmp_path / la.CACHE_FILE).st_mode & 0o777) == "0o600"
    a.begin_call()
    assert a.lookup_steam_id("dragon-quest-vii-reimagined") == 2499860 and a.requests == 0
    b = api(tmp_path, f)  # otra instancia (reinicio): la caché persiste
    assert b.lookup_steam_id("dragon-quest-vii-reimagined") == 2499860 and len(f.urls) == 1


@pytest.mark.parametrize("body", [{"steamid": None}, {"steamid": 0}, {"steamid": ""}, {"slug": "x"}, {"steamid": True}, {"steamid": -3}])
def test_no_steamid_is_negative_cached(tmp_path, body):
    f = Fake({"nethack": (200, body)})
    a = api(tmp_path, f, clock=Clock())
    assert a.lookup_steam_id("nethack") is None
    assert cache(tmp_path)["nethack"]["steamid"] is None
    assert a.lookup_steam_id("nethack") is None and len(f.urls) == 1


def test_steamid_as_digit_string_is_accepted(tmp_path):
    assert api(tmp_path, Fake({"x": (200, {"steamid": "123"})})).lookup_steam_id("x") == 123


def test_404_negative_cached_and_expires_after_30_days_but_positive_never(tmp_path):
    clock = Clock()
    f = Fake({"ok": (200, {"steamid": 7})})
    a = api(tmp_path, f, clock=clock)
    assert a.lookup_steam_id("nope") is None and a.lookup_steam_id("ok") == 7
    assert len(f.urls) == 2
    clock.t += 30 * 86400 - 1
    a.begin_call()
    assert a.lookup_steam_id("nope") is None and a.lookup_steam_id("ok") == 7 and len(f.urls) == 2
    clock.t += 2  # el negativo cumple 30 días; el positivo no caduca
    f.table["nope"] = (200, {"steamid": 99})
    a.begin_call()
    assert a.lookup_steam_id("nope") == 99 and a.lookup_steam_id("ok") == 7
    assert len(f.urls) == 3 and cache(tmp_path)["nope"]["steamid"] == 99


@pytest.mark.parametrize(
    "resp",
    [
        (429, {"detail": "slow"}),
        (500, None),
        (503, {}),
        (200, None),
        (200, ["no", "dict"]),
        OSError("offline"),
        TimeoutError("t"),
        urllib.error.URLError("dns"),
        ValueError("json"),
    ],
)
def test_transient_errors_return_none_do_not_cache_and_stop_the_call(tmp_path, resp):
    f = Fake({"a": resp, "b": (200, {"steamid": 1})})
    a = api(tmp_path, f)
    assert a.lookup_steam_id("a") is None
    assert a.lookup_steam_id("b") is None  # la llamada dejó de preguntar
    assert len(f.urls) == 1 and a.pending == 1
    assert not (tmp_path / la.CACHE_FILE).exists()
    a.begin_call()  # siguiente llamada: reintenta
    f.table["a"] = (200, {"steamid": 5})
    assert a.lookup_steam_id("a") == 5 and a.lookup_steam_id("b") == 1


def test_cap_of_20_new_requests_per_call_with_pauses_and_rest_next_call(tmp_path):
    f = Fake({f"g{i}": (200, {"steamid": 100 + i}) for i in range(25)})
    sleeps = []
    a = api(tmp_path, f, sleeps=sleeps)
    got = [a.lookup_steam_id(f"g{i}") for i in range(25)]
    assert got[:20] == [100 + i for i in range(20)] and got[20:] == [None] * 5
    assert a.requests == 20 and a.pending == 5 and len(f.urls) == 20
    assert len(sleeps) == 19 and min(sleeps) >= 0.5  # pausa entre peticiones, no antes de la primera
    a.begin_call()
    got = [a.lookup_steam_id(f"g{i}") for i in range(25)]
    assert got == [100 + i for i in range(25)] and a.requests == 5 and len(f.urls) == 25


def test_total_time_budget_stops_requests(tmp_path):
    t = [0.0]
    f = Fake({f"g{i}": (200, {"steamid": 1 + i}) for i in range(5)})
    a = api(tmp_path, f, monotonic=lambda: t[0], budget=10.0)
    assert a.lookup_steam_id("g0") == 1
    t[0] = 10.0
    assert a.lookup_steam_id("g1") is None and len(f.urls) == 1 and a.pending == 1


@pytest.mark.parametrize("slug", [None, 5, "", "../etc", "a/b", "A B", "x?y=1", "-x", "é"])
def test_bad_slug_never_goes_out(tmp_path, slug):
    f = Fake()
    assert api(tmp_path, f).lookup_steam_id(slug) is None and f.urls == []


def test_corrupt_cache_is_ignored(tmp_path):
    (tmp_path / la.CACHE_FILE).write_text(json.dumps({"a": {"steamid": "x", "checked_at": 1}, "b": 3, "c": {"steamid": 4, "checked_at": 1}}))
    f = Fake({"a": (200, {"steamid": 9})})
    a = api(tmp_path, f)
    assert a.lookup_steam_id("c") == 4 and a.lookup_steam_id("a") == 9 and len(f.urls) == 1


def test_real_http_path_user_agent_no_credentials_and_status_handling(tmp_path):
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(dict(self.headers))
            slug = self.path.rsplit("/", 1)[1]
            code, body = {"dq": (200, {"name": "DQ", "steamid": 2499860, "id": 1}), "nethack": (200, {"steamid": None}), "rl": (429, {})}.get(
                slug, (404, {"detail": "No Game matches the given query."})
            )
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        a = la.LutrisSteamLookup(str(tmp_path), base_url=f"http://127.0.0.1:{srv.server_port}/api/games", sleep=lambda s: None)
        assert a.lookup_steam_id("dq") == 2499860
        assert a.lookup_steam_id("nethack") is None and a.lookup_steam_id("zz") is None
        assert set(cache(tmp_path)) == {"dq", "nethack", "zz"}
        a.begin_call()
        assert a.lookup_steam_id("rl") is None and "rl" not in cache(tmp_path)
    finally:
        srv.shutdown()
    assert all(h["User-Agent"] == "Checkpoint-Decky/1.0" for h in seen)
    assert not any(k.lower() in ("authorization", "cookie", "x-api-key") for h in seen for k in h)
    # servidor caído: no rompe
    b = la.LutrisSteamLookup(str(tmp_path / "otra"), base_url="http://127.0.0.1:1/api/games", sleep=lambda s: None)
    assert b.lookup_steam_id("dq") is None and not (tmp_path / "otra" / la.CACHE_FILE).exists()


# ---- integración en el casado
def world(tmp_path, rows, *games):
    home = tmp_path / "home"
    lutris_db(home / FP, rows)
    return home, SaveManifest.from_bytes(manifest(*games))


def dq_manifest(**kw):
    return mgame("Dragon Quest VII Reimagined", steam=2499860, paths=[rule("home", "dq/saves")], **kw)


ROW = {"id": 1, "name": "Dragon Quest VII Reimagined", "slug": "dragon-quest-vii-reimagined"}


def test_lutris_game_matches_by_api_steam_high(tmp_path):
    home, m = world(tmp_path, [ROW], dq_manifest())
    f = Fake({ROW["slug"]: (200, DQ)})
    a = api(tmp_path, f)
    out = ss.suggest_all(m, home, lookup=a.lookup_steam_id)
    assert len(out) == 1
    assert (out[0]["match"], out[0]["confidence"]) == ({"by": "lutris_api_steam", "id": 2499860}, "high")
    assert out[0]["needs_confirmation"] is True and a.requests == 1


def test_api_steam_beats_secondary_slug_derived_and_falls_back_when_no_steamid(tmp_path):
    home, m = world(tmp_path, [ROW], dq_manifest(slug=ROW["slug"]))
    f = Fake({ROW["slug"]: (200, DQ)})
    r = ss.suggest_all(m, home, lookup=api(tmp_path, f).lookup_steam_id)[0]
    assert r["match"]["by"] == "lutris_api_steam" and r["confidence"] == "high"
    for resp in ((404, {}), (200, {"steamid": None}), (429, {})):  # sin appid o error: cae al secundario
        r = ss.suggest_all(m, home, lookup=api(tmp_path / str(resp), Fake({ROW["slug"]: resp})).lookup_steam_id)[0]
        assert (r["match"]["by"], r["confidence"]) == ("slug_derived", "doubtful")


def test_games_matched_by_service_or_lutris_slug_do_not_query(tmp_path):
    rows = [
        {"id": 1, "name": "A", "slug": "a-game", "service": "steam", "service_id": "11"},
        {"id": 2, "name": "B", "slug": "b-slug"},
    ]
    home, m = world(tmp_path, rows, mgame("A", steam=11, paths=[rule("home", "a")]), mgame("B", lutris="b-slug", steam=22, paths=[rule("home", "b")]))
    f = Fake({"b-slug": (200, {"steamid": 22})})
    a = api(tmp_path, f)
    out = ss.suggest_all(m, home, lookup=a.lookup_steam_id)
    assert [g["match"]["by"] for g in out] == ["lutris_service_steam", "lutris_slug"]
    assert f.urls == [] and a.requests == 0


def test_steam_games_and_no_lookup_never_query(tmp_path):
    home, m = world(tmp_path, [ROW], dq_manifest())
    a = api(tmp_path, Fake({ROW["slug"]: (200, DQ)}))
    assert [g["match"]["by"] for g in ss.suggest_all(m, home)] == ["name"]  # sin lookup: sin red, solo el secundario
    assert a.requests == 0 and ss.match_game(m, _steam(2499860), a.lookup_steam_id)[1] == "steam_appid" and a.requests == 0


def _steam(appid):
    import checkpoint_installed as ci

    return ci.InstalledGame(source="steam", id=appid, name="x")


def test_suggester_reports_counts_serialises_and_honours_switch(tmp_path):
    home, m = world(tmp_path, [ROW], dq_manifest())
    (tmp_path / "save_manifest.json").write_bytes(manifest(dq_manifest()))
    f = Fake({ROW["slug"]: (200, DQ)})
    on = [True]
    s = ss.SaveSuggester(str(tmp_path), home=home, lookup=api(tmp_path, f), lookup_enabled=lambda: on[0])
    on[0] = False
    out = s.all()
    assert [g["match"]["by"] for g in out["games"]] == ["name"] and out["network_lookups"] == 0 and f.urls == []
    on[0] = True
    out = s.all()
    assert out["games"][0]["match"]["by"] == "lutris_api_steam" and out["network_lookups"] == 1 and out["lookups_pending"] == 0
    out = s.one("lutris", ROW["slug"])
    assert out["game"]["match"]["by"] == "lutris_api_steam" and out["network_lookups"] == 0 and len(f.urls) == 1
    json.dumps(out)


def test_suggester_pending_when_error(tmp_path):
    home, _ = world(tmp_path, [ROW])
    (tmp_path / "save_manifest.json").write_bytes(manifest(dq_manifest()))
    s = ss.SaveSuggester(str(tmp_path), home=home, lookup=api(tmp_path, Fake({ROW["slug"]: OSError()})))
    out = s.all()
    assert [g["match"]["by"] for g in out["games"]] == ["name"] and out["network_lookups"] == 1 and out["lookups_pending"] == 0
