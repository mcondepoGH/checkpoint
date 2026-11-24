"""Conflictos de datos de dispositivos `http` y su «resolución pendiente».

Un dispositivo `http` sincroniza él mismo (el hub no puede escribirle), así que un conflicto no se resuelve en una sync
del hub: se REGISTRA (por juego y dispositivo, con las huellas de cada lado) y quien lo resuelve (la web o el propio
dispositivo) deja una resolución `{winner, expect, by, at}` que `fingerprint` y `commit` honran SOLO si las huellas
actuales siguen siendo las de `expect`. Fichero `data/resolutions/<juego>.json`, pequeño y sin rutas ni nombres de
fichero: solo ids (hashes) y marcas de tiempo. Las funciones no toman el lock: lo hace el llamador (el del juego)."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .fingerprint import SHA256_RE

WINNERS = ("hub", "device")
BODY_MAX_BYTES = 2048  # cuerpo máx. de `PUT .../resolution` (más = 400)
_REASONS = frozenset({"both-changed", "no-baseline", "inconsistent", "resolution_stale"})


def _path(data_dir: Path, game: str) -> Path:
    return Path(data_dir) / "resolutions" / f"{game}.json"


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(s) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def _hash_ok(v) -> bool:
    return v is None or (isinstance(v, str) and SHA256_RE.match(v) is not None)


def _conflict_ok(c) -> bool:
    return (
        isinstance(c, dict)
        and c.get("reason") in _REASONS
        and _hash_ok(c.get("hub"))
        and _hash_ok(c.get("device"))
        and _parse(c.get("at")) is not None
    )


def _resolution_ok(r) -> bool:
    e = r.get("expect") if isinstance(r, dict) else None
    return (
        isinstance(r, dict)
        and r.get("winner") in WINNERS
        and r.get("by") in ("web", "device")
        and isinstance(e, dict)
        and _hash_ok(e.get("hub"))
        and _hash_ok(e.get("device"))
        and _parse(r.get("at")) is not None
    )


def load(data_dir: Path, game: str) -> dict:
    """{"conflicts": {dispositivo: {...}}, "resolutions": {dispositivo: {...}}}. Sin fichero, ilegible o con entradas
    mal formadas: esas entradas se ignoran (comportamiento seguro: sin resolución pendiente)."""
    out = {"conflicts": {}, "resolutions": {}}
    try:
        raw = json.loads(_path(data_dir, game).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if not isinstance(raw, dict):
        return out
    for key, ok in (("conflicts", _conflict_ok), ("resolutions", _resolution_ok)):
        items = raw.get(key)
        if isinstance(items, dict):
            out[key] = {d: v for d, v in items.items() if isinstance(d, str) and ok(v)}
    return out


def _save(data_dir: Path, game: str, data: dict) -> None:
    p = _path(data_dir, game)
    if not data["conflicts"] and not data["resolutions"]:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, p)


def valid_resolution(entry: Optional[dict], now: datetime, ttl_s: float) -> bool:
    """¿Sigue vigente (no caducada)?"""
    at = _parse(entry.get("at")) if entry else None
    return at is not None and now < at + timedelta(seconds=ttl_s)


def expires(entry: dict, ttl_s: float) -> str:
    return iso(_parse(entry["at"]) + timedelta(seconds=ttl_s))


def record_conflict(data_dir: Path, game: str, dev: str, reason: str, hub: Optional[str], device: Optional[str], now):
    """Registra (o actualiza) el conflicto de `dev`. Reescribe solo si cambió algo distinto de la hora."""
    d = load(data_dir, game)
    new = {"reason": reason, "hub": hub, "device": device}
    old = d["conflicts"].get(dev)
    if old and {k: old[k] for k in new} == new:
        return
    d["conflicts"][dev] = {**new, "at": iso(now)}
    _save(data_dir, game, d)


def set_resolution(data_dir: Path, game: str, dev: str, winner: str, expect: dict, by: str, now) -> dict:
    d = load(data_dir, game)
    r = {"winner": winner, "expect": {"hub": expect["hub"], "device": expect["device"]}, "by": by, "at": iso(now)}
    d["resolutions"][dev] = r
    _save(data_dir, game, d)
    return r


def clear(data_dir: Path, game: str, dev: str, conflict: bool = True, resolution: bool = True) -> bool:
    """Borra lo de `dev` (por defecto, ambas cosas). True si había algo que borrar de lo pedido."""
    d = load(data_dir, game)
    had = (conflict and d["conflicts"].pop(dev, None) is not None) | (
        resolution and d["resolutions"].pop(dev, None) is not None
    )
    if had:
        _save(data_dir, game, d)
    return bool(had)
