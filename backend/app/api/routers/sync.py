"""Sync manual, ejecuciones (log en directo), estado por juego y vigilancias de cierre para la UI."""

import json
import logging
import time

from fastapi import Depends, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from ...core.errors import ApiError
from ...services.context import AppContext
from ...services.runs import start_manual_sync
from ...services.status import read_statuses
from ...sync.scheduler import iso, utcnow
from ...sync import resolution
from ..deps import body_json_limited, get_ctx, internal_router

api_log = logging.getLogger(
    "checkpoint.api"
)  # DEBUG: una línea por petición /api y detalle por endpoint (sin secretos)
router = internal_router()


@router.post("/api/sync/{game}")
async def start_sync(game: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    cfg = ctx.cfg()
    game = ctx.game_id(game)
    try:
        body = await request.json()
    except Exception:
        body = {}
    run = start_manual_sync(ctx.runs, ctx.scheduler, cfg, game, body)
    return {"run_id": run.id}


@router.get("/api/watches")
def watches_view(ctx: AppContext = Depends(get_ctx)):
    """Vigilancias de cierre activas para la UI (sesión): {now, watches: [{game, device, state, since, last_poll, poll}],
    playing: [{game, device, since, expires, result?}], results: [{game, device, at, trigger, state, code?}]}.
    `playing` = «jugando ahora» de dispositivos http (avisan ellos); `results` = último resultado de sync por juego y
    dispositivo http. `now` es la hora del servidor (UTC) para que el cliente mida el latido sin depender de su reloj. Sin datos sensibles."""
    cfg = ctx.cfg()
    w = ctx.hooks.active_watches(cfg)
    playing = ctx.hooks.active_playing(cfg)
    api_log.debug("watches: %d vigilancias activas, %d jugando (http)", len(w), len(playing))
    return {
        "now": iso(utcnow()),
        "watches": w,
        "playing": playing,
        "results": ctx.hooks.last_sync_results(cfg),
        **ctx.hooks.pending_resolutions(cfg),
    }


@router.put("/api/sync/{game}/resolution")
async def put_resolution(game: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    """Resolución pendiente de un conflicto de datos de un dispositivo http (web): `{device, winner: hub|device,
    expect: {hub, device}}`. El dispositivo la aplica en su próxima sync. 409 sin conflicto registrado o con `expect` obsoleto."""
    cfg = ctx.cfg()
    game = ctx.game_id(game)
    body = await body_json_limited(request, resolution.BODY_MAX_BYTES, "err.resolution.invalid")
    device, winner, expect = ctx.hooks.parse_resolution_body(body)
    return await run_in_threadpool(ctx.hooks.set_resolution, cfg, game, device, winner, expect, "web")


@router.delete("/api/sync/{game}/resolution")
async def delete_resolution(game: str, device: str = Query(...), ctx: AppContext = Depends(get_ctx)):
    """Cancela la resolución pendiente de (juego, dispositivo http). El conflicto registrado se conserva."""
    cfg = ctx.cfg()
    game = ctx.game_id(game)
    return await run_in_threadpool(ctx.hooks.cancel_resolution, cfg, game, device)


@router.get("/api/games/{game}/hook-status")
def hook_status(game: str, ctx: AppContext = Depends(get_ctx)):
    """Por dispositivo del juego: último evento de hook (`opened` = hook, cierre = hook_closed) y vigilancia activa.
    {devices: [{device, last: {trigger, at, outcome} | null, watching: {state, since} | null}]}. Solo lectura, sin datos sensibles."""
    cfg = ctx.cfg()
    game = ctx.game_id(game)
    return ctx.hooks.status(cfg, game)


@router.get("/api/runs/{run_id}/stream")
def stream(run_id: str, ctx: AppContext = Depends(get_ctx)):
    run = ctx.runs.get(run_id)
    if not run:
        api_log.debug("stream: run %s desconocido (404)", run_id)
        raise ApiError(404, "err.main.run_unknown")
    api_log.debug(
        "stream: run=%s juego=%s líneas ya disponibles=%d hecho=%s", run_id, run.game, len(run.lines), run.done
    )

    def gen():
        i = 0
        while True:
            while i < len(run.lines):
                yield f"data: {json.dumps(run.lines[i])}\n\n"
                i += 1
            if run.done and i >= len(run.lines):
                api_log.debug("stream: run=%s cerrado tras %d líneas", run_id, i)
                yield f"event: done\ndata: {json.dumps(run.status)}\n\n"
                return
            time.sleep(0.3)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/api/status")
def status(ctx: AppContext = Depends(get_ctx)):
    cfg = ctx.store.snapshot().cfg
    return read_statuses(cfg.games if cfg else {})
