"""Dónde vive la clave `ckd_`: llavero del sistema si lo hay y, si no, `settings.json` (0600). Sin llavero real: backend
en memoria (`memory_keyring`) o el backend `fail` (por defecto, como un Linux sin Secret Service)."""

import json
import os
import stat

import pytest

from checkpoint_client import keystore, settings
from conftest import KEY

HUB = "http://h:1"
DEV = "pc-ab12"
USER = f"{DEV}@{HUB}"


def meta(**extra):
    return {"hub_url": HUB, "device": DEV, **extra}


def raw(cfg):
    with open(os.path.join(cfg, "settings.json"), encoding="utf-8") as f:
        return f.read()


def test_username_is_device_and_hub():
    assert keystore.username(meta()) == USER
    assert keystore.SERVICE == "checkpoint-client"


def test_store_in_keyring_keeps_the_key_out_of_settings(settings_dir, memory_keyring):
    s = meta()
    assert keystore.store_key(settings_dir, s, KEY) == "keyring"
    assert memory_keyring.items == {("checkpoint-client", USER): KEY}
    assert KEY not in raw(settings_dir)
    saved = settings.load_settings(settings_dir)
    assert saved == {"hub_url": HUB, "device": DEV, "key_store": "keyring"}
    assert keystore.get_key(settings_dir, saved) == KEY


def test_without_keyring_backend_falls_back_to_a_0600_file(settings_dir):
    assert keystore.keyring_available() is False
    assert keystore.store_key(settings_dir, meta(), KEY) == "file"
    saved = settings.load_settings(settings_dir)
    assert saved["key"] == KEY and saved["key_store"] == "file"
    assert stat.S_IMODE(os.stat(os.path.join(settings_dir, "settings.json")).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(settings_dir).st_mode) == 0o700
    assert keystore.get_key(settings_dir, saved) == KEY


def test_keyring_error_on_save_falls_back_to_file_without_losing_the_key(settings_dir, memory_keyring):
    memory_keyring.fail_set = True
    assert keystore.store_key(settings_dir, meta(), KEY) == "file"
    assert keystore.get_key(settings_dir, settings.load_settings(settings_dir)) == KEY


def test_keyring_that_forgets_the_key_is_not_trusted(settings_dir, memory_keyring):
    memory_keyring.lose_on_set = True  # set_password no falla pero no guarda: se comprueba leyendo
    assert keystore.store_key(settings_dir, meta(), KEY) == "file"
    assert settings.load_settings(settings_dir)["key"] == KEY


def test_store_in_keyring_removes_a_previous_file_key(settings_dir, memory_keyring):
    settings.save_settings(settings_dir, meta(key="ckd_vieja-0000", key_store="file"))
    assert keystore.store_key(settings_dir, settings.load_settings(settings_dir), KEY) == "keyring"
    assert "ckd_vieja-0000" not in raw(settings_dir) and KEY not in raw(settings_dir)


def test_get_key_missing_or_keyring_gone_is_none(settings_dir, memory_keyring):
    assert keystore.get_key(settings_dir, meta()) is None
    keystore.store_key(settings_dir, meta(), KEY)
    memory_keyring.fail_get = True
    assert keystore.get_key(settings_dir, settings.load_settings(settings_dir)) is None
    memory_keyring.fail_get = False
    memory_keyring.items.clear()
    assert keystore.get_key(settings_dir, settings.load_settings(settings_dir)) is None


def test_get_key_rejects_a_value_that_is_not_a_device_key(settings_dir, memory_keyring):
    memory_keyring.items[("checkpoint-client", USER)] = "ck_de-usuario"
    assert keystore.get_key(settings_dir, meta(key_store="keyring")) is None


# ---------------------------------------------------------------- migración
def test_migrates_a_legacy_key_from_settings_to_the_keyring(settings_dir, memory_keyring):
    settings.save_settings(settings_dir, meta(key=KEY))  # formato anterior: sin `key_store`
    assert keystore.get_key(settings_dir, settings.load_settings(settings_dir)) == KEY
    assert memory_keyring.items[("checkpoint-client", USER)] == KEY
    assert KEY not in raw(settings_dir)
    assert settings.load_settings(settings_dir)["key_store"] == "keyring"


def test_migrates_a_file_key_when_a_keyring_appears_later(settings_dir, memory_keyring):
    settings.save_settings(settings_dir, meta(key=KEY, key_store="file"))
    keystore.get_key(settings_dir, settings.load_settings(settings_dir))
    assert "key" not in settings.load_settings(settings_dir) and KEY not in raw(settings_dir)


def test_migration_is_idempotent(settings_dir, memory_keyring):
    settings.save_settings(settings_dir, meta(key=KEY))
    for _ in range(3):
        assert keystore.get_key(settings_dir, settings.load_settings(settings_dir)) == KEY
    assert list(memory_keyring.items.values()) == [KEY]


def test_failed_migration_keeps_the_key_in_the_file(settings_dir, memory_keyring):
    memory_keyring.fail_set = True
    settings.save_settings(settings_dir, meta(key=KEY))
    assert keystore.get_key(settings_dir, settings.load_settings(settings_dir)) == KEY
    assert settings.load_settings(settings_dir)["key"] == KEY and memory_keyring.items == {}


def test_migration_with_a_keyring_that_forgets_does_not_delete_the_file_key(settings_dir, memory_keyring):
    memory_keyring.lose_on_set = True
    settings.save_settings(settings_dir, meta(key=KEY))
    assert keystore.get_key(settings_dir, settings.load_settings(settings_dir)) == KEY
    assert settings.load_settings(settings_dir)["key"] == KEY


def test_migration_cleans_settings_only_after_the_keyring_confirmed(settings_dir, memory_keyring, monkeypatch):
    """Si no se puede reescribir settings.json, la clave queda en los dos sitios (nunca en ninguno)."""
    settings.save_settings(settings_dir, meta(key=KEY))

    def boom(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(settings, "save_settings", boom)
    assert keystore.get_key(settings_dir, settings.load_settings(settings_dir)) == KEY
    assert memory_keyring.items[("checkpoint-client", USER)] == KEY
    assert settings.load_settings(settings_dir)["key"] == KEY


def test_no_keyring_means_no_migration(settings_dir):
    settings.save_settings(settings_dir, meta(key=KEY))
    assert keystore.get_key(settings_dir, settings.load_settings(settings_dir)) == KEY
    assert settings.load_settings(settings_dir)["key"] == KEY


# ---------------------------------------------------------------- borrar
def test_delete_removes_the_key_from_the_keyring_and_settings(settings_dir, memory_keyring):
    keystore.store_key(settings_dir, meta(), KEY)
    keystore.delete_key(settings_dir, settings.load_settings(settings_dir))
    assert memory_keyring.items == {}
    assert settings.load_settings(settings_dir) == {"hub_url": HUB, "device": DEV}


def test_delete_removes_the_file_key(settings_dir):
    keystore.store_key(settings_dir, meta(), KEY)
    keystore.delete_key(settings_dir, settings.load_settings(settings_dir))
    assert KEY not in raw(settings_dir) and "key" not in settings.load_settings(settings_dir)


def test_delete_clears_both_places_even_if_the_store_field_lies(settings_dir, memory_keyring):
    memory_keyring.items[("checkpoint-client", USER)] = KEY
    settings.save_settings(settings_dir, meta(key=KEY, key_store="file"))
    keystore.delete_key(settings_dir, settings.load_settings(settings_dir))
    assert memory_keyring.items == {} and KEY not in raw(settings_dir)


def test_delete_with_keyring_error_still_clears_the_file_and_does_not_raise(settings_dir, memory_keyring):
    keystore.store_key(settings_dir, meta(), KEY)
    memory_keyring.fail_delete = True
    keystore.delete_key(settings_dir, settings.load_settings(settings_dir))
    assert "key_store" not in settings.load_settings(settings_dir)


def test_delete_when_nothing_is_stored_is_fine(settings_dir, memory_keyring):
    keystore.delete_key(settings_dir, meta())


# ---------------------------------------------------------------- sin biblioteca
def test_without_the_keyring_library_everything_is_file(settings_dir, monkeypatch):
    monkeypatch.setattr(keystore, "_backend", lambda: None)
    assert keystore.keyring_available() is False
    assert keystore.store_key(settings_dir, meta(), KEY) == "file"
    assert keystore.get_key(settings_dir, settings.load_settings(settings_dir)) == KEY


def test_keyring_available_with_memory_and_not_with_fail(memory_keyring):
    assert keystore.keyring_available() is True


def test_settings_file_is_valid_json_and_utf8(settings_dir, memory_keyring):
    keystore.store_key(settings_dir, meta(), KEY)
    assert json.loads(raw(settings_dir))["key_store"] == "keyring"


@pytest.mark.parametrize("where", ["keyring", "file"])
def test_location_label(where):
    assert keystore.location_label(where) in ("llavero", "fichero")


# ---------------------------------------------------------------- aviso de migración fallida
@pytest.mark.parametrize("mode", ["fail_set", "lose_on_set"])
def test_failed_migration_warns_once_on_stderr_and_keeps_the_key(settings_dir, memory_keyring, capsys, mode):
    from checkpoint_client import texts

    setattr(memory_keyring, mode, True)
    settings.save_settings(settings_dir, meta(key=KEY))
    s = settings.load_settings(settings_dir)
    assert keystore.get_key(settings_dir, s) == KEY
    assert keystore.get_key(settings_dir, s) == KEY  # segundo uso en la misma ejecución: sin segundo aviso
    out, err = capsys.readouterr()
    assert out == ""
    assert err == texts.KEYRING_MIGRATION_FAILED.format(path=keystore.settings_path(settings_dir)) + "\n"
    assert KEY not in err
    assert settings.load_settings(settings_dir)["key"] == KEY


def test_no_keyring_at_all_does_not_warn(settings_dir, capsys):
    settings.save_settings(settings_dir, meta(key=KEY))
    assert keystore.get_key(settings_dir, settings.load_settings(settings_dir)) == KEY
    assert capsys.readouterr().err == ""
