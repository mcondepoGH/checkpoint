"""Paquete nativo de Linux (packaging/linux): estructura estática de los scripts y construcción real del tarball con un
frontend y un zip de Deck de mentira (sin red, sin Node). El smoke con pip y el hub real corre en CI (job `linux-package`)."""

import hashlib
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LINUX = ROOT / "packaging" / "linux"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash no disponible")


def _text(name):
    return (LINUX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["build.sh", "install.sh", "smoke.sh"])
def test_scripts_existen_ejecutables_y_estrictos(name):
    p = LINUX / name
    assert p.is_file() and os.access(p, os.X_OK)
    t = p.read_text(encoding="utf-8")
    assert t.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in t


@needs_bash
@pytest.mark.parametrize("name", ["build.sh", "install.sh", "smoke.sh"])
def test_sintaxis_bash(name):
    r = subprocess.run([BASH, "-n", str(LINUX / name)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr


def test_nombre_del_tarball_en_build_y_smoke():
    assert 'NAME="checkpoint-$VERSION"' in _text("build.sh") and "$NAME-linux.tar.gz" in _text("build.sh")
    assert "checkpoint-$VERSION-linux.tar.gz" in _text("smoke.sh")


def test_build_usa_el_mismo_manifiesto_que_el_dockerfile():
    assert "LUDUSAVI_MANIFEST_COMMIT" in _text("build.sh")
    assert "gen_save_manifest.py" in _text("build.sh")
    assert "pnpm@9" in _text("build.sh")


def test_smoke_instala_con_install_sh_sin_systemd_real_y_desinstala():
    s = _text("smoke.sh")
    assert "install.sh" in s and "--no-login" in s and "--no-start" in s and "--uninstall" in s
    assert "SYSTEMCTL=false" in s  # el runner puede no tener systemd de usuario
    assert "CHECKPOINT_RUNTIME=native" in s


def test_ci_construye_y_prueba_el_paquete():
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "linux-package:" in ci
    job = ci.split("linux-package:")[1].split("\n  client:")[0]
    assert "ubuntu-latest" in job
    assert "packaging/linux/build.sh" in job and "packaging/linux/smoke.sh" in job
    assert "github.event_name != 'push' || github.ref == 'refs/heads/main'" in job
    assert "release.yml" not in job


def _fake_inputs(tmp_path):
    fe = tmp_path / "fe"
    (fe / "assets").mkdir(parents=True)
    (fe / "index.html").write_text("<html>checkpoint</html>", encoding="utf-8")
    (fe / "assets" / "app.js").write_text("//js", encoding="utf-8")
    z = tmp_path / "Checkpoint.zip"
    z.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    return fe, z


def _build(tmp_path, *args):
    out = tmp_path / "out"
    r = subprocess.run(
        [BASH, str(LINUX / "build.sh"), "--out-dir", str(out), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    return r, out


@needs_bash
def test_build_arma_el_tarball_con_su_estructura(tmp_path):
    fe, z = _fake_inputs(tmp_path)
    r, out = _build(tmp_path, "--frontend-dir", str(fe), "--deck-zip", str(z))
    assert r.returncode == 0, r.stderr + r.stdout
    tgz = out / f"checkpoint-{VERSION}-linux.tar.gz"
    assert tgz.is_file()
    with tarfile.open(tgz) as t:
        names = t.getnames()
        modes = {m.name: m.mode for m in t.getmembers()}
    root = f"checkpoint-{VERSION}"
    for n in (
        f"{root}/VERSION",
        f"{root}/install.sh",
        f"{root}/backend/requirements.txt",
        f"{root}/backend/app/cli.py",
        f"{root}/backend/static/index.html",
        f"{root}/backend/static/assets/app.js",
        f"{root}/checkpoint-deck/out/Checkpoint.zip",
    ):
        assert n in names, n
    assert modes[f"{root}/install.sh"] & 0o111
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    assert not any("/tests" in n for n in names)
    assert all(n == root or n.startswith(root + "/") for n in names)


@needs_bash
def test_build_escribe_sha256_como_el_de_windows(tmp_path):
    fe, z = _fake_inputs(tmp_path)
    r, out = _build(tmp_path, "--frontend-dir", str(fe), "--deck-zip", str(z))
    assert r.returncode == 0, r.stderr
    name = f"checkpoint-{VERSION}-linux.tar.gz"
    digest = hashlib.sha256((out / name).read_bytes()).hexdigest()
    assert (out / f"{name}.sha256").read_bytes() == f"{digest}  {name}\n".encode()


@needs_bash
def test_build_sin_deck_no_incluye_el_zip(tmp_path):
    fe, _ = _fake_inputs(tmp_path)
    r, out = _build(tmp_path, "--frontend-dir", str(fe), "--no-deck")
    assert r.returncode == 0, r.stderr
    with tarfile.open(out / f"checkpoint-{VERSION}-linux.tar.gz") as t:
        assert not any(n.endswith("Checkpoint.zip") for n in t.getnames())


@needs_bash
def test_build_es_reproducible(tmp_path):
    fe, z = _fake_inputs(tmp_path)
    r1, o1 = _build(tmp_path, "--frontend-dir", str(fe), "--deck-zip", str(z))
    a = (o1 / f"checkpoint-{VERSION}-linux.tar.gz").read_bytes()
    shutil.rmtree(o1)
    r2, o2 = _build(tmp_path, "--frontend-dir", str(fe), "--deck-zip", str(z))
    assert r1.returncode == r2.returncode == 0
    assert a == (o2 / f"checkpoint-{VERSION}-linux.tar.gz").read_bytes()


@needs_bash
def test_build_rechaza_tag_distinto_de_version(tmp_path):
    fe, z = _fake_inputs(tmp_path)
    r, out = _build(tmp_path, "--frontend-dir", str(fe), "--deck-zip", str(z), "--tag", "v0.0.1")
    assert r.returncode != 0 and "no coincide" in r.stderr
    assert not out.exists() or not list(out.glob("*.tar.gz"))


@needs_bash
def test_build_acepta_tag_correcto(tmp_path):
    fe, z = _fake_inputs(tmp_path)
    r, _ = _build(tmp_path, "--frontend-dir", str(fe), "--deck-zip", str(z), "--tag", f"v{VERSION}")
    assert r.returncode == 0, r.stderr


@needs_bash
def test_build_falla_si_el_frontend_no_tiene_index(tmp_path):
    fe, z = _fake_inputs(tmp_path)
    (fe / "index.html").unlink()
    r, _ = _build(tmp_path, "--frontend-dir", str(fe), "--deck-zip", str(z))
    assert r.returncode != 0 and "index.html" in r.stderr


@needs_bash
def test_install_help(tmp_path):
    r = subprocess.run([BASH, str(LINUX / "install.sh"), "--help"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and "install.sh" in r.stdout


# --- release.yml: job `linux` (tarball y .sha256 en cada Release) ---

SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}( #.*)?$")


def _release_wf():
    import yaml

    return yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))


def _linux_job():
    jobs = _release_wf()["jobs"]
    assert "linux" in jobs
    return jobs["linux"]


def _run_steps(job):
    return "\n".join(s.get("run", "") for s in job["steps"])


def test_release_job_linux_depende_de_release_y_tiene_permisos_minimos():
    job = _linux_job()
    assert job["needs"] == "release"
    assert job["permissions"] == {"contents": "write"}
    assert "if" not in job  # también las pre-releases
    assert job["runs-on"] == "ubuntu-latest"
    assert isinstance(job.get("timeout-minutes"), int)


def test_release_job_linux_no_bloquea_a_los_demas():
    jobs = _release_wf()["jobs"]
    for name, job in jobs.items():
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        assert "linux" not in needs, name


def test_release_job_linux_actions_pinneadas_por_sha():
    for step in _linux_job()["steps"]:
        if "uses" in step:
            assert SHA_PIN.match(step["uses"]), step["uses"]


def test_release_job_linux_prepara_python_312_y_node_22():
    steps = _linux_job()["steps"]
    py = [s for s in steps if s.get("uses", "").startswith("actions/setup-python@")]
    node = [s for s in steps if s.get("uses", "").startswith("actions/setup-node@")]
    assert py and py[0]["with"]["python-version"] == "3.12"
    assert node and node[0]["with"]["node-version"] == "22"


def test_release_job_linux_construye_con_el_tag_y_hace_smoke_antes_de_subir():
    run = _run_steps(_linux_job())
    build = run.index('packaging/linux/build.sh --tag "$TAG"')
    smoke = run.index("packaging/linux/smoke.sh")
    upload = run.index("gh release upload")
    assert build < smoke < upload
    assert "--no-deck" not in run  # build completo, con el zip de Deck
    assert "dist/checkpoint-$VERSION-linux.tar.gz" in run


def test_release_job_linux_comprueba_version_contra_el_tag():
    run = _run_steps(_linux_job())
    assert "${TAG#v}" in run and "VERSION" in run and "::error::" in run


def test_release_job_linux_sube_tarball_y_sha256_con_clobber():
    run = _run_steps(_linux_job())
    m = re.search(r"gh release upload[^\n]*(\\\n[^\n]*)*", run)
    assert m
    cmd = m.group(0)
    assert "dist/checkpoint-$VERSION-linux.tar.gz" in cmd
    assert "dist/checkpoint-$VERSION-linux.tar.gz.sha256" in cmd
    assert "--clobber" in cmd
    for step in _linux_job()["steps"]:
        if "gh release upload" in step.get("run", ""):
            assert step["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"


def test_release_job_linux_nombre_del_asset_coincide_con_build_sh():
    assert "$NAME-linux.tar.gz" in _text("build.sh")
