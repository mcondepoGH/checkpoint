"""API externa de juegos (API key, `GET /api/games`): lista de juegos y su último estado, para dispositivos sin SSH.
Se publica en el Swagger (tag `docs.GAMES_TAG`); documentación en `api/docs/examples.py`. No choca con
`/api/games/{game}/hook-status` (sesión, `routers/sync.py`): otra ruta."""

import logging

from fastapi import APIRouter, Depends

from ...services.context import AppContext
from ...services.status import read_statuses
from .. import docs
from ..deps import Principal, get_ctx, hook_any

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)

router = APIRouter(tags=[docs.GAMES_TAG], responses={401: docs.R401, 429: docs.R429})

STATUS_FIELDS = ("result", "code", "started", "finished")  # lista cerrada: sin mensaje, params, log ni conflicto


def device_path(g, device: str):
    """Ruta del save de `g` en `device` (tal cual la guarda el modelo: recortada y con `/`), o None si no hay. Nunca
    expone el diccionario `paths` ni las rutas de otros dispositivos."""
    v = g.paths.get(device)
    return v if isinstance(v, str) and v else None


@router.get(docs.GAMES_PATH, **docs.GAMES)
def list_games(p: Principal = Depends(hook_any), ctx: AppContext = Depends(get_ctx)):
    """[{id, name, enabled, steam_appid: int | null, status: {result, code, started, finished} | null}]. Con key de usuario, todos los juegos
    de la config; con key de dispositivo, solo los que tienen ese dispositivo en su lista y cada uno añade
    `path`: la ruta del save en ESE dispositivo (cadena) o null. Con key de usuario no hay campo `path`."""
    cfg = ctx.cfg()
    statuses = read_statuses(cfg.games)
    out = []
    for gid, g in cfg.games.items():
        if p.device is not None and p.device not in g.devices:
            continue
        item = {
            "id": gid,
            "name": g.name,
            "enabled": g.enabled,
            "steam_appid": g.steam_appid,
            "status": {k: st[k] for k in STATUS_FIELDS if k in st} if (st := statuses.get(gid)) else None,
        }
        if p.device is not None:
            item["path"] = device_path(g, p.device)
        out.append(item)
    api_log.debug("games (key): %d juegos dispositivo=%s", len(out), p.device)
    return out
