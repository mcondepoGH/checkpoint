"""Sistema de actualizaciones del plugin: compatibilidad por protocolo (probar conexión) y aviso de versión nueva.
Solo lectura: el plugin NO descarga ni instala; la actualización es por «Instalar plugin desde URL» de Decky."""

import asyncio
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

import checkpoint_update as upd
from checkpoint_hub import check_connection, save_settings

KEY = "ckd_clave-de-prueba-9876"


# ---------------------------------------------------------------- utilidades
def make_zip(version="0.2.0", protocol=1, extra=None, drop=(), pkg=None, raw_members=None) -> bytes:
    """Zip con la forma de scripts/package.sh. `extra`: {nombre: bytes}; `drop`: miembros que faltan."""
    package = pkg if pkg is not None else {"name": "checkpoint-deck", "version": version, "checkpointProtocol": protocol}
    members = {
        "Checkpoint/main.py": b"# main nuevo\n",
        "Checkpoint/plugin.json": b'{"name": "Checkpoint"}',
        "Checkpoint/package.json": json.dumps(package).encode(),
        "Checkpoint/dist/index.js": b"// bundle",
        "Checkpoint/py_modules/checkpoint_hub.py": b"# hub\n",
    }
    for d in drop:
        members.pop(d)
    members.update(extra or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in members.items():
            z.writestr(n, b)
        for zi, b in raw_members or []:
            z.writestr(zi, b)
    return buf.getvalue()


def info_for(data: bytes, version="0.2.0", protocol=1) -> dict:
    return {
        "available": True,
        "version": version,
        "protocol": protocol,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "filename": "Checkpoint.zip",
    }


# ---------------------------------------------------------------- 3: compatibilidad en «Probar conexión»
def ping_with(fakehub, protocol=1, minimum=1):
    body = {"ok": True, "user": "admin", "device": "steam-deck-ab12"}
    if protocol is not None:
        body.update(protocol=protocol, min_plugin_protocol=minimum)
    fakehub.ping = (200, body, {})


def test_connection_compatible(fakehub):
    ping_with(fakehub, 1, 1)
    res, data = check_connection(fakehub.url, KEY, plugin_protocol=1)
    assert res == "ok"
    assert data["compat"] == "ok" and data["protocol"] == 1 and data["min_plugin_protocol"] == 1


def test_connection_plugin_outdated_when_below_minimum(fakehub):
    ping_with(fakehub, 3, 2)
    res, data = check_connection(fakehub.url, KEY, plugin_protocol=1)
    assert res == "ok" and data["compat"] == "plugin_outdated"
    assert data["min_plugin_protocol"] == 2 and data["plugin_protocol"] == 1


def test_connection_old_hub_without_protocol_warns_but_does_not_block(fakehub):
    ping_with(fakehub, None)
    res, data = check_connection(fakehub.url, KEY, plugin_protocol=1)
    assert res == "ok" and data["compat"] == "hub_old" and data["protocol"] is None


@pytest.mark.parametrize("bad", ["1", True, -1, 1.5, None])
def test_connection_garbage_protocol_counts_as_old_hub(fakehub, bad):
    fakehub.ping = (200, {"ok": True, "user": "a", "protocol": bad, "min_plugin_protocol": bad}, {})
    assert check_connection(fakehub.url, KEY, plugin_protocol=1)[1]["compat"] == "hub_old"


def test_connection_plugin_without_declared_protocol_is_unknown_not_blocked(fakehub):
    ping_with(fakehub, 1, 1)
    data = check_connection(fakehub.url, KEY, plugin_protocol=None)[1]
    assert data["compat"] == "plugin_unknown"


# ---------------------------------------------------------------- 4: versión nueva (solo lectura)
def test_evaluate_offers_only_strictly_newer():
    d = make_zip("0.2.0")
    ev = upd.evaluate(info_for(d, "0.2.0"), "0.1.0", 1, hub_protocol=1)
    assert ev["state"] == "available" and ev["latest"] == "0.2.0" and ev["current"] == "0.1.0"
    assert ev["reason"] is None and set(ev) == {"state", "current", "latest", "reason"}  # sin can_install
    for same in ("0.1.0", "0.0.9", "0.1.0-rc.1"):
        assert upd.evaluate(info_for(d, same), "0.1.0", 1, 1)["state"] == "up_to_date", same
    assert upd.evaluate(info_for(d, "0.2.0"), "0.2.0-rc.1", 1, 1)["state"] == "available"  # release > su pre-release


def test_evaluate_unavailable_and_garbage():
    assert upd.evaluate({"available": False}, "0.1.0", 1, 1)["state"] == "unavailable"
    assert upd.evaluate(None, "0.1.0", 1, 1)["state"] == "unavailable"
    assert upd.evaluate(info_for(b"x", "no-semver"), "0.1.0", 1, 1)["state"] == "unavailable"
    assert upd.evaluate(info_for(b"x", "0.2.0"), None, 1, 1)["state"] == "unknown"  # versión local ilegible


def test_evaluate_has_no_install_notions():
    ev = upd.evaluate(info_for(b"x", "0.2.0"), "0.1.0", 1, 1)
    assert "plain_http" not in ev and "can_install" not in ev and "install_mode" not in ev


def test_evaluate_old_hub_is_flagged_without_blocking():
    ev = upd.evaluate(info_for(b"x", "0.2.0"), "0.1.0", 1, hub_protocol=None)
    assert ev["state"] == "available" and ev["reason"] == "hub_old"


def test_evaluate_incomplete_info_still_announces_the_version():
    ev = upd.evaluate(info_for(b"x", "0.2.0", protocol=None), "0.1.0", 1, 1)
    assert ev["state"] == "available" and ev["reason"] is None  # la URL de Decky no necesita size/protocol del hub


def test_removed_install_machinery_is_gone():
    for name in ("download_verified", "validate_zip", "install", "can_write", "UpdateError", "MAX_ZIP", "REQUIRED"):
        assert not hasattr(upd, name), name


def test_plugin_has_no_install_update(fake_decky):
    import importlib

    assert not hasattr(importlib.import_module("main").Plugin, "install_update")


# ---------------------------------------------------------------- Plugin (main.py) de punta a punta con hub falso
def boot(fake_decky, hub_url, with_key=True):
    import importlib

    if with_key:
        save_settings(fake_decky.DECKY_PLUGIN_SETTINGS_DIR, {"hub_url": hub_url, "key": KEY, "device": "steam-deck-x"})
    return importlib.import_module("main").Plugin()


def run(p, fn):
    async def go():
        await p._main()
        try:
            return await fn(p)
        finally:
            await p._unload()

    return asyncio.run(go())


def publish(fakehub, version="0.2.0", protocol=1, **kw):
    d = make_zip(version, protocol, **kw)
    fakehub.deck_zip = d
    fakehub.deck_info = info_for(d, version, protocol)
    ping_with(fakehub, 1, 1)
    return d


def test_main_get_version_reads_installed_package_json(fake_decky, fakehub):
    p = boot(fake_decky, fakehub.url)
    assert run(p, lambda p: p.get_version()) == {"version": "0.1.0", "protocol": 1}


def test_main_test_connection_reports_compat(fake_decky, fakehub):
    ping_with(fakehub, 3, 2)
    r = run(boot(fake_decky, fakehub.url), lambda p: p.test_connection())
    assert r["result"] == "ok" and r["compat"] == "plugin_outdated" and r["min_plugin_protocol"] == 2
    assert r["plugin_protocol"] == 1


def test_main_check_update_available(fake_decky, fakehub):
    d = publish(fakehub, "0.2.0")
    r = run(boot(fake_decky, fakehub.url), lambda p: p.check_update())
    assert r["state"] == "available" and r["latest"] == "0.2.0" and r["current"] == "0.1.0"
    assert "can_install" not in r and "install_mode" not in r and "plain_http" not in r
    assert r["hub_url"] == fakehub.url and r["sha256"] == hashlib.sha256(d).hexdigest()
    assert not [x for x in fakehub.requests if x[1] == "/api/deck/plugin"]  # comprobar NO descarga
    infos = [x for x in fakehub.requests if x[1] == "/api/deck/plugin/info"]
    assert infos and all("Authorization" not in x[2] for x in infos)  # la clave solo va al ping


def test_main_check_update_does_not_touch_the_disk(fake_decky, fakehub):
    publish(fakehub, "0.2.0")
    before = sorted(Path(fake_decky.DECKY_PLUGIN_DIR).parent.rglob("*"))
    r = run(boot(fake_decky, fakehub.url), lambda p: p.check_update())
    assert r["state"] == "available"
    assert sorted(Path(fake_decky.DECKY_PLUGIN_DIR).parent.rglob("*")) == before
    assert not (Path(fake_decky.DECKY_PLUGIN_RUNTIME_DIR) / "update").exists()


def test_main_check_update_same_version_is_up_to_date_without_hub_url(fake_decky, fakehub):
    publish(fakehub, "0.1.0")
    r = run(boot(fake_decky, fakehub.url), lambda p: p.check_update())
    assert r["state"] == "up_to_date" and "hub_url" not in r and "can_install" not in r


def test_main_check_update_up_to_date_old_hub_and_not_linked(fake_decky, fakehub):
    publish(fakehub, "0.1.0")
    assert run(boot(fake_decky, fakehub.url), lambda p: p.check_update())["state"] == "up_to_date"
    publish(fakehub, "0.2.0")
    ping_with(fakehub, None)  # hub viejo: ping sin `protocol`
    r = run(boot(fake_decky, fakehub.url), lambda p: p.check_update())
    assert r["state"] == "available" and r["reason"] == "hub_old" and "can_install" not in r
    (Path(fake_decky.DECKY_PLUGIN_SETTINGS_DIR) / "settings.json").unlink()  # desvinculado
    assert run(boot(fake_decky, fakehub.url, with_key=False), lambda p: p.check_update())["state"] == "not_linked"


def test_main_check_update_hub_down_is_connection_error(fake_decky):
    r = run(boot(fake_decky, "http://127.0.0.1:1"), lambda p: p.check_update())
    assert r["state"] == "error" and r["error"] == "connection"


def test_main_sync_blocked_when_plugin_outdated(fake_decky, fakehub):
    ping_with(fakehub, 3, 2)
    p = boot(fake_decky, fakehub.url)

    async def go(p):
        await p.test_connection()  # el ping deja anotada la incompatibilidad
        return await p.sync_all(), await p.list_games()

    a, b = run(p, go)
    assert a.get("error") == "plugin_outdated" and b.get("error") == "plugin_outdated"
    assert not [x for x in fakehub.requests if "/api/steam" in x[1] or "/api/games" in x[1]]


def test_evaluate_1_0_0_is_offered_over_0_2_9_and_rc_stays_below_release():
    # subida a la primera versión estable: la 1.0.0 se ofrece a quien tiene la 0.2.9, y una pre-release no supera a su release
    d = make_zip("1.0.0")
    assert upd.evaluate(info_for(d, "1.0.0"), "0.2.9", 1, 1)["state"] == "available"
    assert upd.evaluate(info_for(d, "1.0.0"), "1.0.0", 1, 1)["state"] == "up_to_date"
    assert upd.evaluate(info_for(d, "1.0.0-rc.1"), "1.0.0", 1, 1)["state"] == "up_to_date"
    assert upd.evaluate(info_for(d, "1.0.0"), "1.0.0-rc.1", 1, 1)["state"] == "available"
