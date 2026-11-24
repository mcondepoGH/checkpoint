"""Exclusión mutua entre procesos del cliente: un fichero de lock por vigilante y por juego en el directorio de config."""

import os
import stat

import pytest

from checkpoint_client import locks


def test_second_holder_of_the_same_name_is_refused(tmp_path):
    with locks.exclusive(str(tmp_path), "watch"):
        with pytest.raises(locks.Busy):
            with locks.exclusive(str(tmp_path), "watch"):
                pass


def test_lock_is_released_on_exit_and_after_an_error(tmp_path):
    with locks.exclusive(str(tmp_path), "watch"):
        pass
    with pytest.raises(RuntimeError):
        with locks.exclusive(str(tmp_path), "watch"):
            raise RuntimeError("boom")
    with locks.exclusive(str(tmp_path), "watch"):  # otra vez libre
        pass


def test_different_names_do_not_collide(tmp_path):
    with locks.exclusive(str(tmp_path), "watch"):
        with locks.exclusive(str(tmp_path), locks.game_name("g1")):
            with locks.exclusive(str(tmp_path), locks.game_name("g2")):
                pass


def test_is_locked_probes_without_keeping_the_lock(tmp_path):
    name = locks.game_name("g1")
    assert locks.is_locked(str(tmp_path), name) is False
    with locks.exclusive(str(tmp_path), name):
        assert locks.is_locked(str(tmp_path), name) is True
    assert locks.is_locked(str(tmp_path), name) is False


def test_game_name_is_a_safe_file_name_per_game(tmp_path):
    hostile = "../../etc/passwd"
    name = locks.game_name(hostile)
    assert "/" not in name and ".." not in name
    assert locks.game_name(hostile) == name and locks.game_name("g1") != locks.game_name("g2")
    with locks.exclusive(str(tmp_path / "cfg"), name):
        assert os.listdir(tmp_path / "cfg") == [name + ".lock"]


def test_lock_directory_and_file_are_private(tmp_path):
    d = tmp_path / "cfg"
    with locks.exclusive(str(d), "watch"):
        assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(d / "watch.lock").st_mode) == 0o600
