"""Descarga del plugin de Steam Deck. PÚBLICA y de solo lectura (sin key ni sesión): el zip es el plugin de código
abierto del propio repositorio (nada secreto), y la Deck lo baja desde su navegador sin tener cuenta en el hub.
No acepta ningún parámetro: la ruta del zip es fija (`settings.DECK_ZIP`), así que no hay recorrido de rutas posible.

- `GET /api/deck/plugin`: el zip (`application/zip`), con la suma y la versión en las cabeceras `X-Checkpoint-Plugin-*`.
- `GET /api/deck/plugin.sha256`: texto «<sha256>  Checkpoint.zip», listo para `sha256sum -c`.
- `GET /api/deck/plugin/info`: JSON `{available, version, protocol, sha256, size, filename}` (`{available: false}` sin zip).
Sin zip (modo nativo sin empaquetar) los dos primeros dan 404 `err.deck.plugin_missing`."""

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from ...core.errors import ApiError
from ...services import deckplugin

router = APIRouter(prefix="/api/deck", include_in_schema=False)  # público: fuera del Swagger de la API key
HEADERS = {"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"}


def _plugin():
    p = deckplugin.load()
    if p is None:
        raise ApiError(404, "err.deck.plugin_missing")
    return p


@router.get("/plugin/info")
def plugin_info():
    return JSONResponse(deckplugin.info(deckplugin.load()), headers=HEADERS)


@router.get("/plugin.sha256")
def plugin_sha():
    p = _plugin()
    return Response(f"{p.sha256}  {deckplugin.FILENAME}\n", media_type="text/plain; charset=utf-8", headers=HEADERS)


@router.get("/plugin")
def plugin_zip():
    p = _plugin()
    headers = {
        **HEADERS,
        "Content-Disposition": f'attachment; filename="{deckplugin.FILENAME}"',
        "X-Checkpoint-Plugin-Sha256": p.sha256,
    }
    if p.version:
        headers["X-Checkpoint-Plugin-Version"] = p.version
    return Response(p.data, media_type="application/zip", headers=headers)
