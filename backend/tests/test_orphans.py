"""Datos sin dispositivo ni juego en la config («huérfanos»): detección, papelera con caducidad, restauración y API.
Todo en tmp_path con datos sintéticos; ningún test toca el `data/` real."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.auth import Auth
from app.config.models import parse_config
from app.core import settings
from app.main import create_app
from app.services import orphans
from app.sync import locking, trash

sin_symlinks = pytest.mark.skipif(
    sys.platform == "win32", reason="crear symlinks en Windows exige privilegios (WinError 1314)"
)

CFG = parse_config(
    {
        "devices": {
            "pc": {"name": "PC", "host": "h1", "user": "u", "os": "linux"},
            "lap": {"name": "Portátil", "host": "h2", "user": "u", "os": "linux"},
        },
        "games": {"g": {"name": "Juego", "devices": ["pc"], "paths": {"pc": "/p"}}},
    }
)
V1, V2 = "2026-01-01_100000", "2026-02-03_040506"


def mk(data, rel, content="x"):
    p = data / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def seed_origins(data):
    for v, srcs in ((V1, ("pc", "hub", "gone", "lap")), (V2, ("gone", "Steam Deck", "pc"))):
        for s in srcs:
            mk(data, f"versions/g/{v}/{s}/s.sav", "abcd")


def seed_game(data, name="old-1a2b3c4d", hub=True):
    if hub:
        mk(data, f"hub/{name}/s.sav", "12345")
    mk(data, f"versions/{name}/{V1}/hub/s.sav", "123")
    mk(data, f"versions/{name}/{V2}/pc/s.sav", "1")
    mk(data, f"state/{name}.json", "{}")
    mk(data, f"status/{name}.json", "{}")
    mk(data, f"logs/{name}/2026-01-01_100000.log", "log")
    mk(data, f"resolutions/{name}.json", "{}")
    mk(data, f"staging/{name}/dev/f", "z")
    mk(data, f"locks/{name}.lock", "")


def by_id(items):
    return {i["id"]: i for i in items}


# ---------- detección ----------
def test_origenes_desconocidos_de_un_juego_vivo(tmp_path):
    seed_origins(tmp_path)
    items = orphans.scan(CFG, tmp_path)
    ids = by_id(items)
    assert set(ids) == {"origin:g:gone", "origin:g:Steam Deck"}  # pc, lap (en cfg.devices) y hub no son huérfanos
    g = ids["origin:g:gone"]
    assert (g["kind"], g["game"], g["source"]) == ("origin", "g", "gone")
    assert (g["versions"], g["files"], g["size"]) == (2, 2, 8)
    assert (g["oldest"], g["newest"]) == ("2026-01-01 10:00:00", "2026-02-03 04:05:06")
    assert g["only_copy"] is False and len(g["token"]) >= 16
    assert ids["origin:g:Steam Deck"]["versions"] == 1


def test_juego_fuera_de_la_config(tmp_path):
    seed_game(tmp_path)
    (item,) = orphans.scan(CFG, tmp_path)
    assert (item["id"], item["kind"], item["game"], item["source"]) == (
        "game:old-1a2b3c4d",
        "game",
        "old-1a2b3c4d",
        None,
    )
    assert item["only_copy"] is True  # el hub es la única copia
    assert item["versions"] == 2 and item["size"] >= 5 + 3 + 1 + 4  # los locks no cuentan
    assert (item["oldest"], item["newest"]) == ("2026-01-01 10:00:00", "2026-02-03 04:05:06")


def test_juego_sin_datos_en_hub_no_es_unica_copia(tmp_path):
    seed_game(tmp_path, hub=False)
    (tmp_path / "hub" / "old-1a2b3c4d").mkdir(parents=True)  # hub vacío
    (item,) = orphans.scan(CFG, tmp_path)
    assert item["only_copy"] is False


def test_juego_solo_con_logs_y_sin_versiones_usa_mtime(tmp_path):
    p = mk(tmp_path, "logs/solo-logs/a.log", "l")
    os.utime(p, (1_700_000_000, 1_700_000_000))
    (item,) = orphans.scan(CFG, tmp_path)
    assert item["versions"] == 0 and item["oldest"] == item["newest"] != "-"


def test_lo_vigente_nunca_aparece(tmp_path):
    mk(tmp_path, "hub/g/s.sav")
    mk(tmp_path, f"versions/g/{V1}/pc/s.sav")
    mk(tmp_path, "state/g.json", "{}")
    mk(tmp_path, "locks/g.lock", "")
    mk(tmp_path, "state/_steam/dismissed.json", "[]")  # carpeta interna, no es un juego
    mk(tmp_path, "versions/.oculto/x", "x")
    mk(tmp_path, "trash/x/manifest.json", "{}")
    assert orphans.scan(CFG, tmp_path) == []
    assert orphans.scan(CFG, tmp_path / "no-existe") == []


@sin_symlinks
def test_enlaces_simbolicos_se_ignoran(tmp_path):
    out = tmp_path / "fuera"
    mk(out, "s.sav", "secreto")
    (tmp_path / "hub").mkdir()
    (tmp_path / "hub" / "lnk-game").symlink_to(out, target_is_directory=True)
    (tmp_path / f"versions/g/{V1}").mkdir(parents=True)
    (tmp_path / f"versions/g/{V1}/lnk").symlink_to(out, target_is_directory=True)
    assert orphans.scan(CFG, tmp_path) == []


def test_token_cambia_si_cambia_el_contenido(tmp_path):
    seed_origins(tmp_path)
    t1 = by_id(orphans.scan(CFG, tmp_path))["origin:g:gone"]["token"]
    assert by_id(orphans.scan(CFG, tmp_path))["origin:g:gone"]["token"] == t1
    mk(tmp_path, f"versions/g/{V2}/gone/otro.sav", "nuevo")
    assert by_id(orphans.scan(CFG, tmp_path))["origin:g:gone"]["token"] != t1


# ---------- papelera ----------
def req(items, ids):
    m = by_id(items)
    return [{"id": i, "token": m[i]["token"]} for i in ids]


def run(data, ids, cfg=CFG):
    return orphans.move_to_trash(lambda: cfg, data, req(orphans.scan(cfg, data), ids))


def test_mover_origen_a_la_papelera(tmp_path):
    seed_origins(tmp_path)
    out = run(tmp_path, ["origin:g:gone"])
    assert [m["id"] for m in out["moved"]] == ["origin:g:gone"] and out["skipped"] == []
    assert not (tmp_path / "versions/g" / V1 / "gone").exists() and not (tmp_path / "versions/g" / V2 / "gone").exists()
    assert (tmp_path / "versions/g" / V1 / "pc/s.sav").exists()  # lo vigente intacto
    (entry,) = [p for p in (tmp_path / "trash").iterdir()]
    assert (entry / "origin/g/versions" / V1 / "gone/s.sav").read_text(encoding="utf-8") == "abcd"
    man = json.loads((entry / "manifest.json").read_text(encoding="utf-8"))
    assert (
        man["items"][0]["kind"] == "origin" and man["items"][0]["game"] == "g" and man["items"][0]["source"] == "gone"
    )
    assert man["items"][0]["size"] == 8 and man["created"]
    assert str(tmp_path) not in json.dumps(man)  # sin rutas completas
    assert [v["version"] for v in __import__("app.sync.versions", fromlist=["x"]).list_versions(tmp_path, "g")] == [
        V2,
        V1,
    ]


def test_origen_deja_sin_version_vacia(tmp_path):
    mk(tmp_path, f"versions/g/{V1}/gone/s.sav")
    run(tmp_path, ["origin:g:gone"])
    assert not (tmp_path / "versions/g" / V1).exists()  # no queda una versión vacía que cuente para el límite


def test_mover_juego_a_la_papelera(tmp_path):
    seed_game(tmp_path)
    mk(tmp_path, "hub/g/s.sav")  # un juego vigente que no se debe tocar
    out = run(tmp_path, ["game:old-1a2b3c4d"])
    assert len(out["moved"]) == 1
    for rel in ("hub", "versions", "state", "status", "logs", "staging", "resolutions", "locks"):
        assert not any(p.name.startswith("old-1a2b3c4d") for p in (tmp_path / rel).iterdir()), rel
    assert (tmp_path / "hub/g/s.sav").exists()
    (entry,) = list((tmp_path / "trash").iterdir())
    assert (entry / "game/old-1a2b3c4d/hub/s.sav").read_text(encoding="utf-8") == "12345"
    assert (entry / "game/old-1a2b3c4d/state.json").exists()
    assert orphans.scan(CFG, tmp_path) == []


def test_token_distinto_no_mueve_nada(tmp_path):
    seed_origins(tmp_path)
    out = orphans.move_to_trash(lambda: CFG, tmp_path, [{"id": "origin:g:gone", "token": "mal"}])
    assert out["moved"] == [] and out["skipped"][0]["code"] == "err.orphans.changed"
    assert (tmp_path / "versions/g" / V1 / "gone").exists() and not (tmp_path / "trash").exists()


def test_cambio_entre_listado_y_borrado_no_mueve(tmp_path):
    seed_origins(tmp_path)
    r = req(orphans.scan(CFG, tmp_path), ["origin:g:gone"])
    mk(tmp_path, f"versions/g/{V1}/gone/nuevo.sav", "n")  # el usuario no vio este fichero
    out = orphans.move_to_trash(lambda: CFG, tmp_path, r)
    assert (
        out["skipped"][0]["code"] == "err.orphans.changed"
        and (tmp_path / "versions/g" / V1 / "gone/nuevo.sav").exists()
    )


@pytest.mark.parametrize(
    "bad",
    [
        "origin:g:pc",
        "origin:g:lap",
        "origin:g:hub",
        "game:g",
        "origin:g:../x",
        "origin:g:",
        "game:../g",
        "x:y",
        "origin:nope:gone",
        "",
    ],
)
def test_nunca_mueve_lo_vigente_ni_ids_inventados(tmp_path, bad):
    seed_origins(tmp_path)
    mk(tmp_path, "hub/g/s.sav")
    mk(tmp_path, "hub/otro/f", "1")
    out = orphans.move_to_trash(lambda: CFG, tmp_path, [{"id": bad, "token": "t"}])
    assert out["moved"] == [] and out["skipped"][0]["code"] == "err.orphans.unknown"
    assert (tmp_path / "hub/g/s.sav").exists() and (tmp_path / f"versions/g/{V1}/pc/s.sav").exists()
    assert not (tmp_path / "trash").exists()


def test_revalida_con_la_config_actual_al_mover(tmp_path):
    """Si entre el listado y el movimiento el juego vuelve a la config, no se mueve."""
    seed_game(tmp_path)
    r = req(orphans.scan(CFG, tmp_path), ["game:old-1a2b3c4d"])
    cfg2 = parse_config(
        {
            "devices": {"pc": {"name": "PC", "host": "h1", "user": "u", "os": "linux"}},
            "games": {"old-1a2b3c4d": {"name": "Viejo", "devices": ["pc"], "paths": {"pc": "/p"}}},
        }
    )
    out = orphans.move_to_trash(lambda: cfg2, tmp_path, r)
    assert out["moved"] == [] and out["skipped"][0]["code"] == "err.orphans.unknown"
    assert (tmp_path / "hub/old-1a2b3c4d/s.sav").exists()


def test_juego_con_sync_en_curso_se_salta(tmp_path):
    seed_origins(tmp_path)
    r = req(orphans.scan(CFG, tmp_path), ["origin:g:gone"])
    h = locking.acquire(tmp_path / "locks" / "g.lock")
    try:
        out = orphans.move_to_trash(lambda: CFG, tmp_path, r)
    finally:
        h.release()
    assert out["skipped"][0]["code"] == "err.orphans.busy"
    assert (tmp_path / "versions/g" / V1 / "gone").exists()


@sin_symlinks
def test_enlace_simbolico_de_una_parte_no_se_sigue(tmp_path):
    out_dir = tmp_path / "fuera"
    mk(out_dir, "s.sav", "secreto")
    mk(tmp_path, "state/old.json", "{}")
    (tmp_path / "hub").mkdir()
    (tmp_path / "hub" / "old").symlink_to(out_dir, target_is_directory=True)
    run(tmp_path, ["game:old"])
    assert (out_dir / "s.sav").read_text(encoding="utf-8") == "secreto"  # el destino del enlace no se toca
    assert (tmp_path / "hub" / "old").is_symlink()  # y el enlace no se mueve


def test_fallo_al_mover_se_notifica_y_sigue(tmp_path, monkeypatch):
    seed_origins(tmp_path)
    r = req(orphans.scan(CFG, tmp_path), ["origin:g:gone", "origin:g:Steam Deck"])
    real = trash.shutil.move
    calls = []

    def boom(src, dst):
        calls.append(src)
        if "gone" in str(src):
            raise OSError("disco")
        return real(src, dst)

    monkeypatch.setattr(trash.shutil, "move", boom)
    out = orphans.move_to_trash(lambda: CFG, tmp_path, r)
    assert [s["code"] for s in out["skipped"]] == ["err.orphans.move_failed"]
    assert [m["id"] for m in out["moved"]] == ["origin:g:Steam Deck"]


def test_stamp_unico_en_el_mismo_segundo(tmp_path):
    a = trash.new_entry(tmp_path)
    b = trash.new_entry(tmp_path)
    assert a != b and a.parent == b.parent == tmp_path / "trash"


# ---------- caducidad ----------
def entry(data, name, created=None, items=None):
    d = data / "trash" / name
    d.mkdir(parents=True)
    if created is not None:
        (d / "manifest.json").write_text(json.dumps({"created": created, "items": items or []}), encoding="utf-8")
    return d


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def test_purga_solo_lo_caducado(tmp_path):
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    old = entry(tmp_path, "2026-04-01_000000", iso(now - timedelta(days=31)))
    new = entry(tmp_path, "2026-05-20_000000", iso(now - timedelta(days=29)))
    border = entry(tmp_path, "2026-05-02_000000", iso(now - timedelta(days=30)))
    (old / "x").mkdir()
    (old / "x" / "f").write_text("1", encoding="utf-8")
    other = tmp_path / "trash" / "no-es-entrada"
    other.mkdir()
    assert trash.purge_expired(tmp_path, 30, now) == 1
    assert not old.exists() and new.exists() and border.exists() and other.exists()


def test_purga_sin_manifiesto_usa_el_mtime(tmp_path):
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    e = entry(tmp_path, "2026-01-01_000000")
    t = (now - timedelta(days=40)).timestamp()
    os.utime(e, (t, t))
    assert trash.purge_expired(tmp_path, 30, now) == 1 and not e.exists()
    e2 = entry(tmp_path, "2026-01-02_000000")
    assert trash.purge_expired(tmp_path, 30, datetime.now(timezone.utc)) == 0 and e2.exists()


def test_purga_manifiesto_ilegible_usa_el_mtime(tmp_path):
    e = entry(tmp_path, "2026-01-01_000000")
    (e / "manifest.json").write_text("{no", encoding="utf-8")
    t = (datetime.now(timezone.utc) - timedelta(days=60)).timestamp()
    os.utime(e, (t, t))
    assert trash.purge_expired(tmp_path, 30) == 1


@sin_symlinks
def test_purga_sin_papelera_o_enlace(tmp_path):
    assert trash.purge_expired(tmp_path, 30) == 0
    out = tmp_path / "fuera"
    mk(out, "f", "1")
    (tmp_path / "trash").mkdir()
    (tmp_path / "trash" / "2020-01-01_000000").symlink_to(out, target_is_directory=True)
    assert trash.purge_expired(tmp_path, 30) == 0 and (out / "f").exists()


def test_ttl_por_defecto_y_variable(monkeypatch):
    assert settings.TRASH_TTL_DAYS == 30


# ---------- listado y restauración ----------
def test_listar_la_papelera(tmp_path):
    seed_origins(tmp_path)
    run(tmp_path, ["origin:g:gone"])
    (e,) = orphans.list_trash(tmp_path, 30)
    assert e["items"][0]["game"] == "g" and e["items"][0]["source"] == "gone" and e["expires"] > e["created"]


def test_restaurar_origen(tmp_path):
    seed_origins(tmp_path)
    run(tmp_path, ["origin:g:gone"])
    (e,) = orphans.list_trash(tmp_path, 30)
    orphans.restore_from_trash(tmp_path, e["entry"], 0)
    assert (tmp_path / "versions/g" / V1 / "gone/s.sav").read_text(encoding="utf-8") == "abcd"
    assert (tmp_path / "versions/g" / V2 / "gone/s.sav").exists()
    assert orphans.list_trash(tmp_path, 30) == [] and not (tmp_path / "trash" / e["entry"]).exists()


def test_restaurar_juego(tmp_path):
    seed_game(tmp_path)
    run(tmp_path, ["game:old-1a2b3c4d"])
    (e,) = orphans.list_trash(tmp_path, 30)
    orphans.restore_from_trash(tmp_path, e["entry"], 0)
    assert (tmp_path / "hub/old-1a2b3c4d/s.sav").read_text(encoding="utf-8") == "12345"
    assert (tmp_path / "state/old-1a2b3c4d.json").exists() and (tmp_path / "logs/old-1a2b3c4d").is_dir()


def test_restaurar_con_destino_ocupado_falla_sin_pisar(tmp_path):
    seed_origins(tmp_path)
    run(tmp_path, ["origin:g:gone"])
    mk(tmp_path, f"versions/g/{V1}/gone/s.sav", "otro")  # ya hay algo ahí
    (e,) = orphans.list_trash(tmp_path, 30)
    with pytest.raises(orphans.TrashError) as ex:
        orphans.restore_from_trash(tmp_path, e["entry"], 0)
    assert ex.value.code == "err.orphans.restore_conflict"
    assert (tmp_path / f"versions/g/{V1}/gone/s.sav").read_text(encoding="utf-8") == "otro"
    assert (tmp_path / "trash" / e["entry"]).exists()  # lo de la papelera sigue ahí


@pytest.mark.parametrize(
    "entry_name,idx", [("../x", 0), ("nope", 0), ("2026-01-01_000000", 0), ("2026-01-01_000000", 5)]
)
def test_restaurar_entrada_desconocida(tmp_path, entry_name, idx):
    entry(tmp_path, "2026-01-01_000000", iso(datetime.now(timezone.utc)), [])
    with pytest.raises(orphans.TrashError) as ex:
        orphans.restore_from_trash(tmp_path, entry_name, idx)
    assert ex.value.code == "err.orphans.trash_unknown"


def test_manifiesto_manipulado_no_restaura_fuera_de_data(tmp_path):
    seed_origins(tmp_path)
    run(tmp_path, ["origin:g:gone"])
    (e,) = orphans.list_trash(tmp_path, 30)
    mp = tmp_path / "trash" / e["entry"] / "manifest.json"
    man = json.loads(mp.read_text(encoding="utf-8"))
    man["items"][0]["moves"][0]["from"] = "../../etc/x"
    mp.write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(orphans.TrashError) as ex:
        orphans.restore_from_trash(tmp_path, e["entry"], 0)
    assert ex.value.code == "err.orphans.trash_unknown"


def test_restaurar_con_juego_ocupado(tmp_path):
    seed_origins(tmp_path)
    run(tmp_path, ["origin:g:gone"])
    (e,) = orphans.list_trash(tmp_path, 30)
    h = locking.acquire(tmp_path / "locks" / "g.lock")
    try:
        with pytest.raises(orphans.TrashError) as ex:
            orphans.restore_from_trash(tmp_path, e["entry"], 0)
    finally:
        h.release()
    assert ex.value.code == "err.orphans.busy"


# ---------- API ----------
@pytest.fixture
def cl(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "devices": {"pc": {"name": "PC", "host": "h1", "user": "u", "os": "linux"}},
                "games": {"g": {"name": "Juego", "devices": ["pc"], "paths": {"pc": "/p"}}},
            }
        ),
        encoding="utf-8",
    )
    c = TestClient(create_app(Auth("admin", "pw-test-1234", 1, rounds=4)))
    c.data = tmp_path / "data"
    return c


def login(c):
    assert c.post("/api/login", json={"user": "admin", "password": "pw-test-1234"}).status_code == 200


def test_api_exige_sesion(cl):
    for m, p in [
        ("get", "/api/orphans"),
        ("post", "/api/orphans/trash"),
        ("get", "/api/orphans/trash"),
        ("post", "/api/orphans/trash/restore"),
    ]:
        assert getattr(cl, m)(p).status_code == 401, p


def test_api_flujo_completo(cl):
    login(cl)
    seed_origins(cl.data)
    seed_game(cl.data)
    r = cl.get("/api/orphans")
    assert r.status_code == 200
    body = r.json()
    assert body["ttl_days"] == 30
    ids = {i["id"] for i in body["items"]}
    assert ids == {
        "origin:g:gone",
        "origin:g:Steam Deck",
        "origin:g:lap",
        "game:old-1a2b3c4d",
    }  # aquí «lap» no está en la config
    pick = [
        {"id": i["id"], "token": i["token"]} for i in body["items"] if i["id"] in ("origin:g:gone", "game:old-1a2b3c4d")
    ]
    r = cl.post("/api/orphans/trash", json={"items": pick})
    assert r.status_code == 200, r.text
    assert len(r.json()["moved"]) == 2 and r.json()["skipped"] == []
    assert {i["id"] for i in cl.get("/api/orphans").json()["items"]} == {"origin:g:Steam Deck", "origin:g:lap"}
    t = cl.get("/api/orphans/trash").json()
    assert len(t) == 1 and len(t[0]["items"]) == 2
    entry = t[0]["entry"]
    idx = next(i["index"] for i in t[0]["items"] if i["kind"] == "game")
    r = cl.post("/api/orphans/trash/restore", json={"entry": entry, "item": idx})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert (cl.data / "hub/old-1a2b3c4d/s.sav").exists()
    assert "game:old-1a2b3c4d" in {i["id"] for i in cl.get("/api/orphans").json()["items"]}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"items": "x"},
        {"items": []},
        {"items": [1]},
        {"items": [{"id": "a"}]},
        {"items": [{"id": 1, "token": "t"}]},
        {"items": [{"id": "a", "token": "t"}] * 201},
    ],
)
def test_api_cuerpo_invalido(cl, body):
    login(cl)
    r = cl.post("/api/orphans/trash", json=body)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "err.orphans.body_invalid"


def test_api_confirmacion_ligada_al_listado(cl):
    login(cl)
    seed_origins(cl.data)
    r = cl.post("/api/orphans/trash", json={"items": [{"id": "origin:g:gone", "token": "inventado"}]})
    assert r.status_code == 200 and r.json()["moved"] == []
    assert r.json()["skipped"] == [{"id": "origin:g:gone", "code": "err.orphans.changed", "params": {}}]
    assert (cl.data / "versions/g" / V1 / "gone").exists()


def test_api_restaurar_cuerpo_invalido_y_desconocido(cl):
    login(cl)
    for body in (
        {},
        {"entry": 1, "item": 0},
        {"entry": "2026-01-01_000000", "item": "x"},
        {"entry": "2026-01-01_000000", "item": -1},
    ):
        r = cl.post("/api/orphans/trash/restore", json=body)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "err.orphans.body_invalid", body
    r = cl.post("/api/orphans/trash/restore", json={"entry": "2026-01-01_000000", "item": 0})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "err.orphans.trash_unknown"


def test_api_restaurar_con_conflicto_es_409(cl):
    login(cl)
    seed_origins(cl.data)
    items = cl.get("/api/orphans").json()["items"]
    pick = [{"id": i["id"], "token": i["token"]} for i in items if i["id"] == "origin:g:gone"]
    cl.post("/api/orphans/trash", json={"items": pick})
    mk(cl.data, f"versions/g/{V1}/gone/s.sav", "otro")
    t = cl.get("/api/orphans/trash").json()[0]
    r = cl.post("/api/orphans/trash/restore", json={"entry": t["entry"], "item": 0})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "err.orphans.restore_conflict"


def test_mantenimiento_vacia_la_papelera_caducada(cl):
    old = entry(cl.data, "2020-01-01_000000", "2020-01-01T00:00:00Z")
    cl.app.state.ctx.purge_trash()
    assert not old.exists()


# ---------- reubicar un juego huérfano en un juego existente ----------
CFG_T = parse_config(
    {
        "devices": {"pc": {"name": "PC", "host": "h1", "user": "u", "os": "linux"}},
        "games": {
            "g": {"name": "Juego", "devices": ["pc"], "paths": {"pc": "/p"}},
            "tgt": {"name": "Destino", "devices": ["pc"], "paths": {"pc": "/p2"}},
        },
    }
)
OLD = "old-1a2b3c4d"


def orphan(data, cfg=CFG_T):
    return by_id(orphans.scan(cfg, data))[f"game:{OLD}"]


def reloc(data, target="tgt", cfg=CFG_T, item=None, token=None):
    it = item or orphan(data, cfg)
    return orphans.relocate(lambda: cfg, data, it["id"], token or it["token"], target)


def seed_target(data):
    mk(data, "hub/tgt/keep.sav", "actual")
    mk(data, f"versions/tgt/{V1}/pc/t.sav", "propia")
    mk(data, "locks/tgt.lock", "")


def test_reubicar_suma_versiones_sin_tocar_el_hub_del_destino(tmp_path):
    seed_game(tmp_path)
    seed_target(tmp_path)
    out = reloc(tmp_path)
    assert out["ok"] and out["versions"] == 2 and out["hub"] is True and out["target"] == "tgt"
    assert (tmp_path / "hub/tgt/keep.sav").read_text(encoding="utf-8") == "actual"  # el hub del destino, intacto
    assert (tmp_path / f"versions/tgt/{V1}/pc/t.sav").read_text(
        encoding="utf-8"
    ) == "propia"  # la versión del destino, intacta
    assert (tmp_path / f"versions/tgt/{V1}-1/hub/s.sav").read_text(
        encoding="utf-8"
    ) == "123"  # V1 chocaba: llega con sufijo
    assert (tmp_path / f"versions/tgt/{V2}/pc/s.sav").read_text(encoding="utf-8") == "1"  # V2 no chocaba: igual
    hubs = [d for d in (tmp_path / "versions/tgt").iterdir() if (d / "hub/s.sav").exists() and d.name != f"{V1}-1"]
    assert (
        len(hubs) == 1 and (hubs[0] / "hub/s.sav").read_text(encoding="utf-8") == "12345"
    )  # el hub actual del huérfano, como versión
    assert not (tmp_path / f"hub/{OLD}").exists() and not (tmp_path / f"versions/{OLD}").exists()


def test_reubicar_el_resto_va_a_la_papelera_y_se_restaura(tmp_path):
    seed_game(tmp_path)
    seed_target(tmp_path)
    reloc(tmp_path)
    assert orphans.scan(CFG_T, tmp_path) == []
    for rel in (f"state/{OLD}.json", f"status/{OLD}.json", f"resolutions/{OLD}.json", f"staging/{OLD}", f"logs/{OLD}"):
        assert not (tmp_path / rel).exists()
    assert not (tmp_path / f"locks/{OLD}.lock").exists()
    (t,) = orphans.list_trash(tmp_path, 30)
    assert t["items"][0]["game"] == OLD
    orphans.restore_from_trash(tmp_path, t["entry"], t["items"][0]["index"])
    assert (tmp_path / f"state/{OLD}.json").exists() and (tmp_path / f"staging/{OLD}/dev/f").exists()


def test_reubicar_sin_colision_conserva_los_nombres(tmp_path):
    seed_game(tmp_path, hub=False)
    mk(tmp_path, "hub/tgt/keep.sav")
    out = reloc(tmp_path)
    assert out["hub"] is False
    assert sorted(p.name for p in (tmp_path / "versions/tgt").iterdir()) == [V1, V2]


def test_reubicar_con_varias_colisiones_no_pisa_nada(tmp_path):
    seed_game(tmp_path)
    mk(tmp_path, f"versions/tgt/{V1}/pc/a", "a")
    mk(tmp_path, f"versions/tgt/{V1}-1/pc/b", "b")
    reloc(tmp_path)
    assert (tmp_path / f"versions/tgt/{V1}/pc/a").read_text(encoding="utf-8") == "a"
    assert (tmp_path / f"versions/tgt/{V1}-1/pc/b").read_text(encoding="utf-8") == "b"
    assert (tmp_path / f"versions/tgt/{V1}-2/hub/s.sav").read_text(encoding="utf-8") == "123"


@pytest.mark.parametrize("target", ["nope", "", "../g", "a/b", "..", ".hid", "old-1a2b3c4d", None, 3])
def test_reubicar_destino_invalido(tmp_path, target):
    seed_game(tmp_path)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    with pytest.raises(orphans.TrashError) as ex:
        reloc(tmp_path, target=target)
    assert ex.value.code == "err.orphans.target_unknown"
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before


def test_reubicar_token_obsoleto(tmp_path):
    seed_game(tmp_path)
    it = orphan(tmp_path)
    mk(tmp_path, f"versions/{OLD}/{V1}/hub/extra", "más")
    with pytest.raises(orphans.TrashError) as ex:
        reloc(tmp_path, item=it)
    assert ex.value.code == "err.orphans.changed"
    assert (tmp_path / f"hub/{OLD}/s.sav").exists() and not (tmp_path / "versions/tgt").exists()


def test_reubicar_huerfano_inexistente(tmp_path):
    with pytest.raises(orphans.TrashError) as ex:
        reloc(tmp_path, item={"id": "game:zzz", "token": "t"})
    assert ex.value.code == "err.orphans.unknown"


def test_reubicar_huerfano_de_dispositivo_se_rechaza(tmp_path):
    seed_origins(tmp_path)
    it = by_id(orphans.scan(CFG_T, tmp_path))["origin:g:gone"]
    with pytest.raises(orphans.TrashError) as ex:
        reloc(tmp_path, item=it)
    assert ex.value.code == "err.orphans.not_game"
    assert (tmp_path / f"versions/g/{V1}/gone/s.sav").exists()


def test_reubicar_con_destino_ocupado(tmp_path):
    seed_game(tmp_path)
    h = locking.acquire(tmp_path / "locks" / "tgt.lock")
    try:
        with pytest.raises(orphans.TrashError) as ex:
            reloc(tmp_path)
    finally:
        h.release()
    assert ex.value.code == "err.orphans.busy"
    assert (tmp_path / f"hub/{OLD}/s.sav").exists()
    h = locking.acquire(tmp_path / "locks" / "tgt.lock")  # y no deja el lock del huérfano tomado
    h.release()
    reloc(tmp_path)


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_reubicar_fallo_a_medias_lo_deshace(tmp_path, monkeypatch, fail_at):
    seed_game(tmp_path)
    seed_target(tmp_path)

    def snap():
        return {
            p.relative_to(tmp_path).as_posix(): (p.read_text(encoding="utf-8") if p.is_file() else None)
            for p in tmp_path.rglob("*")
        }

    before = snap()
    real, calls = orphans.shutil.move, {"n": 0}

    def flaky(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] == fail_at:
            raise OSError("disco lleno")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(orphans.shutil, "move", flaky)
    with pytest.raises(orphans.TrashError) as ex:
        reloc(tmp_path)
    assert ex.value.code == "err.orphans.relocate_failed"
    monkeypatch.undo()
    after = snap()
    assert {k: v for k, v in after.items() if not k.startswith("trash")} == before  # nada perdido ni a medias
    assert [k for k in after if k.startswith("trash") and after[k] is not None] == []  # sin ficheros en la papelera
    h = locking.acquire(tmp_path / "locks" / "tgt.lock")
    h.release()


def test_api_reubicar(cl):
    login(cl)
    seed_game(cl.data)
    body = cl.get("/api/orphans").json()
    assert body["games"] == [{"id": "g", "name": "Juego"}]
    cfg = yaml.safe_load(settings.CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["games"]["tgt"] = {"name": "Destino", "devices": ["pc"], "paths": {"pc": "/p2"}}
    settings.CONFIG_PATH.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    games = cl.get("/api/orphans").json()["games"]
    assert games == [{"id": "g", "name": "Juego"}, {"id": "tgt", "name": "Destino"}]
    it = next(i for i in cl.get("/api/orphans").json()["items"] if i["kind"] == "game")
    for bad in ({}, {"id": it["id"], "token": it["token"]}, {"id": 1, "token": "t", "target": "g"}):
        assert cl.post("/api/orphans/relocate", json=bad).status_code == 400
    r = cl.post("/api/orphans/relocate", json={"id": it["id"], "token": "viejo", "target": "g"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "err.orphans.changed"
    r = cl.post("/api/orphans/relocate", json={"id": it["id"], "token": it["token"], "target": "../x"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "err.orphans.target_unknown"
    r = cl.post("/api/orphans/relocate", json={"id": it["id"], "token": it["token"], "target": "g"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "target": "g", "versions": 2, "hub": True, "size": it["size"]}
    assert cl.get("/api/orphans").json()["items"] == []


def test_api_reubicar_exige_sesion(cl):
    assert cl.post("/api/orphans/relocate", json={}).status_code == 401
