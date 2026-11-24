"""CLI de punta a punta contra el FakeHub: salidas, códigos de salida (0 ok, 1 error, 2 uso, 3 conflicto) y seguridad."""

import ast
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import KEY, set_hash

from checkpoint_client import cli, hub, settings, texts

SRC = Path(__file__).resolve().parent.parent / "src" / "checkpoint_client"
GAME = "g1"
ACCEPTED = (200, {"status": "accepted", "key": KEY, "device": "pc-ab12"}, {})


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    monkeypatch.setattr(hub, "POLL_S", 0.01)


@pytest.fixture
def run(capsys):
    def go(*argv):
        code = cli.main(list(argv))
        cap = capsys.readouterr()
        return code, cap.out, cap.err

    return go


@pytest.fixture
def linked(fakehub, home):
    settings.save_settings(
        settings.config_dir(), {"hub_url": fakehub.url, "key": KEY, "device": "pc-ab12", "device_name": "pc"}
    )
    save = home / "Games" / "g1"
    fakehub.games = [
        {
            "id": GAME,
            "name": "Mi Juego",
            "enabled": True,
            "steam_appid": None,
            "status": None,
            "path": str(save),
            "process": "mijuego.exe",
        }  # fmt: skip
    ]
    fakehub.save = save
    return fakehub


def put(root: Path, rel: str, data: bytes):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def tree(root: Path):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def no_secrets(*outs):
    for o in outs:
        assert KEY not in o and "SECRET-xyz" not in o


# ---------------------------------------------------------------- link
def test_link_saves_key_once_and_prints_code(fakehub, home, run):
    fakehub.script = [(200, {"status": "pending", "expires_in": 500}, {}), ACCEPTED]
    code, out, err = run("link", fakehub.url, "--name", "Mi PC")
    assert code == 0 and err == ""
    assert texts.LINK_CODE.format(code="123 456") in out and texts.LINK_WAITING in out
    assert texts.LINK_DONE.format(device="pc-ab12", where="fichero") in out
    no_secrets(out, err)
    f = Path(settings.config_dir()) / "settings.json"
    assert settings.load_settings(settings.config_dir())["key"] == KEY
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    assert b'"name": "Mi PC"' in fakehub.requests[0][3]


def test_link_default_name_is_the_hostname(fakehub, home, run, monkeypatch):
    monkeypatch.setattr("socket.gethostname", lambda: "mi-portatil")
    fakehub.script = [ACCEPTED]
    assert run("link", fakehub.url)[0] == 0
    assert b'"name": "mi-portatil"' in fakehub.requests[0][3]


def test_link_twice_needs_force(linked, run):
    linked.script = [ACCEPTED]
    code, out, err = run("link", linked.url)
    assert code == 1 and out == "" and err.strip() == texts.LINK_ALREADY.format(device="pc-ab12")
    assert len(linked.requests) == 0
    assert run("link", linked.url, "--force")[0] == 0


def test_link_without_hub_uses_saved_one_or_fails(linked, home, run):
    linked.script = [ACCEPTED]
    assert run("link", "--force")[0] == 0
    settings.save_settings(settings.config_dir(), {})
    code, _, err = run("link")
    assert code == 2 and texts.LINK_BAD_URL in err


@pytest.mark.parametrize("bad", ["hub:8088", "ftp://x", "http://u:p@h", "http://h/ruta"])
def test_link_bad_url(home, run, bad):
    code, out, err = run("link", bad)
    assert code == 2 and out == "" and texts.LINK_BAD_URL in err


def test_link_bad_name(fakehub, home, run):
    code, _, err = run("link", fakehub.url, "--name", "a/b")
    assert code == 2 and texts.ERR_NAME_INVALID in err
    assert fakehub.requests == []


@pytest.mark.parametrize(
    ("script", "msg"),
    [([(200, {"status": "rejected"}, {})], texts.LINK_REJECTED), ([(404, {}, {})], texts.LINK_EXPIRED)],
)
def test_link_rejected_or_expired_saves_nothing(fakehub, home, run, script, msg):
    fakehub.script = script
    code, _, err = run("link", fakehub.url)
    assert code == 1 and msg in err
    assert settings.load_settings(settings.config_dir()) == {}
    no_secrets(err)


def test_link_connection_error(home, run):
    code, _, err = run("link", "http://127.0.0.1:1")
    assert code == 1 and texts.ERR_CONNECTION.format(url="http://127.0.0.1:1") in err


def test_link_rate_limited_shows_wait(fakehub, home, run):
    fakehub.create = (429, {}, {"Retry-After": "12"})
    code, _, err = run("link", fakehub.url)
    assert code == 1 and texts.ERR_RATE_LIMITED.format(s=12) in err


def test_link_ctrl_c_saves_nothing(fakehub, home, run, monkeypatch):
    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(hub, "pair", boom)
    assert run("link", fakehub.url)[0] == 1
    assert settings.load_settings(settings.config_dir()) == {}


def test_unlink_removes_key_only(linked, run):
    assert run("unlink")[0] == 0
    s = settings.load_settings(settings.config_dir())
    assert "key" not in s and s["hub_url"] == linked.url
    code, _, err = run("unlink")
    assert code == 1 and texts.ERR_NOT_LINKED in err


# ---------------------------------------------------------------- games
def test_games_lists_tab_separated_and_needs_link(linked, run, home):
    code, out, err = run("games")
    assert code == 0 and err == ""
    assert out.splitlines() == [f"{GAME}\tMi Juego\t{linked.save}\t-"]
    linked.games = []
    assert run("games")[1].strip() == texts.SYNC_NO_GAMES


def test_games_not_linked(home, run):
    code, out, err = run("games")
    assert code == 1 and out == "" and err.strip() == texts.ERR_NOT_LINKED


def test_games_check_compares_without_changing_anything(linked, run):
    put(linked.save, "a.sav", b"1")
    code, out, _ = run("games", "--check")
    assert code == 0 and texts.CHECK_UPLOAD.format(game="Mi Juego") in out
    assert not linked.files.get(GAME)
    assert not any(r[0] == "PUT" for r in linked.requests)


# ---------------------------------------------------------------- conexión y compatibilidad
def test_unauthorized_key(linked, run):
    linked.key = "ckd_otra"
    code, out, err = run("games")
    assert code == 1 and err.strip() == texts.ERR_UNAUTHORIZED and out == ""


def test_unreachable_hub(linked, run):
    settings.save_settings(settings.config_dir(), {"hub_url": "http://127.0.0.1:1", "key": KEY})
    code, _, err = run("sync", GAME)
    assert code == 1 and texts.ERR_CONNECTION.format(url="http://127.0.0.1:1") in err
    no_secrets(err)


def test_outdated_client_does_not_sync(linked, run):
    linked.ping = (200, {"ok": True, "device": "pc-ab12", "protocol": 5, "min_plugin_protocol": 3}, {})
    put(linked.save, "a.sav", b"1")
    code, _, err = run("sync", GAME)
    assert code == 1 and texts.ERR_CLIENT_OUTDATED.format(min=3, n=1) in err
    assert not linked.files.get(GAME)


def test_old_hub_warns_but_syncs(linked, run):
    linked.ping = (200, {"ok": True, "device": "pc-ab12"}, {})
    put(linked.save, "a.sav", b"1")
    code, out, err = run("sync", GAME)
    assert code == 0 and texts.ERR_HUB_OLD in err
    assert texts.SYNC_UPLOADED.format(game="Mi Juego", n=1) in out


# ---------------------------------------------------------------- sync
def test_sync_upload_then_up_to_date_then_download(linked, run):
    put(linked.save, "a.sav", b"1")
    code, out, err = run("sync", GAME)
    assert code == 0 and err == ""
    assert out.splitlines() == [
        texts.SYNC_UPLOADING.format(game="Mi Juego", n=1),
        texts.SYNC_UPLOADED.format(game="Mi Juego", n=1),
    ]
    assert run("sync", GAME)[1].strip() == texts.SYNC_UP_TO_DATE.format(game="Mi Juego")
    linked.files[GAME] = {"b.sav": b"2", "c.sav": b"3"}
    code, out, _ = run("sync", "Mi Juego")  # también por nombre
    assert code == 0
    assert texts.SYNC_DOWNLOADING.format(game="Mi Juego", n=2) in out
    assert texts.SYNC_DOWNLOADED.format(game="Mi Juego", n=2, path=linked.save) in out
    assert tree(linked.save) == {"b.sav": b"2", "c.sav": b"3"}


def test_sync_dry_run_changes_nothing(linked, run):
    put(linked.save, "a.sav", b"1")
    code, out, _ = run("sync", GAME, "--dry-run")
    assert code == 0 and out.strip() == texts.CHECK_UPLOAD.format(game="Mi Juego")
    assert not linked.files.get(GAME)
    linked.files[GAME] = {"b.sav": b"2"}
    linked.base[GAME] = set_hash({"a.sav": b"1"})  # el equipo no cambió desde la última sync
    code, out, _ = run("sync", GAME, "--dry-run")
    assert out.strip() == texts.CHECK_DOWNLOAD.format(game="Mi Juego") and tree(linked.save) == {"a.sav": b"1"}


def make_conflict(linked, run):
    put(linked.save, "a.sav", b"dispositivo")
    assert run("sync", GAME)[0] == 0
    linked.files[GAME] = {"a.sav": b"hub"}
    put(linked.save, "a.sav", b"cambio local")


def test_sync_conflict_exit_3_touches_nothing(linked, run):
    make_conflict(linked, run)
    code, out, err = run("sync", GAME)
    assert code == 3 and out == ""
    assert err.splitlines() == [
        texts.SYNC_CONFLICT.format(game="Mi Juego"),
        texts.SYNC_CONFLICT_HOW.format(game="Mi Juego"),
    ]
    assert tree(linked.save) == {"a.sav": b"cambio local"} and linked.files[GAME] == {"a.sav": b"hub"}
    assert run("sync", GAME, "--dry-run")[0] == 3


@pytest.mark.parametrize("winner", ["hub", "device"])
def test_sync_resolve(linked, run, winner):
    make_conflict(linked, run)
    code, out, err = run("sync", GAME, "--resolve", winner)
    assert code == 0, err
    assert tree(linked.save) == linked.files[GAME]
    assert linked.files[GAME]["a.sav"] == (b"hub" if winner == "hub" else b"cambio local")


def test_sync_resolve_value_checked(linked, run):
    code, _, err = run("sync", GAME, "--resolve", "newest")
    assert code == 2 and texts.ERR_BAD_RESOLVE in err


def test_sync_usage_errors(linked, run):
    assert run("sync")[0:1] == (2,) and texts.ERR_NEED_GAME in run("sync")[2]
    assert run("sync", GAME, "--all")[0] == 2
    assert run("sync", "--all", "--resolve", "hub")[0] == 2
    assert run("nada")[0] == 2


def test_sync_unknown_game(linked, run):
    code, _, err = run("sync", "no-existe")
    assert code == 1 and texts.SYNC_ERRORS["unknown_game"] in err


def test_sync_skips_without_path_or_disabled(linked, run):
    linked.games[0]["path"] = None
    code, out, _ = run("sync", GAME)
    assert code == 0 and out.strip() == texts.SYNC_NO_PATH.format(game="Mi Juego")
    linked.games[0].update(path=str(linked.save), enabled=False)
    assert run("sync", GAME)[1].strip() == texts.SYNC_DISABLED.format(game="Mi Juego")
    linked.games[0]["enabled"] = True
    assert run("sync", GAME)[1].strip() == texts.SYNC_MISSING_DIR.format(game="Mi Juego")


def test_sync_forbidden_path_message(linked, run):
    linked.games[0]["path"] = "/etc/ssh"
    code, _, err = run("sync", GAME)
    assert code == 1 and err.strip() == texts.ERR_PATH_FORBIDDEN.format(path="/etc/ssh")


def test_sync_open_game_hook(linked, run, monkeypatch):
    put(linked.save, "a.sav", b"1")
    monkeypatch.setattr(cli, "is_running", lambda game: True)
    code, _, err = run("sync", GAME)
    assert code == 1 and err.strip() == texts.SYNC_RUNNING.format(game="Mi Juego")
    assert not linked.files.get(GAME)
    assert run("sync", GAME, "--dry-run")[0] == 0  # comprobar sí vale con el juego abierto


def test_sync_default_hook_says_not_running():
    assert cli.is_running("lo-que-sea") is False


def test_sync_all_summary_and_exit_code(linked, run, home):
    put(linked.save, "a.sav", b"1")
    other = home / "Games" / "g2"
    put(other, "z", b"z")
    linked.games.append({"id": "g2", "name": "Dos", "enabled": True, "path": str(other), "process": None})
    linked.games.append({"id": "g3", "name": "Tres", "enabled": True, "path": "/etc", "process": None})
    code, out, err = run("sync", "--all")
    assert code == 1
    assert (
        texts.SYNC_ITEM.format(i=1, n=3, name="Mi Juego", message=texts.SYNC_UPLOADED.format(game="Mi Juego", n=1))
        in out
    )
    assert texts.SYNC_SUMMARY.format(ok=2, c=0, e=1) in out
    assert texts.ERR_PATH_FORBIDDEN.format(path="/etc") in err
    linked.games.pop()
    assert run("sync", "--all")[0] == 0


def test_sync_all_conflict_is_exit_3(linked, run):
    make_conflict(linked, run)
    code, out, err = run("sync", "--all")
    assert (
        code == 3
        and texts.SYNC_SUMMARY.format(ok=0, c=1, e=0) in out
        and texts.SYNC_CONFLICT.format(game="Mi Juego") in err
    )


def test_sync_all_without_games(linked, run):
    linked.games = []
    code, out, _ = run("sync", "--all")
    assert code == 0 and out.strip() == texts.SYNC_NO_GAMES


# ---------------------------------------------------------------- run
def play(code: str):
    """Comando que 'juega': ejecuta `code` con el Python de los tests."""
    return [sys.executable, "-c", code]


def test_run_downloads_launches_and_uploads_on_close(linked, run, tmp_path):
    linked.files[GAME] = {"slot.sav": b"nivel1"}
    marker = tmp_path / "ran"
    script = (
        f"import pathlib;s=pathlib.Path({str(linked.save)!r});"
        f"assert (s/'slot.sav').read_bytes()==b'nivel1';(s/'slot.sav').write_bytes(b'nivel2');"
        f"(s/'nuevo.sav').write_bytes(b'x');pathlib.Path({str(marker)!r}).write_text('ok', encoding='utf-8')"
    )
    code, out, err = run("run", GAME, "--", *play(script))
    assert code == 0, err
    assert marker.exists()
    assert linked.files[GAME] == {"slot.sav": b"nivel2", "nuevo.sav": b"x"}
    assert texts.SYNC_DOWNLOADED.format(game="Mi Juego", n=1, path=linked.save) in out
    assert texts.SYNC_UPLOADED.format(game="Mi Juego", n=2) in out
    assert [e[0] for e in linked.events] == ["opened", "closed"]
    assert linked.events[1][2] == {"result": {"state": "uploaded"}}


def test_run_with_conflict_does_not_launch(linked, run, tmp_path):
    make_conflict(linked, run)
    marker = tmp_path / "ran"
    code, _, err = run(
        "run", GAME, "--", *play(f"import pathlib;pathlib.Path({str(marker)!r}).write_text('x', encoding='utf-8')")
    )
    assert code == 3 and texts.SYNC_CONFLICT.format(game="Mi Juego") in err
    assert not marker.exists() and tree(linked.save) == {"a.sav": b"cambio local"}


def test_run_game_exit_status_does_not_hide_sync_result(linked, run):
    put(linked.save, "a.sav", b"1")
    code, out, _ = run("run", GAME, "--", *play("import sys;sys.exit(7)"))
    assert code == 0 and texts.SYNC_UPLOADED.format(game="Mi Juego", n=1) in out


def test_run_first_time_with_nothing_anywhere_still_launches_and_uploads(linked, run):
    code, out, err = run(
        "run",
        GAME,
        "--",
        *play(
            f"import pathlib;p=pathlib.Path({str(linked.save)!r});p.mkdir(parents=True);(p/'n.sav').write_bytes(b'1')"
        ),
    )
    assert code == 0, err
    assert linked.files[GAME] == {"n.sav": b"1"}


def test_run_without_command_or_with_missing_binary(linked, run):
    code, _, err = run("run", GAME)
    assert code == 2 and texts.ERR_RUN_NO_COMMAND in err
    code, _, err = run("run", GAME, "--")
    assert code == 2
    code, _, err = run("run", GAME, "--", "/no/existe/juego")
    assert code == 1 and err.strip() == texts.ERR_RUN_LAUNCH.format(reason="No such file or directory")
    assert [e[0] for e in linked.events] == ["opened", "closed"]  # el «jugando» del hub no se queda colgado


def test_run_does_not_use_a_shell(linked, run, tmp_path):
    put(linked.save, "a.sav", b"1")
    evil = tmp_path / "pwned"
    code, _, _ = run("run", GAME, "--", sys.executable, "-c", "pass", f"; touch {evil}")
    assert not evil.exists()


def test_run_skip_states_do_not_launch(linked, run, tmp_path):
    linked.games[0]["path"] = None
    marker = tmp_path / "ran"
    code, _, err = run(
        "run", GAME, "--", *play(f"import pathlib;pathlib.Path({str(marker)!r}).write_text('x', encoding='utf-8')")
    )
    assert code == 1 and texts.SYNC_NO_PATH.format(game="Mi Juego") in err and not marker.exists()


def test_run_notification_failures_are_not_fatal(linked, run, monkeypatch):
    put(linked.save, "a.sav", b"1")

    def deaf(*a, **k):
        raise cli.HubApiError(404, None)

    monkeypatch.setattr(cli.SyncEngine, "notify_opened", deaf)
    monkeypatch.setattr(cli.SyncEngine, "notify_closed", deaf)
    code, out, _ = run("run", GAME, "--", *play("pass"))
    assert code == 0 and texts.SYNC_UP_TO_DATE.format(game="Mi Juego") in out


# ---------------------------------------------------------------- status
def test_status_ok(linked, run):
    code, out, err = run("status")
    assert code == 0 and err == ""
    lines = out.splitlines()
    assert texts.STATUS_LINE.format(key=texts.STATUS_KEYS["hub"], value=linked.url) in lines
    assert texts.STATUS_LINE.format(key=texts.STATUS_KEYS["device"], value="pc-ab12") in lines
    assert texts.STATUS_LINE.format(key=texts.STATUS_KEYS["connection"], value=texts.STATUS_OK) in lines
    assert texts.STATUS_LINE.format(key=texts.STATUS_KEYS["protocol"], value="1") in lines
    assert texts.STATUS_LINE.format(key=texts.STATUS_KEYS["version"], value=cli.__version__) in lines
    no_secrets(out)


def test_status_not_linked_unreachable_or_unauthorized(home, linked, run):
    linked.key = "otra"
    code, out, err = run("status")
    assert code == 1 and texts.ERR_UNAUTHORIZED in err and texts.STATUS_KEYS["version"] in out
    settings.save_settings(settings.config_dir(), {"hub_url": "http://127.0.0.1:1", "key": KEY})
    assert run("status")[0] == 1
    settings.save_settings(settings.config_dir(), {})
    code, out, err = run("status")
    assert code == 1 and texts.ERR_NOT_LINKED in err


# ---------------------------------------------------------------- robustez
def test_unexpected_failure_is_logged_without_secrets(linked, run, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError(f"fallo con {KEY}")

    monkeypatch.setattr(cli.SyncEngine, "sync_game", boom)
    code, out, err = run("sync", GAME)
    log = Path(settings.config_dir()) / "checkpoint-client.log"
    assert code == 1 and err.strip() == texts.ERR_UNEXPECTED.format(log=log)
    no_secrets(out, err, log.read_text(encoding="utf-8"))
    assert "RuntimeError" in log.read_text(encoding="utf-8")
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o600


def test_python_dash_m_works(home, fakehub):
    env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(SRC.parent)}
    r = subprocess.run(
        [sys.executable, "-m", "checkpoint_client", "status"], capture_output=True, text=True, encoding="utf-8", env=env
    )
    assert r.returncode == 1 and texts.ERR_NOT_LINKED in r.stderr


def test_help_texts_come_from_texts_module(capsys):
    assert cli.main(["--help"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert texts.HELP_ROOT in out and texts.HELP_LINK in out and texts.HELP_RUN.split(":")[0] in out
    for cmd in ("link", "games", "sync", "run", "status", "unlink"):
        assert cmd in out
    for later in ("watch", "install", "uninstall", "check-update"):
        assert later not in out


def test_cli_has_no_loose_text_literals():
    """Todo texto visible va en texts.py: en cli.py ningún literal lleva espacios (salvo docstrings)."""
    tree_ = ast.parse((SRC / "cli.py").read_text(encoding="utf-8"))
    docs = {
        id(n.body[0].value)
        for n in ast.walk(tree_)
        if isinstance(n, (ast.Module, ast.FunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    loose = [
        n.value
        for n in ast.walk(tree_)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and " " in n.value
    ]
    assert not loose, loose
