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


def _new_password():
    m = re.search(r"^function NewPassword: String;\n(.*?)^end;", ISS, re.S | re.M)
    assert m
    return m.group(1)


def test_generacion_de_contrasena_sin_plan_b_debil():
    body = _new_password()
    assert "Random(" not in body and "Randomize" not in body
    assert "GetInt32" not in body  # no existe en Windows PowerShell 5.1
    assert "RandomNumberGenerator]::Create()" in body and "GetBytes" in body
    assert "Result := ''" in body  # fallo o longitud inválida: cadena vacía


def test_fallo_de_generacion_avisa_y_exige_minimo():
    cm = _section("CustomMessages")
    for lang in ("spanish", "english"):
        assert f"{lang}.PwGenFailed=" in cm and f"{lang}.PasswordShort=" in cm
    assert "CustomMessage('PwGenFailed')" in ISS and "CustomMessage('PasswordShort')" in ISS
    assert "Length(PassEdit.Text) < 8" in ISS


def _spec():
    return (Path(__file__).resolve().parents[2] / "packaging/windows/checkpoint.spec").read_text(encoding="utf-8")


def test_spec_no_depende_de_collect_submodules_app():
    """collect_submodules('app') se evalúa al cargar el spec, cuando backend/ aún no está en sys.path: devolvía []
    y el bundle salía sin el paquete `app`. Se recorren los ficheros de backend/app, sin importar nada."""
    spec = _spec()
    assert 'collect_submodules("app")' not in spec and "collect_submodules('app')" not in spec
    assert '"backend", "app"' in spec and "os.walk" in spec
    assert "hiddenimports=hidden" in spec
    for mod in ("fastapi", "starlette", "uvicorn"):
        assert f'"{mod}"' in spec


def test_spec_comprueba_que_el_paquete_app_no_sale_vacio():
    spec = _spec()
    assert "app.main" in spec and "sys.exit" in spec


def test_modulos_descubiertos_por_el_spec_incluyen_main_y_routers():
    """Misma lógica que el spec, replicada: si cambia la estructura de backend/app hay que mirar el spec."""
    import os

    base = Path(__file__).resolve().parents[1]
    mods = set()
    for dirpath, _dirs, files in os.walk(base / "app"):
        rel = Path(dirpath).relative_to(base)
        for f in files:
            if f.endswith(".py"):
                mods.add(".".join(rel.parts if f == "__init__.py" else (*rel.parts, f[:-3])))
    assert {"app.main", "app.cli", "app.core.settings"} <= mods


def test_smoke_vuelca_log_y_salida_y_falla_rapido_si_el_hub_muere():
    smoke = (Path(__file__).resolve().parents[2] / "packaging/windows/smoke.ps1").read_text(encoding="utf-8")
    assert "HasExited" in smoke
    assert "checkpoint.log" in smoke and "stdout" in smoke and "stderr" in smoke
    assert "finally" in smoke and smoke.index("Show-Diagnostics") < smoke.index("finally")


def test_cli_serve_importa_app_estaticamente():
    cli = (Path(__file__).resolve().parents[1] / "app/cli.py").read_text(encoding="utf-8")
    assert "from .main import app_factory" in cli and '"app.main:app_factory"' not in cli.split("def serve")[1]
