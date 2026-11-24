"""Asociación de juegos de Steam. DOS routers en `/api/steam`:

- `device`: `POST /library`, `POST /games` (crear un juego de esa Deck) y `PUT /games/{game}/enabled` (activar o
  desactivar uno de SUS juegos), SOLO con key de dispositivo `ckd_` (`deps.hook_device`: una `ck_`, la sesión o nada es el
  mismo 401, y los fallos cuentan para el 429 por IP). Alcance: únicamente los juegos que tienen ese dispositivo.
- `session`: sugerencias y descartes para la web (cookie + Origin en las escrituras, como `/api/pairing/pending`).

Toda respuesta lleva `Cache-Control: no-store`. La lógica está en `services/steam.py`; documentación en
`api/docs/steam.py`."""

import logging

from fastapi import APIRouter, Depends, Path, Request, Response
from starlette.concurrency import run_in_threadpool

from ...config.store import InvalidConfig
from ...core.errors import ApiError, error_response
from ...services import steam as svc
from ...services.context import AppContext
from .. import docs
from ..deps import Principal, body_json, get_ctx, hook_device, require

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)

NO_STORE = {"Cache-Control": "no-store"}


def _no_store(response: Response):
    response.headers.update(NO_STORE)


device = APIRouter(
    prefix="/api/steam",
    tags=[docs.STEAM_TAG],
    dependencies=[Depends(_no_store)],
    responses={401: docs.R401, 429: docs.R429},
)
session = APIRouter(
    prefix="/api/steam",
    tags=[docs.STEAM_SESSION_TAG],
    dependencies=[Depends(require), Depends(_no_store)],
    responses={401: docs.R401_SESSION, 403: docs.R403_ORIGIN},
)


@device.post("/library", **docs.STEAM_LIBRARY)
async def library(request: Request, p: Principal = Depends(hook_device), ctx: AppContext = Depends(get_ctx)):
    # La key ya está comprobada (dependencia): solo a partir de aquí se lee el cuerpo.
    length = request.headers.get("content-length", "")
    if (length.isdigit() and int(length) > svc.MAX_BODY) or len(await request.body()) > svc.MAX_BODY:
        raise ApiError(413, "err.steam.body_too_large", max=svc.MAX_BODY)
    entries = svc.parse_library(await body_json(request))
    return await run_in_threadpool(ctx.steam.library, p.device, entries)


@device.post("/games", **docs.STEAM_GAME_CREATE)
async def create_game(request: Request, p: Principal = Depends(hook_device), ctx: AppContext = Depends(get_ctx)):
    length = request.headers.get("content-length", "")
    if (length.isdigit() and int(length) > svc.MAX_GAME_BODY) or len(await request.body()) > svc.MAX_GAME_BODY:
        raise ApiError(413, "err.steam.body_too_large", max=svc.MAX_GAME_BODY)
    appid, name, path = svc.parse_game(await body_json(request))
    return await run_in_threadpool(ctx.steam.create_game, p.device, appid, name, path)


@device.put("/games/{game}/enabled", **docs.STEAM_GAME_ENABLED)
async def set_game_enabled(
    request: Request,
    game: str = Path(max_length=64),
    p: Principal = Depends(hook_device),
    ctx: AppContext = Depends(get_ctx),
):
    length = request.headers.get("content-length", "")
    if (length.isdigit() and int(length) > svc.MAX_GAME_BODY) or len(await request.body()) > svc.MAX_GAME_BODY:
        raise ApiError(413, "err.steam.body_too_large", max=svc.MAX_GAME_BODY)
    enabled = svc.parse_enabled(await body_json(request))
    return await run_in_threadpool(ctx.steam.set_enabled, p.device, game, enabled)


@device.put("/games/{game}/path", **docs.STEAM_GAME_PATH)
async def set_game_path(
    request: Request,
    game: str = Path(max_length=64),
    p: Principal = Depends(hook_device),
    ctx: AppContext = Depends(get_ctx),
):
    length = request.headers.get("content-length", "")
    if (length.isdigit() and int(length) > svc.MAX_GAME_BODY) or len(await request.body()) > svc.MAX_GAME_BODY:
        raise ApiError(413, "err.steam.body_too_large", max=svc.MAX_GAME_BODY)
    path = svc.parse_path(await body_json(request))
    return await run_in_threadpool(ctx.steam.change_path, p.device, game, path)


@session.get("/suggestions", **docs.STEAM_SUGGESTIONS)
def list_suggestions(ctx: AppContext = Depends(get_ctx)):
    return ctx.steam.suggestions()


@session.post("/suggestions/{suggestion_id}/accept", **docs.STEAM_ACCEPT)
async def accept_suggestion(suggestion_id: str = Path(max_length=64), ctx: AppContext = Depends(get_ctx)):
    try:
        return await run_in_threadpool(ctx.steam.accept, suggestion_id)
    except InvalidConfig as e:  # mismo cuerpo que `PUT /api/config`
        return error_response(422, "err.main.config_invalid", extra={"errors": e.errors})


@session.post("/suggestions/{suggestion_id}/dismiss", **docs.STEAM_DISMISS)
def dismiss_suggestion(suggestion_id: str = Path(max_length=64), ctx: AppContext = Depends(get_ctx)):
    return ctx.steam.dismiss(suggestion_id)


@session.get("/dismissed", **docs.STEAM_DISMISSED)
def list_dismissed(ctx: AppContext = Depends(get_ctx)):
    return ctx.steam.dismissed()


@session.delete("/dismissed/{dismissed_id}", **docs.STEAM_FORGET)
def forget_dismissed(dismissed_id: str = Path(max_length=64), ctx: AppContext = Depends(get_ctx)):
    return ctx.steam.forget(dismissed_id)
