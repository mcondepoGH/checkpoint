"""Nombre editable del dispositivo: por defecto, validación (reglas del hub), persistencia y envío al hub."""

import asyncio
import json

import pytest

from checkpoint_core.names import DeviceNameError
from checkpoint_hub import Pairing, load_settings, save_settings
from test_pairing import ACCEPTED, KEY, finish, make


def sent_body(fakehub):
    return json.loads(fakehub.requests[0][3])


def run_pairing(p):
    async def go():
        p.start()
        await asyncio.sleep(0)
        await finish(p)

    asyncio.run(go())


def test_default_name_is_steam_deck(fakehub, settings_dir):
    fakehub.script = [ACCEPTED]
    p = make(settings_dir, fakehub.url)
    assert p.state()["device_name"] == "Steam Deck"
    run_pairing(p)
    assert sent_body(fakehub) == {"name": "Steam Deck", "os": "linux"}


def test_custom_name_sent_in_body(fakehub, settings_dir):
    fakehub.script = [ACCEPTED]
    p = make(settings_dir, fakehub.url)
    assert p.set_device_name("  Deck salón ") == "Deck salón"  # se recortan los bordes
    run_pairing(p)
    assert sent_body(fakehub) == {"name": "Deck salón", "os": "linux"}


def test_name_persists_across_restart(settings_dir):
    p = Pairing(settings_dir)
    p.set_device_name("Deck cuarto")
    assert load_settings(settings_dir)["device_name"] == "Deck cuarto"
    assert Pairing(settings_dir).state()["device_name"] == "Deck cuarto"


@pytest.mark.parametrize(
    "raw,code",
    [
        (None, "empty"),
        (5, "empty"),
        ("", "empty"),
        ("   ", "empty"),
        ("a" * 65, "too_long"),
        ("a/b", "slash"),
        ("a\\b", "slash"),
        ("a  b", "spaces"),
        ("a\x00b", "control"),
        ("a\tb", "control"),
        ("...", "dots"),
    ],
)
def test_invalid_names_rejected_and_not_saved(settings_dir, raw, code):
    p = Pairing(settings_dir)
    with pytest.raises(DeviceNameError) as e:
        p.set_device_name(raw)
    assert e.value.code == code
    assert "device_name" not in load_settings(settings_dir)
    assert p.state()["device_name"] == "Steam Deck"


def test_invalid_name_in_settings_file_falls_back_to_default(settings_dir):
    save_settings(settings_dir, {"device_name": "a/b"})
    assert Pairing(settings_dir).state()["device_name"] == "Steam Deck"


def test_hub_name_invalid_shows_clear_error(fakehub, settings_dir):
    fakehub.create = (400, {"detail": {"code": "err.pairing.name_invalid", "params": {}}}, {})
    p = make(settings_dir, fakehub.url)
    run_pairing(p)
    st = p.state()
    assert st["status"] == "error" and st["error"] == "name_invalid"


def test_rename_while_linked_keeps_key_and_warns(settings_dir):
    save_settings(settings_dir, {"hub_url": "http://hub", "device": "deck-1", "key": KEY, "paired_name": "Steam Deck"})
    p = Pairing(settings_dir)
    assert p.state()["name_changed"] is False
    p.set_device_name("Deck salón")
    st = p.state()
    assert st["status"] == "linked" and st["name_changed"] is True
    assert load_settings(settings_dir)["key"] == KEY
    p.set_device_name("Steam Deck")
    assert p.state()["name_changed"] is False


def test_accepting_records_paired_name(fakehub, settings_dir):
    fakehub.script = [ACCEPTED]
    p = make(settings_dir, fakehub.url)
    p.set_device_name("Deck salón")
    run_pairing(p)
    assert load_settings(settings_dir)["paired_name"] == "Deck salón"
    assert p.state()["name_changed"] is False


def test_plugin_set_device_name(fake_decky):
    async def go():
        import main

        p = main.Plugin()
        await p._main()
        bad = await p.set_device_name("a/b")
        ok = await p.set_device_name("Deck 2")
        return bad, ok

    bad, ok = asyncio.run(go())
    assert bad == {"ok": False, "name_error": "slash"}
    assert ok["ok"] is True and ok["device_name"] == "Deck 2"
