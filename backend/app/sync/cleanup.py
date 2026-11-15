"""Limpieza de METADATOS de dispositivos borrados de la config: línea base (`state/<juego>.json`), staging
(`staging/<juego>/<id>/`) y conflictos/resoluciones (`resolutions/<juego>.json`).

NUNCA toca versiones ni el hub: son datos del usuario y su destino lo decide él (ver `services/orphans`). Cada juego se
limpia con su lock (no bloqueante): si hay una sync u operación en curso, ese juego se salta y queda para otra vez."""

import logging
import shutil
from pathlib import Path
from typing import Dict, Iterable, List

from ..config.models import ID_RE, RESERVED_SLUGS
from . import locking, resolution
from .baseline import drop_baseline, load_baseline

log = logging.getLogger("checkpoint.sync")


def _games_with_metadata(data_dir: Path) -> List[str]:
    games = set()
    for sub, suffix in (("state", ".json"), ("resolutions", ".json")):
        d = data_dir / sub
        if d.is_dir():
            games |= {p.stem for p in d.iterdir() if p.is_file() and p.suffix == suffix and ID_RE.fullmatch(p.stem)}
    st = data_dir / "staging"
    if st.is_dir():
        games |= {p.name for p in st.iterdir() if p.is_dir() and not p.is_symlink() and ID_RE.fullmatch(p.name)}
    return sorted(games)


def purge_device_metadata(data_dir: Path, removed: Iterable[str]) -> Dict[str, int]:
    """Borra los metadatos de los dispositivos `removed` (ids) en todos los juegos. Devuelve cuántas cosas quitó:
    {state, staging, resolutions}. Los ids que no son un id válido de dispositivo se ignoran."""
    data_dir = Path(data_dir)
    ids = sorted({i for i in removed if isinstance(i, str) and ID_RE.fullmatch(i) and i not in RESERVED_SLUGS})
    out = {"state": 0, "staging": 0, "resolutions": 0}
    if not ids:
        return out
    for game in _games_with_metadata(data_dir):
        base = load_baseline(data_dir, game)
        res = resolution.load(data_dir, game)
        stage = [i for i in ids if (data_dir / "staging" / game / i).is_dir()]
        in_state = [i for i in ids if i in base]
        in_res = [i for i in ids if i in res["conflicts"] or i in res["resolutions"]]
        if not (stage or in_state or in_res):
            continue
        try:
            handle = locking.acquire(data_dir / "locks" / f"{game}.lock")
        except locking.LockBusy:
            log.info("limpieza de dispositivos: un juego está ocupado y se salta")
            continue
        try:
            if drop_baseline(data_dir, game, in_state):
                out["state"] += 1
            for i in in_res:
                if resolution.clear(data_dir, game, i):
                    out["resolutions"] += 1
            for i in stage:
                d = data_dir / "staging" / game / i
                if d.is_symlink():  # nunca se sigue un enlace: se quita el enlace, no su destino
                    d.unlink()
                else:
                    shutil.rmtree(d, ignore_errors=True)
                out["staging"] += 1
        finally:
            handle.release()
    if any(out.values()):
        log.info("limpieza de dispositivos borrados: %s", out)
    return out
