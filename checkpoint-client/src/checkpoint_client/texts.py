"""Todos los textos visibles del cliente (CLI en español, sin i18n, como la CLI del hub y el plugin).

Son los «Textos aprobados» de la tarjeta, tal cual, más los que el usuario aprobó después (sección «Aprobados fuera de
la tarjeta»). Un texto que el comando necesita y aún no está aprobado va en una sección «Pendientes de aprobar» al final,
marcado como tal (ahora mismo no hay ninguno). Los errores se escriben en stderr.
"""

# ---------------------------------------------------------------- ayuda de la CLI
HELP_ROOT = "checkpoint-client: sincroniza los guardados de tus juegos con el hub de Checkpoint, sin SSH"
HELP_LINK = "vincula este equipo con el hub (código de 6 dígitos que se acepta en la web)"
HELP_LINK_HUB = "dirección del hub, p. ej. http://192.168.1.10:8088"
HELP_LINK_NAME = "nombre de este equipo en el hub (por defecto el del equipo; máximo 64 caracteres)"
HELP_GAMES = "lista los juegos del hub para este equipo y su estado"
HELP_GAMES_CHECK = "compara con el hub sin cambiar nada"
HELP_SYNC = "sincroniza un juego (o todos con --all) con el hub"
HELP_SYNC_DRY_RUN = "solo comprueba: no cambia nada"
HELP_SYNC_RESOLVE = "resuelve un conflicto: hub o este equipo"
HELP_RUN = "baja el guardado, lanza el juego y lo sube al cerrarlo: checkpoint-client run <juego> -- <comando>"
HELP_WATCH = "vigila los juegos del hub y sube su guardado al cerrarse"
HELP_INSTALL = "deja el vigilante arrancando solo al iniciar sesión (systemd --user en Linux)"
HELP_UNINSTALL = "quita el arranque automático (no borra la vinculación ni los datos)"
HELP_STATUS = "muestra la vinculación, la conexión con el hub, el vigilante y la versión"
HELP_UNLINK = "borra la clave de este equipo (la revocación real se hace en el hub, en Dispositivos)"
HELP_VERSION = "muestra la versión instalada"
HELP_CHECK_UPDATE = "comprueba si hay una versión nueva (no instala nada)"

# ---------------------------------------------------------------- vinculación
LINK_CODE = (
    "Código de vinculación: {code}. Acéptalo en el hub (Configuración > Biblioteca > Solicitudes de vinculación). "
    "Caduca en 10 minutos."
)


def spaced_code(code: str) -> str:
    """Código de 6 dígitos en dos grupos de 3 (123456 -> 123 456), como en el texto aprobado."""
    return f"{code[:3]} {code[3:]}"


LINK_WAITING = "Esperando aceptación en el hub… (Ctrl+C para cancelar)"
LINK_DONE = "Vinculado a {device}. Clave guardada en {where}."
LINK_REJECTED = "El hub rechazó la solicitud. Vuelve a ejecutar «checkpoint-client link» si fue un error."
LINK_EXPIRED = "La solicitud caducó. Vuelve a ejecutar «checkpoint-client link»."
LINK_BAD_URL = "La dirección no es válida. Usa http://servidor:puerto."
LINK_ALREADY = "Este equipo ya está vinculado a {device}. Usa --force para vincular de nuevo."

# ---------------------------------------------------------------- sincronización
SYNC_DOWNLOADING = "{game}: bajando del hub ({n} ficheros)…"
SYNC_UPLOADING = "{game}: subiendo al hub ({n} ficheros)…"
SYNC_DOWNLOADED = "{game}: bajado ({n} ficheros). Tu carpeta anterior quedó en «{path}.checkpoint-backup»."
SYNC_UPLOADED = "{game}: subido ({n} ficheros)."
SYNC_UP_TO_DATE = "{game}: al día."
SYNC_CONFLICT = "CONFLICTO en {game}: hay cambios en este equipo y en el hub. No se ha tocado nada."
SYNC_CONFLICT_HOW = "Resuélvelo con: checkpoint-client sync {game} --resolve hub|device"
SYNC_NO_GAMES = "No hay juegos para este equipo en el hub."
SYNC_NO_PATH = "{game}: sin ruta en el hub, se omite."
SYNC_DISABLED = "{game}: desactivado, se omite."
SYNC_MISSING_DIR = "{game}: carpeta no encontrada, se omite."
SYNC_RUNNING = "{game} está abierto: no se sincroniza. Ciérralo y vuelve a intentarlo."
SYNC_ITEM = "Juego {i}/{n} ({name}): {message}"
SYNC_SUMMARY = "{ok} al día o sincronizados, {c} en conflicto, {e} con error."

# ---------------------------------------------------------------- vigilante
WATCH_START = "Vigilando {n} juegos. Ctrl+C para salir."
WATCH_OPENED = "{game} abierto."
WATCH_CLOSED = "{game} cerrado: subiendo guardado…"
WATCH_OFFLINE = "{game} cerrado, pero el hub no responde: se reintentará."
WATCH_NO_PROCESS = "{game} no tiene proceso configurado en el hub: no se puede vigilar."
WATCH_ALREADY_OPEN = "{game} ya estaba abierto: se subirá al cerrarlo, no se baja."
WATCH_STOPPED = "Vigilante detenido."

# ---------------------------------------------------------------- instalación
INSTALL_DONE = (
    "Instalado: el vigilante arrancará al iniciar sesión (unidad systemd --user «checkpoint-client»). "
    "Estado: systemctl --user status checkpoint-client."
)
INSTALL_FAILED = "No se pudo crear la unidad systemd --user: {reason}. No se ha cambiado nada."
INSTALL_NO_SYSTEMD = "systemd --user no está disponible en esta sesión."
INSTALL_ONLY_LINUX = "El arranque automático solo está disponible en Linux (systemd)."

# ---------------------------------------------------------------- versión
UPDATE_UP_TO_DATE = "El cliente está al día ({v})."
UPDATE_AVAILABLE = "Hay una versión nueva: {v} (instalada: {c})."
UPDATE_COMMAND = "pipx install --force {url}"
UPDATE_FAILED = "No se pudo comprobar la versión nueva: {reason}."

# ---------------------------------------------------------------- errores
ERR_CONNECTION = "No se pudo conectar con el hub. Revisa la dirección y la red. Hub: {url}."
ERR_UNAUTHORIZED = (
    "El hub no acepta la clave de este equipo. Quizá se revocó: ejecuta «checkpoint-client link» de nuevo."
)
ERR_NOT_LINKED = "Este equipo no está vinculado. Ejecuta «checkpoint-client link <hub>»."
ERR_CLIENT_OUTDATED = (
    "Este cliente es demasiado antiguo para el hub (exige el protocolo {min} y este es el {n}). "
    "Actualízalo; mientras tanto no se sincroniza."
)
ERR_HUB_OLD = (
    "El hub es de una versión antigua (no anuncia su protocolo): puede que algo no funcione. Actualiza el hub."
)
ERR_PATH_FORBIDDEN = "Ruta no permitida: el hub indica una carpeta que este equipo no acepta ({path}). No se toca nada."
ERR_RATE_LIMITED = "El hub pide esperar antes de otra petición. Espera {s} s."
ERR_HUB_ERROR = "El hub respondió con un error inesperado. Mira sus registros."
ERR_UNEXPECTED = "Fallo inesperado en el cliente. Mira el registro: {log}."

# Códigos del motor de sincronización: los de checkpoint-deck/src/texts.ts cambiando «Deck» por «este equipo».
SYNC_ERRORS = {
    "busy": "Ya hay una sincronización de este juego en marcha.",
    "unknown_game": "El hub ya no tiene este juego.",
    "hub_changed": "El hub cambió mientras se subía. Vuelve a intentarlo.",
    "commit_rejected": "El hub rechazó la subida porque tiene cambios más recientes. Vuelve a comprobar.",
    "upload_incomplete": "El hub no recibió todos los ficheros. Vuelve a intentarlo.",
    "set_mismatch": "El hub no pudo verificar los ficheros subidos. Vuelve a intentarlo.",
    "file_changed": "Un fichero cambió mientras se subía. Cierra el juego y vuelve a intentarlo.",
    "file_too_large": "Hay un fichero demasiado grande (máximo 512 MB por fichero). No se sube nada.",
    "too_many_files": "La carpeta tiene demasiados ficheros (máximo 50 000). No se sincroniza.",
    "staging_full": "El hub no tiene espacio para recibir la subida.",
    "hub_busy": "El hub está ocupado con este juego. Inténtalo en un momento.",
    "bad_name": "Hay un nombre de fichero que no se puede enviar. No se sincroniza.",
    "unreadable": "No se pudo leer un fichero o carpeta del juego.",
    "empty_dir": "La carpeta está vacía: no se sube nada.",
    "hub_empty": "El hub no tiene ficheros de este juego.",
    "bad_manifest": "El hub envió una lista de ficheros no válida. No se toca nada.",
    "no_space": "No hay espacio libre suficiente en este equipo para bajar los ficheros.",
    "verify_failed": "Los ficheros bajados no coinciden con los del hub. Tu carpeta sigue intacta.",
    "inconsistent": "Se bajaron los ficheros, pero el hub no los da por iguales. Revisa el juego en el hub.",
    "io_error": "Error de disco en este equipo. Tu carpeta no se ha modificado a medias.",
    "cancelled": "Cancelado. Tu carpeta no se ha modificado a medias.",
    "bad_winner": "Opción de resolución no válida.",
    "resolution_unsupported": "El hub no admite esta función: actualízalo.",
    "resolution_stale": "Los datos cambiaron mientras se resolvía. Vuelve a elegir.",
    "side_empty": "El lado elegido no tiene datos: no se puede usar para resolver.",
}

# ---------------------------------------------------------------- aprobados fuera de la tarjeta (los aprobó el usuario)
# Salida de `games` y `status`: valores técnicos sin prosa (TSV y `clave: valor`).
STATUS_LINE = "{key}: {value}"
STATUS_KEYS = {
    "hub": "hub",
    "device": "dispositivo",
    "connection": "conexión",
    "protocol": "protocolo",
    "version": "versión",
    "watch": "vigilante",
}
STATUS_OK = "ok"
STATUS_WATCH_ACTIVE = "activo"
STATUS_WATCH_STOPPED = "parado"
# Resultado de `sync --dry-run` y de `games --check`.
CHECK_UPLOAD = "{game}: hay cambios en este equipo (se subirían)."
CHECK_DOWNLOAD = "{game}: hay cambios en el hub (se bajarían)."
# Errores de uso que la tarjeta no cubre.
ERR_NAME_INVALID = "--name: " + HELP_LINK_NAME
ERR_NEED_GAME = "Indica un juego o usa --all."
ERR_BAD_RESOLVE = "--resolve solo admite hub o device."
ERR_RUN_NO_COMMAND = "Falta el comando: checkpoint-client run <juego> -- <comando>."
ERR_RUN_LAUNCH = "No se pudo lanzar el comando: {reason}."
ERR_GAME_UNKNOWN = "{game}: el hub no tiene ese juego para este equipo."

# Segundo `watch` a la vez (exclusión mutua entre procesos del cliente).
WATCH_RUNNING = "Ya hay un vigilante en marcha."
# `sync` manual con el juego abierto y un vigilante activo.
SYNC_RUNNING_WATCHED = "{game} está abierto: no se sincroniza. El vigilante lo sincronizará al cerrarlo."

# `uninstall` en Linux hace `disable --now`: PARA el vigilante de systemd (el texto de la tarjeta es el de Windows).
UNINSTALL_DONE_LINUX = "Desinstalado el arranque automático y detenido el vigilante de systemd."
# Fallo al quitar la unidad (la tarjeta solo aprueba el fallo al crearla).
UNINSTALL_FAILED = "No se pudo quitar la unidad systemd --user: {reason}."

# Dónde se guarda la clave (textos de «Instalación» de la tarjeta; «llavero» y «fichero» son los valores de
# «Clave guardada en {llavero|fichero}» de la vinculación).
KEYRING_SAVED = "Clave guardada en el llavero del sistema."
# Migración de una clave antigua de settings.json al llavero que falla (aprobado por el usuario; stderr, una vez por ejecución).
KEYRING_MIGRATION_FAILED = "No se pudo mover la clave al llavero; se mantiene en {path}."
KEYRING_UNAVAILABLE = "No hay llavero disponible: la clave se guarda en {path} (solo legible por tu usuario)."
# Hay vinculación con `key_store=keyring` pero el llavero no devuelve la clave (aprobado por el usuario; stderr, salida 1).
KEYRING_LOCKED = (
    "No se pudo leer la clave del llavero (bloqueado o borrada). "
    "Desbloquéalo o ejecuta «checkpoint-client link --force»."
)
LOCATION_KEYRING = "llavero"
LOCATION_FILE = "fichero"

# ---------------------------------------------------------------- aprobados fuera de la tarjeta
# El «{motivo}» de «No se pudo comprobar la versión nueva: {motivo}.» (aprobados por el usuario). Claves = `UpdateError.reason`.
UPDATE_REASONS = {
    "network": "no se pudo conectar con GitHub",
    "timeout": "GitHub no respondió a tiempo",
    "rate_limited": "GitHub limitó las consultas, inténtalo más tarde",
    "http": "GitHub respondió con un error",
    "invalid": "la respuesta de GitHub no es válida",
}
