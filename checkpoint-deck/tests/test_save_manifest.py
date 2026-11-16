"""Generador del manifiesto propio de rutas de guardado (`scripts/gen_save_manifest.py`): herramienta de desarrollo."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
yaml = pytest.importorskip("yaml")  # PyYAML del backend; el plugin no lo necesita

import gen_save_manifest as gen  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "ludusavi-mini.yaml"


@pytest.fixture(scope="module")
def built():
    manifest = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    doc, stats = gen.build(manifest, "abc1234", gen.load_overrides(gen.DEFAULT_OVERRIDES))
    return doc, stats, {g["n"]: g for g in doc["games"]}


def paths(game, os_=None):
    return {(p["r"], p["p"], p["os"]) for p in game["paths"] if os_ in (None, p["os"])}


def test_stardew_aceptacion(built):
    g = built[2]["Stardew Valley"]
    assert g["steam"] == 413150 and g["lutris"] is None
    assert paths(g) == {("xdgConfig", "StardewValley/Saves", "linux"), ("pfxRoaming", "StardewValley/Saves", "win")}


def test_esquema(built):
    doc = built[0]
    assert doc["v"] == 1 and doc["src"] == "ludusavi-manifest@abc1234"
    for g in doc["games"]:
        assert set(g) - {"slug"} == {"n", "steam", "lutris", "paths"}
        assert g["steam"] or g["lutris"]
        assert ("slug" in g) == (g["lutris"] is None)
        for p in g["paths"]:
            assert set(p) - {"x"} == {"r", "p", "os"} and p["os"] in ("linux", "win")
            assert "x" not in p or (isinstance(p["x"], list) and p["x"])
    assert [g["n"].lower() for g in doc["games"]] == sorted(g["n"].lower() for g in doc["games"])
    text = gen.dump(doc)
    assert text.startswith('{"v":1,"src":"ludusavi-manifest@abc1234","games":[{"n":') and '", "' not in text
    assert json.loads(text) == doc


def test_solo_juegos_con_id_y_con_rutas(built):
    names = built[2]
    assert "No Id Game" not in names  # sin steam ni lutris
    assert "Registry Only" not in names  # solo registro
    assert names["Slug Game"]["lutris"] == "slug-game" and names["Slug Game"]["steam"] is None


def test_mapeo_de_raices(built):
    p = paths(built[2]["Roots Game"])
    assert ("pfxRoaming", "Pub/Roots/Saves", "win") in p
    assert ("pfxLocal", "Pub/Roots/Saves", "win") in p
    assert ("pfxLocalLow", "Pub/Roots/Saves", "win") in p
    assert ("pfxDocs", "My Games/Pub/Roots/Saves", "win") in p
    assert ("pfxSaved", "Pub/Roots/Saves", "win") in p
    assert ("pfxProgData", "Pub/Roots/Saves", "win") in p
    assert ("xdgData", "Pub/Roots/Saves", "linux") in p
    assert ("xdgData", "Pub/Roots/Saves2", "linux") in p  # <home>/.local/share
    assert ("xdgConfig", "Pub/Roots/Saves3", "linux") in p  # <home>/.config
    assert ("home", ".pub/Roots", "linux") in p
    assert ("install", "data/Saves", "win") in p
    assert ("steamCloud", "remote/slot1", "linux") in p


def test_otra_tienda_y_os(built):
    p = paths(built[2]["Other Store Game"])
    assert p == {("pfxRoaming", "Epic Co/Epic Game/Saves2", "win")}
    assert built[1]["descartes"]["otra_tienda"] == 1
    assert built[1]["descartes"]["otro_os"] >= 1  # Stardew mac


def test_derive_os_y_when():
    assert gen.derive_os("<xdgData>/a/b") == "linux"
    assert gen.derive_os("<home>/.config/a/b") == "linux"
    assert gen.derive_os("<winAppData>/a/b") == "win"
    assert gen.when_oses(None, "<base>/x") == ({"win"}, None)
    assert gen.when_oses([{"os": "windows"}, {"os": "linux"}], "<base>/x") == ({"win", "linux"}, None)
    assert gen.when_oses([{"os": "mac"}], "<base>/x") == (set(), "otro_os")
    assert gen.when_oses([{"store": "gog"}], "<base>/x") == (set(), "otra_tienda")
    assert gen.when_oses([{"store": "steam"}], "<xdgData>/x") == ({"linux"}, None)


@pytest.mark.parametrize(
    ("root", "rel", "game", "why"),
    [
        ("pfxRoaming", "Single", "Filter Game", "segmento_unico"),
        ("pfxRoaming", "Filter Game", "Filter Game", None),  # coincide con el nombre del juego
        ("pfxRoaming", "Solo/*.sav", "Filter Game", "segmento_unico"),
        ("home", ".solo", "Filter Game", "segmento_unico"),
        ("pfxRoaming", "Pub/Filter Game", "Filter Game", None),  # >=2 segmentos propios
        ("pfxRoaming", "Pub/Filter Game/cache", "Filter Game", "excluida"),
        ("pfxRoaming", "Pub/Filter Game/Shaders/x", "Filter Game", "excluida"),
        ("pfxRoaming", "Pub/Filter Game/Saves/crash.dump", "Filter Game", "excluida"),
        ("pfxRoaming", "Pub/Game/a.log", "Filter Game", "excluida"),
        ("pfxRoaming", "Other/Stuff/*.sav", "Filter Game", None),
        ("pfxRoaming", "Foo/Bar/Saves/a/b/c/d", "Filter Game", "demasiado_profundo"),
        ("pfxRoaming", "Foo/Bar/Saves/a/b/c", "Filter Game", None),
        ("pfxRoaming", "Foo/Bar/a/b/c/d/e", "Filter Game", "demasiado_profundo"),
        ("pfxRoaming", "Foo/Saves/profile.json", "Filter Game", None),
        ("pfxRoaming", "Foo/Config/profile.json", "Filter Game", None),  # 2 segmentos propios
        ("pfxDocs", "My Games/Saves", "Filter Game", "segmento_unico"),  # My Games no cuenta
        ("pfxDocs", "My Games/Pub/Saves", "Filter Game", None),
        ("install", "", "G", "base_sola"),
        ("install", "*", "G", "base_comodin"),
        ("install", "*.dat", "G", None),
        ("install", "slot", "G", "fuera_de_lista_blanca"),
        ("install", "slot1.sav", "G", None),
        ("install", "Saves", "G", None),
        ("install", "Mods/Saves", "G", "excluida"),
        ("install", "Binaries/Win64/x.sav", "G", "excluida"),
        ("steamCloud", "remote", "G", None),
    ],
)
def test_reglas_de_filtro(root, rel, game, why):
    assert gen.filter_path(root, rel, game) == why


@pytest.mark.parametrize(
    ("path", "os_", "expected"),
    [
        ("<winAppData>/a/b", "win", ("pfxRoaming", "a/b")),
        ("<winLocalAppData>/../LocalLow/a/b", "win", ("pfxLocalLow", "a/b")),
        ("<home>/appdata/locallow/a/b", "win", ("pfxLocalLow", "a/b")),  # sin distinguir mayúsculas
        ("<home>/Documents/a", "win", ("pfxDocs", "a")),
        ("<home>/Otro/a", "win", (None, "raiz_no_mapeable")),
        ("<winPublic>/a", "win", (None, "raiz_no_mapeable")),
        ("<xdgData>/a", "win", (None, "raiz_incoherente")),
        ("<winAppData>/a", "linux", (None, "raiz_incoherente")),
        ("<home>/x/y", "linux", ("home", "x/y")),
        ("<root>/userdata/<storeUserId>/5", "win", (None, "steamcloud_sin_subruta")),
        ("<root>/userdata/<storeUserId>/5/remote/a", "win", ("steamCloud", "remote/a")),
        ("<root>/steamapps/common/x", "win", (None, "raiz_no_mapeable")),
    ],
)
def test_map_root(path, os_, expected):
    assert gen.map_root(path, os_) == expected


def test_reglas_sobre_el_manifiesto(built):
    p = paths(built[2]["Filter Game"])
    assert ("pfxRoaming", "Filter Game", "win") in p
    assert not any(x[1] == "Single" for x in p)
    assert not any(x[0] == "steamCloud" and x[1] == "" for x in p)
    assert ("install", "Saves", "win") in p
    assert not any(x[1] == "Pub/Reg/Saves" for x in p)  # sin tag save


def test_dedupe(built):
    saves = [x for x in built[0]["games"] if x["n"] == "Filter Game"][0]["paths"]
    assert sum(1 for x in saves if x["p"] == "Pub/Dupe/Saves") == 1
    assert built[1]["descartes"]["duplicada"] >= 1


def test_overrides(built):
    rim = built[2]["RimWorld"]
    assert ("xdgConfig", "unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Saves", "linux") in paths(rim)
    assert not any(p["p"] == "unity3d/Wrong/Path" for p in rim["paths"])  # el linux generado se sustituye
    assert ("pfxLocal", "Ludeon/RimWorld/Saves", "win") in paths(rim)  # el win se conserva
    assert any("Dave the Diver" in n and "SData/SteamSData" in n for n in built[1]["notas"])
    assert "Dave the Diver" in built[2]  # su ruta generada se conserva


def test_override_add_y_sin_coincidencia():
    manifest = {"G": {"steam": {"id": 1}, "files": {}}}
    ov = [{"steam": 1, "add": [{"r": "home", "p": "x/y", "os": "linux"}]}, {"steam": 2, "add": []}]
    doc, _ = gen.build(manifest, "c", ov)
    assert doc["games"] == [
        {"n": "G", "steam": 1, "lutris": None, "slug": "g", "paths": [{"r": "home", "p": "x/y", "os": "linux"}]}
    ]


def test_informe_y_cli(tmp_path, capsys):
    out = tmp_path / "saves.json"
    assert gen.main([str(FIXTURE), str(out), "--commit", "abc1234"]) == 0
    text = capsys.readouterr().out
    for frag in ("juegos en el manifiesto", "descartes por regla", "tamaño del JSON", "segmento_unico", "nota: Dave"):
        assert frag in text
    assert json.loads(out.read_text(encoding="utf-8"))["src"] == "ludusavi-manifest@abc1234"


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Dragon Quest VII Reimagined", "dragon-quest-vii-reimagined"),
        ("Dragon Quest VII: Reimagined", "dragon-quest-vii-reimagined"),
        ('Ünïcode: Game\'s "Edition"!', "unicode-games-edition"),
        ("  --Half-Life 2--  ", "half-life-2"),
        ("日本語", ""),
    ],
)
def test_lutris_slug(name, slug):
    assert gen.lutris_slug(name) == slug


def test_slug_solo_si_lutris_es_null(built):
    names = built[2]
    assert names["Dragon Quest Mini"]["slug"] == "dragon-quest-mini" and names["Dragon Quest Mini"]["lutris"] is None
    assert names['Ünïcode: Game\'s "Edition"!']["slug"] == "unicode-games-edition"
    assert "slug" not in names["Slug Game"]  # tiene lutris: no hace falta el casado secundario
    doc, _ = gen.build({"日本語": {"steam": {"id": 5}, "files": {"<xdgData>/Pub/Jp/Saves": {"tags": ["save"]}}}}, "c")
    assert "slug" not in doc["games"][0]  # slug vacío: se omite


def test_x_en_carpeta_ancha_con_config(built):
    magicka = built[2]["Magicka Mini"]["paths"]
    win = next(p for p in magicka if p["os"] == "win")
    assert win["p"] == "ParadoxInteractive/Magicka2"
    assert win["x"] == ["logs", "*.log", "cache", "crash*", "*.config"]
    lin = next(p for p in magicka if p["p"] == ".bitsquid/Magicka2/*.sav")  # glob: su carpeta padre es la sugerida
    assert lin["x"] == win["x"]


def test_x_ausente_en_lista_blanca_y_steamcloud(built):
    assert "x" not in next(p for p in built[2]["Stardew Valley"]["paths"] if p["os"] == "win")  # .../Saves
    assert all("x" not in p for p in built[2]["Roots Game"]["paths"] if p["r"] in ("steamCloud", "pfxRoaming"))
    sin_config = next(p for p in built[2]["Roots Game"]["paths"] if p["r"] == "home")
    assert sin_config["x"] == ["logs", "*.log", "cache", "crash*"]  # sin ficheros config: sin `*.config`


def test_exclusions_directo():
    assert gen.exclusions("home", ["a", "b"], set()) == ["logs", "*.log", "cache", "crash*"]
    assert gen.exclusions("home", ["a", "Saves"], {"*.ini"}) == []
    assert gen.exclusions("home", ["a", "SaveGames", "*.sav"], set()) == []  # carpeta padre en lista blanca
    assert gen.exclusions("home", ["a", "b", "*.sav"], {"*.cfg"}) == [*gen.X_BASE, "*.cfg"]
    assert gen.exclusions("steamCloud", ["remote"], set()) == []
    assert gen.exclusions("home", ["a", "b", "*"], set()) == list(gen.X_BASE)  # `*` final: ya es la carpeta


def test_glob_de_fichero_emite_tambien_la_carpeta(built):
    p = paths(built[2]["Dragon Quest Mini"])
    base = "My Games/DQ Mini/Steam/*/release/Saved/SaveGames"
    assert ("pfxDocs", base + "/GameSaveData*.sav", "win") in p
    assert ("pfxDocs", base, "win") in p
    assert len(p) == 2  # el config Lang998.sav no sale


def test_glob_sin_carpeta_de_lista_blanca_no_emite_carpeta(built):
    p = paths(built[2]["Filter Game"])
    assert ("pfxRoaming", "Other/Stuff/*.sav", "win") in p
    assert ("pfxRoaming", "Other/Stuff", "win") not in p
    assert ("pfxLocal", "Ludeon/RimWorld", "win") not in paths(built[2]["RimWorld"])


def test_glob_de_fichero_en_carpeta_whitelist_simple():
    m = {"G": {"steam": {"id": 1}, "files": {"<xdgData>/Pub/G/saves/*.sav": {"tags": ["save"]}}}}
    doc, _ = gen.build(m, "c")
    assert [(p["p"], "x" in p) for p in doc["games"][0]["paths"]] == [
        ("Pub/G/saves/*.sav", False),
        ("Pub/G/saves", False),
    ]
