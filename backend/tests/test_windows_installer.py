"""installer.iss no se puede compilar en Linux: aquí solo se comprueba lo estático (paridad es/en del asistente y
que cada {cm:...} / CustomMessage('...') tiene texto en los dos idiomas)."""

import re
from pathlib import Path

ISS = (Path(__file__).resolve().parents[2] / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8")


def _section(name):
    m = re.search(rf"^\[{name}\]\n(.*?)(?=^\[|\Z)", ISS, re.S | re.M)
    return m.group(1) if m else ""


def _keys(section, lang):
    return {m.group(1) for m in re.finditer(rf"^{lang}\.(\w+)=", section, re.M)}


def test_custom_messages_paridad_es_en():
    cm = _section("CustomMessages")
    es, en = _keys(cm, "spanish"), _keys(cm, "english")
    assert es and es == en


def test_messages_paridad_es_en():
    m = _section("Messages")
    assert _keys(m, "spanish") == _keys(m, "english") != set()


def test_todo_custom_message_usado_esta_definido():
    defined = _keys(_section("CustomMessages"), "spanish")
    used = set(re.findall(r"CustomMessage\('(\w+)'\)", ISS)) | set(re.findall(r"\{cm:(\w+)\}", ISS))
    assert used <= defined, used - defined


def test_instalacion_por_usuario_y_parametros_silenciosos():
    assert "PrivilegesRequired=lowest" in ISS
    for p in ("NOLOGIN", "CPUSER", "CPPASSWORD"):
        assert p in ISS


def test_contrasena_limitada_a_72():
    assert ISS.count("MaxLength := 72") == 2
