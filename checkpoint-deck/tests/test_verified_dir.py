"""Comprobación única de las carpetas sugeridas (`verified_dir`): existe, es carpeta, se lee y pasa la validación de rutas.

Todo sintético en tmp_path."""

import os

import checkpoint_sync as cs
import pytest

needs_user = pytest.mark.skipif(os.geteuid() == 0, reason="root ignora los permisos de carpeta")


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home" / "deck"
    h.mkdir(parents=True)
    return h


def test_an_existing_readable_folder_inside_home_passes(home):
    d = home / "saves" / "juego"
    d.mkdir(parents=True)
    assert cs.verified_dir(str(d), home) == str(d)


def test_a_missing_folder_does_not_pass(home):
    assert cs.verified_dir(str(home / "no" / "existe"), home) is None


def test_a_file_does_not_pass(home):
    f = home / "saves"
    f.write_text("x")
    assert cs.verified_dir(str(f), home) is None


@needs_user
def test_an_unreadable_folder_does_not_pass(home):
    d = home / "saves"
    d.mkdir()
    d.chmod(0)
    try:
        assert cs.verified_dir(str(d), home) is None
    finally:
        d.chmod(0o755)


def test_unreadable_is_detected_without_relying_on_permissions(home, monkeypatch):
    d = home / "saves"
    d.mkdir()
    real_access = os.access
    monkeypatch.setattr(os, "access", lambda p, m, **k: False if str(p) == str(d) else real_access(p, m, **k))
    assert cs.verified_dir(str(d), home) is None


def test_scandir_failure_fails_closed(home, monkeypatch):
    d = home / "saves"
    d.mkdir()

    def boom(*_a, **_k):
        raise PermissionError("denegado")

    monkeypatch.setattr(os, "scandir", boom)
    assert cs.verified_dir(str(d), home) is None


def test_any_unexpected_exception_fails_closed(home, monkeypatch):
    d = home / "saves"
    d.mkdir()
    monkeypatch.setattr(cs, "validate_game_path", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("raro")))
    assert cs.verified_dir(str(d), home) is None


def test_a_symlink_pointing_outside_home_does_not_pass(home, tmp_path):
    outside = tmp_path / "fuera"
    outside.mkdir()
    (home / "enlace").symlink_to(outside)
    assert cs.verified_dir(str(home / "enlace"), home) is None
    assert cs.verified_dir(str(home / "enlace" / "x"), home) is None


def test_a_symlink_to_a_folder_inside_home_does_not_pass_either(home):
    (home / "real").mkdir()
    (home / "enlace").symlink_to(home / "real")
    assert cs.verified_dir(str(home / "enlace"), home) is None


def test_a_folder_outside_home_needs_an_allowed_root(home, tmp_path):
    card = tmp_path / "card" / "steamapps" / "compatdata" / "1"
    card.mkdir(parents=True)
    assert cs.verified_dir(str(card), home) is None
    assert cs.verified_dir(str(card), home, extra_roots=[tmp_path / "card"]) == str(card)


@pytest.mark.parametrize("bad", ["", "relativa", "/", "/etc", "/home", "x/../y", None, 5])
def test_non_normalized_or_forbidden_paths_do_not_pass(home, bad):
    assert cs.verified_dir(bad, home) is None


def test_a_non_normalized_path_does_not_pass(home):
    (home / "a").mkdir()
    assert cs.verified_dir(str(home) + "//a", home) is None
    assert cs.verified_dir(str(home) + "/a/", home) is None


def test_protected_folders_do_not_pass(home):
    prot = home / "homebrew"
    (prot / "settings").mkdir(parents=True)
    assert cs.verified_dir(str(prot / "settings"), home, [prot]) is None


def test_the_hub_filter_is_applied(home):
    d = home / "juego; raro"
    d.mkdir()
    assert cs.verified_dir(str(d), home, accept=lambda s: ";" not in s) is None
    assert cs.verified_dir(str(d), home, accept=lambda s: True) == str(d)
