"""Estado que recuerda el plugin para el panel: sellos de sincronización, sugerencias ignoradas, versión vista,
sugerencias de carpeta distinta para juegos ya añadidos y medición de la carpeta configurada."""

import json
import os
import stat

import pytest

import checkpoint_uistate as ui


def test_stamps_record_only_good_results_and_persist(tmp_path):
    s = ui.Stamps(str(tmp_path), now=lambda: 1000.9)
    s.record("g1", {"state": "uploaded", "files": 4})
    s.record("g2", {"state": "conflict"})
    s.record("g3", {"state": "error", "code": "connection"})
    s.record("g4", {"state": "up_to_date"})
    assert s.get("g1") == {"at": 1000, "state": "uploaded", "files": 4}
    assert s.get("g2") is None and s.get("g3") is None
    assert s.get("g4") == {"at": 1000, "state": "up_to_date"}
    assert s.latest() == 1000
    again = ui.Stamps(str(tmp_path))  # persistió en disco
    assert again.get("g1")["files"] == 4
    f = tmp_path / ui.STAMPS_FILE
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_stamps_ignore_corrupt_file_and_junk_entries(tmp_path):
    (tmp_path / ui.STAMPS_FILE).write_text(json.dumps({"a": {"at": 5, "state": "uploaded"}, "b": {"at": "x", "state": "uploaded"}, "c": 3, "d": {"at": True, "state": "uploaded"}}))
    s = ui.Stamps(str(tmp_path))
    assert s.get("a") == {"at": 5, "state": "uploaded"}
    assert s.get("b") is None and s.get("c") is None and s.get("d") is None
    (tmp_path / ui.STAMPS_FILE).write_text("no json")
    assert ui.Stamps(str(tmp_path)).latest() is None


def test_stamps_cap_drops_oldest(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "MAX_ENTRIES", 3)
    t = iter(range(1, 100))
    s = ui.Stamps(str(tmp_path), now=lambda: next(t))
    for g in "abcd":
        s.record(g, {"state": "uploaded"})
    assert s.get("a") is None and s.get("d") is not None


def test_ignored_remembers_one_path_per_game(tmp_path):
    i = ui.Ignored(str(tmp_path))
    assert i.add("g1", "/home/deck/a") is True
    assert i.has("g1", "/home/deck/a") and not i.has("g1", "/home/deck/b")
    assert ui.Ignored(str(tmp_path)).as_dict() == {"g1": "/home/deck/a"}
    i.add("g1", "/home/deck/b")  # una ruta nueva sustituye la anterior
    assert i.has("g1", "/home/deck/b") and not i.has("g1", "/home/deck/a")


@pytest.mark.parametrize("game,path", [("", "/x"), (None, "/x"), ("g", "relativa"), ("g", 5), ("g", None)])
def test_ignored_rejects_bad_args(tmp_path, game, path):
    assert ui.Ignored(str(tmp_path)).add(game, path) is False


def test_ack_version_reports_previous_only_after_the_first_time(tmp_path):
    d = str(tmp_path)
    assert ui.ack_version(d, "1.2.1") == {"current": "1.2.1", "previous": None}
    assert ui.ack_version(d, "1.2.1") == {"current": "1.2.1", "previous": "1.2.1"}
    assert ui.ack_version(d, "1.3.0") == {"current": "1.3.0", "previous": "1.2.1"}
    assert ui.ack_version(d, "1.3.0")["previous"] == "1.3.0"  # ya visto: sin aviso
    assert ui.ack_version(d, None) == {"current": None, "previous": "1.3.0"}


def P(path, **o):
    return {"path": path, "exists": True, "mtime": 100, "size": 10, "files": 2, **o}


def S(appid, paths, conf="high", source="steam"):
    return {"source": source, "id": appid, "name": "J", "confidence": conf, "paths": paths}


def row(gid="g1", appid=10, path="/h/old"):
    return {"id": gid, "name": "Juego", "appid": appid, "path": path}


def test_changed_suggestions_only_for_a_different_safe_existing_folder():
    out = ui.changed_suggestions([row()], [S(10, [P("/h/new")])])
    assert out == [{"game": "g1", "name": "Juego", "path": "/h/new", "size": 10, "files": 2, "mtime": 100}]
    assert ui.changed_suggestions([row(path="/h/new")], [S(10, [P("/h/new")])]) == []  # ya es la configurada
    assert ui.changed_suggestions([row(path="/h/new/")], [S(10, [P("/h/new")])]) == []  # barra final
    assert ui.changed_suggestions([row()], [S(10, [P("/h/new", exists=False)])]) == []  # no existe
    assert ui.changed_suggestions([row()], [S(10, [P("/h/new", doubtful=True)])]) == []  # dudosa
    assert ui.changed_suggestions([row()], [S(10, [P("/h/new")], conf="doubtful")]) == []
    assert ui.changed_suggestions([row()], [S(10, [P("/h/new")], source="lutris")]) == []
    assert ui.changed_suggestions([row(appid=None)], [S(10, [P("/h/new")])]) == []
    assert ui.changed_suggestions([row(path=None)], [S(10, [P("/h/new")])]) == []


def test_changed_suggestions_picks_best_and_honours_ignored(tmp_path):
    paths = [P("/h/dudosa", doubtful=True, mtime=900), P("/h/vieja", mtime=1), P("/h/nueva", mtime=50)]
    out = ui.changed_suggestions([row()], [S(10, paths)])
    assert out[0]["path"] == "/h/nueva"  # no dudosa y la más reciente
    ign = ui.Ignored(str(tmp_path))
    ign.add("g1", "/h/nueva")
    assert ui.changed_suggestions([row()], [S(10, paths)], ign) == []
    ign.add("g1", "/h/otra")  # otra ruta distinta: vuelve a avisar
    assert len(ui.changed_suggestions([row()], [S(10, paths)], ign)) == 1


def test_folder_info_measures_only_folders_under_allowed_roots(tmp_path):
    home = tmp_path / "home"
    d = home / "saves"
    d.mkdir(parents=True)
    (d / "a.sav").write_bytes(b"x" * 100)
    info = ui.folder_info(str(d), home)
    assert info["exists"] is True and info["size"] == 100 and info["files"] == 1
    assert ui.folder_info(str(home / "nada"), home) == {"exists": False}
    assert ui.folder_info("/etc", home) == {"exists": False}  # fuera de lo permitido
    assert ui.folder_info(str(d) + "/../..", home) == {"exists": False}  # `..`
    assert ui.folder_info("relativa", home) == {"exists": False}
    assert ui.folder_info(None, home) == {"exists": False}
    (home / "enlace").symlink_to("/etc")
    assert ui.folder_info(str(home / "enlace"), home) == {"exists": False}  # el enlace resuelve fuera
    assert os.path.isdir("/etc")
