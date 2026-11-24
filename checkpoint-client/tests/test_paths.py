"""Validación de rutas Linux: la ruta y el manifiesto que da el hub son DATOS NO CONFIABLES."""

from pathlib import Path

import pytest

from checkpoint_client import paths


@pytest.fixture
def h(home):
    return home


@pytest.mark.parametrize(
    "raw",
    [
        None, "", 5, "relativa/ruta", "~/saves", "/home/u/../etc", "/a\0b",  # no válidas
        "/", "/home", "/etc", "/etc/ssh", "/usr/share/x", "/boot", "/dev/shm", "/proc/1", "/sys/x", "/bin", "/lib64/x",
        "/tmp", "/var", "/opt", "/run", "/mnt", "/media", "/srv", "/root",
    ],
)  # fmt: skip
def test_forbidden_or_malformed_paths(h, raw):
    with pytest.raises(paths.PathNotAllowed):
        paths.validate_game_path(raw, h)


def test_home_and_its_parents_are_forbidden(h):
    for p in (h, h.parent, "/home/otrousuario"):
        with pytest.raises(paths.PathNotAllowed):
            paths.validate_game_path(str(p), h)


@pytest.mark.parametrize("sub", [".config", ".local", ".local/share", ".cache", ".var", ".var/app", ".steam"])
def test_home_system_folders_cannot_be_a_game_folder(h, sub):
    with pytest.raises(paths.PathNotAllowed):
        paths.validate_game_path(str(h / sub), h)


def test_folders_inside_home_system_dirs_are_allowed(h):
    # Los guardados reales viven ahí: Proton, Flatpak, XDG...
    for sub in (".local/share/Celeste/Saves", ".config/unity3d/Studio/Game", ".steam/steam/steamapps/compatdata/1/pfx"):
        assert paths.validate_game_path(str(h / sub), h) == h / sub


def test_normal_game_folder_is_ok_even_if_missing(h):
    assert paths.validate_game_path(str(h / "Games" / "saves"), h) == h / "Games" / "saves"
    assert paths.validate_game_path(str(h / "Games/./saves//x"), h) == h / "Games" / "saves" / "x"


def test_mnt_children_are_ok_but_not_system_trees(tmp_path, h):
    assert paths.validate_game_path("/mnt/disco/saves", h) == Path("/mnt/disco/saves")
    assert paths.validate_game_path("/media/u/USB/saves", h) == Path("/media/u/USB/saves")


def test_symlinked_game_folder_rejected(h, tmp_path):
    real = h / "real"
    real.mkdir()
    (h / "enlace").symlink_to(real)
    with pytest.raises(paths.PathNotAllowed):
        paths.validate_game_path(str(h / "enlace"), h)


def test_symlinked_parent_into_forbidden_tree_rejected(h):
    (h / "jugo").symlink_to("/etc")
    with pytest.raises(paths.PathNotAllowed):
        paths.validate_game_path(str(h / "jugo" / "ssh"), h)


def test_protected_dirs_cannot_be_or_contain_a_game(h):
    cfg = h / ".config" / "checkpoint-client"
    cfg.mkdir(parents=True)
    for p in (cfg, cfg / "sub", h / ".config"):
        with pytest.raises(paths.PathNotAllowed):
            paths.validate_game_path(str(p), h, protected=[cfg])


# ---- rutas relativas del manifiesto
@pytest.mark.parametrize("rel", ["a.sav", "a/b/c.sav", "con espacio/ñ.dat", "a\\b.sav"])
def test_validate_rel_ok(rel):
    assert paths.validate_rel(rel) == rel.replace("\\", "/")


@pytest.mark.parametrize(
    "rel", ["", None, "/abs", "../x", "a/../b", "a//b", "./a", "a/./b", "a\0b", "x" * 1025, "a/" + "y" * 256]
)
def test_validate_rel_rejects(rel):
    with pytest.raises(paths.BadManifest):
        paths.validate_rel(rel)


def _e(path, size=1, sha="a" * 64, mtime=1):
    return {"path": path, "sha256": sha, "size": size, "mtime": mtime}


def test_parse_hub_manifest_normalizes():
    out = paths.parse_hub_manifest([_e("a.sav", sha="A" * 64, mtime=2.7)], 10, 100)
    assert out == [{"path": "a.sav", "sha256": "a" * 64, "size": 1, "mtime": 2}]


@pytest.mark.parametrize(
    "raw",
    [
        None, [], "x", [5], [_e("a", sha="zz")], [_e("a", size=-1)], [_e("a", size=101)], [_e("a", size=True)],
        [_e("a", mtime=-1)], [_e("a"), _e("a")], [_e("a"), _e("a/b")], [_e("../a")],
    ],
)  # fmt: skip
def test_parse_hub_manifest_rejects(raw):
    with pytest.raises(paths.BadManifest):
        paths.parse_hub_manifest(raw, 10, 100)


def test_parse_hub_manifest_limits_file_count():
    with pytest.raises(paths.BadManifest):
        paths.parse_hub_manifest([_e(f"f{i}") for i in range(3)], 2, 100)
