"""La clave en la CLI: llavero (backend en memoria) o fichero, migración, unlink y que no se filtre a ningún sitio."""

import os
from pathlib import Path

import pytest
from conftest import KEY

from checkpoint_client import cli, hub, keystore, settings, texts

OTHER_KEY = KEY.replace("9876", "5432")  # otra clave de prueba sin literal nuevo (gitleaks)
ACCEPTED = (200, {"status": "accepted", "key": KEY, "device": "pc-ab12"}, {})
USER = "pc-ab12@"  # + url del hub


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


def settings_text():
    return (Path(settings.config_dir()) / "settings.json").read_text(encoding="utf-8")


def tree_text(root):
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in Path(root).rglob("*") if p.is_file())


def test_link_with_keyring_keeps_the_key_out_of_settings_and_output(fakehub, home, run, memory_keyring):
    fakehub.script = [ACCEPTED]
    code, out, err = run("link", fakehub.url)
    assert code == 0 and err == ""
    assert texts.LINK_DONE.format(device="pc-ab12", where="llavero") in out
    assert KEY not in out and KEY not in tree_text(settings.config_dir())
    assert memory_keyring.items == {("checkpoint-client", USER + fakehub.url): KEY}
    s = settings.load_settings(settings.config_dir())
    assert s["key_store"] == "keyring" and "key" not in s and s["hub_url"] == fakehub.url


def test_link_without_keyring_says_where_the_file_is(fakehub, home, run):
    fakehub.script = [ACCEPTED]
    code, out, err = run("link", fakehub.url)
    path = os.path.join(settings.config_dir(), "settings.json")
    assert code == 0
    assert texts.KEYRING_UNAVAILABLE.format(path=path) in out and err == ""
    assert texts.LINK_DONE.format(device="pc-ab12", where="fichero") in out
    assert KEY not in out and KEY not in err
    assert settings.load_settings(settings.config_dir())["key_store"] == "file"


def test_commands_work_with_the_key_in_the_keyring(fakehub, home, run, memory_keyring):
    fakehub.script = [ACCEPTED]
    run("link", fakehub.url)
    code, out, err = run("status")
    assert code == 0 and "conexión: ok" in out
    assert any(KEY in str(r) for r in fakehub.requests[1:])  # el hub recibió la clave leída del llavero


def test_legacy_key_in_settings_is_migrated_on_first_use(fakehub, home, run, memory_keyring):
    settings.save_settings(settings.config_dir(), {"hub_url": fakehub.url, "key": KEY, "device": "pc-ab12"})
    code, out, err = run("status")
    assert code == 0 and "conexión: ok" in out
    assert err.strip() == texts.KEYRING_SAVED
    assert KEY not in settings_text()
    assert memory_keyring.items[("checkpoint-client", USER + fakehub.url)] == KEY
    code, out, err = run("status")
    assert code == 0 and err == ""  # el aviso sale una sola vez


def test_migration_failure_is_silent_and_keeps_working(fakehub, home, run, memory_keyring):
    memory_keyring.fail_set = True
    settings.save_settings(settings.config_dir(), {"hub_url": fakehub.url, "key": KEY, "device": "pc-ab12"})
    code, out, err = run("status")
    assert code == 0 and err == "" and KEY in settings_text()


def test_unlink_removes_the_key_from_the_keyring(fakehub, home, run, memory_keyring):
    fakehub.script = [ACCEPTED]
    run("link", fakehub.url)
    assert run("unlink")[0] == 0
    assert memory_keyring.items == {}
    s = settings.load_settings(settings.config_dir())
    assert s == {"hub_url": fakehub.url, "device_name": s["device_name"]}
    code, _, err = run("unlink")
    assert code == 1 and texts.ERR_NOT_LINKED in err


def test_unlink_removes_the_file_key(fakehub, home, run):
    fakehub.script = [ACCEPTED]
    run("link", fakehub.url)
    assert run("unlink")[0] == 0
    assert KEY not in settings_text()


def test_relink_with_force_replaces_the_old_key_in_the_keyring(fakehub, home, run, memory_keyring):
    fakehub.script = [ACCEPTED]
    run("link", fakehub.url)
    fakehub.script = [(200, {"status": "accepted", "key": OTHER_KEY, "device": "pc-cd34"}, {})]
    assert run("link", fakehub.url, "--force")[0] == 0
    assert list(memory_keyring.items.values()) == [OTHER_KEY]


def test_key_missing_from_the_keyring_means_not_linked(fakehub, home, run, memory_keyring):
    fakehub.script = [ACCEPTED]
    run("link", fakehub.url)
    memory_keyring.items.clear()  # el llavero ya no la tiene: no está vinculado de verdad
    code, _, err = run("status")
    assert code == 1 and texts.ERR_NOT_LINKED in err


def test_unexpected_failure_log_has_no_key_with_keyring(fakehub, home, run, memory_keyring, monkeypatch):
    fakehub.script = [ACCEPTED]
    run("link", fakehub.url)

    def boom(*a, **k):
        raise RuntimeError(f"fallo con {KEY}")

    monkeypatch.setattr(cli, "_check", boom)
    code, out, err = run("status")
    assert code == 1 and KEY not in out + err
    assert KEY not in tree_text(settings.config_dir())


def test_keyring_error_on_read_does_not_crash(fakehub, home, run, memory_keyring):
    fakehub.script = [ACCEPTED]
    run("link", fakehub.url)
    memory_keyring.fail_get = True
    code, out, err = run("games")
    assert code == 1 and err.strip() == texts.ERR_NOT_LINKED


def test_keystore_module_not_importing_keyring_at_top_level():
    src = (Path(keystore.__file__)).read_text(encoding="utf-8")
    assert "\nimport keyring" not in src and "\nfrom keyring" not in src  # import perezoso: sin la biblioteca, fichero
