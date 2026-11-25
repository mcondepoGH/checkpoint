"""Versión y actualizaciones (solo detección): estado, comprobación y ajustes del comprobador."""

import logging

from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool

from ...core import updates
from ...core.errors import error_body, error_response
from ...services import selfupdate
from ...services.context import AppContext
from ..deps import body_json, get_ctx, internal_router

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)
router = internal_router()


def _with_install(ctx: AppContext, state: dict) -> dict:
    """`instalador`: es el hub de Windows instalado; `instalable`: la actualización con un clic está disponible (instalador de Windows + Release con instalador y hash)."""
    state["instalador"] = selfupdate.supported()  # este hub se actualiza con el instalador de Windows
    state["instalable"] = bool(
        state.get("hay_actualizacion") and selfupdate.supported() and ctx.checker.latest_installer()
    )
    return state


@router.get("/api/updates")
def get_updates(refresh: bool = False, ctx: AppContext = Depends(get_ctx)):
    api_log.debug("updates: refresh=%s", refresh)
    return _with_install(ctx, ctx.checker.state(refresh=refresh))


@router.post("/api/updates/install")
def post_install(ctx: AppContext = Depends(get_ctx)):
    """Descarga, verifica y lanza el instalador de la última versión. No lee nada del cuerpo: el servidor usa solo lo
    que él mismo comprobó en GitHub."""
    try:
        return ctx.updater.start()
    except selfupdate.UpdateError as e:
        api_log.debug("updates instalar: %s (%s)", e.code, e.status)
        return error_response(e.status, e.code, **e.params)


@router.get("/api/updates/install")
def get_install(ctx: AppContext = Depends(get_ctx)):
    return ctx.updater.status()


@router.put("/api/updates")
async def put_updates(request: Request, ctx: AppContext = Depends(get_ctx)):
    checker = ctx.checker
    if not updates.applicable():
        api_log.debug("updates actualizar: no aplicable (409)")
        return error_response(409, "err.main.updates_not_applicable", extra={"aplicable": False})
    body = await body_json(request)
    errors = {}
    if "enabled" in body and not isinstance(body["enabled"], bool):
        errors["enabled"] = error_body("err.main.updates.enabled_bool")
    if "channel" in body and body["channel"] not in updates.CHANNELS:
        errors["channel"] = error_body("err.main.updates.channel_invalid")
    if not errors and "enabled" not in body and "channel" not in body:
        errors["enabled"] = error_body("err.main.updates.field_required")
    if errors:
        api_log.debug("updates actualizar: inválido en %s", sorted(errors))
        return error_response(422, "err.main.settings_invalid", extra={"errors": errors})
    api_log.debug("updates actualizar: enabled=%s channel=%s", body.get("enabled"), body.get("channel"))
    if "enabled" in body:
        checker.set_enabled(body["enabled"])
    if "channel" in body:
        checker.set_channel(body["channel"])
    return _with_install(ctx, await run_in_threadpool(checker.state))
