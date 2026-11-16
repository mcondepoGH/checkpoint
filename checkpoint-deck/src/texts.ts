// Textos de error compartidos por el panel (index.tsx) y los avisos automáticos (autosync.ts).

export function wait(s?: number): string {
  return s && s > 0 ? ` Espera ${s} s.` : "";
}

// Errores de un juego (`code` de main.py / sync) y de una tarea entera (`error`)
export const SYNC_ERRORS: Record<string, string> = {
  busy: "Ya hay una sincronización de este juego en marcha.",
  game_running: "El juego está abierto: no se sincroniza a mano. Ciérralo y se sincroniza solo.",
  unknown_game: "El hub ya no tiene este juego.",
  path_forbidden: "Ruta no permitida: el hub indica una carpeta que la Deck no acepta. No se toca nada.",
  hub_changed: "El hub cambió mientras se subía. Vuelve a intentarlo.",
  commit_rejected: "El hub rechazó la subida porque tiene cambios más recientes. Vuelve a comprobar.",
  upload_incomplete: "El hub no recibió todos los ficheros. Vuelve a intentarlo.",
  set_mismatch: "El hub no pudo verificar los ficheros subidos. Vuelve a intentarlo.",
  file_changed: "Un fichero cambió mientras se subía. Cierra el juego y vuelve a intentarlo.",
  file_too_large: "Hay un fichero demasiado grande (máximo 512 MB por fichero). No se sube nada.",
  too_many_files: "La carpeta tiene demasiados ficheros (máximo 50 000). No se sincroniza.",
  staging_full: "El hub no tiene espacio para recibir la subida.",
  hub_busy: "El hub está ocupado con este juego. Inténtalo en un momento.",
  bad_name: "Hay un nombre de fichero que no se puede enviar. No se sincroniza.",
  unreadable: "No se pudo leer un fichero o carpeta del juego.",
  empty_dir: "La carpeta está vacía: no se sube nada.",
  hub_empty: "El hub no tiene ficheros de este juego.",
  bad_manifest: "El hub envió una lista de ficheros no válida. No se toca nada.",
  no_space: "No hay espacio libre suficiente en la Deck para bajar los ficheros.",
  verify_failed: "Los ficheros bajados no coinciden con los del hub. Tu carpeta sigue intacta.",
  inconsistent: "Se bajaron los ficheros, pero el hub no los da por iguales. Revisa el juego en el hub.",
  io_error: "Error de disco en la Deck. Tu carpeta no se ha modificado a medias.",
  cancelled: "Cancelado. Tu carpeta no se ha modificado a medias.",
  connection: "No se pudo conectar con el hub. Revisa la dirección y la red.",
  unauthorized: "La clave ya no vale: vuelve a vincular.",
  rate_limited: "El hub pide esperar antes de otra petición.",
  hub_error: "El hub respondió con un error inesperado. Mira sus registros.",
  not_linked: "Primero vincula la Deck con el hub.",
  no_steam: "No se encontró ninguna biblioteca de Steam en la Deck.",
  config_changed: "La configuración del hub cambió a la vez. Vuelve a intentarlo.",
  unexpected: "Fallo inesperado en el plugin. Mira el registro de Decky.",
  bad_winner: "Opción de resolución no válida.",
  resolution_unsupported: "El hub no admite esta función: actualízalo.",
  resolution_stale: "Los datos cambiaron mientras se resolvía. Vuelve a elegir.",
  side_empty: "El lado elegido no tiene datos: no se puede usar para resolver.",
  plugin_outdated: "Este plugin es demasiado antiguo para el hub. Actualiza el plugin para volver a sincronizar.",
};

export function syncError(code: string, params?: { wait_s?: number }): string {
  return (SYNC_ERRORS[code] ?? SYNC_ERRORS.hub_error) + wait(params?.wait_s);
}


// ---- actualizaciones del plugin (main.py: get_version / check_update) ----
// El plugin solo AVISA de la versión nueva; se actualiza con «Instalar plugin desde URL» de Decky.
export interface UpdateInfo {
  state?: string;
  current?: string | null;
  latest?: string | null;
  hub_url?: string;
  reason?: string | null;
  error?: string;
}

export const UPDATE_ERRORS: Record<string, string> = {
  hub_old: "El hub es de una versión antigua (no anuncia su protocolo): actualiza el hub para comprobar actualizaciones del plugin.",
  connection: "No se pudo conectar con el hub. Revisa la dirección y la red.",
  unauthorized: "La clave ya no vale: vuelve a vincular.",
  rate_limited: "El hub pide esperar antes de otra petición.",
  hub_error: "El hub respondió con un error inesperado. Mira sus registros.",
  not_linked: "Primero vincula la Deck con el hub.",
  unavailable: "El hub no tiene el plugin empaquetado.",
  unknown: "No se pudo leer la versión instalada del plugin.",
  unexpected: "Fallo inesperado al buscar actualizaciones. Mira el registro de Decky.",
};

export function updateError(code: string): string {
  return UPDATE_ERRORS[code] ?? UPDATE_ERRORS.unexpected;
}

// `compat` del ping: ok | plugin_outdated | hub_old | plugin_unknown. null = nada que avisar.
export function describeCompat(
  compat?: string,
  p?: { min_plugin_protocol?: number | null; plugin_protocol?: number | null },
): string | null {
  switch (compat) {
    case "plugin_outdated":
      return `Actualiza el plugin: este hub exige el protocolo ${p?.min_plugin_protocol ?? "?"} o superior y este plugin es el ${p?.plugin_protocol ?? "?"}. Mientras tanto no se sincroniza.`;
    case "hub_old":
      return "El hub es de una versión antigua (no anuncia su protocolo): puede que algo no funcione. Actualiza el hub.";
    case "plugin_unknown":
      return "No se pudo leer la versión del protocolo de este plugin: no se puede comprobar la compatibilidad.";
    default:
      return null;
  }
}

export function describeUpdate(u: UpdateInfo): string {
  switch (u.state) {
    case "up_to_date":
      return `El plugin está al día (${u.current ?? "?"}).`;
    case "available":
      if (u.reason === "hub_old") return `${UPDATE_TITLE(u.latest)} (instalada: ${u.current ?? "?"}). ${UPDATE_ERRORS.hub_old}`;
      return `${UPDATE_TITLE(u.latest)} (instalada: ${u.current ?? "?"}).`;
    case "unavailable":
      return UPDATE_ERRORS.unavailable;
    case "not_linked":
      return UPDATE_ERRORS.not_linked;
    case "error":
      return updateError(u.error ?? "unexpected");
    default:
      return updateError("unknown");
  }
}

// «Instalar plugin desde URL» de Decky acepta esta dirección (http); comprobado en una Deck real. Que recargue el plugin sin reiniciar puede variar según la versión de Decky.
export function pluginUrl(hub: string): string {
  return `${hub.replace(/\/+$/, "")}/api/deck/plugin`;
}

export const UPDATE_TITLE = (latest?: string | null) => `Actualización disponible: ${latest ?? "?"}`;
export const UPDATE_STEPS = [
  "1) Ajustes de Decky > Desarrollador > Instalar plugin desde URL.",
  "2) Pega esta dirección:",
  "3) Reinicia Decky si no se recarga solo.",
];
export const COPY_BUTTON = "Copiar dirección";
export const COPY_OK = "Dirección copiada";
export const COPY_FAIL = "No se pudo copiar: selecciona y escribe la dirección";


// ---- panel «Juegos»: textos fijos (index.tsx) ----
export const GAMES_INTRO =
  "Al abrir un juego se cargan los datos guardados más actuales; al cerrarlo se guardan en el hub.";
export const SEARCH_LABEL = "Buscar juegos de Steam";
export const SEARCH_HELP =
  "Mira qué juegos hay instalados en la Deck y los enlaza con los del hub. Úsalo tras instalar un juego nuevo.";
export const CHECK_LABEL = "Comprobar cambios pendientes";
export const CHECK_HELP =
  "Compara tus guardados con los del hub sin cambiar nada y dice qué juegos tienen algo que subir o bajar.";
export const TOGGLE_HELP =
  "El interruptor activa o desactiva el juego en el hub, para todos tus dispositivos. Desactivado no se sincroniza.";
export const UNCONFIGURED_HELP =
  "Instalados en la Deck pero sin juego en el hub. Configúralos aquí: el nombre y la ruta de guardado se rellenan solos si se detectan.";
export const NO_PATH_FOUND = "No se encontró ninguna carpeta de guardado que exista: escríbela (ruta completa) o usa Examinar….";
export const PATH_FOUND: Record<string, string> = {
  proton: "Ruta detectada en el prefijo de Proton del juego. Revísala y confirma.",
  cloud: "Ruta detectada en los guardados de Steam Cloud. Revísala y confirma.",
  manifest: "Carpeta elegida de las sugerencias de guardado. Revísala y confirma.",
  lutris: "Candidatos encontrados en el prefijo de Lutris; elige la carpeta de partidas guardadas o usa Examinar…",
};
export const NO_PATH_LUTRIS = "No se encontró ninguna carpeta de partidas en el prefijo; usa Examinar…";

/** Ayuda bajo «Carpeta de guardado»: qué se detectó (`source`) y si hay ruta. Un atajo de Lutris sin candidatos tiene la suya. */
export function pathHelp(path: string, source?: string): string {
  if (source === "lutris") return path ? PATH_FOUND.lutris : NO_PATH_LUTRIS;
  return path && source ? PATH_FOUND[source] : NO_PATH_FOUND;
}

export interface GameFailure {
  ok?: boolean;
  error?: string;
  error_params?: { wait_s?: number; field?: string; reason?: string; code?: string };
  error_detail?: string | null;
}

// Causa que el hub da al rechazar un juego nuevo (`err.config.*`)
export const GAME_REASONS: Record<string, string> = {
  "err.config.name_duplicate":
    "Ya hay un juego con ese nombre en el hub. Si es el mismo, acepta la sugerencia en el hub; si no, usa otro nombre.",
  "err.steam.no_free_slot": "El juego ya tiene 2 dispositivos.",
  "err.steam.appid_mismatch": "Ese nombre ya existe con otro juego de Steam.",
  "err.steam.appid_in_use": "Ese juego de Steam ya lo usa otro juego del hub.",
  "err.config.steam_appid_duplicate": "Este juego de Steam ya está en el hub con otro nombre.",
  "err.config.name_empty": "Escribe un nombre.",
  "err.config.name_spaces": "El nombre no puede llevar espacios dobles ni al principio o al final.",
  "err.config.name_too_long": "El nombre es demasiado largo (máximo 64 caracteres).",
  "err.config.name_slash": "El nombre no puede llevar «/» ni «\\».",
  "err.config.name_control": "El nombre lleva caracteres no permitidos.",
  "err.config.name_dots": "El nombre no puede ser solo puntos.",
  "err.config.path_absolute": "La ruta debe empezar por «/».",
  "err.config.path_chars": "La ruta lleva caracteres que el hub no acepta.",
  "err.config.path_dotdot": "La ruta no puede llevar «..».",
  "err.config.path_root": "La ruta no puede ser la raíz.",
};
const GAME_FIELDS: Record<string, string> = {
  name: "El hub no acepta ese nombre.",
  path: "El hub no acepta esa ruta.",
  appid: "El hub no acepta ese juego de Steam.",
};

// ---- toasts cortos: el cuerpo entero cabe en `TOAST_MAX` caracteres (si no, Decky lo corta). Los detalles van al panel y al log.
export const TOAST_MAX = 45;
const NAME_MAX = 22;
/** «<nombre>: <resto>» sin pasar de `TOAST_MAX`: el nombre se recorta (máx. 22) con «…», el resto no. */
export function toastLine(name: string, rest: string): string {
  const room = Math.max(1, Math.min(NAME_MAX, TOAST_MAX - [...rest].length - 2));
  const chars = [...name];
  const shown = chars.length <= room ? name : `${chars.slice(0, Math.max(1, room - 1)).join("")}…`;
  return `${shown}: ${rest}`;
}

/** Aviso al unirse este dispositivo a un juego que el hub ya tenía (respuesta `joined: true`). */
export const joinedText = (name: string): string => toastLine(name, "unido a este equipo");

// ---- resolver un conflicto de datos (panel «Juegos en el hub»; main.py: resolve_conflict) ----
export const RESOLVE_HUB_LABEL = "Usar datos del hub";
export const RESOLVE_DEVICE_LABEL = "Usar datos de este equipo";
export const RESOLVE_HELP =
  "Conflicto: los datos del hub y los de esta Deck han cambiado. Elige cuáles se quedan; se guarda una copia de los otros y se sincroniza al momento.";
export interface ResolveConfirm {
  title: string;
  description: string;
  ok: string;
}
export function resolveConfirm(winner: "hub" | "device", name: string): ResolveConfirm {
  const title = `Resolver el conflicto de ${name}`;
  return winner === "hub"
    ? {
        title,
        description:
          "Se bajarán los datos del hub y sustituirán los de esta Deck. Tu carpeta actual queda como copia en «<carpeta>.checkpoint-backup», junto a la del juego.",
        ok: RESOLVE_HUB_LABEL,
      }
    : {
        title,
        description:
          "Se subirán los datos de esta Deck al hub. El hub guarda antes una versión con los que tiene ahora (la verás en Versiones).",
        ok: RESOLVE_DEVICE_LABEL,
      };
}
/** Texto de un juego en conflicto: el genérico o, si el último intento de resolverlo falló, el motivo (`code`). */
export function conflictText(g: { state?: string; code?: string }): string {
  return g.code && SYNC_ERRORS[g.code]
    ? `Conflicto sin resolver. ${syncError(g.code)}`
    : "Conflicto: cambios en los dos lados, no se toca nada";
}

/** Texto de un fallo al configurar o activar un juego (`GameFailure` de main.py). */
export function gameError(f: GameFailure): string {
  const code = f.error ?? "unexpected";
  const p = f.error_params ?? {};
  switch (code) {
    case "game_invalid":
      return (
        (p.reason && GAME_REASONS[p.reason]) ||
        (p.field && GAME_FIELDS[p.field]) ||
        "El hub no acepta los datos de este juego."
      );
    case "path_forbidden":
      return "Esa carpeta no se puede usar (sistema, Steam o Decky). Elige la carpeta de guardado del juego.";
    case "path_missing":
      return "La carpeta no existe o no es una carpeta. No se ha creado el juego: crea la carpeta, o elige otra con Examinar… o escribe la ruta de una que exista.";
    case "path_vanished":
      return "La carpeta sugerida ya no existe o ya no es una carpeta. No se ha creado el juego: elige otra con Examinar… o escribe la ruta.";
    case "unknown_game":
      return "Ese juego ya no está en la lista. Busca de nuevo los juegos de Steam.";
    default:
      return syncError(code, p);
  }
}

// ---- selector de carpetas nativo de Decky (`openFilePicker`) en el formulario «Configurar» ----
export const BROWSE_LABEL = "Examinar…";
export const BROWSE_HELP = "Abre el selector de carpetas de Decky, o escribe la ruta completa.";
/** Fallo conocido del selector de Decky (su frontend hace `theError.match` sobre un error que llega como objeto). */
export const PICKER_FAIL = "Decky no puede abrir esa carpeta; escribe la ruta.";

/** Argumentos de `openFilePicker` tras el tipo de selección, todos explícitos y aceptados por `filepicker_ls` de Decky:
 *  inicio, ficheros no, carpetas sí, filtro y extensiones sin definir (llegan como null; un RegExp viajaría como `{}` y el
 *  backend lanza), ocultos sí, «todos los ficheros» sí, máximo numérico. `start` debe venir ya validado por `picker_start`. */
export function pickerArgs(
  start: string,
): [string, boolean, boolean, undefined, undefined, boolean, boolean, number] {
  return [start, false, true, undefined, undefined, true, true, 1000];
}

// ---- último aviso (0.2.3) ----
export interface LastNotice {
  time: string;
  text: string;
}
export function lastNoticeText(n: LastNotice | null): string {
  return n ? `Último aviso: ${n.time} — ${n.text}` : "Último aviso: Ninguno todavía";
}

// ---- interruptor «Mostrar juegos sin configurar» (oculta TODA la sección «Sin configurar en el hub») ----
export const SHOW_UNCONFIGURED_LABEL = "Mostrar juegos sin configurar";
export const SHOW_UNCONFIGURED_HELP = "Muestra u oculta la lista «Sin configurar en el hub».";
export function hiddenUnconfiguredText(n: number): string {
  return n === 1 ? "1 juego sin configurar oculto" : `${n} juegos sin configurar ocultos`;
}
// Qué se pinta de esa sección: la lista entera (con su formulario) o, si está oculta, solo el conteo (sin nombres)
export function unconfiguredView(show: boolean, count: number): { showList: boolean; hiddenNote: string | null } {
  if (count <= 0) return { showList: false, hiddenNote: null };
  return show ? { showList: true, hiddenNote: null } : { showList: false, hiddenNote: hiddenUnconfiguredText(count) };
}

// ---- atajos de Steam (juegos que no son de Steam, p. ej. Lutris) en «Sin configurar en el hub» ----
export const SHORTCUT_LABEL = "Atajo";
export const SHORTCUT_HELP =
  "Los marcados como «Atajo» son juegos que no son de Steam (p. ej. Lutris) añadidos a Steam. Si el atajo lanza un juego de Lutris, se ofrecen como candidatas las carpetas de partidas que existan en su prefijo (elige una o usa «Examinar…», que abre en el prefijo). En los demás atajos la carpeta no se detecta: escríbela o usa «Examinar…».";
// Línea de descripción de un juego sin configurar: un atajo lo dice; su número no es un id de la tienda de Steam
export function unconfiguredDescription(appid: number, source?: string): string {
  return source === "shortcut" ? `${SHORTCUT_LABEL} · N.º de Steam: ${appid}` : `N.º de Steam: ${appid}`;
}

// ---- «Sugerencias de guardado» (main.py: suggest_saves / apply_save_suggestion): carpetas exactas del manifiesto propio ----
export const SAVES_TITLE = "Sugerencias de guardado";
export const SAVES_INTRO =
  "Busca la carpeta de guardado de los juegos instalados que aún no están en el hub. Nada se añade sin que lo confirmes.";
export const SAVES_BUTTON = "Sugerir carpeta";
export const SAVES_AGAIN = "Buscar de nuevo";
export const SAVES_LOADING = "Buscando carpetas de guardado… Puede tardar unos segundos si hay que consultar lutris.net.";
export const SAVES_EMPTY =
  "No hay juegos sin configurar con carpeta sugerida: o ya están en el hub o no coinciden con la lista de rutas.";
export const SAVES_NO_MANIFEST =
  "Este plugin no lleva la lista de rutas de guardado (save_manifest.json), así que no puede sugerir carpetas. Instala un ZIP del plugin que la incluya.";
export const SAVES_SETTINGS = "Ajustes de las sugerencias";
export const SAVES_LOOKUP_LABEL = "Consultar lutris.net para identificar juegos de Lutris";
export const SAVES_LOOKUP_HELP =
  "Solo se envía el nombre interno del juego (slug), una vez por juego y sin datos personales. Sin esto, algunos juegos de Lutris salen como dudosos o no salen.";
export const SAVES_NOT_FOUND = "No encontrada aún";
export const SAVES_DOUBTFUL = "dudosa";
export const SAVES_ADD = "Añadir al hub";
export const SAVES_REVIEW = "Revisar y añadir";
export const SAVES_ADDED = "Añadido";
export const SAVES_MANUAL = "Añadir manualmente";
export const SAVES_MANUAL_ALL = "Añadir un juego manualmente";
export const SAVES_MANUAL_ALL_HIDE = "Cerrar la lista";
export const SAVES_MANUAL_ALL_HELP = "Elige uno de los juegos instalados que aún no están en el hub y rellena su nombre y carpeta a mano.";
export const SAVES_MANUAL_EMPTY = "No hay juegos sin configurar. Pulsa «Buscar juegos de Steam» en «Juegos» y vuelve a intentarlo.";
export const SAVES_DOUBTFUL_GAME = "Coincidencia dudosa: comprueba que es de este juego antes de guardar.";
export const SAVES_NOT_FOUND_GAME = "La carpeta aún no existe (se crea al jugar o guardar por primera vez). Puedes añadirlo a mano.";
export type CardBadge = "safe" | "doubtful" | "not_found";
export const SAVES_BADGES: Record<CardBadge, string> = { safe: "Segura", doubtful: "Dudosa", not_found: SAVES_NOT_FOUND };
export function savesOthers(n: number, open: boolean): string {
  return open ? `Ocultar otras rutas (${n})` : `Ver otras rutas (${n})`;
}
export function savesSummary(n: number): string {
  return n === 1 ? "1 juego sin configurar con sugerencia." : `${n} juegos sin configurar con sugerencia.`;
}
export const SAVES_ERRORS: Record<string, string> = {
  no_manifest: SAVES_NO_MANIFEST,
  no_match: "Ese juego ya no está instalado o no está en la lista de rutas.",
  bad_args: "Petición no válida.",
  not_suggested: "Esa carpeta ya no es una de las sugeridas. Vuelve a pulsar «Buscar de nuevo».",
  path_missing: "La carpeta sugerida ya no existe o no se puede usar. No se ha cambiado nada.",
  not_unconfigured:
    "Este juego no está en «Sin configurar en el hub» (ya está en el hub o no se ha buscado). Pulsa «Buscar juegos de Steam» y vuelve a intentarlo.",
  plugin_outdated: "Este plugin es demasiado antiguo para el hub. Actualiza el plugin.",
  unexpected: "Fallo inesperado en el plugin. Mira el registro de Decky.",
};
export function saveError(code?: string): string {
  return (code && SAVES_ERRORS[code]) || SAVES_ERRORS.unexpected;
}
export function lookupsPendingText(n: number): string {
  return n === 1
    ? "Queda 1 juego de Lutris por consultar a lutris.net: vuelve a pulsar «Buscar de nuevo»."
    : `Quedan ${n} juegos de Lutris por consultar a lutris.net: vuelve a pulsar «Buscar de nuevo».`;
}

export function formatSize(bytes?: number | null): string {
  if (typeof bytes !== "number" || bytes < 0) return "tamaño desconocido";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 ? 1 : 0).replace(".", ",")} ${units[i]}`;
}
/** Fecha local dd/mm/aaaa de un mtime en segundos (época Unix); "fecha desconocida" si no hay. */
export function formatDate(mtime?: number | null): string {
  if (typeof mtime !== "number" || !isFinite(mtime) || mtime <= 0) return "fecha desconocida";
  const d = new Date(mtime * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`;
}
export interface SavePath {
  path: string;
  exists: boolean;
  mtime?: number | null;
  size?: number | null;
  files?: number | null;
  truncated?: boolean;
  doubtful?: boolean;
}
/** Línea de detalle de una ruta candidata: tamaño, ficheros y fecha (existe) o «No encontrada aún»; «dudosa» si lo es. */
export function savePathDetail(p: SavePath): string {
  const tag = p.doubtful ? ` · ${SAVES_DOUBTFUL}` : "";
  if (!p.exists) return `${SAVES_NOT_FOUND}${tag}`;
  const n = p.files ?? 0;
  const files = `${n}${p.truncated ? "+" : ""} ${n === 1 && !p.truncated ? "fichero" : "ficheros"}`;
  return `${formatSize(p.size)} · ${files} · modificada ${formatDate(p.mtime)}${tag}`;
}
export interface SaveConfirm {
  title: string;
  description: string;
  ok: string;
}
/** Modal de «Añadir al hub»: juego y carpeta; al confirmar se aplica la sugerencia y se guarda en el hub. */
export function saveConfirm(name: string, path: string): SaveConfirm {
  return {
    title: "¿Añadir al hub?",
    description: `${name}\nCarpeta de guardado: ${path}\nSe creará el juego en el hub con esta carpeta.`,
    ok: SAVES_ADD,
  };
}
