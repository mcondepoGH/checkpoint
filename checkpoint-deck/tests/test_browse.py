"""Ruta inicial del selector nativo de Decky (`picker_start`). El backend de Decky (`filepicker_ls`) lanza si la ruta no existe,
no es carpeta o no se puede leer, y su frontend revienta con `TypeError: theError.match is not a function`: aquí se comprueba
la ruta antes y se degrada a una segura (ruta -> home -> `/`). Nunca lanza."""

import asyncio
import os

import checkpoint_browse as cb
from test_main_library import make_plugin


def test_usable_path_is_kept_without_trailing_slash(tmp_path):
    home = tmp_path / "home"
    (home / "saves").mkdir(parents=True)
    assert cb.usable_start(str(home / "saves"), home) == str(home / "saves")
    assert cb.usable_start(str(home / "saves") + "/", home) == str(home / "saves")
    assert cb.usable_start(f"  {home / 'saves'}  ", home) == str(home / "saves")


def test_missing_file_relative_or_odd_values_degrade_to_home(tmp_path):
    home = tmp_path / "home"
    (home / "saves").mkdir(parents=True)
    (home / "f.txt").write_text("x")
    for raw in (str(home / "nada"), str(home / "f.txt"), "relativa/ruta", "", "   ", None, 5, "/x\0y", str(home / ".." / "home")):
        assert cb.usable_start(raw, home) == str(home), repr(raw)


def test_unreadable_directory_degrades_to_home(tmp_path):
    home = tmp_path / "home"
    (home / "cerrada").mkdir(parents=True)
    os.chmod(home / "cerrada", 0)
    try:
        if os.geteuid() != 0:
            assert cb.usable_start(str(home / "cerrada"), home) == str(home)
    finally:
        os.chmod(home / "cerrada", 0o755)


def test_system_folders_of_the_nas_degrade_to_home(tmp_path):
    home = tmp_path / "home"
    for d in ("@Recycle", ".@qnap", "@Recently-Snapshot/x"):
        (home / d).mkdir(parents=True)
        assert cb.usable_start(str(home / d), home) == str(home), d


def test_unusable_home_degrades_to_root(tmp_path):
    assert cb.usable_start("", tmp_path / "no_existe") == "/"
    assert cb.usable_start("/definitivamente/no/existe", tmp_path / "no_existe") == "/"


def test_plugin_picker_start_validates_and_never_raises(fake_decky, tmp_path, monkeypatch):
    p = make_plugin(fake_decky, "http://127.0.0.1:1", tmp_path, monkeypatch)
    home = tmp_path / "deckhome"
    (home / "saves").mkdir(parents=True, exist_ok=True)
    assert asyncio.run(p.picker_start(str(home / "saves"))) == {"ok": True, "path": str(home / "saves")}
    assert asyncio.run(p.picker_start("/no/existe/seguro")) == {"ok": True, "path": str(home)}
    assert asyncio.run(p.picker_start(None)) == {"ok": True, "path": str(home)}


def test_old_own_browser_is_gone(fake_decky, tmp_path, monkeypatch):
    assert not hasattr(cb, "list_dirs")
    p = make_plugin(fake_decky, "http://127.0.0.1:1", tmp_path, monkeypatch)
    assert not hasattr(p, "list_dirs")
