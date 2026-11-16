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


MANIFIESTO = {"v": 1, "src": "ludusavi-manifest@0b39b91", "games": [{"n": "A", "steam": 1, "lutris": None, "paths": [{"r": "home", "p": "x", "os": "linux"}]}]}


def manifiesto(deck, nombre="save_manifest.json", datos=None):
    """Un manifiesto SINTÉTICO fuera de la copia del plugin (el real pesa ~2 MB y no se commitea)."""
    import json

    f = deck.parent / nombre
    f.write_text(json.dumps(MANIFIESTO if datos is None else datos))
    return f


def empaquetar(deck, *args, con_manifiesto=True, env=None):
    import os

    e = {k: v for k, v in os.environ.items() if k != "SAVE_MANIFEST"}  # el entorno del que ejecuta no cuenta
    e.update(env or {})
    if con_manifiesto and "SAVE_MANIFEST" not in e and "--save-manifest" not in args:
        e["SAVE_MANIFEST"] = str(manifiesto(deck))
    return subprocess.run(["bash", "scripts/package.sh", *args], cwd=deck, capture_output=True, text=True, env=e)


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
    for esperado in ["dist/index.js", "data/save_manifest.json", "main.py", "plugin.json", "package.json", "LICENSE", "README.md"]:
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


def test_manifiesto_entra_al_zip_por_variable_o_por_opcion(copia):
    import json

    con_dist(copia)
    otro = manifiesto(copia, "otro.json", {**MANIFIESTO, "src": "ludusavi-manifest@abcdef1"})
    for args, env in (((), {"SAVE_MANIFEST": str(otro)}), (("--save-manifest", str(otro)), None), ((f"--save-manifest={otro}",), None)):
        r = empaquetar(copia, *args, env=env)
        assert r.returncode == 0, r.stderr
        with zipfile.ZipFile(copia / "out" / "Checkpoint.zip") as z:
            assert json.loads(z.read("Checkpoint/data/save_manifest.json"))["src"] == "ludusavi-manifest@abcdef1"


def test_manifiesto_ruta_relativa_cuenta_desde_donde_se_ejecuta(copia):
    con_dist(copia)
    manifiesto(copia, "rel.json")
    r = subprocess.run(["bash", str(copia / "scripts/package.sh"), "--save-manifest", "rel.json", "salida"], cwd=copia.parent, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "Checkpoint/data/save_manifest.json" in zipfile.ZipFile(copia / "salida" / "Checkpoint.zip").namelist()


def test_falla_sin_manifiesto_con_mensaje_claro(copia):
    con_dist(copia)
    r = empaquetar(copia, con_manifiesto=False)
    assert r.returncode != 0 and "--save-manifest" in r.stderr and "SAVE_MANIFEST" in r.stderr
    assert not (copia / "out" / "Checkpoint.zip").exists()


def test_falla_con_manifiesto_inexistente_o_invalido(copia):
    con_dist(copia)
    r = empaquetar(copia, "--save-manifest", str(copia.parent / "no-existe.json"))
    assert r.returncode != 0 and "No existe el manifiesto" in r.stderr
    for datos in ({"v": 2, "src": "ludusavi-manifest@0b39b91", "games": [{}]}, {**MANIFIESTO, "src": ""}, {**MANIFIESTO, "games": []}):
        r = empaquetar(copia, "--save-manifest", str(manifiesto(copia, "mal.json", datos)))
        assert r.returncode != 0 and "no es válido" in r.stderr, datos
    (copia.parent / "mal.json").write_text("no es json")
    r = empaquetar(copia, "--save-manifest", str(copia.parent / "mal.json"))
    assert r.returncode != 0 and "no es válido" in r.stderr


def test_el_manifiesto_del_zip_no_se_commitea(copia):
    ignorados = subprocess.run(["git", "check-ignore", "-q", "data/save_manifest.json"], cwd=ROOT, capture_output=True)
    assert ignorados.returncode == 0  # .gitignore: data/ (raíz del repo) cubre el manifiesto empaquetado


def test_sin_manifiesto_explicito_empaqueta_con_aviso(copia):
    con_dist(copia)
    for args, env in (((), {"SAVE_MANIFEST": "none"}), (("--no-save-manifest",), None)):
        r = empaquetar(copia, *args, env=env)
        assert r.returncode == 0 and "SIN el manifiesto" in r.stderr, r.stderr
        assert not any("data" in n for n in zipfile.ZipFile(copia / "out" / "Checkpoint.zip").namelist())
