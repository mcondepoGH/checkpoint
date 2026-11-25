"""Ajustes del sistema que solo aplican al hub instalado en Windows: arranque al iniciar sesión (Tarea Programada)."""

import logging

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from ...core.errors import error_response
from ...services import autostart
from ..deps import body_json, internal_router

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)
router = internal_router()


def _state() -> dict:
    return {"supported": autostart.supported(), "enabled": autostart.is_enabled()}


@router.get("/api/autostart")
def get_autostart():
    return _state()


@router.put("/api/autostart")
async def put_autostart(request: Request):
    body = await body_json(request)
    if not isinstance(body.get("enabled"), bool):
        api_log.debug("autostart: enabled no es booleano (422)")
        return error_response(
            422,
            "err.main.settings_invalid",
            extra={"errors": {"enabled": {"code": "err.main.updates.enabled_bool", "params": {}}}},
        )
    if not autostart.supported():
        return error_response(409, "err.main.autostart.not_supported")
    api_log.debug("autostart: enabled=%s", body["enabled"])
    try:
        await run_in_threadpool(autostart.enable if body["enabled"] else autostart.disable)
    except autostart.AutostartError as e:
        return error_response(500, e.code, reason=e.reason)
    return await run_in_threadpool(_state)
