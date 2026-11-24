"""Manifiesto local (`checkpoint_core.manifest`) frente al hub real: mismas reglas que `sync/fingerprint.py`.

Las pruebas unitarias del manifiesto están en `checkpoint-core/tests/test_manifest.py`; aquí solo la equivalencia con
el hub, que necesita el backend del repositorio (se omite sin él)."""

import os
import sys
from pathlib import Path

import pytest

from checkpoint_core import manifest as lm

BACKEND = Path(__file__).resolve().parents[2] / "backend"


def put(root: Path, rel: str, data: bytes = b"x", mtime: int = 1_700_000_000):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    os.utime(p, (mtime, mtime))
    return p


# ---- equivalencia con el hub real
@pytest.fixture(scope="module")
def hub_fp():
    sys.path.insert(0, str(BACKEND))
    try:
        from app.sync import fingerprint as f
    except Exception as e:  # pragma: no cover
        pytest.skip(f"backend del hub no disponible: {e!r}")
    return f


def _fixtures(base: Path):
    d1 = base / "anidado"
    for rel in ["z/y/x/deep.sav", "z/a.sav", "a.sav", "z.sav", "z-1/q", "z/y.txt"]:
        put(d1, rel, rel.encode())
    d2 = base / "nombres"
    for rel in ["it's.sav", "a&b.sav", "c:d.sav", "con espacio/x y.dat", "tildes/ñandú ácido.sav", "ünï/çö", "a b/c", "a,b;c"]:
        put(d2, rel, rel.encode(), 1_650_000_000)
    d3 = base / "vacios"
    put(d3, "vacio.dat", b"")
    put(d3, "otro/vacio2", b"")
    put(d3, "con datos", b"1")
    d4 = base / "enlaces"
    put(d4, "real.sav", b"real")
    (d4 / "enlace.sav").symlink_to(d4 / "real.sav")
    (d4 / "dir_enlace").symlink_to(d3)
    os.mkfifo(d4 / "tuberia")
    (d4 / "vacia").mkdir()
    d5 = base / "orden"
    for rel in ["a.txt", "a/b", "a-b", "a b", "a+b/c", "A/B", "a/b.c", "a/c/d", "a0"]:
        put(d5, rel, rel.encode())
    d6 = base / "solo_vacias"
    (d6 / "x" / "y").mkdir(parents=True)
    d7 = base / "grande"
    put(d7, "big.bin", os.urandom(2_500_000))
    put(d7, "mtimes", b"m", 1_700_000_001)
    return [d1, d2, d3, d4, d5, d6, d7]


def test_equivalence_with_hub_fingerprint(tmp_path, hub_fp):
    for d in _fixtures(tmp_path):
        mine = hub_fp.fingerprint_from_manifest(lm.build_manifest(d))
        ref = hub_fp.fingerprint(d)
        assert mine == ref, d.name  # hash, mtime, ficheros y tamaño
        assert hub_fp.dir_manifest(d) == lm.build_manifest(d), d.name
