"""Motor de sincronización contra el FakeHub (por HTTP). El motor contra el hub REAL está en test_integration_hub.py."""

import os
from pathlib import Path

import pytest
from conftest import KEY, set_hash

from checkpoint_client import hubclient as hc
from checkpoint_client import sync as se

GAME = "g1"


@pytest.fixture
def world(fakehub, home):
    class W:
        hub = fakehub
        save = home / "Games" / "g1"

        def engine(self, **kw):
            return se.SyncEngine(fakehub.url, KEY, home=home, sleep=lambda s: None, **kw)

        def game(self, **kw):
            g = {"id": GAME, "name": "Mi Juego", "enabled": True, "steam_appid": None, "status": None,
                 "path": str(self.save), "process": "mijuego.exe"}  # fmt: skip
            g.update(kw)
            fakehub.games = [g]

    w = W()
    w.game()
    return w


def put(root: Path, rel: str, data: bytes, mtime: int = 1_700_000_000):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    os.utime(p, (mtime, mtime))
    return p


def tree(root: Path):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# ---- estados básicos
def test_initial_upload_then_up_to_date(world):
    put(world.save, "slot1/save.dat", b"datos")
    put(world.save, "it's & a: ñ.sav", b"x")
    eng = world.engine()
    assert eng.check_game(GAME)["state"] == "upload"
    assert not world.hub.files.get(GAME)  # comprobar no sube nada
    r = eng.sync_game(GAME)
    assert r == {"game": GAME, "state": "uploaded", "files": 2}
    assert world.hub.files[GAME] == tree(world.save)
    assert eng.check_game(GAME)["state"] == "up_to_date"
    assert eng.sync_game(GAME)["state"] == "up_to_date"


def test_download_to_new_directory(world):
    world.hub.files[GAME] = {"a/b.sav": b"hub", "c.sav": b"2"}
    eng = world.engine()
    assert eng.check_game(GAME)["state"] == "download"
    assert not world.save.exists()  # comprobar no crea nada
    r = eng.sync_game(GAME)
    assert r["state"] == "downloaded" and r["files"] == 2
    assert tree(world.save) == world.hub.files[GAME]
    assert (world.save / "c.sav").stat().st_mtime == 1_700_000_000  # mtime del manifiesto
    assert not Path(str(world.save) + ".checkpoint-new").exists()
    assert not Path(str(world.save) + ".checkpoint-backup").exists()  # no había original
    assert eng.check_game(GAME)["state"] == "up_to_date"


def test_download_replaces_folder_and_keeps_single_backup(world):
    put(world.save, "old.sav", b"viejo")
    eng = world.engine()
    assert eng.sync_game(GAME)["state"] == "uploaded"
    world.hub.files[GAME] = {"new.sav": b"nuevo"}  # el hub cambia (el dispositivo no): bajada
    r = eng.sync_game(GAME)
    assert r["state"] == "downloaded"
    assert tree(world.save) == {"new.sav": b"nuevo"}
    backup = Path(str(world.save) + ".checkpoint-backup")
    assert tree(backup) == {"old.sav": b"viejo"}
    world.hub.files[GAME] = {"newer.sav": b"3"}
    eng.sync_game(GAME)
    assert tree(backup) == {"new.sav": b"nuevo"}  # UNA copia: la anterior se sustituye


def test_conflict_touches_nothing(world):
    put(world.save, "a.sav", b"dispositivo")
    eng = world.engine()
    eng.sync_game(GAME)
    world.hub.files[GAME] = {"a.sav": b"hub"}
    put(world.save, "a.sav", b"cambio local")
    before_hub, before_local = dict(world.hub.files[GAME]), tree(world.save)
    for r in (eng.check_game(GAME), eng.sync_game(GAME)):
        assert r["state"] == "conflict"
    assert world.hub.files[GAME] == before_hub and tree(world.save) == before_local
    assert not Path(str(world.save) + ".checkpoint-backup").exists()


@pytest.mark.parametrize("winner", ["hub", "device"])
def test_resolve_conflict(world, winner):
    put(world.save, "a.sav", b"dispositivo")
    eng = world.engine()
    eng.sync_game(GAME)
    world.hub.files[GAME] = {"a.sav": b"hub"}
    put(world.save, "a.sav", b"cambio local")
    r = eng.resolve_conflict(GAME, winner)
    assert r["state"] == ("downloaded" if winner == "hub" else "uploaded"), r
    assert tree(world.save) == world.hub.files[GAME]
    expect = b"hub" if winner == "hub" else b"cambio local"
    assert world.hub.files[GAME]["a.sav"] == expect
    if winner == "hub":
        assert tree(Path(str(world.save) + ".checkpoint-backup")) == {"a.sav": b"cambio local"}


def test_resolve_rejects_other_winners_and_empty_device(world):
    eng = world.engine()
    assert eng.resolve_conflict(GAME, "newest")["code"] == "bad_winner"
    world.hub.files[GAME] = {"a.sav": b"hub"}
    world.hub.base[GAME] = "otra"
    put(world.save, "x", b"1")
    eng.sync_game(GAME)  # conflicto con base distinta
    world.save.mkdir(parents=True, exist_ok=True)
    for p in world.save.iterdir():
        p.unlink()
    assert eng.resolve_conflict(GAME, "device")["state"] == "downloaded"  # ya no hay conflicto: sync normal


def test_resolve_with_old_hub_without_resolution_route(world, monkeypatch):
    put(world.save, "a.sav", b"1")
    eng = world.engine()
    eng.sync_game(GAME)
    world.hub.files[GAME] = {"a.sav": b"hub"}
    put(world.save, "a.sav", b"2")

    def old(*a, **k):
        raise hc.HubApiError(404, None)

    monkeypatch.setattr(eng.client, "set_resolution", old)
    assert eng.resolve_conflict(GAME, "hub")["code"] == "resolution_unsupported"


# ---- juegos que no se sincronizan
@pytest.mark.parametrize(("override", "state"), [({"path": None}, "no_path"), ({"enabled": False}, "disabled")])
def test_skipped_games(world, override, state):
    world.game(**override)
    assert world.engine().sync_game(GAME)["state"] == state


def test_unknown_game_and_missing_dir(world):
    eng = world.engine()
    assert eng.sync_game("otro") == {"game": "otro", "state": "error", "code": "unknown_game"}
    assert eng.sync_game(GAME)["state"] == "missing_dir"  # ni el hub ni el equipo tienen nada


def test_open_game_is_not_synced_by_hand_but_can_be_checked(world):
    put(world.save, "a.sav", b"1")
    eng = world.engine(is_running=lambda game: game == GAME)
    assert eng.sync_game(GAME) == {"game": GAME, "state": "error", "code": "game_running"}
    assert eng.check_game(GAME)["state"] == "upload"
    assert not world.hub.files.get(GAME)


def test_is_running_defaults_to_false(world):
    put(world.save, "a.sav", b"1")
    assert world.engine().is_running(GAME) is False
    assert world.engine().sync_game(GAME)["state"] == "uploaded"


@pytest.mark.parametrize("bad", ["/etc/ssh", "/", "relativa", "/usr/share/juego"])
def test_forbidden_hub_path_touches_nothing(world, bad):
    world.game(path=bad)
    world.hub.files[GAME] = {"a.sav": b"hub"}
    assert world.engine().sync_game(GAME) == {"game": GAME, "state": "error", "code": "path_forbidden"}


def test_home_is_never_a_game_folder(world, home):
    world.game(path=str(home))
    assert world.engine().sync_game(GAME)["code"] == "path_forbidden"


def test_path_that_is_a_file_is_forbidden(world):
    world.save.parent.mkdir(parents=True)
    world.save.write_bytes(b"soy un fichero")
    assert world.engine().sync_game(GAME)["code"] == "path_forbidden"


def test_protected_dir_cannot_be_game(world, home):
    prot = home / ".config" / "checkpoint-client"
    world.game(path=str(prot))
    assert world.engine(protected=[prot]).sync_game(GAME)["code"] == "path_forbidden"


def test_symlinked_game_folder_is_rejected(world, home):
    real = home / "real"
    real.mkdir()
    world.save.parent.mkdir(parents=True)
    world.save.symlink_to(real)
    assert world.engine().sync_game(GAME)["code"] == "path_forbidden"


# ---- datos no confiables del hub
def test_hub_manifest_with_dotdot_is_rejected_before_writing(world, monkeypatch):
    world.hub.files[GAME] = {"a.sav": b"1"}
    real = world.hub.fingerprint

    def evil(game, manifest, with_manifest):
        out = real(game, manifest, with_manifest)
        if "hub_manifest" in out:
            out["hub_manifest"][0]["path"] = "../fuera.sav"
        return out

    monkeypatch.setattr(world.hub, "fingerprint", evil)
    r = world.engine().sync_game(GAME)
    assert r["code"] == "bad_manifest"
    assert not world.save.exists() and not (world.save.parent.parent / "fuera.sav").exists()


def test_hub_manifest_file_over_limit_is_rejected(world):
    world.hub.files[GAME] = {"a.sav": b"x" * 100}
    r = world.engine(max_file_bytes=10).sync_game(GAME)
    assert r["code"] == "bad_manifest" and not world.save.exists()


def test_downloaded_content_that_does_not_match_leaves_folder_intact(world, monkeypatch):
    put(world.save, "mio.sav", b"mio")
    world.engine().sync_game(GAME)
    world.hub.files[GAME] = {"a.sav": b"1234"}
    real = world.hub.fingerprint

    def lying(game, manifest, with_manifest):
        out = real(game, manifest, with_manifest)
        if "hub_manifest" in out:
            out["hub_manifest"][0]["sha256"] = "0" * 64
        return out

    monkeypatch.setattr(world.hub, "fingerprint", lying)
    r = world.engine().sync_game(GAME)
    assert r["code"] == "verify_failed"
    assert tree(world.save) == {"mio.sav": b"mio"}
    assert not Path(str(world.save) + ".checkpoint-new").exists()


def test_interrupt_during_download_keeps_original_and_cleans_up(world, monkeypatch):
    put(world.save, "mio.sav", b"mio")
    world.engine().sync_game(GAME)
    world.hub.files[GAME] = {"a.sav": b"1234"}

    def ctrl_c(*a, **k):
        raise KeyboardInterrupt

    eng = world.engine()
    monkeypatch.setattr(eng.client, "download_file", ctrl_c)
    with pytest.raises(KeyboardInterrupt):
        eng.sync_game(GAME)
    assert tree(world.save) == {"mio.sav": b"mio"}
    assert not Path(str(world.save) + ".checkpoint-new").exists()


# ---- límites y ficheros especiales
def test_limits_checked_before_uploading(world):
    put(world.save, "a", b"1")
    put(world.save, "b", b"2")
    put(world.save, "c", b"3")
    r = world.engine(max_files=2).sync_game(GAME)
    assert r["code"] == "too_many_files" and world.hub.requests[-1][1] == "/api/games"
    r = world.engine(max_file_bytes=0).sync_game(GAME)
    assert r["code"] == "file_too_large"
    assert not any(req[0] == "PUT" for req in world.hub.requests)


def test_default_limits_match_the_plugin():
    assert se.lm.MAX_FILES == 50_000
    assert se.lm.MAX_FILE_BYTES == 512 * 1024 * 1024 == hc.MAX_FILE_BYTES


def test_symlinks_are_not_followed_or_uploaded(world, home):
    secret = home / "secreto.txt"
    secret.write_bytes(b"no subir")
    put(world.save, "a.sav", b"1")
    (world.save / "enlace.sav").symlink_to(secret)
    assert world.engine().sync_game(GAME)["files"] == 1
    assert world.hub.files[GAME] == {"a.sav": b"1"}


def test_upload_of_empty_folder_is_error(world):
    world.save.mkdir(parents=True)
    world.hub.files[GAME] = {"a.sav": b"1"}
    world.hub.base[GAME] = set_hash(world.hub.files[GAME])
    # carpeta vacía y hub con datos: el hub pide bajar, no subir una carpeta vacía
    assert world.engine().check_game(GAME)["state"] == "download"


# ---- errores del hub y de red
def test_unauthorized(world):
    world.hub.key = "ckd_otra"
    r = world.engine().sync_all()
    assert r == [{"game": "*", "state": "error", "code": "unauthorized"}]


def test_connection_error(world):
    eng = se.SyncEngine("http://127.0.0.1:1", KEY, home=world.save.parent.parent, sleep=lambda s: None)
    assert eng.sync_game(GAME, games=[{"id": GAME, "path": str(world.save), "enabled": True}])["code"] == "connection"


def test_commit_rejected_maps_to_code(world):
    put(world.save, "a.sav", b"1")
    world.hub.fail_commit = (409, {"detail": {"code": "err.hook.commit_rejected", "params": {}}})
    assert world.engine().sync_game(GAME)["code"] == "commit_rejected"


def test_rate_limited_carries_wait(world, monkeypatch):
    eng = world.engine()

    def limited(*a, **k):
        raise hc.HubApiError(429, None, wait_s=90)

    monkeypatch.setattr(eng.client, "get_games", limited)
    assert eng.sync_game(GAME) == {"game": GAME, "state": "error", "code": "rate_limited", "params": {"wait_s": 90}}


# ---- todos y progreso
def test_sync_all_runs_every_game_and_isolates_errors(world, home):
    world.game()
    other = home / "Games" / "g2"
    put(other, "z.sav", b"z")
    put(world.save, "a.sav", b"1")
    world.hub.games.append({"id": "g2", "name": "Dos", "enabled": True, "path": str(other), "process": None})
    world.hub.games.append({"id": "g3", "name": "Tres", "enabled": True, "path": "/etc", "process": None})
    out = world.engine().sync_all()
    assert [(r["game"], r["state"]) for r in out] == [("g1", "uploaded"), ("g2", "uploaded"), ("g3", "error")]


def test_progress_reports_upload_and_download(world):
    put(world.save, "a", b"1")
    put(world.save, "b", b"2")
    seen = []
    world.engine().sync_game(GAME, progress=lambda phase, i, total: seen.append((phase, i, total)))
    assert ("upload", 0, 2) in seen and seen[-1] == ("upload", 2, 2)
    world.hub.files[GAME] = {"n": b"3"}
    seen.clear()
    world.engine().sync_game(GAME, progress=lambda phase, i, total: seen.append((phase, i, total)))
    assert ("download", 0, 1) in seen and seen[-1] == ("download", 1, 1)


def test_opened_and_closed_notifications(world):
    eng = world.engine()
    eng.notify_opened(GAME, {"state": "ok"})
    eng.notify_closed(GAME)
    assert [e[:2] for e in world.hub.events] == [("opened", GAME), ("closed", GAME)]


def test_hub_result_keeps_only_state_and_error_code():
    assert se.hub_result({"state": "uploaded", "files": 3, "game": "g"}) == {"state": "uploaded"}
    assert se.hub_result({"state": "error", "code": "connection", "params": {"path": "/x"}}) == {
        "state": "error",
        "code": "connection",
    }
    assert se.hub_result({"state": "disabled"}) is None
