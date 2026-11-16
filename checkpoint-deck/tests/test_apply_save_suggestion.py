"""`apply_save_suggestion` (main.py): aplica una carpeta sugerida del manifiesto que el usuario confirmó, sin crear nada en el hub."""

import asyncio
import os
from pathlib import Path

from savefix import manifest, mgame, rule, write
from test_main_games import setup
from test_main_library import settled

import checkpoint_games as cg


def prepare(fake_decky, scripthub, tmp_path, monkeypatch, rules=None, steam=730):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    lib = tmp_path / "card" if steam == 730 else Path(os.environ["HOME"]) / ".local/share/Steam"  # 730 está en la SD
    save = lib / f"steamapps/compatdata/{steam}/pfx/drive_c/users/steamuser/AppData/Roaming/Juego730"
    write(save / "a.sav")
    os.makedirs(fake_decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
    with open(os.path.join(fake_decky.DECKY_PLUGIN_SETTINGS_DIR, "save_manifest.json"), "wb") as f:
        f.write(manifest(mgame("Juego", steam=steam, paths=rules or [rule("pfxRoaming", "Juego730", "win")])))
    return st, p, save


def run(p, *calls):
    async def go():
        await p._main()
        await p.refresh_library()
        await settled(p)
        out = [await c() for c in calls]
        await p._unload()
        return out

    return asyncio.run(go())


def test_apply_returns_the_unconfigured_game_and_creates_nothing(fake_decky, scripthub, tmp_path, monkeypatch):
    st, p, save = prepare(fake_decky, scripthub, tmp_path, monkeypatch)
    before = [dict(g) for g in st.games]
    (out,) = run(p, lambda: p.apply_save_suggestion("steam", 730, str(save)))
    assert out["ok"] and out["appid"] == 730 and out["path"] == str(save) and out["name"]
    assert st.games == before  # no se llamó al hub: el guardado sigue el flujo de «Configurar»
    assert str(save) in p._offered[730]


def test_apply_rejects_a_path_that_was_not_suggested(fake_decky, scripthub, tmp_path, monkeypatch):
    st, p, save = prepare(fake_decky, scripthub, tmp_path, monkeypatch)
    otra = save.parent / "otra"
    write(otra / "x")
    (a, b, c) = run(
        p,
        lambda: p.apply_save_suggestion("steam", 730, str(otra)),
        lambda: p.apply_save_suggestion("steam", 730, 5),
        lambda: p.apply_save_suggestion("steam", 730, str(save / "a.sav")),
    )
    assert [x["error"] for x in (a, b, c)] == ["not_suggested"] * 3 and not a["ok"]


def test_apply_path_that_vanished_or_is_not_verified(fake_decky, scripthub, tmp_path, monkeypatch):
    st, p, save = prepare(fake_decky, scripthub, tmp_path, monkeypatch)
    monkeypatch.setattr("main.verify_applied", lambda *a, **k: None)
    (out,) = run(p, lambda: p.apply_save_suggestion("steam", 730, str(save)))
    assert out["error"] == "path_missing"


def test_apply_forbidden_by_real_verification(fake_decky, scripthub, tmp_path, monkeypatch):
    """Sin simular `verified_dir`: una ruta del manifiesto dentro de una carpeta protegida (la del plugin) se rechaza."""
    st, p, save = prepare(fake_decky, scripthub, tmp_path, monkeypatch)
    prot = Path(fake_decky.DECKY_PLUGIN_SETTINGS_DIR)
    assert cg.verify_applied(str(prot), Path(os.environ["HOME"]), [prot]) is None
    assert cg.verify_applied(str(save), Path(os.environ["HOME"]), [prot]) == str(save)
    assert cg.verify_applied(str(save) + "/../juego730", Path(os.environ["HOME"]), [prot]) is None  # no normalizada
    assert cg.verify_applied("/etc", Path(os.environ["HOME"]), [prot]) is None


def test_apply_game_already_in_hub_or_not_installed(fake_decky, scripthub, tmp_path, monkeypatch):
    st, p, save = prepare(fake_decky, scripthub, tmp_path, monkeypatch, steam=220)  # 220 ya está en el hub
    (a, b) = run(p, lambda: p.apply_save_suggestion("steam", 220, str(save)), lambda: p.apply_save_suggestion("steam", 12345, str(save)))
    assert a["error"] == "not_unconfigured" and b["error"] == "no_match"


def test_apply_without_manifest_and_bad_args(fake_decky, scripthub, tmp_path, monkeypatch):
    st, hub, p = setup(fake_decky, scripthub, tmp_path, monkeypatch)
    (a, b) = run(p, lambda: p.apply_save_suggestion("steam", 730, "/x"), lambda: p.apply_save_suggestion("gog", 1, "/x"))
    assert a["error"] == "no_manifest" and b["error"] == "no_manifest"


def test_apply_lutris_goes_through_the_shortcut_of_that_row(fake_decky, scripthub, tmp_path, monkeypatch):
    st, p, save = prepare(fake_decky, scripthub, tmp_path, monkeypatch)
    seen = {}

    def fake_one(source, ident):
        seen["q"] = (source, ident)
        return {"ok": True, "game": {"id": 7, "name": "DQ7", "paths": [{"path": str(save), "exists": True}]}}

    async def go():
        await p._main()
        p.saves.one = fake_one
        p.jobs.snapshot = lambda: {"unconfigured": [{"appid": 3000000001, "name": "DQ7", "source": "shortcut"}, {"appid": 730, "name": "x"}]}
        monkeypatch.setattr("main.lutris_shortcut_appid", lambda home, row, apps: apps[0] if row == 7 and apps == [3000000001] else None)
        out = await p.apply_save_suggestion("lutris", "dq7", str(save))
        await p._unload()
        return out

    out = asyncio.run(go())
    assert out["ok"] and out["appid"] == 3000000001 and seen["q"] == ("lutris", "dq7")


def test_lutris_shortcut_appid_reads_launch_options(tmp_path):
    from test_shortcuts import entry, put, s, vdf

    home = tmp_path / "h"
    (home / ".local/share/Steam/steamapps").mkdir(parents=True)
    put(
        home,
        "1",
        vdf(
            entry(0, appid=3000000001, name="A", extra=s("LaunchOptions", "run net.lutris.Lutris lutris:rungameid/7")),
            entry(1, appid=3000000002, name="B", extra=s("LaunchOptions", "lutris:rungameid/8")),
        ),
    )
    ids = [3000000001, 3000000002]
    assert cg.lutris_shortcut_appid(home, 7, ids) == 3000000001
    assert cg.lutris_shortcut_appid(home, 8, ids) == 3000000002
    assert cg.lutris_shortcut_appid(home, 9, ids) is None
    assert cg.lutris_shortcut_appid(home, 7, [3000000002]) is None

