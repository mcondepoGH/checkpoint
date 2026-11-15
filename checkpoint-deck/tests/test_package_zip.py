"""El empaquetado (scripts/package.sh) sobre una copia: contenido del zip y errores claros. Se omite sin bash o python3."""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Mínimo fijo + todo checkpoint_*.py real de py_modules/: si se añade un módulo y no entra al zip, el test falla.
MODULES = sorted(
    {"hub", "steam", "client", "manifest", "sync", "jobs", "auto", "version", "update"}
    | {p.stem.removeprefix("checkpoint_") for p in (ROOT / "py_modules").glob("checkpoint_*.py")}
)

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("python3") is None, reason="faltan bash o python3"
)


@pytest.fixture
def copia(tmp_path):
    dst = tmp_path / "deck"
    shutil.copytree(
        ROOT, dst, ignore=shutil.ignore_patterns("node_modules", "dist", "out", "__pycache__", ".pytest_cache")
    )
    # Basura que NO debe entrar al zip
    (dst / "py_modules" / "__pycache__").mkdir()
    (dst / "py_modules" / "__pycache__" / "x.pyc").write_bytes(b"x")
    return dst


def empaquetar(deck):
    return subprocess.run(["bash", "scripts/package.sh"], cwd=deck, capture_output=True, text=True)


def con_dist(deck):
    (deck / "dist").mkdir()
    (deck / "dist" / "index.js").write_text("// bundle")
    (deck / "dist" / "index.js.map").write_text("{}")


def test_zip_contiene_lo_justo(copia):
    con_dist(copia)
    r = empaquetar(copia)
    assert r.returncode == 0, r.stderr
    names = zipfile.ZipFile(copia / "out" / "Checkpoint.zip").namelist()
    assert {n.split("/")[0] for n in names} == {"Checkpoint"}
    for esperado in ["dist/index.js", "main.py", "plugin.json", "package.json", "LICENSE", "README.md"]:
        assert f"Checkpoint/{esperado}" in names
    for m in MODULES:
        assert f"Checkpoint/py_modules/checkpoint_{m}.py" in names
    for n in names:
        assert not n.endswith(".map")
        assert not any(p in n for p in ("tests/", "node_modules/", "__pycache__", ".pytest_cache", "out/"))


def test_zip_declara_version_semver_y_protocolo(copia):
    """El package.json del zip lleva `version` semver y `checkpointProtocol` entero: lo que `/info` anuncia al plugin."""
    import json

    from checkpoint_version import parse_semver

    con_dist(copia)
    assert empaquetar(copia).returncode == 0
    with zipfile.ZipFile(copia / "out" / "Checkpoint.zip") as z:
        pkg = json.loads(z.read("Checkpoint/package.json"))
    assert parse_semver(pkg["version"]) is not None and pkg["checkpointProtocol"] == 1


def test_falla_sin_dist(copia):
    r = empaquetar(copia)
    assert r.returncode != 0 and "Falta dist/index.js" in r.stderr


def test_falla_sin_py_modules(copia):
    con_dist(copia)
    shutil.rmtree(copia / "py_modules")
    r = empaquetar(copia)
    assert r.returncode != 0 and "py_modules" in r.stderr
