"""Redacción: ninguna clave de Checkpoint ni secreto sale en un log, un mensaje o el detalle de un fallo."""

import re

from checkpoint_core.redaction import DETAIL_MAX, describe_error, redact

KEY = "ckd_clave-de-prueba-9876"  # literal de prueba (allowlist exacta en .gitleaks.toml)


def test_redact_hides_keys_and_secrets():
    out = redact(f"fallo con {KEY} y ck_otra-1 y SECRET-xyz", "SECRET-xyz")
    assert KEY not in out and "ck_otra-1" not in out and "SECRET-xyz" not in out
    assert redact("sin nada", None, "") == "sin nada"


def test_redact_extra_patterns_are_applied_too():
    steamid = re.compile(r"\b7656119\d{10}\b")
    assert "76561198000000000" in redact("id 76561198000000000")  # el núcleo no sabe de Steam
    assert "76561198000000000" not in redact("id 76561198000000000", extra=(steamid,))


def test_describe_error_has_no_key_and_is_bounded():
    assert DETAIL_MAX == 1500
    out = describe_error(ValueError("motivo largo " * 60 + KEY))
    assert 300 < len(out) <= DETAIL_MAX and KEY not in out
    assert len(describe_error(ValueError("x" * 5000))) == DETAIL_MAX
    assert len(describe_error(ValueError("x" * 5000), limit=50)) == 50


def test_describe_error_shows_status_code_and_endpoint():
    class Api(Exception):
        status, code, endpoint = 409, "err.x", "PUT /api/hook/g/files"

    assert describe_error(Api(f"clave {KEY}")) == "Api: estado 409, código err.x [PUT /api/hook/g/files]"
    assert describe_error(ValueError()) == "ValueError"


def test_describe_error_applies_extra_patterns():
    steamid = re.compile(r"\b7656119\d{10}\b")
    assert "76561198000000000" not in describe_error(ValueError("id 76561198000000000"), extra=(steamid,))
