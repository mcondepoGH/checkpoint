"""Datos sin dispositivo ni juego en la config («huérfanos»): detección, papelera con caducidad y restauración. Sin FastAPI.

Huérfano = (a) `versions/<juego>/<versión>/<origen>/` de un juego vivo cuyo `<origen>` no es `hub` ni un id de
`cfg.devices` (dispositivo borrado o nombre antiguo); (b) todo lo que hay en disco de un juego que ya no está en
`cfg.games`. Nada se borra desde aquí: se MUEVE a `data/trash/` (ver `sync/trash`) y caduca. Antes de mover se
revalida con la config actual y bajo el lock del juego; lo vigente (juego de la config, `hub`, dispositivo de la
config) nunca se mueve, aunque el cliente mande un id inventado. La confirmación va ligada a lo listado: cada
elemento lleva un `token` (huella de su contenido) que el cliente devuelve; si algo cambió desde que lo vio, no se mueve."""

import hashlib
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List

from ..config.models import Config
from ..core import settings
from ..sync import locking
from ..sync import trash
from ..sync.trash import TrashError as TrashError, plain_name
from ..sync.versions import VERSION_RE, _fmt, _version_key

api_log = logging.getLogger("checkpoint.api")

MAX_ITEMS = 200  # elementos por petición de mover a la papelera


def _subdirs(d: Path):
    """Subcarpetas reales (nunca enlaces simbólicos) con nombre simple."""
    if not d.is_dir() or d.is_symlink():
        return []
    return sorted(
        (p for p in d.iterdir() if p.is_dir() and not p.is_symlink() and plain_name(p.name)), key=lambda p: p.name
    )


def _json_stems(d: Path):
    if not d.is_dir() or d.is_symlink():
        return []
    return [
        p.stem for p in d.iterdir() if p.is_file() and not p.is_symlink() and p.suffix == ".json" and plain_name(p.stem)
    ]


def _version_date(name: str) -> str:
    """`2026-01-01_100000[-n]` -> `2026-01-01 10:00:00`."""
    s = name[:17]
    return f"{s[:10]} {s[11:13]}:{s[13:15]}:{s[15:17]}"


def _item(item_id, kind, game, source, parts, version_names) -> dict:
    """Ficha de un huérfano. `parts` = [(ruta relativa a data, destino en la papelera, Path)]."""
    files = size = 0
    newest = 0.0
    hub_files = 0
    for rel, _dest, p in parts:
        f, s, m = trash.tree_stats(p)
        files, size, newest = files + f, size + s, max(newest, m)
        if rel.startswith("hub/"):
            hub_files += f
    versions = sorted(version_names)
    if versions:
        stamps = sorted(versions, key=lambda n: (n[:17], int(n[18:]) if n[18:].isdigit() else 0))
        oldest, last = _version_date(stamps[0]), _version_date(stamps[-1])
    else:
        oldest = last = _fmt(int(newest)) if newest else "-"
    token = hashlib.sha256(f"{item_id}|{size}|{files}|{len(versions)}|{int(newest)}".encode()).hexdigest()[:32]
    return {
        "id": item_id,
        "kind": kind,
        "game": game,
        "source": source,
        "size": size,
        "files": files,
        "versions": len(versions),
        "oldest": oldest,
        "newest": last,
        # El hub de un juego que ya no está en la config es la única copia en el servidor de esos datos.
        "only_copy": kind == "game" and hub_files > 0,
        "token": token,
        "_parts": parts,
    }


def _game_parts(data: Path, game: str):
    out = []
    for rel, dest in (
        (f"hub/{game}", "hub"),
        (f"versions/{game}", "versions"),
        (f"state/{game}.json", "state.json"),
        (f"status/{game}.json", "status.json"),
        (f"logs/{game}", "logs"),
        (f"staging/{game}", "staging"),
        (f"resolutions/{game}.json", "resolutions.json"),
    ):
        p = data / rel
        if p.is_symlink() or not p.exists():
            continue
        out.append((rel, f"game/{game}/{dest}", p))
    return out


def _scan(cfg: Config, data_dir) -> List[dict]:
    data = Path(data_dir)
    known = set(cfg.devices) | {"hub"}
    items: List[dict] = []
    # (a) orígenes desconocidos en juegos vivos
    for gdir in _subdirs(data / "versions"):
        if gdir.name not in cfg.games:
            continue
        acc: Dict[str, list] = {}
        for vdir in _subdirs(gdir):
            if not VERSION_RE.match(vdir.name):
                continue
            for sdir in _subdirs(vdir):
                if sdir.name not in known:
                    acc.setdefault(sdir.name, []).append((vdir.name, sdir))
        for src, found in sorted(acc.items()):
            parts = [(f"versions/{gdir.name}/{v}/{src}", f"origin/{gdir.name}/versions/{v}/{src}", p) for v, p in found]
            items.append(_item(f"origin:{gdir.name}:{src}", "origin", gdir.name, src, parts, [v for v, _ in found]))
    # (b) juegos con datos que ya no están en la config
    games = set()
    for sub in ("hub", "versions", "logs", "staging"):
        games |= {d.name for d in _subdirs(data / sub)}
    for sub in ("state", "status", "resolutions"):
        games |= set(_json_stems(data / sub))
    for game in sorted(games - set(cfg.games)):
        parts = _game_parts(data, game)
        vers = [v.name for v in _subdirs(data / "versions" / game) if VERSION_RE.match(v.name)] if parts else []
        items.append(_item(f"game:{game}", "game", game, None, parts, vers))
    return items


def scan(cfg: Config, data_dir) -> List[dict]:
    """Huérfanos actuales (ver el docstring del módulo), sin rutas internas."""
    return [{k: v for k, v in i.items() if not k.startswith("_")} for i in _scan(cfg, data_dir)]


def _skip(item_id, code, **params) -> dict:
    return {"id": item_id, "code": code, "params": params}


def move_to_trash(cfg_fn: Callable[[], Config], data_dir, requested: List[dict]) -> dict:
    """Mueve a la papelera los huérfanos `requested` ([{id, token}]). `cfg_fn` se vuelve a leer con el lock del juego
    tomado. Devuelve {moved, skipped}: nada vigente se mueve y un elemento que falla no impide los demás."""
    data = Path(data_dir)
    moved: List[dict] = []
    skipped: List[dict] = []
    manifest_items: List[dict] = []
    entry = None
    created = datetime.now(timezone.utc)
    for r in requested:
        item_id, token = r["id"], r["token"]
        first = {i["id"]: i for i in _scan(cfg_fn(), data)}.get(item_id)
        if first is None:
            skipped.append(_skip(item_id, "err.orphans.unknown"))
            continue
        try:
            handle = locking.acquire(data / "locks" / f"{first['game']}.lock")
        except locking.LockBusy:
            skipped.append(_skip(item_id, "err.orphans.busy"))
            continue
        try:
            item = {i["id"]: i for i in _scan(cfg_fn(), data)}.get(item_id)  # revalidar con el lock tomado
            if item is None:
                skipped.append(_skip(item_id, "err.orphans.unknown"))
                continue
            if item["token"] != token:
                skipped.append(_skip(item_id, "err.orphans.changed"))
                continue
            entry = entry or trash.new_entry(data)
            done: List[dict] = []
            try:
                for rel, dest, _p in item["_parts"]:
                    done.append(trash.move_in(data, entry, rel, dest))
            except (OSError, TrashError):
                skipped.append(_skip(item_id, "err.orphans.move_failed"))
            else:
                moved.append({k: item[k] for k in ("id", "kind", "game", "source", "size")})
            if done:
                manifest_items.append(
                    {
                        **{
                            k: item[k]
                            for k in ("kind", "game", "source", "size", "files", "versions", "oldest", "newest")
                        },
                        "moves": done,
                        "restored": False,
                    }
                )
                if item["kind"] == "origin":  # sin dejar versiones vacías que cuenten para el límite
                    for rel in {m["from"].rsplit("/", 1)[0] for m in done}:
                        try:
                            (data / rel).rmdir()
                        except OSError:
                            pass
        finally:
            handle.release()
        if first["kind"] == "game":  # el fichero de lock (vacío) de un juego que ya no existe no se queda suelto
            for suffix in ("", ".excl"):
                (data / "locks" / f"{first['game']}.lock{suffix}").unlink(missing_ok=True)
    if entry is not None:
        trash.write_manifest(entry, created, manifest_items)
    if moved:
        api_log.info(
            "datos sin dispositivo: %d elementos movidos a la papelera (%d bytes)",
            len(moved),
            sum(m["size"] for m in moved),
        )
    return {"moved": moved, "skipped": skipped}


def _free_version(taken: set, stamp: str) -> str:
    """`stamp` si está libre entre las versiones `taken`; si no, `<AAAA-MM-DD_HHMMSS>-<n>` con el menor n libre. Se anota."""
    name, n = stamp, 0
    while name in taken:
        n += 1
        name = f"{stamp[:17]}-{n}"
    taken.add(name)
    return name


def _undo(done: List[tuple], made: List[Path], entry) -> None:
    """Deshace los movimientos hechos (en orden inverso) y quita las carpetas que quedaron vacías. Nunca borra datos."""
    for src, dst in reversed(done):
        try:
            shutil.move(str(dst), str(src))
        except OSError:
            api_log.error("reubicar: no se pudo deshacer un movimiento (los datos siguen en %s)", dst)
            continue
        try:
            dst.parent.rmdir()
        except OSError:
            pass
    for d in made:  # carpetas creadas para recibir datos que al final no llegaron
        try:
            d.rmdir()
        except OSError:
            pass
    if entry is not None:
        for dirpath, _dirs, _files in os.walk(entry, topdown=False):
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


def relocate(cfg_fn: Callable[[], Config], data_dir, item_id: str, token: str, target: str) -> dict:
    """Reubica un huérfano de tipo JUEGO en el juego `target` de la config. Semántica:

    - `hub/<target>` NO se toca: el destino conserva sus partidas actuales.
    - Cada versión del huérfano (`versions/<huérfano>/<ts>/<origen>/`) se SUMA al historial del destino como carpeta
      entera. Nunca se mezcla con una versión que ya exista: si `<ts>` ya está en el destino, la versión llega con el
      siguiente `<ts>-<n>` libre (no se pisa nada, no se pierde nada).
    - El hub actual del huérfano (`hub/<huérfano>`) se suma también al historial del destino como una versión nueva
      (fecha de la reubicación, origen `hub`): se puede restaurar desde Versiones como cualquier otra.
    - Lo demás (state, status, logs, staging, resolutions) va a la papelera, restaurable hasta que caduque.

    Con el lock de los dos juegos (`err.orphans.busy` si alguno está ocupado) y revalidando token y config con ellos
    tomados. Si un movimiento falla se deshacen los anteriores (`err.orphans.relocate_failed`). Sin FastAPI: lanza `TrashError`."""
    data = Path(data_dir)
    cfg = cfg_fn()
    if not isinstance(target, str) or not plain_name(target) or target not in cfg.games:
        raise TrashError("err.orphans.target_unknown")
    first = {i["id"]: i for i in _scan(cfg, data)}.get(item_id)
    if first is None:
        raise TrashError("err.orphans.unknown")
    if first["kind"] != "game":
        raise TrashError("err.orphans.not_game")
    game = first["game"]
    if game == target:
        raise TrashError("err.orphans.target_unknown")
    handles = []
    try:
        for name in sorted((game, target)):  # siempre en el mismo orden
            try:
                handles.append(locking.acquire(data / "locks" / f"{name}.lock"))
            except locking.LockBusy:
                raise TrashError("err.orphans.busy") from None
        cfg = cfg_fn()
        item = {i["id"]: i for i in _scan(cfg, data)}.get(item_id)  # revalidar con los locks tomados
        if item is None:
            raise TrashError("err.orphans.unknown")
        if target not in cfg.games or item["kind"] != "game":
            raise TrashError("err.orphans.target_unknown")
        if item["token"] != token:
            raise TrashError("err.orphans.changed")
        vroot = data / "versions" / target
        if vroot.is_symlink() or (data / "versions").is_symlink():
            raise TrashError("err.orphans.unsafe")
        taken = {p.name for p in vroot.iterdir()} if vroot.is_dir() else set()
        done: List[tuple] = []
        made: List[Path] = []
        entry = None
        try:
            for vdir in sorted(_subdirs(data / "versions" / game), key=lambda p: _version_key(p.name)):
                if not VERSION_RE.match(vdir.name):
                    continue
                dst = vroot / _free_version(taken, vdir.name)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(vdir), str(dst))
                done.append((vdir, dst))
            hub = data / "hub" / game
            hub_in = hub.is_dir() and not hub.is_symlink() and bool(trash.tree_stats(hub)[0])
            if hub_in:
                dst = vroot / _free_version(taken, datetime.now().strftime("%Y-%m-%d_%H%M%S")) / "hub"
                dst.parent.mkdir(parents=True, exist_ok=True)
                made.append(dst.parent)
                shutil.move(str(hub), str(dst))
                done.append((hub, dst))
            try:  # si no queda nada dentro, la carpeta de versiones vacía del huérfano se quita
                (data / "versions" / game).rmdir()
            except OSError:
                pass
            created = datetime.now(timezone.utc)
            rest = [(rel, dest, p) for rel, dest, p in _game_parts(data, game) if not (hub_in and rel == f"hub/{game}")]
            rest_files = rest_size = 0
            for _rel, _dest, p in rest:
                f, s, _m = trash.tree_stats(p)
                rest_files, rest_size = rest_files + f, rest_size + s
            moves: List[dict] = []
            if rest:
                entry = trash.new_entry(data)
                for rel, dest, _p in rest:
                    moves.append(trash.move_in(data, entry, rel, dest))
                    done.append((data / rel, entry / dest))
                trash.write_manifest(
                    entry,
                    created,
                    [
                        {
                            "kind": "game",
                            "game": game,
                            "source": None,
                            "size": rest_size,
                            "files": rest_files,
                            "versions": 0,
                            "oldest": item["oldest"],
                            "newest": item["newest"],
                            "moves": moves,
                            "restored": False,
                        }
                    ],
                )
        except (OSError, TrashError, shutil.Error):
            _undo(done, made, entry)
            raise TrashError("err.orphans.relocate_failed") from None
    finally:
        for h in handles:
            h.release()
    for suffix in ("", ".excl"):  # el lock (vacío) de un juego que ya no existe no se queda suelto
        (data / "locks" / f"{game}.lock{suffix}").unlink(missing_ok=True)
    api_log.info("datos sin dispositivo: un juego reubicado (%d versiones, %d bytes)", item["versions"], item["size"])
    return {
        "ok": True,
        "target": target,
        "versions": item["versions"],
        "hub": bool(hub_in),
        "size": item["size"],
    }


def list_trash(data_dir, ttl_days: float) -> List[dict]:
    """Entradas de la papelera con su manifiesto legible (las más nuevas primero)."""
    out = []
    for d in reversed(list(trash.entries(data_dir))):
        man = trash.read_manifest(d)
        if man is None:
            continue
        items = [
            {
                "index": i,
                **{k: it.get(k) for k in ("kind", "game", "source", "size", "versions", "oldest", "newest")},
            }
            for i, it in enumerate(man["items"])
            if isinstance(it, dict) and not it.get("restored")
        ]
        if items:
            out.append(
                {
                    "entry": d.name,
                    "created": trash.created_of(d, man).isoformat(timespec="seconds"),
                    "expires": trash.expires_of(d, man, ttl_days).isoformat(timespec="seconds"),
                    "items": items,
                }
            )
    return out


def restore_from_trash(data_dir, entry_name: str, index: int) -> None:
    """Devuelve a `data/` el elemento `index` de la entrada `entry_name`. No pisa nada: si algún destino existe,
    `err.orphans.restore_conflict`. Con el lock del juego (`err.orphans.busy` si hay una operación en curso)."""
    data = Path(data_dir)
    if not isinstance(entry_name, str) or not VERSION_RE.match(entry_name):
        raise TrashError("err.orphans.trash_unknown")
    entry = trash.root(data) / entry_name
    man = trash.read_manifest(entry) if entry.is_dir() and not entry.is_symlink() else None
    if man is None or not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(man["items"]):
        raise TrashError("err.orphans.trash_unknown")
    item = man["items"][index]
    game = item.get("game") if isinstance(item, dict) else None
    if not plain_name(game) or item.get("restored"):
        raise TrashError("err.orphans.trash_unknown")
    moves = trash.checked_moves(item.get("moves"), entry)
    if any(f.split("/")[1].removesuffix(".json") != game for f, _ in moves):
        raise TrashError("err.orphans.trash_unknown")
    try:
        handle = locking.acquire(data / "locks" / f"{game}.lock")
    except locking.LockBusy:
        raise TrashError("err.orphans.busy") from None
    try:
        trash.restore_moves(data, entry, moves)
    finally:
        handle.release()
    item["restored"] = True
    if all(isinstance(i, dict) and i.get("restored") for i in man["items"]):
        trash.shutil.rmtree(entry, ignore_errors=True)  # solo quedan carpetas vacías y el manifiesto
    else:
        trash.write_manifest(entry, trash.created_of(entry, man), man["items"])
    api_log.info("papelera: elemento restaurado")


def purge_expired() -> int:
    """Vacía lo caducado de la papelera (`CHECKPOINT_TRASH_TTL_DAYS`). Lo llama el mantenimiento programado."""
    return trash.purge_expired(settings.DATA_DIR, settings.TRASH_TTL_DAYS)
