"""Datos sin dispositivo ni juego en la config: detección, papelera y restauración (solo con sesión)."""

from fastapi import Depends, Request

from ...core import settings
from ...core.errors import ApiError
from ...services import orphans as svc
from ...services.context import AppContext
from ..deps import body_json, get_ctx, internal_router

router = internal_router()

_STATUS = {
    "err.orphans.trash_unknown": 404,
    "err.orphans.restore_conflict": 409,
    "err.orphans.busy": 409,
    "err.orphans.restore_failed": 500,
}


def _invalid():
    return ApiError(400, "err.orphans.body_invalid")


@router.get("/api/orphans")
def list_orphans(ctx: AppContext = Depends(get_ctx)):
    return {"items": svc.scan(ctx.cfg(), settings.DATA_DIR), "ttl_days": settings.TRASH_TTL_DAYS}


@router.post("/api/orphans/trash")
async def trash_orphans(request: Request, ctx: AppContext = Depends(get_ctx)):
    """Mueve a la papelera los elementos `items` ([{id, token}], de `GET /api/orphans`); no borra nada."""
    body = await body_json(request)
    items = body.get("items")
    if not isinstance(items, list) or not 0 < len(items) <= svc.MAX_ITEMS:
        raise _invalid()
    for i in items:
        if not (isinstance(i, dict) and isinstance(i.get("id"), str) and isinstance(i.get("token"), str)):
            raise _invalid()
    ctx.cfg()  # config inválida: 500 antes de tocar nada
    return svc.move_to_trash(ctx.cfg, settings.DATA_DIR, [{"id": i["id"], "token": i["token"]} for i in items])


@router.get("/api/orphans/trash")
def list_trash(ctx: AppContext = Depends(get_ctx)):
    return svc.list_trash(settings.DATA_DIR, settings.TRASH_TTL_DAYS)


@router.post("/api/orphans/trash/restore")
async def restore_trash(request: Request, ctx: AppContext = Depends(get_ctx)):
    body = await body_json(request)
    entry, item = body.get("entry"), body.get("item")
    if not isinstance(entry, str) or not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise _invalid()
    try:
        svc.restore_from_trash(settings.DATA_DIR, entry, item)
    except svc.TrashError as e:
        raise ApiError(_STATUS.get(e.code, 400), e.code, **e.params) from None
    return {"ok": True}
