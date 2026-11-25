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


def test_nombre_del_instalador_coincide_entre_iss_build_release_y_selfupdate():
    """El nombre del asset lo fija installer.iss y lo esperan build.ps1, release.yml y la actualización con un clic."""
    from app.core import updates

    root = Path(__file__).resolve().parents[2]
    prefix = updates.INSTALLER_NAME.format(version="{#AppVersion}").replace(".exe", "")
    assert f"OutputBaseFilename={prefix}" in ISS
    stem = updates.INSTALLER_NAME.replace("{version}", "$version")
    assert stem in (root / "packaging/windows/build.ps1").read_text(encoding="utf-8")
    release = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert stem in release and '"packaging/windows/Output/$name.sha256"' in release
    assert "-Tag $env:TAG" in release  # verifica VERSION contra el tag


def test_ci_construye_y_prueba_el_instalador():
    root = Path(__file__).resolve().parents[2]
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "windows-installer:" in ci and "smoke.ps1" in ci
    smoke = (root / "packaging/windows/smoke.ps1").read_text(encoding="utf-8")
    assert "127.0.0.1:8088" in smoke and "/NOLOGIN=1" in smoke
