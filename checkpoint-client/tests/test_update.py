"""Comprobación de versión nueva: Release de GitHub, wheel del cliente, caché y tolerancia a fallos (sin red real)."""

import json
import os
import stat
from pathlib import Path

import pytest
from conftest import release

from checkpoint_client import update

CUR = "1.0.0"
WHEEL = "checkpoint_client-1.2.0-py3-none-any.whl"


# ---------------------------------------------------------------- nombre del wheel y elección
@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("checkpoint_client-1.2.0-py3-none-any.whl", "1.2.0"),
        ("checkpoint_client-10.20.30-py3-none-any.whl", "10.20.30"),
        ("checkpoint_client-1.2.0-py3-none-linux_x86_64.whl", "1.2.0"),
        ("checkpoint_client-1.2-py3-none-any.whl", None),  # no es X.Y.Z
        ("checkpoint_client-1.2.0rc1-py3-none-any.whl", None),  # pre-release PEP 440: canal estable, se ignora
        ("checkpoint_client-01.2.0-py3-none-any.whl", None),
        ("otro_paquete-1.2.0-py3-none-any.whl", None),
        ("checkpoint_client-1.2.0.tar.gz", None),
        ("checkpoint_client-1.2.0.whl", None),
        ("../checkpoint_client-1.2.0-py3-none-any.whl", None),
        (None, None),
        (5, None),
    ],
)
def test_parse_wheel_version(name, version):
    assert update.parse_wheel_version(name) == version


def test_pick_wheel_uses_the_asset_of_the_release():
    assert update.pick_wheel(release()) == (
        "1.2.0",
        "https://github.com/mcondepoGH/checkpoint/releases/download/v1.4.0/" + WHEEL,
    )


def test_pick_wheel_none_when_the_release_has_no_wheel():
    assert update.pick_wheel(release(wheels=())) is None


def test_pick_wheel_takes_the_highest_when_there_are_several():
    rel = release(wheels=("checkpoint_client-1.2.0-py3-none-any.whl", "checkpoint_client-1.10.0-py3-none-any.whl"))
    assert update.pick_wheel(rel)[0] == "1.10.0"


@pytest.mark.parametrize("bad", [None, [], "x", {}, {"assets": None}, {"assets": "x"}, {"assets": [None, 3, {}]}])
def test_pick_wheel_tolerates_garbage(bad):
    assert update.pick_wheel(bad) is None


def test_pick_wheel_ignores_a_download_url_that_is_not_https():
    rel = {"assets": [{"name": WHEEL, "browser_download_url": "http://evil.example/" + WHEEL}]}
    assert update.pick_wheel(rel) is None
    assert update.pick_wheel({"assets": [{"name": WHEEL, "browser_download_url": "file:///etc/passwd"}]}) is None
    assert update.pick_wheel({"assets": [{"name": WHEEL}]}) is None


def test_pick_wheel_ignores_a_prerelease_or_draft_release():
    assert update.pick_wheel(release(prerelease=True)) is None
    assert update.pick_wheel({**release(), "draft": True}) is None


# ---------------------------------------------------------------- check con un fetch inyectado
class Fetch:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result if result is not None else release(), error, []

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        if self.error:
            raise update.UpdateError(self.error)
        return self.result


def now():
    return 1_000_000.0


def test_new_version_available_gives_the_wheel_url(settings_dir):
    r = update.check(settings_dir, CUR, fetch=Fetch(), clock=now)
    assert r["state"] == "available" and r["latest"] == "1.2.0" and r["current"] == CUR
    assert r["wheel_url"].endswith("/" + WHEEL) and r["reason"] is None


def test_same_version_is_up_to_date(settings_dir):
    r = update.check(settings_dir, "1.2.0", fetch=Fetch(), clock=now)
    assert r["state"] == "up_to_date" and r["latest"] == "1.2.0"


def test_installed_newer_than_release_is_up_to_date(settings_dir):
    assert update.check(settings_dir, "1.3.0", fetch=Fetch(), clock=now)["state"] == "up_to_date"


def test_release_without_wheel_means_no_new_version(settings_dir):
    r = update.check(settings_dir, CUR, fetch=Fetch(release(wheels=())), clock=now)
    assert r["state"] == "up_to_date" and r["latest"] is None and r["wheel_url"] is None


def test_prerelease_release_is_ignored_on_the_stable_channel(settings_dir):
    assert update.check(settings_dir, CUR, fetch=Fetch(release(prerelease=True)), clock=now)["state"] == "up_to_date"


def test_unreadable_installed_version_never_offers_anything(settings_dir):
    assert update.check(settings_dir, "basura", fetch=Fetch(), clock=now)["state"] == "up_to_date"


@pytest.mark.parametrize("code", ["rate_limited", "network", "timeout", "invalid", "http"])
def test_fetch_failures_are_reported_and_not_cached(settings_dir, code):
    r = update.check(settings_dir, CUR, fetch=Fetch(error=code), clock=now)
    assert r["state"] == "error" and r["reason"] == code and r["latest"] is None
    assert not os.path.exists(os.path.join(settings_dir, update.CACHE_FILE))


# ---------------------------------------------------------------- caché
def test_second_check_inside_the_ttl_does_not_ask_again(settings_dir):
    f = Fetch()
    update.check(settings_dir, CUR, fetch=f, clock=now)
    r = update.check(settings_dir, CUR, fetch=f, clock=lambda: now() + update.CACHE_TTL - 1)
    assert len(f.calls) == 1 and r["state"] == "available" and r["latest"] == "1.2.0"


def test_cache_expires_after_the_ttl(settings_dir):
    f = Fetch()
    update.check(settings_dir, CUR, fetch=f, clock=now)
    update.check(settings_dir, CUR, fetch=f, clock=lambda: now() + update.CACHE_TTL + 1)
    assert len(f.calls) == 2


def test_cache_ttl_is_at_most_six_hours():
    assert 0 < update.CACHE_TTL <= 6 * 3600


def test_cache_keeps_a_no_wheel_answer_too(settings_dir):
    f = Fetch(release(wheels=()))
    update.check(settings_dir, CUR, fetch=f, clock=now)
    update.check(settings_dir, CUR, fetch=f, clock=now)
    assert len(f.calls) == 1


def test_cache_is_judged_against_the_installed_version_each_time(settings_dir):
    f = Fetch()
    assert update.check(settings_dir, CUR, fetch=f, clock=now)["state"] == "available"
    assert update.check(settings_dir, "1.2.0", fetch=f, clock=now)["state"] == "up_to_date"  # ya actualizado
    assert len(f.calls) == 1


def test_cache_from_another_source_is_not_used(settings_dir):
    f = Fetch()
    update.check(settings_dir, CUR, fetch=f, clock=now, url="https://a.example/releases/latest")
    update.check(settings_dir, CUR, fetch=f, clock=now, url="https://b.example/releases/latest")
    assert len(f.calls) == 2


@pytest.mark.parametrize(
    "content",
    [
        "no es json",
        "[]",
        '{"source": 1}',
        json.dumps({"checked_at": "ayer"}),
        json.dumps({"checked_at": 1e9, "latest": 5}),
    ],
)
def test_garbage_cache_is_ignored(settings_dir, content):
    Path(settings_dir).mkdir(parents=True)
    (Path(settings_dir) / update.CACHE_FILE).write_text(content, encoding="utf-8")
    f = Fetch()
    assert update.check(settings_dir, CUR, fetch=f, clock=now)["state"] == "available"
    assert len(f.calls) == 1


def test_cache_from_the_future_is_ignored(settings_dir):
    f = Fetch()
    update.check(settings_dir, CUR, fetch=f, clock=lambda: now() + 10_000)
    update.check(settings_dir, CUR, fetch=f, clock=now)  # el reloj retrocedió: no se fía de la caché
    assert len(f.calls) == 2


def test_cache_file_is_private_and_holds_no_secret(settings_dir):
    update.check(settings_dir, CUR, fetch=Fetch(), clock=now)
    p = Path(settings_dir) / update.CACHE_FILE
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert "ckd_" not in p.read_text(encoding="utf-8")


def test_unwritable_config_dir_does_not_break_the_check(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    r = update.check(str(blocker / "cfg"), CUR, fetch=Fetch(), clock=now)
    assert r["state"] == "available"


# ---------------------------------------------------------------- fetch real contra la API falsa
def test_fetch_asks_the_public_api_without_credentials(fakegithub):
    body = update.fetch_latest(fakegithub.url, 2)
    assert body["tag_name"] == "v1.4.0"
    req = fakegithub.requests[0]
    assert req["path"].endswith("/releases/latest")
    assert "authorization" not in req["headers"] and "cookie" not in req["headers"]
    assert req["headers"]["user-agent"].startswith("checkpoint-client/")
    assert "json" in req["headers"]["accept"]


@pytest.mark.parametrize(
    ("status", "headers", "reason"),
    [
        (403, {"X-RateLimit-Remaining": "0"}, "rate_limited"),
        (403, {}, "rate_limited"),
        (429, {"Retry-After": "60"}, "rate_limited"),
        (404, {}, "http"),
        (500, {}, "http"),
        (302, {"Location": "http://evil.example/x"}, "http"),
    ],
)
def test_fetch_http_errors(fakegithub, status, headers, reason):
    fakegithub.response = (status, {"message": "x"}, headers)
    with pytest.raises(update.UpdateError) as e:
        update.fetch_latest(fakegithub.url, 2)
    assert e.value.reason == reason


@pytest.mark.parametrize("body", [b"<html>", b"", b"[]", b'"x"', b"\xff\xfe"])
def test_fetch_invalid_json_or_shape(fakegithub, body):
    fakegithub.response = (200, body, {})
    with pytest.raises(update.UpdateError) as e:
        update.fetch_latest(fakegithub.url, 2)
    assert e.value.reason == "invalid"


def test_fetch_oversized_body_is_invalid(fakegithub):
    fakegithub.response = (200, b'{"x": "' + b"a" * (update.MAX_BODY + 10) + b'"}', {})
    with pytest.raises(update.UpdateError) as e:
        update.fetch_latest(fakegithub.url, 2)
    assert e.value.reason == "invalid"


def test_fetch_timeout(fakegithub):
    fakegithub.delay = 1.0
    with pytest.raises(update.UpdateError) as e:
        update.fetch_latest(fakegithub.url, 0.2)
    assert e.value.reason == "timeout"


def test_fetch_connection_refused():
    with pytest.raises(update.UpdateError) as e:
        update.fetch_latest("http://127.0.0.1:1/releases/latest", 1)
    assert e.value.reason == "network"


def test_check_end_to_end_against_the_fake_api(fakegithub, settings_dir):
    r = update.check(settings_dir, CUR)
    assert r["state"] == "available" and len(fakegithub.requests) == 1
    update.check(settings_dir, CUR)
    assert len(fakegithub.requests) == 1  # caché


def test_default_url_is_the_public_repo_without_override(monkeypatch):
    monkeypatch.delenv("CHECKPOINT_CLIENT_RELEASES_URL", raising=False)
    assert update.releases_url() == "https://api.github.com/repos/mcondepoGH/checkpoint/releases/latest"


def test_module_has_no_shell_tokens_nor_access_to_the_device_key():
    import ast

    src = Path(update.__file__).read_text(encoding="utf-8")
    for bad in ("subprocess", "os.system", "GITHUB_TOKEN", "Authorization"):
        assert bad not in src
    imported = {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not imported & {"hub", "hubclient", "keystore"}  # el módulo no puede ni leer la clave
