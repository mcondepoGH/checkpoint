"""Documentación OpenAPI de la asociación de juegos de Steam (`/api/steam/*`): modelos, errores y ejemplos. Solo describe."""

from typing import List, Optional

from pydantic import BaseModel, Field

from .examples import _ok, error_response
from .pairing import _body

STEAM_TAG = "Steam (key de dispositivo)"
STEAM_SESSION_TAG = "Steam (sesión)"
STEAM_PREFIX = "/api/steam/"

STEAM_TAG_DESCRIPTION = (
    "Ruta `POST /api/steam/library`: la Steam Deck envía los juegos de Steam que tiene instalados y el hub asocia "
    "solo los que coinciden con certeza (ver el endpoint). **Solo vale una key de dispositivo `ckd_`.**"
)
STEAM_SESSION_TAG_DESCRIPTION = (
    "Rutas `/api/steam/suggestions*` y `/api/steam/dismissed*`: el usuario, **con sesión web**, ve las sugerencias "
    "dudosas, las acepta o descarta, y puede olvidar un descarte."
)

_NOSTORE = " La respuesta lleva `Cache-Control: no-store`."


class SteamEntry(BaseModel):
    appid: int = Field(gt=0, description="Id de Steam del juego (entero positivo).", examples=[1145360])
    name: str = Field(
        min_length=1, max_length=200, description="Nombre del juego en Steam (1 a 200 caracteres).", examples=["Hades"]
    )


class SteamLibraryBody(BaseModel):
    games: List[SteamEntry] = Field(max_length=5000, description="Juegos de Steam instalados (hasta 5000).")


class SteamAssociated(BaseModel):
    appid: int = Field(description="Appid que se acaba de escribir en el juego.")
    game: str = Field(description="Id del juego (uno de los que tienen ese dispositivo).")


class SteamLibraryResult(BaseModel):
    associated: List[SteamAssociated] = Field(description="Juegos a los que se acaba de asignar `steam_appid`.")
    suggested: int = Field(description="Entradas dudosas: el usuario decide en la web (no se asocia nada).")
    unchanged: int = Field(description="Entradas cuyo juego ya tenía ese mismo appid (no se toca nada).")
    ignored: int = Field(description="Entradas sin juego de este dispositivo, o que no se pueden asignar.")


class SteamGameBody(BaseModel):
    appid: int = Field(
        gt=0, description="Id de Steam del juego (entero positivo, no usado por otro juego).", examples=[504230]
    )
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Nombre del juego (mismas reglas que en la config).",
        examples=["Celeste"],
    )
    path: str = Field(
        min_length=1,
        max_length=1024,
        description="Ruta absoluta de los saves en la Deck (mismas reglas que en la config).",
        examples=["/home/deck/.local/share/Celeste/Saves"],
    )


class SteamGameCreated(BaseModel):
    id: str = Field(
        description="Id del juego (nuevo: lo genera el hub a partir del nombre; unido: el del juego existente)."
    )
    name: str = Field(description="Nombre del juego (si te has unido, el del hub).")
    appid: int = Field(description="Appid guardado.")
    path: str = Field(description="Ruta de ESTE dispositivo guardada (normalizada).")
    joined: Optional[bool] = Field(
        None,
        description=(
            "Solo cuando el hub ya tenía un juego con ese nombre: `true` = este dispositivo se ha añadido a él; `false` = ya "
            "estaba (mismo appid) y no se ha cambiado nada. Ausente = juego nuevo."
        ),
    )
    devices: Optional[List[str]] = Field(None, description="Con `joined`: ids de los dispositivos del juego (máx. 2).")
    enabled: Optional[bool] = Field(
        None, description="Con `joined`: si el juego está activo (un juego desactivado se une pero no se activa)."
    )


class SteamEnabledBody(BaseModel):
    enabled: bool = Field(description="`true` = activo, `false` = desactivado.")


class SteamEnabled(BaseModel):
    game: str = Field(description="Id del juego.")
    enabled: bool = Field(description="Estado actual.")


class SteamSuggestion(BaseModel):
    id: str = Field(description="Id de la sugerencia (para aceptar o descartar).")
    appid: int = Field(description="Appid de Steam propuesto.")
    steam_name: str = Field(description="Nombre que dio la Deck (no verificado).")
    game: str = Field(description="Id del juego del hub propuesto.")
    game_name: str = Field(description="Nombre de ese juego.")
    device: str = Field(description="Id del dispositivo que la envió.")
    device_name: Optional[str] = Field(None, description="Nombre de ese dispositivo (`null` si ya no existe).")


class SteamAccepted(BaseModel):
    id: str = Field(description="Id de la sugerencia aceptada.")
    appid: int = Field(description="Appid escrito en el juego.")
    game: str = Field(description="Id del juego.")
    name: str = Field(description="Nombre del juego.")


class SteamDismissedNow(BaseModel):
    id: str = Field(description="Id de la sugerencia descartada.")
    appid: int = Field(description="Appid descartado.")
    game: str = Field(description="Id del juego con el que se descarta el par.")


class SteamDismissed(BaseModel):
    id: str = Field(description="Id del descarte (para olvidarlo).")
    appid: int = Field(description="Appid descartado.")
    steam_name: str = Field(description="Nombre de Steam cuando se descartó.")
    game: str = Field(description="Id del juego.")
    game_name: Optional[str] = Field(None, description="Nombre del juego (`null` si ya no existe).")


class SteamForgotten(BaseModel):
    id: str = Field(description="Id del descarte olvidado.")
    forgotten: bool = Field(description="Siempre `true`.")


R413 = error_response(
    "Cuerpo de más de 1 MiB (`body_too_large`) o más de 5000 entradas (`too_many_games`).",
    ("big", "Cuerpo demasiado grande", "err.steam.body_too_large", {"max": 1048576}),
    ("many", "Demasiadas entradas", "err.steam.too_many_games", {"max": 5000}),
)
R400 = error_response(
    "El cuerpo no es JSON.", ("body", "El cuerpo no es un objeto JSON", "err.main.json_body_required", {})
)
R422 = error_response(
    'Forma incorrecta: el cuerpo debe ser exactamente `{"games": [...]}` (`body_invalid`) y cada entrada exactamente '
    "`{appid, name}` con `appid` entero positivo y `name` de 1 a 200 caracteres (`entry_invalid`, `index` = posición).",
    ("body", "Cuerpo con otra forma", "err.steam.body_invalid", {}),
    ("entry", "Entrada inválida", "err.steam.entry_invalid", {"index": 3}),
)
R409_LIBRARY = error_response(
    "`config.yaml` cambió sin parar mientras se escribía (`err.main.config_changed`; reintenta) o el resultado no era "
    "una configuración válida (`config_invalid`, sin detalle).",
    ("changed", "La configuración cambió", "err.main.config_changed", {}),
    ("invalid", "Configuración resultante inválida", "err.steam.config_invalid", {}),
)
R422_GAME = error_response(
    "Cuerpo con otra forma (`game_body_invalid`: exactamente `{appid, name, path}` / `{enabled}`) o un valor que la config "
    "no acepta (`game_invalid`: `params.field` = `name` | `path` | `appid` | `game` y `params.reason` = el código "
    "`err.config.*` de la causa; nunca datos de otros juegos).",
    ("body", "Cuerpo con otra forma", "err.steam.game_body_invalid", {}),
    ("name", "Nombre repetido", "err.steam.game_invalid", {"field": "name", "reason": "err.config.name_duplicate"}),
    ("path", "Ruta no válida", "err.steam.game_invalid", {"field": "path", "reason": "err.config.path_absolute"}),
    ("slot", "Sin hueco para unirse", "err.steam.game_invalid", {"field": "name", "reason": "err.steam.no_free_slot"}),
    ("mismatch", "Otro appid", "err.steam.game_invalid", {"field": "name", "reason": "err.steam.appid_mismatch"}),
    ("inuse", "Appid de otro juego", "err.steam.game_invalid", {"field": "name", "reason": "err.steam.appid_in_use"}),
)
R404_GAME = error_response(
    "El juego no existe o no tiene este dispositivo (mismo error en los dos casos).",
    ("unknown", "Desconocido", "err.steam.game_unknown", {}),
)
R413_GAME = error_response(
    "Cuerpo de más de 8192 bytes.", ("big", "Cuerpo demasiado grande", "err.steam.body_too_large", {"max": 8192})
)
R404_SUGGESTION = error_response(
    "La sugerencia no existe o caducó.", ("unknown", "Desconocida o caducada", "err.steam.suggestion_unknown", {})
)
R404_ACCEPT = error_response(
    "La sugerencia no existe o caducó (`suggestion_unknown`), o el juego propuesto ya no existe (`game_unknown`).",
    ("unknown", "Desconocida o caducada", "err.steam.suggestion_unknown", {}),
    ("game", "El juego ya no existe", "err.steam.game_unknown", {}),
)
R409_ACCEPT = error_response(
    "Entre tanto el juego ya tiene appid (`game_has_appid`), otro juego usa ese appid (`appid_in_use`) o `config.yaml` "
    "cambió sin parar (`err.main.config_changed`; reintenta, la sugerencia sigue pendiente). En los dos primeros casos la "
    "sugerencia deja de valer y se borra.",
    ("has", "El juego ya tiene appid", "err.steam.game_has_appid", {"game": "Hades"}),
    ("use", "Appid en uso por otro juego", "err.steam.appid_in_use", {"appid": 1145360}),
    ("changed", "La configuración cambió", "err.main.config_changed", {}),
)
R422_ACCEPT = error_response(
    "La configuración resultante no es válida (mismo cuerpo que `PUT /api/config`, con `errors`).",
    ("invalid", "Configuración inválida", "err.main.config_invalid", {}),
)
R404_DISMISSED = error_response("El descarte no existe.", ("unknown", "Desconocido", "err.steam.dismissed_unknown", {}))

STEAM_LIBRARY = dict(
    summary="Enviar los juegos de Steam instalados (asociación automática)",
    description=(
        "La Deck envía su lista de juegos de Steam. El hub compara **solo con los juegos activos que tienen este "
        "dispositivo** (el resto no existe para esta key). Comparación por nombre **normalizado** (minúsculas, sin "
        "tildes ni ™ ® ©, signos y espacios simplificados).\n\n"
        "- **Asocia** (escribe `steam_appid` en el juego) solo si: el juego aún no tiene appid, hay exactamente UNA "
        "entrada con el mismo nombre normalizado, ningún otro juego del hub tiene ese mismo nombre normalizado y el "
        "appid no lo usa otro juego.\n"
        "- **Sugiere** (la persona decide en la web; no se asocia nada): nombre igual pero ambiguo, o parecido (similitud "
        ">= 0,85). Las sugerencias viven en memoria 24 h; reenvía la lista al abrir.\n"
        "- **Nunca pisa** un appid existente: si es el mismo, no hace nada (`unchanged`); si es otro, lo ignora.\n\n"
        "**Seguridad.** Esta key puede fijar el appid de SUS juegos que no lo tienen, nada más. La respuesta solo "
        "habla de los juegos de este dispositivo. Máximo 5000 entradas y 1 MiB." + _NOSTORE
    ),
    responses={
        200: _ok(
            SteamLibraryResult,
            "Resultado del envío.",
            (
                "mixed",
                "Una asociada, una dudosa y una sin juego",
                {"associated": [{"appid": 1145360, "game": "hades"}], "suggested": 1, "unchanged": 0, "ignored": 1},
            ),
        ),
        400: R400,
        409: R409_LIBRARY,
        413: R413,
        422: R422,
    },
    **{
        "openapi_extra": _body(
            SteamLibraryBody,
            "Juegos de Steam instalados.",
            {"games": [{"appid": 1145360, "name": "Hades"}, {"appid": 292030, "name": "The Witcher® 3: Wild Hunt"}]},
        )
    },
)

STEAM_GAME_CREATE = dict(
    summary="Crear un juego de esta Deck (o unirse a uno existente)",
    description=(
        "La Deck da el appid, el nombre y la ruta de los saves de un juego que el hub aún no tiene. El hub crea el "
        "juego **solo con este dispositivo**, activo, con ese `steam_appid` y un id derivado del nombre, con las mismas "
        "validaciones que `PUT /api/config` (nombre y ruta válidos, nombre y appid únicos) y copia de seguridad de la "
        "config. La plataforma sale del dispositivo.\n\n"
        "**Unión automática.** Si el hub ya tiene UN juego con ese nombre (comparación normalizada, la misma que la "
        "asociación por nombre: sin mayúsculas, tildes ni ™ ® ©) NO se crea otro: este dispositivo se **añade** al "
        "existente (`devices` + su ruta; si el juego no tenía `steam_appid` se le pone) y la respuesta lleva "
        "`joined: true`. Condiciones: el juego tiene hueco (menos de 2 dispositivos), este dispositivo no está ya en él, "
        "su appid es el de la petición (o no tiene) y ningún otro juego usa ese appid. Un juego desactivado se une pero "
        "sigue desactivado (`enabled: false` en la respuesta). Si el dispositivo ya está en el juego con ese mismo appid "
        "es idempotente: `200` con `joined: false` y nada cambia (se devuelve la ruta ya guardada). En cualquier otro "
        "caso es `422 game_invalid` con `field: name` y `reason` = `err.config.name_duplicate` (genérico: dispositivo ya "
        "en el juego con otro appid, o varios juegos con ese nombre), `err.steam.no_free_slot` (ya tiene 2 "
        "dispositivos), `err.steam.appid_mismatch` (tiene otro appid) o `err.steam.appid_in_use` (otro juego usa ese "
        "appid).\n\n**Seguridad.** Esta key solo puede añadirse a sí misma: no quita ni cambia otros dispositivos ni "
        "sus rutas, y la ruta se valida como en la creación. Los errores no revelan datos de otros juegos ni "
        "dispositivos. Máximo 8192 bytes." + _NOSTORE
    ),
    responses={
        200: _ok(
            SteamGameCreated,
            "Juego creado, o dispositivo unido a un juego existente (`joined`).",
            (
                "ok",
                "Creado",
                {"id": "celeste", "name": "Celeste", "appid": 504230, "path": "/home/deck/.local/share/Celeste/Saves"},
            ),
            (
                "joined",
                "Unido a un juego existente",
                {
                    "id": "celeste",
                    "name": "Celeste",
                    "appid": 504230,
                    "path": "/home/deck/.local/share/Celeste/Saves",
                    "joined": True,
                    "devices": ["pc", "deck"],
                    "enabled": True,
                },
            ),
        ),
        400: R400,
        409: R409_LIBRARY,
        413: R413_GAME,
        422: R422_GAME,
    },
    **{
        "openapi_extra": _body(
            SteamGameBody,
            "Datos del juego.",
            {"appid": 504230, "name": "Celeste", "path": "/home/deck/.local/share/Celeste/Saves"},
        )
    },
)

STEAM_GAME_ENABLED = dict(
    summary="Activar o desactivar un juego de esta Deck",
    description=(
        "Pone `enabled` del juego (el campo de la config). **Vale para todo el hub:** un juego desactivado no se "
        "sincroniza por ninguna vía en ningún dispositivo (automática, manual, avisos de apertura y cierre). Solo juegos que "
        "tienen este dispositivo; si no, `404`. Repetir el mismo valor no escribe nada." + _NOSTORE
    ),
    responses={
        200: _ok(SteamEnabled, "Estado actual.", ("off", "Desactivado", {"game": "celeste", "enabled": False})),
        400: R400,
        404: R404_GAME,
        409: R409_LIBRARY,
        413: R413_GAME,
        422: R422_GAME,
    },
    **{"openapi_extra": _body(SteamEnabledBody, "Estado deseado.", {"enabled": False})},
)

STEAM_SUGGESTIONS = dict(
    summary="Listar las sugerencias de appid",
    description="Sugerencias pendientes (appid de Steam + juego propuesto + dispositivo que la envió). Se omiten las que "
    "ya no valen (el juego tiene appid, el appid está en uso o el juego se borró). Lista vacía si no hay." + _NOSTORE,
    responses={
        200: _ok(
            List[SteamSuggestion],
            "Sugerencias pendientes (puede estar vacía).",
            (
                "list",
                "Una sugerencia",
                [
                    {
                        "id": "k3x9Qd2LmP0a",
                        "appid": 292030,
                        "steam_name": "The Witcher 3 Wild Hunt GOTY",
                        "game": "witcher",
                        "game_name": "The Witcher 3: Wild Hunt",
                        "device": "deck",
                        "device_name": "Steam Deck",
                    }
                ],
            ),
            ("empty", "Sin sugerencias", []),
        )
    },
)

STEAM_ACCEPT = dict(
    summary="Aceptar una sugerencia",
    description=(
        "Escribe `steam_appid` en el juego propuesto (mismo camino y validaciones que `PUT /api/config`, con copia de "
        "seguridad). Si entre tanto el juego ya tiene appid o el appid está en uso, `409` y no se escribe nada."
        + _NOSTORE
    ),
    responses={
        200: _ok(
            SteamAccepted,
            "Appid escrito.",
            ("ok", "Aceptada", {"id": "k3x9Qd2LmP0a", "appid": 292030, "game": "witcher", "name": "The Witcher 3"}),
        ),
        404: R404_ACCEPT,
        409: R409_ACCEPT,
        422: R422_ACCEPT,
    },
)

STEAM_DISMISS = dict(
    summary="Descartar una sugerencia (se recuerda)",
    description="Descarta la sugerencia y recuerda el par appid + juego en disco: no se vuelve a proponer hasta que se "
    "olvide el descarte." + _NOSTORE,
    responses={
        200: _ok(
            SteamDismissedNow,
            "Descartada.",
            ("ok", "Descartada", {"id": "k3x9Qd2LmP0a", "appid": 292030, "game": "witcher"}),
        ),
        404: R404_SUGGESTION,
    },
)

STEAM_DISMISSED = dict(
    summary="Listar los descartes recordados",
    description="Pares appid + juego descartados (hasta 1000; al pasarse, se olvidan los más antiguos)." + _NOSTORE,
    responses={
        200: _ok(
            List[SteamDismissed],
            "Descartes recordados (puede estar vacía).",
            (
                "list",
                "Un descarte",
                [
                    {
                        "id": "aB3dE9fG",
                        "appid": 292030,
                        "steam_name": "The Witcher 3 Wild Hunt GOTY",
                        "game": "witcher",
                        "game_name": "The Witcher 3: Wild Hunt",
                    }
                ],
            ),
            ("empty", "Sin descartes", []),
        )
    },
)

STEAM_FORGET = dict(
    summary="Olvidar un descarte",
    description="Borra el descarte: el par vuelve a poder proponerse cuando la Deck reenvíe su lista." + _NOSTORE,
    responses={
        200: _ok(SteamForgotten, "Olvidado.", ("ok", "Olvidado", {"id": "aB3dE9fG", "forgotten": True})),
        404: R404_DISMISSED,
    },
)
