"""Motor de sincronización contra el HUB REAL (uvicorn en un hilo): vinculación por solicitud/aceptación, un juego con
`steam_appid` y la ruta del dispositivo http hacia un directorio temporal. Más pruebas puras de la seguridad de rutas."""

import hashlib
import os
import threading
from pathlib import Path

import httpx
import pytest

from test_integration_hub import PW, real_hub  # noqa: F401  (fixture del hub real; omite el módulo si no hay hub)

from app.services import hookfiles  # noqa: E402  (el backend ya está en sys.path por test_integration_hub)

import checkpoint_client as hc
import checkpoint_sync as se
from checkpoint_hub import HubNetworkError

pytestmark = pytest.mark.integration
GAME = "g1"


def put(root: Path, rel: str, data: bytes, mtime: int = 1_700_000_000):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    os.utime(p, (mtime, mtime))
    return p


def tree(root: Path):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class World:
    def __init__(self, hub_url, tmp_path):
        self.url, self.tmp = hub_url, tmp_path
        self.home = tmp_path / "home"
        self.save = self.home / "saves" / "g1"
        self.save.parent.mkdir(parents=True)
        self.hubdir = tmp_path / "data" / "hub" / GAME
        admin = self.admin = httpx.Client(base_url=hub_url)
        assert admin.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
        r = httpx.post(hub_url + "/api/pairing/requests", json={"name": "Steam Deck", "os": "linux"})
        b = r.json()
        acc = admin.post(
            f"/api/pairing/pending/{b['id']}/accept", json={"code": b["code"]}, headers={"Origin": hub_url}
        )
        assert acc.status_code == 200, acc.text
        self.device = acc.json()["device"]
        got = httpx.get(f"{hub_url}/api/pairing/requests/{b['id']}", headers={"X-Pairing-Secret": b["secret"]}).json()
        self.key = got["key"]
        self.set_game(path=str(self.save))

    def set_game(self, path=None, enabled=True, appid=730):
        snap = self.admin.get("/api/config").json()
        cfg = snap["config"]
        g = {"name": "Mi Juego", "devices": [self.device], "enabled": enabled, "steam_appid": appid}
        if path is not None:
            g["paths"] = {self.device: path}
        cfg.setdefault("games", {})[GAME] = g
        r = self.admin.put("/api/config", json={"base_version": snap["version"], "config": cfg})
        assert r.status_code == 200, r.text

    def engine(self, **kw):
        kw.setdefault("home", self.home)
        kw.setdefault("sleep", lambda s: None)
        return se.SyncEngine(self.url, self.key, **kw)

    def hub_files(self, files: dict, mtime=1_700_000_100):
        import shutil

        if self.hubdir.exists():
            shutil.rmtree(self.hubdir)
        for rel, data in files.items():
            put(self.hubdir, rel, data, mtime)


@pytest.fixture
def world(real_hub, tmp_path):  # noqa: F811
    return World(real_hub, tmp_path)


def hub_tree(w):
    return tree(w.hubdir)


# ---- estados básicos
def test_initial_upload_to_empty_hub(world):
    put(world.save, "slot1/save.dat", b"datos")
    put(world.save, "it's & a: ñ.sav", b"x")
    eng = world.engine()
    assert eng.check_game(GAME)["state"] == "upload"
    r = eng.sync_game(GAME)
    assert r["state"] == "uploaded", r
    assert hub_tree(world) == tree(world.save)
    assert eng.check_game(GAME)["state"] == "up_to_date"  # el commit dejó la línea base


def test_download_to_new_directory(world):
    world.hub_files({"a/b.sav": b"hub", "c.sav": b"2"})
    assert not world.save.exists()
    eng = world.engine()
    assert eng.check_game(GAME)["state"] == "download"
    r = eng.sync_game(GAME)
    assert r["state"] == "downloaded", r
    assert tree(world.save) == hub_tree(world)
    assert not Path(str(world.save) + ".checkpoint-new").exists()
    assert not Path(str(world.save) + ".checkpoint-backup").exists()  # no había original
    assert eng.check_game(GAME)["state"] == "up_to_date"


def test_download_to_existing_dir_keeps_one_backup(world):
    put(world.save, "s.sav", b"v1")
    eng = world.engine()
    assert eng.sync_game(GAME)["state"] == "uploaded"
    world.hub_files({"s.sav": b"v2-del-hub", "nuevo.sav": b"n"})
    assert eng.check_game(GAME)["state"] == "download"
    assert eng.sync_game(GAME)["state"] == "downloaded"
    assert tree(world.save) == {"s.sav": b"v2-del-hub", "nuevo.sav": b"n"}
    backup = Path(str(world.save) + ".checkpoint-backup")
    assert tree(backup) == {"s.sav": b"v1"}
    # segunda descarga: la copia anterior se sustituye por el original de ahora
    world.hub_files({"s.sav": b"v3"})
    assert eng.sync_game(GAME)["state"] == "downloaded"
    assert tree(backup) == {"s.sav": b"v2-del-hub", "nuevo.sav": b"n"}
    assert tree(world.save) == {"s.sav": b"v3"}


def test_none_after_sync_and_nothing_touched(world):
    put(world.save, "s.sav", b"1")
    eng = world.engine()
    eng.sync_game(GAME)
    before = hub_tree(world)
    r = eng.sync_game(GAME)
    assert r["state"] == "up_to_date" and hub_tree(world) == before


def test_local_change_uploads(world):
    put(world.save, "s.sav", b"1")
    eng = world.engine()
    eng.sync_game(GAME)
    put(world.save, "s.sav", b"2 cambiado")
    assert eng.check_game(GAME)["state"] == "upload"
    assert eng.sync_game(GAME)["state"] == "uploaded"
    assert hub_tree(world) == {"s.sav": b"2 cambiado"}


def test_hub_change_downloads(world):
    put(world.save, "s.sav", b"1")
    eng = world.engine()
    eng.sync_game(GAME)
    world.hub_files({"s.sav": b"del hub"})
    assert eng.sync_game(GAME)["state"] == "downloaded"
    assert tree(world.save) == {"s.sav": b"del hub"}


def test_both_changed_is_conflict_and_touches_nothing(world):
    put(world.save, "s.sav", b"1")
    eng = world.engine()
    eng.sync_game(GAME)
    put(world.save, "s.sav", b"local")
    world.hub_files({"s.sav": b"hub"})
    local_before, hub_before = tree(world.save), hub_tree(world)
    assert eng.check_game(GAME)["state"] == "conflict"
    r = eng.sync_game(GAME)
    assert r["state"] == "conflict"
    assert tree(world.save) == local_before and hub_tree(world) == hub_before
    assert not Path(str(world.save) + ".checkpoint-backup").exists()
    assert not Path(str(world.save) + ".checkpoint-new").exists()


def test_check_game_does_not_ask_for_hub_manifest(world):
    world.hub_files({"s.sav": b"x"})
    eng = world.engine()
    seen = []
    orig = eng.client.fingerprint
    eng.client.fingerprint = lambda g, m, with_manifest=False: (seen.append(with_manifest), orig(g, m, with_manifest))[1]
    assert eng.check_game(GAME)["state"] == "download"
    assert seen == [False]


def test_no_path_disabled_unknown_and_missing_dir(world):
    eng = world.engine()
    real_games = eng.client.get_games
    eng.client.get_games = lambda: [{**g, "path": None} for g in real_games()]  # el hub exige ruta; se simula
    assert eng.check_game(GAME)["state"] == "no_path"
    assert eng.sync_game(GAME)["state"] == "no_path"
    eng.client.get_games = real_games
    world.set_game(path=str(world.save), enabled=False)
    assert eng.check_game(GAME)["state"] == "disabled"
    assert eng.sync_game(GAME)["state"] == "disabled"
    world.set_game(path=str(world.save))
    assert eng.check_game(GAME)["state"] == "missing_dir"  # hub vacío y carpeta inexistente: no hay nada que subir
    assert eng.sync_game(GAME)["state"] == "missing_dir"
    assert not world.save.exists()
    assert eng.check_game("nope")["state"] == "error"


def test_upload_never_creates_missing_dir_even_with_hub_data(world):
    put(world.save, "s.sav", b"1")
    eng = world.engine()
    eng.sync_game(GAME)
    import shutil

    shutil.rmtree(world.save)
    # el hub ya tiene los datos: con la carpeta borrada se rellena desde el hub (descarga), no se sube nada vacío
    assert eng.check_game(GAME)["state"] == "download"


def test_sync_all(world):
    put(world.save, "s.sav", b"1")
    res = world.engine().sync_all()
    assert [(r["game"], r["state"]) for r in res] == [(GAME, "uploaded")]


# ---- fallos y red
def test_interrupted_upload_is_resumed(world, monkeypatch):
    data = os.urandom(300_000)
    put(world.save, "big.bin", data)
    real_read = hc._Slice.read
    state = {"cut": True, "puts": []}

    def flaky(self, n=-1):
        if state["cut"] and self.sent >= 100_000:
            state["cut"] = False
            raise ConnectionResetError("corte simulado")
        return real_read(self, n)

    monkeypatch.setattr(hc._Slice, "read", flaky)
    orig = hc.HubClient._stream

    def spy(self, method, path, headers, data=None):
        if method == "PUT":
            state["puts"].append(path)
        return orig(self, method, path, headers, data)

    monkeypatch.setattr(hc.HubClient, "_stream", spy)

    # El cliente reintenta al instante (sleep falso), pero el hub tarda en darse cuenta del corte: hasta que su manejador
    # del primer PUT termina, la parte sigue reservada (`part_lock`) y el reintento recibe 409 `upload_busy`. En vez del
    # backoff real, el sleep espera a que el hub acabe de atender ese primer PUT (señal del propio hub, sin tiempos).
    first_put_done = threading.Event()
    real_receive = hookfiles.receive_file

    async def receive_spy(*a, **kw):
        try:
            return await real_receive(*a, **kw)
        finally:
            first_put_done.set()

    monkeypatch.setattr(hookfiles, "receive_file", receive_spy)

    def wait_hub_releases_part(_s):
        assert first_put_done.wait(10), "el hub no terminó de atender el PUT cortado"

    r = world.engine(sleep=wait_hub_releases_part).sync_game(GAME)
    assert r["state"] == "uploaded", r
    assert hub_tree(world) == {"big.bin": data}
    assert len(state["puts"]) >= 2 and "offset=0" in state["puts"][0] and "offset=0" not in state["puts"][-1]


def test_hub_changed_between_fingerprint_and_commit(world):
    put(world.save, "s.sav", b"1")
    eng = world.engine()
    orig = eng.client.fingerprint

    def fp(game, manifest, with_manifest=False):
        out = orig(game, manifest, with_manifest)
        world.hub_files({"otro.sav": b"alguien subio esto"})  # el hub cambia a mitad
        return out

    eng.client.fingerprint = fp
    r = eng.sync_game(GAME)
    assert r["state"] == "error" and r["code"] == "hub_changed"
    assert hub_tree(world) == {"otro.sav": b"alguien subio esto"}  # no se pisó
    assert tree(world.save) == {"s.sav": b"1"}


def test_unauthorized_key(world):
    eng = se.SyncEngine(world.url, "ckd_mala", home=world.home, sleep=lambda s: None)
    r = eng.check_game(GAME)
    assert r["state"] == "error" and r["code"] == "unauthorized"


def test_connection_error():
    eng = se.SyncEngine("http://127.0.0.1:1", "ckd_x", home=Path("/tmp"), sleep=lambda s: None)
    assert eng.check_game(GAME) == {"game": GAME, "state": "error", "code": "connection"}


def test_too_many_files_and_big_files_refused(world):
    put(world.save, "a", b"1")
    put(world.save, "b", b"2")
    eng = world.engine(max_files=1)
    assert eng.sync_game(GAME)["code"] == "too_many_files"
    eng = world.engine(max_file_bytes=1)
    put(world.save, "b", b"22")
    r = eng.sync_game(GAME)
    assert r["state"] == "error" and r["code"] == "file_too_large" and r["params"] == {"path": "b"}
    assert hub_tree(world) == {}  # no se subió nada


def test_empty_local_dir_never_uploaded(world):
    world.save.mkdir()
    r = world.engine().sync_game(GAME)
    assert r["state"] in ("missing_dir", "up_to_date") and hub_tree(world) == {}


def test_concurrent_same_game_second_is_busy(world):
    put(world.save, "s.sav", b"1")
    eng = world.engine()
    gate, started = threading.Event(), threading.Event()
    orig = eng.client.fingerprint

    def slow(*a, **k):
        started.set()
        gate.wait(5)
        return orig(*a, **k)

    eng.client.fingerprint = slow
    first = []
    t = threading.Thread(target=lambda: first.append(eng.sync_game(GAME)))
    t.start()
    assert started.wait(5)
    second = eng.sync_game(GAME)
    gate.set()
    t.join(10)
    assert second["state"] == "error" and second["code"] == "busy"
    assert first[0]["state"] == "uploaded"


# ---- seguridad de la ruta que da el hub
HOME = Path("/home/deck")
PROTECTED = [Path("/home/deck/homebrew/plugins/Checkpoint"), Path("/home/deck/homebrew/settings/Checkpoint")]


@pytest.mark.parametrize(
    "raw",
    [
        "/",
        "/home",
        "/home/deck",
        "/home/deck/",
        "/home/deck/saves/..",
        "/home/deck/../other",
        "/home/other",
        "/run",
        "/usr",
        "/usr/share/x",
        "/etc",
        "/etc/cron.d",
        "/var",
        "/tmp",
        "relativa/ruta",
        "",
        "saves",
        "/home/deck/x\0y",
        "/home/deck/homebrew",
        "/home/deck/homebrew/plugins/Checkpoint",
        "/home/deck/homebrew/plugins/Checkpoint/py_modules",
        "/home/deck/homebrew/settings/Checkpoint",
        "/home/deck/.local",
        "/home/deck/.local/share",
        "/home/deck/.config",
        "/home/deck/.steam",
        None,
        7,
    ],
)
def test_dangerous_paths_rejected(raw):
    with pytest.raises(se.PathNotAllowed):
        se.validate_game_path(raw, HOME, PROTECTED)


@pytest.mark.parametrize(
    "raw",
    [
        "/home/deck/.local/share/Steam/steamapps/compatdata/123/pfx/drive_c/users/steamuser/Documents/Juego",
        "/home/deck/.config/Juego/saves",
        "/home/deck/Documents/Juego",
        "/run/media/mmcblk0p1/steamapps/compatdata/5/x",
        "/home/deck/ñandú ácido's & co: 1/save",
    ],
)
def test_legit_paths_accepted(raw):
    assert str(se.validate_game_path(raw, HOME, PROTECTED)) == raw


def test_steam_root_and_steamapps_protected(tmp_path):
    root = tmp_path / "h" / ".local/share/Steam"
    (root / "steamapps").mkdir(parents=True)
    for bad in (root, root / "steamapps"):
        with pytest.raises(se.PathNotAllowed):
            se.validate_game_path(str(bad), tmp_path / "h", [])
    assert se.validate_game_path(str(root / "steamapps/compatdata/5/pfx"), tmp_path / "h", [])


def test_symlinked_leaf_and_symlinked_ancestor_to_forbidden(tmp_path):
    home = tmp_path / "home"
    (home / "saves").mkdir(parents=True)
    (home / "link_to_home").symlink_to(home)
    (home / "saves" / "leaf").symlink_to(home / "saves")
    with pytest.raises(se.PathNotAllowed):  # un enlace que lleva al directorio personal
        se.validate_game_path(str(home / "link_to_home"), home, [])
    with pytest.raises(se.PathNotAllowed):  # el directorio raíz del juego no puede ser un enlace
        se.validate_game_path(str(home / "saves" / "leaf"), home, [])


def test_engine_rejects_dangerous_hub_path_with_message(world):
    eng = world.engine()
    real_games = eng.client.get_games
    for bad in ("/", str(world.home), "/home", "/etc/x/../../etc", "relativa"):
        # el hub valida la config, pero el plugin no se fía: se le inyecta la ruta peligrosa
        eng.client.get_games = lambda bad=bad: [{**g, "path": bad} for g in real_games()]
        r = eng.sync_game(GAME)
        assert r["state"] == "error" and r["code"] == "path_forbidden", bad
        assert eng.check_game(GAME)["code"] == "path_forbidden"


def test_symlink_root_dir_is_rejected_by_engine(world):
    real = world.home / "real"
    real.mkdir()
    put(real, "s.sav", b"1")
    link = world.home / "saves" / "link"
    link.symlink_to(real)
    world.set_game(path=str(link))
    assert world.engine().sync_game(GAME)["code"] == "path_forbidden"
    assert hub_tree(world) == {}


# ---- manifiesto malicioso del hub
def _evil_engine(world, hub_manifest):
    eng = world.engine()
    eng.client.fingerprint = lambda g, m, with_manifest=False: {
        "action": "download",
        "hub": {"hash": "x"},
        "hub_manifest": hub_manifest,
    }
    return eng


def entry(rel, data=b"x"):
    return {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "mtime": 1}


@pytest.mark.parametrize(
    "rel", ["../x", "a/../../x", "/etc/passwd", "a\\..\\..\\x", "a/\0/b", "", ".", "a/", "//x", "..", "C:/../x"]
)
def test_malicious_hub_manifest_path_rejected_without_writing(world, rel):
    put(world.save, "s.sav", b"orig")
    eng = _evil_engine(world, [entry("ok.sav"), entry(rel)])
    before = set(os.listdir(world.home / "saves")), set(os.listdir(world.home))
    calls = []
    eng.client.download_file = lambda *a, **k: calls.append(a)
    r = eng.sync_game(GAME)
    assert r["state"] == "error" and r["code"] == "bad_manifest"
    assert calls == []  # ni se pidió ningún fichero
    assert (set(os.listdir(world.home / "saves")), set(os.listdir(world.home))) == before
    assert tree(world.save) == {"s.sav": b"orig"}


def test_malicious_manifest_duplicates_and_bad_fields(world):
    for bad in (
        [entry("a"), entry("a")],
        [{"path": "a", "sha256": "zz", "size": 1, "mtime": 1}],
        [{"path": "a", "sha256": "0" * 64, "size": -1, "mtime": 1}],
        [{"path": "a", "sha256": "0" * 64, "size": hc.MAX_FILE_BYTES + 1, "mtime": 1}],
        [],
        ["no es dict"],
    ):
        r = _evil_engine(world, bad).sync_game(GAME)
        assert r["state"] == "error" and r["code"] in ("bad_manifest", "hub_empty"), bad


def test_symlink_inside_destination_is_not_followed(world):
    """El temporal es nuevo: un enlace que ya hubiera (de un intento anterior) se elimina, no se sigue."""
    victim = world.home / "victima.txt"
    victim.write_text("intacto")
    tmp = Path(str(world.save) + ".checkpoint-new")
    tmp.mkdir(parents=True)
    (tmp / "s.sav").symlink_to(victim)
    data = b"nuevo"
    eng = _evil_engine(world, [entry("s.sav", data)])
    eng.client.download_file = lambda g, rel, dest, offset=0: Path(dest).write_bytes(data) or len(data)
    eng.client.fingerprint = lambda g, m, with_manifest=False: (
        {"action": "download", "hub": {"hash": "x"}, "hub_manifest": [entry("s.sav", data)]}
        if with_manifest
        else {"action": "none"}
    )
    r = eng.sync_game(GAME)
    assert r["state"] == "downloaded", r
    assert victim.read_text() == "intacto" and (world.save / "s.sav").read_bytes() == data


def test_corrupt_sha_with_empty_original_cleans_temp(world):
    world.save.mkdir()  # carpeta existente y vacía (un lado vacío nunca gana: el hub baja)
    world.hub_files({"s.sav": b"hub1", "b.sav": b"hub2"})
    eng = world.engine()
    assert eng.check_game(GAME)["state"] == "download"
    orig_dl = eng.client.download_file

    def corrupt(g, rel, dest, offset=0):
        n = orig_dl(g, rel, dest, offset)
        with open(dest, "ab") as f:
            f.write(b"X")  # sha y tamaño ya no cuadran
        return n

    eng.client.download_file = corrupt
    r = eng.sync_game(GAME)
    assert r["state"] == "error" and r["code"] == "verify_failed"
    assert world.save.is_dir() and tree(world.save) == {}
    assert not Path(str(world.save) + ".checkpoint-new").exists()
    assert not Path(str(world.save) + ".checkpoint-backup").exists()


def test_corrupt_download_with_existing_original_and_backup_untouched(world):
    put(world.save, "s.sav", b"v1")
    eng = world.engine()
    eng.sync_game(GAME)
    backup = Path(str(world.save) + ".checkpoint-backup")
    backup.mkdir()
    put(backup, "viejo", b"copia anterior")
    world.hub_files({"s.sav": b"v2"})
    orig_dl = eng.client.download_file

    def corrupt(g, rel, dest, offset=0):
        n = orig_dl(g, rel, dest, offset)
        Path(dest).write_bytes(b"otra cosa")
        return n

    eng.client.download_file = corrupt
    r = eng.sync_game(GAME)
    assert r["state"] == "error" and r["code"] == "verify_failed"
    assert tree(world.save) == {"s.sav": b"v1"}  # original intacto
    assert tree(backup) == {"viejo": b"copia anterior"}  # la copia previa también
    assert not Path(str(world.save) + ".checkpoint-new").exists()


def test_inconsistent_after_download_warns_without_looping(world):
    world.hub_files({"s.sav": b"hub"})
    eng = world.engine()
    orig = eng.client.fingerprint
    calls = []

    def fp(g, m, with_manifest=False):
        calls.append(with_manifest)
        out = orig(g, m, with_manifest)
        if len(calls) >= 2:
            return {**out, "action": "upload"}
        return out

    eng.client.fingerprint = fp
    r = eng.sync_game(GAME)
    assert r["state"] == "error" and r["code"] == "inconsistent"
    assert len(calls) == 2
    assert tree(world.save) == {"s.sav": b"hub"}  # la descarga ya se hizo


def test_download_failure_midway_cleans_temp_and_keeps_original(world):
    put(world.save, "s.sav", b"v1")
    eng = world.engine()
    eng.sync_game(GAME)
    world.hub_files({"a": b"1", "b": b"2", "c": b"3"})
    n = []
    orig_dl = eng.client.download_file

    def flaky(g, rel, dest, offset=0):
        n.append(rel)
        if len(n) == 2:
            raise HubNetworkError("ConnectionResetError")
        return orig_dl(g, rel, dest, offset)

    eng.client.download_file = flaky
    r = eng.sync_game(GAME)
    assert r["state"] == "error" and r["code"] == "connection"
    assert tree(world.save) == {"s.sav": b"v1"}
    assert not Path(str(world.save) + ".checkpoint-new").exists()


def test_cancel_stops_before_replacing(world):
    put(world.save, "s.sav", b"v1")
    eng = world.engine()
    eng.sync_game(GAME)
    world.hub_files({"a": b"1", "b": b"2"})
    orig_dl = eng.client.download_file

    def dl(g, rel, dest, offset=0):
        eng.cancel()
        return orig_dl(g, rel, dest, offset)

    eng.client.download_file = dl
    r = eng.sync_game(GAME)
    assert r["state"] == "error" and r["code"] == "cancelled"
    assert tree(world.save) == {"s.sav": b"v1"} and not Path(str(world.save) + ".checkpoint-new").exists()


def test_progress_reports_files(world):
    for i in range(3):
        put(world.save, f"f{i}", b"x%d" % i)
    seen = []
    world.engine().sync_game(GAME, progress=lambda phase, done, total: seen.append((phase, done, total)))
    assert ("upload", 3, 3) in seen


# ---- juego abierto: la sincronización manual no toca nada
def test_running_game_blocks_apply_but_not_check(world):
    put(world.save, "slot1/save.dat", b"datos")
    eng = world.engine(is_running=lambda appid: appid == 730)
    assert eng.sync_game(GAME) == {"game": GAME, "state": "error", "code": "game_running"}
    assert eng.sync_all() == [{"game": GAME, "state": "error", "code": "game_running"}]
    assert eng.check_game(GAME)["state"] == "upload"  # solo mirar no es peligroso
    assert hub_tree(world) == {}  # no se subió nada


def test_other_running_game_does_not_block(world):
    put(world.save, "slot1/save.dat", b"datos")
    eng = world.engine(is_running=lambda appid: appid == 1)
    assert eng.sync_game(GAME)["state"] == "uploaded"


# ---- resolver un conflicto de datos (el hub deja una resolución pendiente y el motor la aplica al momento)
def make_conflict(world):
    put(world.save, "s.sav", b"1")
    eng = world.engine()
    assert eng.sync_game(GAME)["state"] == "uploaded"
    put(world.save, "s.sav", b"local")
    world.hub_files({"s.sav": b"hub"})
    assert eng.check_game(GAME)["state"] == "conflict"
    return eng


def pending(world):
    return world.admin.get("/api/watches").json()


def test_resolve_conflict_hub_downloads_and_keeps_a_local_backup(world):
    eng = make_conflict(world)
    r = eng.resolve_conflict(GAME, "hub")
    assert r["state"] == "downloaded", r
    assert tree(world.save) == {"s.sav": b"hub"} and hub_tree(world) == {"s.sav": b"hub"}
    assert tree(Path(str(world.save) + ".checkpoint-backup")) == {"s.sav": b"local"}  # lo local, a salvo
    assert eng.check_game(GAME)["state"] == "up_to_date"
    p = pending(world)
    assert p["conflicts"] == [] and p["resolutions"] == []


def test_resolve_conflict_device_uploads_and_hub_keeps_previous_version(world):
    eng = make_conflict(world)
    r = eng.resolve_conflict(GAME, "device")
    assert r["state"] == "uploaded", r
    assert hub_tree(world) == {"s.sav": b"local"} and tree(world.save) == {"s.sav": b"local"}
    (v,) = list((world.tmp / "data" / "versions" / GAME).iterdir())
    assert (v / "hub" / "s.sav").read_bytes() == b"hub"  # la versión previa del hub
    assert eng.check_game(GAME)["state"] == "up_to_date"
    assert pending(world)["conflicts"] == [] and pending(world)["resolutions"] == []


def test_resolve_conflict_that_is_no_longer_a_conflict_just_syncs(world):
    put(world.save, "s.sav", b"1")
    eng = world.engine()
    eng.sync_game(GAME)
    put(world.save, "s.sav", b"solo local")  # el hub no cambió: sube, sin conflicto
    assert eng.resolve_conflict(GAME, "hub")["state"] == "uploaded"
    assert hub_tree(world) == {"s.sav": b"solo local"}


def test_resolve_conflict_stale_when_the_hub_changes_in_between(world):
    eng = make_conflict(world)
    real = eng.client.set_resolution

    def racing(game, winner, expect):
        out = real(game, winner, expect)
        world.hub_files({"s.sav": b"el hub cambio otra vez"})  # alguien toca el hub tras registrar la resolución
        return out

    eng.client.set_resolution = racing
    r = eng.resolve_conflict(GAME, "hub")
    assert r["state"] == "conflict" and r["code"] == "resolution_stale", r
    assert tree(world.save) == {"s.sav": b"local"}  # nada tocado
    assert not Path(str(world.save) + ".checkpoint-backup").exists()
    assert pending(world)["resolutions"] == []  # la obsoleta se descartó


def test_resolve_conflict_refused_while_the_game_runs_and_registers_nothing(world):
    eng = make_conflict(world)
    eng.is_running = lambda appid: True
    r = eng.resolve_conflict(GAME, "hub")
    assert r["state"] == "error" and r["code"] == "game_running"
    assert pending(world)["resolutions"] == [] and tree(world.save) == {"s.sav": b"local"}


def test_resolve_conflict_bad_winner_and_missing_path(world):
    eng = make_conflict(world)
    for w in ("newest", "device:x", "", None, 3):
        assert eng.resolve_conflict(GAME, w) == {"game": GAME, "state": "error", "code": "bad_winner"}
    assert pending(world)["resolutions"] == []


def test_resolve_conflict_device_with_empty_folder_is_refused(world):
    eng = make_conflict(world)
    for p in world.save.iterdir():
        p.unlink()  # carpeta vacía: un lado vacío nunca gana
    r = eng.resolve_conflict(GAME, "device")
    assert r["state"] != "uploaded" and pending(world)["resolutions"] == []
    assert hub_tree(world) == {"s.sav": b"hub"}


def test_resolve_conflict_on_an_old_hub_explains_it(scripthub, tmp_path):
    home = tmp_path / "home"
    (home / "saves" / "g1").mkdir(parents=True)
    (home / "saves" / "g1" / "s.sav").write_bytes(b"x")
    games = [{"id": GAME, "name": "Mi Juego", "enabled": True, "steam_appid": 1, "status": None, "path": str(home / "saves" / "g1")}]

    def handler(req):
        if req.path == "/api/games":
            return 200, games, {}
        if req.path.startswith("/api/hook/g1/fingerprint"):
            return 200, {"action": "conflict", "reason": "both-changed", "hub": {"hash": "a" * 64}, "device_state": {"hash": "b" * 64}}, {}
        return 404, {"detail": "Not Found"}, {}  # un hub antiguo no tiene la ruta de resolución

    hub = scripthub(handler)
    eng = se.SyncEngine(hub.url, "ckd_k", home=home, sleep=lambda s: None)
    r = eng.resolve_conflict(GAME, "hub")
    assert r == {"game": GAME, "state": "error", "code": "resolution_unsupported"}
    assert any(q.method == "PUT" for q in hub.requests)
