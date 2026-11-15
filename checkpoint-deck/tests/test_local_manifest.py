"""Manifiesto local: describe la carpeta del juego con las mismas reglas que el hub (`sync/fingerprint.py`)."""

import hashlib
import os
import sys
from pathlib import Path

import pytest

import checkpoint_manifest as lm

BACKEND = Path(__file__).resolve().parents[2] / "backend"


def put(root: Path, rel: str, data: bytes = b"x", mtime: int = 1_700_000_000):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    os.utime(p, (mtime, mtime))
    return p


def test_entries_shape_and_values(tmp_path):
    put(tmp_path, "a/b.sav", b"hola", 1234)
    (m,) = lm.build_manifest(tmp_path)
    assert m == {"path": "a/b.sav", "sha256": hashlib.sha256(b"hola").hexdigest(), "size": 4, "mtime": 1234}


def test_empty_file_and_empty_dirs(tmp_path):
    put(tmp_path, "vacio", b"")
    (tmp_path / "carpeta_vacia").mkdir()
    (m,) = lm.build_manifest(tmp_path)
    assert m["path"] == "vacio" and m["size"] == 0 and m["sha256"] == hashlib.sha256(b"").hexdigest()


def test_symlinks_and_special_files_ignored(tmp_path):
    put(tmp_path, "real.sav")
    (tmp_path / "enlace.sav").symlink_to(tmp_path / "real.sav")
    (tmp_path / "dir").mkdir()
    put(tmp_path, "dir/x")
    (tmp_path / "enlace_dir").symlink_to(tmp_path / "dir")
    os.mkfifo(tmp_path / "fifo")
    assert [e["path"] for e in lm.build_manifest(tmp_path)] == ["dir/x", "real.sav"]


def test_order_by_path_components(tmp_path):
    # se ordena por componentes de ruta: ["a","b"] < ["a-b"] < ["a.txt"]
    for rel in ["a.txt", "a/b", "a-b", "B"]:
        put(tmp_path, rel)
    assert [e["path"] for e in lm.build_manifest(tmp_path)] == ["B", "a/b", "a-b", "a.txt"]


def test_hashes_in_1mib_blocks(tmp_path):
    data = os.urandom(3 * 1024 * 1024 + 17)
    put(tmp_path, "big", data)
    assert lm.build_manifest(tmp_path)[0]["sha256"] == hashlib.sha256(data).hexdigest()
    assert lm.BLOCK == 1 << 20


def test_file_too_large_fails_before_hashing(tmp_path, monkeypatch):
    put(tmp_path, "big", b"123456")
    with pytest.raises(lm.LocalManifestError) as e:
        lm.build_manifest(tmp_path, max_file_bytes=5)
    assert e.value.code == "file_too_large" and e.value.path == "big"


def test_too_many_files(tmp_path):
    for i in range(4):
        put(tmp_path, f"f{i}")
    with pytest.raises(lm.LocalManifestError) as e:
        lm.build_manifest(tmp_path, max_files=3)
    assert e.value.code == "too_many_files"


def test_backslash_name_rejected(tmp_path):
    put(tmp_path, "a\\b")
    with pytest.raises(lm.LocalManifestError) as e:
        lm.build_manifest(tmp_path)
    assert e.value.code == "bad_name"


def test_path_too_long_rejected(tmp_path):
    d = tmp_path
    for _ in range(6):
        d = d / ("d" * 200)
    put(d, "x")
    with pytest.raises(lm.LocalManifestError) as e:
        lm.build_manifest(tmp_path)
    assert e.value.code == "bad_name"


def test_missing_dir(tmp_path):
    with pytest.raises(lm.LocalManifestError) as e:
        lm.build_manifest(tmp_path / "no")
    assert e.value.code == "missing_dir"


def test_progress_callback(tmp_path):
    put(tmp_path, "a")
    put(tmp_path, "b")
    seen = []
    lm.build_manifest(tmp_path, progress=lambda done, total: seen.append((done, total)))
    assert seen[-1] == (2, 2)


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
