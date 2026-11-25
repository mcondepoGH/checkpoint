"""packaging/linux/install.sh: instalación, actualización y desinstalación con systemd de usuario.

Ejecutan el script de verdad en un HOME temporal, con un `systemctl`/`loginctl` falsos (registran las llamadas) y un
Python falso (no crea venvs ni descarga nada). La instalación real (venv, pip, hub arrancado) la ejercita `smoke.sh` en CI."""

import os
import pty
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LINUX = ROOT / "packaging" / "linux"
INSTALL = LINUX / "install.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash no disponible")

OTRA = "otra-contrasena-1"  # una segunda contraseña de prueba
GENERADA = "Gen-Pass_abcdefghijklmnop"  # la que devuelve el Python falso
PW = "S3cret-Pass-123"  # contraseña de prueba: no debe salir NUNCA por la salida ni por la unidad


class Sandbox:
    """HOME temporal + herramientas falsas. `src(version)` crea el contenido de un tarball extraído."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.log = tmp_path / "calls.log"
        self.log.write_text("", encoding="utf-8")
        self._tool("systemctl", self._SYSTEMCTL)
        self._tool("loginctl", self._LOGINCTL)
        self._tool("python", self._PYTHON.replace("@REAL@", sys.executable))
        self.systemctl, self.loginctl, self.python = (self.bin / n for n in ("systemctl", "loginctl", "python"))

    _SYSTEMCTL = """#!/usr/bin/env bash
echo "systemctl $*" >> "$FAKE_LOG"
[ "$2" = show-environment ] && { [ "${FAKE_SYSTEMD:-1}" = 1 ]; exit; }
case " ${FAKE_FAIL:-} " in *" $2 "*) exit 1 ;; esac
exit 0
"""
    _LOGINCTL = """#!/usr/bin/env bash
echo "loginctl $*" >> "$FAKE_LOG"
[ "$1" = show-user ] && echo "Linger=${FAKE_LINGER:-yes}"
exit 0
"""
    _PYTHON = """#!/usr/bin/env bash
echo "python $*" >> "$FAKE_LOG"
[ "$1" = -I ] && shift
case "$1" in
  -c) case "$2" in
        *version_info*) [ "${FAKE_PY_OLD:-0}" = 1 ] && exit 1; exit 0 ;;
        *import\\ venv*) [ "${FAKE_NO_VENV:-0}" = 1 ] && exit 1; exit 0 ;;
        *token_urlsafe*) echo "Gen-Pass_abcdefghijklmnop"; exit 0 ;;
      esac
      exec "@REAL@" -I -c "$2" "${@:3}" ;;
  -m) case "$2" in
        venv) mkdir -p "$3/bin"; cp "$0" "$3/bin/python"; exit 0 ;;
        pip) [ "${FAKE_PIP_FAIL:-0}" = 1 ] && exit 1; exit 0 ;;
      esac ;;
esac
exit 0
"""

    def _tool(self, name, text):
        p = self.bin / name
        p.write_text(text, encoding="utf-8")
        p.chmod(0o755)

    def src(self, version="9.9.9", name=None):
        d = self.tmp / (name or f"src-{version}") / f"checkpoint-{version}"
        (d / "backend" / "app").mkdir(parents=True, exist_ok=True)
        (d / "backend" / "static").mkdir(exist_ok=True)
        (d / "backend" / "app" / "cli.py").write_text(f"# v{version}\n", encoding="utf-8")
        (d / "backend" / "static" / "index.html").write_text("<html></html>", encoding="utf-8")
        (d / "backend" / "requirements.txt").write_text("fastapi==0\n", encoding="utf-8")
        (d / "checkpoint-deck" / "out").mkdir(parents=True, exist_ok=True)
        (d / "checkpoint-deck" / "out" / "Checkpoint.zip").write_bytes(b"PK")
        (d / "VERSION").write_text(version + "\n", encoding="utf-8")
        shutil.copy(INSTALL, d / "install.sh")
        return d

    def env(self, **extra):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("CHECKPOINT_", "XDG_", "FAKE_"))}
        e.update(
            HOME=str(self.home),
            SYSTEMCTL=str(self.systemctl),
            LOGINCTL=str(self.loginctl),
            PYTHON=str(self.python),
            FAKE_LOG=str(self.log),
            CHECKPOINT_INSTALL_WAIT="0",
            USER="tester",
            LANG="C.UTF-8",
        )
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def run(self, src, *args, stdin="", **extra):
        r = subprocess.run(
            [BASH, str(src / "install.sh"), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env(**extra),
            input=stdin,
            cwd=self.tmp,
            timeout=60,
        )
        return r

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines()

    def sysctl_calls(self):
        return [c for c in self.calls() if c.startswith("systemctl ") and "show-environment" not in c]

    # rutas por defecto
    @property
    def app(self):
        return self.home / ".local" / "share" / "checkpoint-app"

    @property
    def conf(self):
        return self.home / ".config" / "checkpoint"

    @property
    def envfile(self):
        return self.conf / "checkpoint.env"

    @property
    def unit(self):
        return self.home / ".config" / "systemd" / "user" / "checkpoint.service"

    @property
    def data(self):
        return self.home / ".local" / "share" / "checkpoint"


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path)


def all_output(r):
    return r.stdout + r.stderr


def install_ok(sb, *args, version="9.9.9", **extra):
    src = sb.src(version)
    r = sb.run(src, *args, **extra)
    assert r.returncode == 0, all_output(r)
    return src, r


def tree(p: Path):
    return sorted(str(x.relative_to(p)) for x in p.rglob("*")) if p.exists() else []


# ---------------------------------------------------------------- estructura estática


def test_el_script_no_usa_eval_ni_acepta_la_contrasena_por_linea_de_comandos():
    t = INSTALL.read_text(encoding="utf-8")
    assert "set -euo pipefail" in t and "umask 077" in t and "trap " in t
    assert "eval " not in t.replace("evaluar", "")
    assert "CHECKPOINT_RUNTIME=native" in t
    assert "--password)" not in t and "--password " not in t.replace("--password-file", "")


def test_ayuda_lista_las_opciones(sb):
    r = sb.run(sb.src(), "--help")
    assert r.returncode == 0
    for o in (
        "--upgrade",
        "--uninstall",
        "--purge",
        "--no-login",
        "--port",
        "--host",
        "--no-start",
        "--dry-run",
        "--user",
        "--password-file",
        "--enable-linger",
        "CHECKPOINT_USER",
        "CHECKPOINT_PASSWORD",
    ):
        assert o in r.stdout, o


def test_opcion_desconocida_y_contrasena_en_linea_de_comandos_se_rechazan(sb):
    src = sb.src()
    for bad in (["--nope"], ["--password", "x"]):
        r = sb.run(src, *bad)
        assert r.returncode == 2 and "install.sh" in r.stderr
    assert tree(sb.home) == []


# ---------------------------------------------------------------- instalación


def test_instala_sin_login_y_sin_arrancar(sb):
    src, r = install_ok(sb, "--no-login", "--no-start")
    v = sb.app / "9.9.9"
    assert (v / "backend" / "app" / "cli.py").is_file()
    assert (v / "backend" / "static" / "index.html").is_file()
    assert (v / "backend" / "requirements.txt").is_file()
    assert (v / "checkpoint-deck" / "out" / "Checkpoint.zip").is_file()
    assert (v / "VERSION").read_text(encoding="utf-8").strip() == "9.9.9"
    assert (v / "venv" / "bin" / "python").exists()
    assert (v / "install.sh").is_file()
    cur = sb.app / "current"
    assert cur.is_symlink() and os.readlink(cur) == "9.9.9"
    assert any("-m pip install" in c and "requirements.txt" in c for c in sb.calls())
    txt = sb.envfile.read_text(encoding="utf-8")
    assert "CHECKPOINT_USER" not in txt and "CHECKPOINT_PASSWORD" not in txt
    assert oct(sb.envfile.stat().st_mode & 0o777) == "0o600"
    assert sb.unit.is_file()
    # sin arrancar: ni enable ni start ni restart
    assert not any(" enable" in c or " start" in c or " restart" in c for c in sb.sysctl_calls())
    assert "systemctl --user enable --now checkpoint" in all_output(r)
    assert not sb.data.exists()  # el hub crea sus datos; el instalador no


def test_unidad_generada(sb):
    install_ok(sb, "--no-login", "--no-start")
    u = sb.unit.read_text(encoding="utf-8")
    cur = sb.app / "current"
    assert f'ExecStart="{cur}/venv/bin/python" -m app.cli serve\n' in u
    assert f"WorkingDirectory={cur}/backend\n" in u
    assert f"EnvironmentFile={sb.envfile}\n" in u
    assert "Environment=CHECKPOINT_RUNTIME=native\n" in u
    assert "Restart=on-failure\n" in u
    assert "WantedBy=default.target\n" in u
    assert "[Unit]" in u and "[Service]" in u and "[Install]" in u


def test_instala_y_arranca_con_credenciales_del_entorno(sb):
    src, r = install_ok(sb, CHECKPOINT_USER="ana", CHECKPOINT_PASSWORD=PW)
    txt = sb.envfile.read_text(encoding="utf-8")
    assert 'CHECKPOINT_USER="ana"\n' in txt and f'CHECKPOINT_PASSWORD="{PW}"\n' in txt
    assert oct(sb.envfile.stat().st_mode & 0o777) == "0o600"
    sc = sb.sysctl_calls()
    assert "systemctl --user daemon-reload" in sc
    assert "systemctl --user enable --now checkpoint" in sc
    assert PW not in all_output(r) and PW not in sb.unit.read_text(encoding="utf-8")
    assert PW not in "\n".join(sb.calls())  # nunca por argumentos de ningún comando


def test_credenciales_con_user_y_fichero_de_contrasena(sb):
    pwf = sb.tmp / "pw.txt"
    pwf.write_text(PW + "\n", encoding="utf-8")
    src, r = install_ok(sb, "--user", "luis", "--password-file", str(pwf))
    txt = sb.envfile.read_text(encoding="utf-8")
    assert 'CHECKPOINT_USER="luis"\n' in txt and f'CHECKPOINT_PASSWORD="{PW}"\n' in txt
    assert PW not in all_output(r)


def test_contrasena_con_caracteres_especiales_se_escapa_en_el_env(sb):
    pw = "a\"b\\c$d%e'f g#h"
    install_ok(sb, "--no-start", CHECKPOINT_USER="ana", CHECKPOINT_PASSWORD=pw)
    assert 'CHECKPOINT_PASSWORD="a\\"b\\\\c$d%e\'f g#h"\n' in sb.envfile.read_text(encoding="utf-8")
    assert pw not in sb.unit.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "pw,msg",
    [("corta1", "8 caracteres"), ("x" * 73, "72 bytes"), ("ñ" * 37, "72 bytes"), ("con\ttab-largo", "control")],
)
def test_rechaza_contrasenas_invalidas_sin_instalar_nada(sb, pw, msg):
    r = sb.run(sb.src(), "--no-start", CHECKPOINT_USER="ana", CHECKPOINT_PASSWORD=pw)
    assert r.returncode != 0 and msg in r.stderr
    assert tree(sb.home) == []


@pytest.mark.parametrize("pw", ["x" * 72, "ñ" * 8])
def test_acepta_72_bytes_y_ocho_caracteres_multibyte(sb, pw):
    r = sb.run(sb.src(), "--no-start", CHECKPOINT_USER="ana", CHECKPOINT_PASSWORD=pw)
    assert r.returncode == 0, all_output(r)


def test_sin_terminal_y_sin_credenciales_explica_las_tres_salidas(sb):
    r = sb.run(sb.src(), "--no-start")
    assert r.returncode != 0
    for t in ("CHECKPOINT_USER", "--password-file", "--no-login"):
        assert t in r.stderr
    assert tree(sb.home) == []


def test_user_sin_contrasena_falla(sb):
    r = sb.run(sb.src(), "--user", "ana")
    assert r.returncode != 0 and "contraseña" in r.stderr


def test_no_login_con_host_no_local_se_rechaza(sb):
    r = sb.run(sb.src(), "--no-login", "--host", "0.0.0.0")
    assert r.returncode != 0 and "127.0.0.1" in r.stderr
    assert tree(sb.home) == []


def test_host_y_puerto_van_al_env(sb):
    install_ok(sb, "--no-start", "--host", "0.0.0.0", "--port", "9090", CHECKPOINT_USER="ana", CHECKPOINT_PASSWORD=PW)
    t = sb.envfile.read_text(encoding="utf-8")
    assert 'CHECKPOINT_HOST="0.0.0.0"\n' in t and 'CHECKPOINT_PORT="9090"\n' in t


@pytest.mark.parametrize("port", ["0", "65536", "abc", "80x", ""])
def test_puerto_invalido(sb, port):
    r = sb.run(sb.src(), "--no-login", "--port", port)
    assert r.returncode != 0 and "puerto" in r.stderr.lower()
    assert tree(sb.home) == []


def test_python_viejo_avisa_y_no_instala_nada(sb):
    r = sb.run(sb.src(), "--no-login", FAKE_PY_OLD="1")
    assert r.returncode != 0
    assert "Python 3.12" in r.stderr and "no instalo nada" in r.stderr
    assert tree(sb.home) == []
    assert sb.sysctl_calls() == []


def test_sin_venv_avisa_con_el_paquete_de_la_distro(sb):
    r = sb.run(sb.src(), "--no-login", FAKE_NO_VENV="1")
    assert r.returncode != 0 and "venv" in r.stderr and "python3-venv" in r.stderr
    assert tree(sb.home) == []


def test_busca_python312_si_python3_es_viejo(sb, tmp_path):
    bindir = tmp_path / "pybin"
    bindir.mkdir()
    # El instalador prueba python3, python3.14, python3.13 y python3.12 en ese orden: se falsean todos para que un
    # Python real del sistema o del runner (p. ej. /usr/bin/python3.14) no gane a python3.12.
    for name, ok in (("python3", "1"), ("python3.14", "1"), ("python3.13", "1"), ("python3.12", "0")):
        p = bindir / name
        p.write_text(f'#!/usr/bin/env bash\ncase "$2" in *version_info*) exit {ok} ;; esac\nexit 0\n', encoding="utf-8")
        p.chmod(0o755)
    src = sb.src()
    env = sb.env()
    del env["PYTHON"]
    env["PATH"] = f"{bindir}:{os.environ['PATH']}"
    env["CHECKPOINT_MIN_PYTHON"] = "3.12"
    r = subprocess.run(
        [BASH, str(src / "install.sh"), "--dry-run", "--no-login"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert r.returncode == 0, all_output(r)
    assert str(bindir / "python3.12") in all_output(r)


def test_python_explicito_viejo_no_busca_otro(sb):
    r = sb.run(sb.src(), "--no-login", FAKE_PY_OLD="1", PYTHON="/no/existe/python")
    assert r.returncode != 0 and "/no/existe/python" in r.stderr


def test_falla_pip_limpia_la_carpeta_a_medias(sb):
    r = sb.run(sb.src(), "--no-login", FAKE_PIP_FAIL="1")
    assert r.returncode != 0 and "dependencias" in r.stderr
    assert not (sb.app / "9.9.9").exists() and not (sb.app / "current").exists()
    assert not sb.unit.exists() and not sb.envfile.exists()


def test_sin_systemd_instala_los_ficheros_y_avisa(sb):
    src, r = install_ok(sb, "--no-login", FAKE_SYSTEMD="0")
    assert (sb.app / "current").is_symlink() and sb.envfile.is_file()
    assert sb.sysctl_calls() == []
    out = all_output(r)
    assert "systemd" in out and "app.cli serve" in out
    assert "CHECKPOINT_RUNTIME=native" in out


def test_reinstalar_sin_upgrade_se_niega(sb):
    install_ok(sb, "--no-login", "--no-start")
    r = sb.run(sb.src("9.9.9"), "--no-login")
    assert r.returncode != 0 and "--upgrade" in r.stderr


def test_prefijo_de_instalacion_configurable(sb):
    pre = sb.tmp / "otro prefijo"
    install_ok(sb, "--no-login", "--no-start", CHECKPOINT_INSTALL_PREFIX=pre)
    assert (pre / "9.9.9" / "backend" / "app").is_dir() and (pre / "current").is_symlink()
    assert not sb.app.exists()
    assert f'ExecStart="{pre}/current/venv/bin/python"' in sb.unit.read_text(
        encoding="utf-8"
    )  # espacios: entre comillas
    assert f"WorkingDirectory={pre}/current/backend" in sb.unit.read_text(encoding="utf-8")


def test_xdg_config_home_se_respeta(sb):
    x = sb.tmp / "xdg-cfg"
    install_ok(sb, "--no-login", "--no-start", XDG_CONFIG_HOME=x)
    assert (x / "checkpoint" / "checkpoint.env").is_file()
    assert (x / "systemd" / "user" / "checkpoint.service").is_file()


def test_rutas_con_porcentaje_y_dolar_se_escapan_en_la_unidad(sb):
    pre = sb.tmp / "p%d$HOME x"
    install_ok(sb, "--no-login", "--no-start", CHECKPOINT_INSTALL_PREFIX=pre)
    u = sb.unit.read_text(encoding="utf-8")
    assert f'ExecStart="{str(pre).replace("%", "%%").replace("$", "$$")}/current/venv/bin/python"' in u
    assert f"WorkingDirectory={str(pre).replace('%', '%%')}/current/backend" in u


def test_rutas_con_comillas_se_rechazan(sb):
    r = sb.run(sb.src(), "--no-login", CHECKPOINT_INSTALL_PREFIX=sb.tmp / 'a"b')
    assert r.returncode != 0 and "comillas" in r.stderr


def test_reinstalar_conserva_el_env_existente(sb):
    install_ok(sb, "--no-start", CHECKPOINT_USER="ana", CHECKPOINT_PASSWORD=PW)
    before = sb.envfile.read_bytes()
    # tras --uninstall el env queda: una instalación nueva lo reutiliza sin pedir credenciales
    assert sb.run(sb.app / "current", "--uninstall").returncode == 0
    r = sb.run(sb.src("9.9.9"), "--no-start")
    assert r.returncode == 0, all_output(r)
    assert sb.envfile.read_bytes() == before


# ---------------------------------------------------------------- arranque y linger


def test_avisa_de_enable_linger_si_esta_desactivado(sb):
    _, r = install_ok(sb, "--no-login", FAKE_LINGER="no")
    assert "loginctl enable-linger tester" in all_output(r)
    assert not any(c.startswith("loginctl enable-linger") for c in sb.calls())


def test_no_avisa_si_linger_ya_esta_activo(sb):
    _, r = install_ok(sb, "--no-login", FAKE_LINGER="yes")
    assert "enable-linger" not in all_output(r)


def test_enable_linger_solo_con_flag_explicito(sb):
    install_ok(sb, "--no-login", "--enable-linger", FAKE_LINGER="no")
    assert "loginctl enable-linger tester" in sb.calls()


def test_falla_el_arranque_restaura_la_unidad_nueva(sb):
    r = sb.run(sb.src(), "--no-login", FAKE_FAIL="enable")
    assert r.returncode != 0 and "journalctl --user -u checkpoint" in r.stderr
    assert not sb.unit.exists()


def test_espera_a_que_el_hub_responda_y_avisa_si_no(sb):
    r = sb.run(sb.src(), "--no-login", CHECKPOINT_INSTALL_WAIT="2")
    assert r.returncode == 0, all_output(r)
    assert "no respondió" in all_output(r) and "journalctl --user -u checkpoint" in all_output(r)


# ---------------------------------------------------------------- dry-run


def test_dry_run_no_toca_nada_y_describe_el_plan(sb):
    r = sb.run(sb.src(), "--dry-run", "--no-login")
    assert r.returncode == 0, all_output(r)
    assert tree(sb.home) == []
    assert sb.sysctl_calls() == []
    out = all_output(r)
    assert "dry-run" in out.lower() and "9.9.9" in out and "checkpoint.service" in out


def test_dry_run_con_credenciales_no_las_muestra(sb):
    r = sb.run(sb.src(), "--dry-run", CHECKPOINT_USER="ana", CHECKPOINT_PASSWORD=PW)
    assert r.returncode == 0 and PW not in all_output(r) and tree(sb.home) == []


def test_dry_run_valida_igual_que_la_instalacion(sb):
    r = sb.run(sb.src(), "--dry-run", CHECKPOINT_USER="ana", CHECKPOINT_PASSWORD="corta")
    assert r.returncode != 0


def test_dry_run_de_upgrade_y_uninstall_no_toca_nada(sb):
    install_ok(sb, "--no-login")
    snap = tree(sb.home)
    calls = len(sb.sysctl_calls())
    s2 = sb.src("10.0.0")
    assert sb.run(s2, "--upgrade", "--dry-run").returncode == 0
    assert sb.run(sb.app / "current", "--uninstall", "--purge", "--dry-run").returncode == 0
    assert tree(sb.home) == snap and len(sb.sysctl_calls()) == calls


# ---------------------------------------------------------------- upgrade


def test_upgrade_cambia_current_conserva_env_y_reinicia(sb):
    install_ok(sb, CHECKPOINT_USER="ana", CHECKPOINT_PASSWORD=PW)
    before = sb.envfile.read_bytes()
    s2 = sb.src("10.0.0")
    r = sb.run(s2, "--upgrade", CHECKPOINT_USER="otro", CHECKPOINT_PASSWORD=OTRA)
    assert r.returncode == 0, all_output(r)
    assert os.readlink(sb.app / "current") == "10.0.0"
    assert (sb.app / "9.9.9").is_dir() and (
        sb.app / "10.0.0" / "venv" / "bin" / "python"
    ).exists()  # vuelta atrás posible
    assert sb.envfile.read_bytes() == before
    assert "systemctl --user restart checkpoint" in sb.sysctl_calls()
    assert OTRA not in all_output(r)
    assert "conservo" in all_output(r).lower()


def test_upgrade_no_pide_credenciales_sin_terminal(sb):
    install_ok(sb, "--no-login")
    r = sb.run(sb.src("10.0.0"), "--upgrade")
    assert r.returncode == 0, all_output(r)


def test_upgrade_sin_instalacion_previa_instala(sb):
    r = sb.run(sb.src(), "--upgrade", "--no-login")
    assert r.returncode == 0, all_output(r)
    assert os.readlink(sb.app / "current") == "9.9.9"


def test_upgrade_mismo_numero_reutiliza_la_carpeta(sb):
    install_ok(sb, "--no-login")
    n = len([c for c in sb.calls() if "-m venv" in c])
    r = sb.run(sb.src("9.9.9", name="otra"), "--upgrade")
    assert r.returncode == 0, all_output(r)
    assert len([c for c in sb.calls() if "-m venv" in c]) == n


def test_upgrade_deja_solo_la_actual_y_la_anterior(sb):
    install_ok(sb, "--no-login")
    for v in ("10.0.0", "11.0.0"):
        assert sb.run(sb.src(v), "--upgrade").returncode == 0
    assert sorted(p.name for p in sb.app.iterdir()) == ["10.0.0", "11.0.0", "current"]


def test_upgrade_con_fallo_al_reiniciar_vuelve_a_la_version_anterior(sb):
    install_ok(sb, "--no-login")
    r = sb.run(sb.src("10.0.0"), "--upgrade", FAKE_FAIL="restart")
    assert r.returncode != 0
    assert os.readlink(sb.app / "current") == "9.9.9"
    assert "9.9.9" in r.stderr
    assert sb.sysctl_calls().count("systemctl --user restart checkpoint") == 2  # el intento y el de la vuelta atrás


def test_upgrade_con_no_start_no_reinicia(sb):
    install_ok(sb, "--no-login")
    r = sb.run(sb.src("10.0.0"), "--upgrade", "--no-start")
    assert r.returncode == 0
    assert "systemctl --user restart checkpoint" not in sb.sysctl_calls()
    assert "restart checkpoint" in all_output(r)


# ---------------------------------------------------------------- uninstall / purge


def seed_data(sb):
    (sb.data / "config").mkdir(parents=True)
    (sb.data / "config" / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    (sb.data / "keys").mkdir()
    (sb.data / "keys" / "id_ed25519").write_text("KEY", encoding="utf-8")


def test_uninstall_quita_codigo_y_unidad_pero_no_los_datos(sb):
    install_ok(sb, CHECKPOINT_USER="ana", CHECKPOINT_PASSWORD=PW)
    seed_data(sb)
    env = sb.envfile.read_bytes()
    r = sb.run(sb.app / "current", "--uninstall")
    assert r.returncode == 0, all_output(r)
    sc = sb.sysctl_calls()
    assert "systemctl --user disable --now checkpoint" in sc and sc[-1] == "systemctl --user daemon-reload"
    assert not sb.unit.exists() and not sb.app.exists()
    assert (sb.data / "keys" / "id_ed25519").read_text(encoding="utf-8") == "KEY"
    assert (sb.data / "config" / "config.yaml").is_file()
    assert sb.envfile.read_bytes() == env
    assert "--purge" in all_output(r) and PW not in all_output(r)


def test_uninstall_sin_instalacion_es_idempotente(sb):
    r = sb.run(sb.src(), "--uninstall")
    assert r.returncode == 0 and "no hay" in all_output(r).lower()


def test_uninstall_sin_systemd_igual_quita_el_codigo(sb):
    install_ok(sb, "--no-login", FAKE_SYSTEMD="0")
    r = sb.run(sb.app / "current", "--uninstall", FAKE_SYSTEMD="0")
    assert r.returncode == 0 and not sb.app.exists() and not sb.unit.exists()


def test_uninstall_no_borra_lo_ajeno_del_prefijo(sb):
    pre = sb.tmp / "prefijo"
    install_ok(sb, "--no-login", "--no-start", CHECKPOINT_INSTALL_PREFIX=pre)
    (pre / "mis-cosas").mkdir()
    (pre / "mis-cosas" / "f").write_text("x", encoding="utf-8")
    assert sb.run(pre / "current", "--uninstall", CHECKPOINT_INSTALL_PREFIX=pre).returncode == 0
    assert (pre / "mis-cosas" / "f").is_file()
    assert not (pre / "9.9.9").exists() and not (pre / "current").exists()


def test_purge_sin_terminal_se_niega_y_no_borra_nada(sb):
    install_ok(sb, "--no-login")
    seed_data(sb)
    r = sb.run(sb.app / "current", "--uninstall", "--purge")
    assert r.returncode != 0 and "terminal" in r.stderr
    assert (sb.data / "keys" / "id_ed25519").exists() and sb.app.exists() and sb.unit.exists()


def test_purge_sin_uninstall_es_un_error_de_uso(sb):
    r = sb.run(sb.src(), "--purge", "--no-login")
    assert r.returncode == 2


def run_tty(sb, src, args, answers, **extra):
    """Ejecuta el script con un pseudoterminal como stdin. `answers`: [(texto que espera ver, respuesta), ...]."""
    master, slave = pty.openpty()
    p = subprocess.Popen(
        [BASH, str(src / "install.sh"), *args],
        stdin=slave,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=sb.env(**extra),
        cwd=sb.tmp,
        close_fds=True,
    )
    os.close(slave)
    out, pos, pending, deadline = "", 0, list(answers), time.time() + 30
    fd = p.stdout.fileno()
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            out += chunk.decode("utf-8", "replace")
        if pending and pending[0][0] in out[pos:]:
            time.sleep(0.2)  # que bash desactive el eco (read -s) antes de teclear
            os.write(master, (pending.pop(0)[1] + "\n").encode())
            pos = len(out)
    p.wait(timeout=30)
    os.close(master)
    return p.returncode, out


def test_purge_con_confirmacion_borra_datos_y_credenciales(sb):
    install_ok(sb, "--no-login")
    seed_data(sb)
    rc, out = run_tty(sb, sb.app / "current", ["--uninstall", "--purge"], [("BORRAR", "BORRAR")])
    assert rc == 0, out
    assert not sb.data.exists() and not sb.conf.exists() and not sb.app.exists() and not sb.unit.exists()


def test_purge_con_otra_respuesta_cancela_sin_borrar_nada(sb):
    install_ok(sb, "--no-login")
    seed_data(sb)
    rc, out = run_tty(sb, sb.app / "current", ["--uninstall", "--purge"], [("BORRAR", "no")])
    assert rc != 0
    assert (sb.data / "keys" / "id_ed25519").exists() and sb.envfile.exists() and sb.app.exists()


# ---------------------------------------------------------------- credenciales interactivas


def test_pide_usuario_y_contrasena_con_terminal(sb):
    src = sb.src()
    rc, out = run_tty(sb, src, ["--no-start"], [("Usuario", "marta"), ("Contraseña", PW), ("Repite", PW)])
    assert rc == 0, out
    t = sb.envfile.read_text(encoding="utf-8")
    assert 'CHECKPOINT_USER="marta"\n' in t and f'CHECKPOINT_PASSWORD="{PW}"\n' in t
    assert PW not in out  # sin eco


def test_contrasenas_que_no_coinciden_se_vuelven_a_pedir(sb):
    src = sb.src()
    rc, out = run_tty(
        sb,
        src,
        ["--no-start"],
        [("Usuario", "marta"), ("Contraseña", PW), ("Repite", "otra-distinta-1"), ("Contraseña", PW), ("Repite", PW)],
    )
    assert rc == 0, out
    assert "no coinciden" in out
    assert f'CHECKPOINT_PASSWORD="{PW}"' in sb.envfile.read_text(encoding="utf-8")


def test_contrasena_corta_con_terminal_se_vuelve_a_pedir(sb):
    src = sb.src()
    rc, out = run_tty(
        sb, src, ["--no-start"], [("Usuario", "marta"), ("Contraseña", "corta"), ("Contraseña", PW), ("Repite", PW)]
    )
    assert rc == 0, out
    assert f'CHECKPOINT_PASSWORD="{PW}"' in sb.envfile.read_text(encoding="utf-8")


def test_contrasena_generada_se_muestra_una_vez(sb):
    src = sb.src()
    rc, out = run_tty(sb, src, ["--no-start"], [("Usuario", "marta"), ("Contraseña", "")])
    assert rc == 0, out
    assert out.count(GENERADA) == 1
    assert f'CHECKPOINT_PASSWORD="{GENERADA}"' in sb.envfile.read_text(encoding="utf-8")
    assert GENERADA not in sb.unit.read_text(encoding="utf-8")
