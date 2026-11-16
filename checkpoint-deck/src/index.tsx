import { MutableRefObject, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  Field,
  Focusable,
  GamepadButton,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  showModal,
  staticClasses,
} from "@decky/ui";
import { FileSelectionType, callable, definePlugin, openFilePicker, toaster } from "@decky/api";
import { FaChevronDown, FaChevronUp, FaCloud, FaCog } from "react-icons/fa";
import { CrashItem, CrashWatch, startCrashWatch } from "./crashwatch";
import { copyText } from "./clipboard";
import { drafts } from "./drafts";
import { CardKind, SaveGame, bestPath, cardKind, gameKey, otherPaths, unconfiguredOnly } from "./suggestions";
import { Notice, RunningApps, ToastKind, getLastNotice, startGameWatch, startNoticePump } from "./autosync";
import {
  Banner,
  Level,
  SyncGate,
  TabInput,
  Tally,
  VersionNotifier,
  banners,
  canSyncRest,
  conflictGames,
  countStates,
  errorGames,
  firstPlan,
  gameBadge,
  gameExpanded,
  hasUpdate,
  homeStatus,
  latestSync,
  playingGame,
  progressRows,
  stepTab,
  summaryLevel,
  syncBlockReason,
  tabDisabled,
  tabDot,
  tally,
  updatedTo,
  whenText,
} from "./panel";
import { BannerList, Bar, LongText, MONO, MUTED, RunList, StatusBadge, TONE_COLOR, TabBar, WRAP, showToast } from "./ui";
import {
  BANNER,
  CHANGED_IGNORE,
  CHANGED_TITLE,
  CHANGED_VIEW,
  CHANGE_FOLDER,
  CHANGE_FOLDER_HELP,
  COMING_SOON,
  DETAIL_ERROR,
  DETAIL_FOLDER_MISSING,
  DETAIL_HISTORY_NOTE,
  DETAIL_LAST_COPY,
  DETAIL_LOADING,
  DETAIL_NO_COPY,
  DETAIL_SIZE,
  FIRST_CHECKING,
  FIRST_TEXT,
  FIRST_TITLE,
  GAME_BACK,
  GAME_DETAIL,
  GAME_ENABLED,
  GAME_ENABLED_HELP,
  GAME_FOLDER,
  GAME_LAST_SYNC,
  GAME_OPEN_HINT,
  HOME_CONNECTION,
  HOME_HUB,
  HOME_NEVER_SYNCED,
  HOME_LAST_SYNC,
  HOME_PENDING_NONE,
  HOME_SEE_SUGGESTIONS,
  HOME_STATUS,
  HOME_UNCONF_HELP,
  HOME_UNCONF_TITLE,
  LINKED_TOAST,
  OPEN_NOW,
  PEND_HIDDEN_HELP,
  PEND_NONE,
  PEND_SEE_SUGGESTION,
  PEND_SHOW_LIST,
  PEND_TITLE,
  SYNC_ALL,
  SYNC_CANCEL,
  SYNC_CANCELLED_TOAST,
  SYNC_CUT_TOAST,
  SYNC_PER_GAME,
  SYNC_PROGRESS_TITLE,
  SYNC_REST,
  TabId,
  UNLINK_CONFIRM,
  UNLINK_TOAST,
  UPDATED_TOAST,
  VER_AUTO_TOAST,
  VER_AVAILABLE,
  VER_CHECK,
  VER_CHECKING,
  VER_HOW,
  VER_INSTALLED,
  VER_NOT_SELF,
  VER_PLUGIN,
  VER_TITLE,
  firstConfirm,
  formatDate,
  formatSize,
  pendingParts,
  summaryToast,
  BROWSE_HELP,
  BROWSE_LABEL,
  CHECK_HELP,
  CHECK_LABEL,
  COPY_BUTTON,
  COPY_FAIL,
  COPY_OK,
  GAMES_INTRO,
  GameFailure,
  pathHelp,
  PICKER_FAIL,
  SAVES_ADD,
  SAVES_ADDED,
  SAVES_AGAIN,
  SAVES_BADGES,
  SAVES_BUTTON,
  SAVES_DOUBTFUL_GAME,
  SAVES_EMPTY,
  SAVES_INTRO,
  SAVES_LOADING,
  SAVES_LOOKUP_HELP,
  SAVES_LOOKUP_LABEL,
  SAVES_MANUAL,
  SAVES_MANUAL_ALL,
  SAVES_MANUAL_ALL_HELP,
  SAVES_MANUAL_ALL_HIDE,
  SAVES_MANUAL_EMPTY,
  SAVES_NOT_FOUND_GAME,
  SAVES_REVIEW,
  SAVES_SETTINGS,
  SAVES_TITLE,
  lookupsPendingText,
  savesOthers,
  savesSummary,
  saveConfirm,
  saveError,
  savePathDetail,
  RESOLVE_DEVICE_LABEL,
  RESOLVE_HELP,
  RESOLVE_HUB_LABEL,
  SEARCH_HELP,
  SEARCH_LABEL,
  SHORTCUT_HELP,
  SHOW_UNCONFIGURED_HELP,
  SHOW_UNCONFIGURED_LABEL,
  TOGGLE_HELP,
  UNCONFIGURED_HELP,
  unconfiguredDescription,
  UPDATE_STEPS,
  UpdateInfo,
  describeCompat,
  describeUpdate,
  conflictText,
  gameError,
  joinedText,
  lastNoticeText,
  pickerArgs,
  pluginUrl,
  resolveConfirm,
  syncError,
  unconfiguredView,
  wait,
} from "./texts";

// ---- contrato con main.py (los nombres coinciden con los métodos de `Plugin`) ----
// La clave del dispositivo y el secreto de la solicitud NUNCA llegan aquí: solo el estado.
type Status = "unlinked" | "waiting" | "linked" | "rejected" | "expired" | "error";
type PairError =
  | "connection"
  | "rate_limited"
  | "busy"
  | "hub_error"
  | "bad_response"
  | "settings"
  | "name_invalid";
type NameError = "empty" | "spaces" | "too_long" | "slash" | "control" | "dots";
type UrlError = "empty" | "scheme" | "credentials" | "path" | "invalid";

interface State {
  hub_url: string;
  device_name: string;
  name_changed?: boolean;
  status: Status;
  code?: string;
  seconds_left?: number;
  retrying?: boolean;
  device?: string;
  error?: PairError;
  wait_s?: number;
}
type Action = Partial<State> & { ok: boolean; url_error?: UrlError; name_error?: NameError };
interface Ping {
  result: "ok" | "not_linked" | "unauthorized" | "rate_limited" | "connection" | "hub_error";
  device?: string | null;
  wait_s?: number;
  compat?: "ok" | "plugin_outdated" | "hub_old" | "plugin_unknown";
  min_plugin_protocol?: number | null;
  plugin_protocol?: number | null;
}

const getState = callable<[], State>("get_state");
const setHubUrl = callable<[url: string], Action>("set_hub_url");
const setDeviceName = callable<[name: string], Action>("set_device_name");
const startPairing = callable<[], Action>("start_pairing");
const cancelPairing = callable<[], State>("cancel_pairing");
const unlink = callable<[], State>("unlink");
const testConnection = callable<[], Ping>("test_connection");
const getVersion = callable<[], { version: string | null; protocol: number | null }>("get_version");
const checkUpdate = callable<[], UpdateInfo>("check_update");

// ---- juegos y sincronización (tareas de fondo de main.py; la interfaz consulta `get_sync_state`) ----
type GameStatus =
  | "unknown"
  | "up_to_date"
  | "upload"
  | "download"
  | "conflict"
  | "no_path"
  | "missing_dir"
  | "disabled"
  | "error";
interface GameRow {
  id: string;
  name: string;
  appid: number | null;
  enabled: boolean;
  state: GameStatus;
  last_at?: number; // época de la última sincronización correcta (la recuerda el plugin)
  code?: string;
  params?: Record<string, unknown>;
  last?: { state: string; files?: number; code?: string };
}
interface SyncState {
  running: boolean;
  busy?: boolean;
  kind: "refresh" | "check" | "check_one" | "sync_game" | "resolve" | "sync_all" | null;
  game: string | null;
  phase: "scan" | "upload" | "download" | null;
  done: number;
  total: number;
  index: number;
  count: number;
  error: string | null;
  error_params: { wait_s?: number; code?: string };
  error_detail: string | null; // tipo, mensaje y endpoint saneados del fallo (sin claves ni steamid)
  summary: {
    found: number;
    associated: number;
    suggested: number;
    unchanged: number;
    ignored: number;
  } | null;
  plan?: string[]; // sync_all: ids de los juegos que se recorren, en orden
  results?: Record<string, { state: string; code?: string; files?: number }>; // sync_all: lo hecho por juego
  games: GameRow[];
  unconfigured: { appid: number; name: string; source?: string }[]; // instalados en la Deck sin juego en el hub (tras buscar)
}
interface Suggestion extends GameFailure {
  appid?: number;
  name?: string;
  path?: string;
  home?: string; // home de la Deck: donde abre el selector si no hay ruta
  candidates?: string[];
  browse_start?: string; // atajo de Lutris: dónde abre «Examinar…» (<prefijo>/drive_c/users, o el prefijo)
  source?: "proton" | "cloud" | "lutris" | "manifest" | "";
}
// Sugerencias del manifiesto propio (`suggest_saves`): una entrada por juego instalado que casa
interface SaveResult extends GameFailure {
  manifest?: string;
  games?: SaveGame[];
  network_lookups?: number;
  lookups_pending?: number;
}
interface SaveTarget extends GameFailure {
  appid?: number;
  name?: string;
}
interface SaveApplied extends GameFailure {
  appid?: number;
  name?: string;
  path?: string;
}
interface Configured extends GameFailure {
  game?: { id: string; name: string; appid: number; joined?: boolean };
}
interface Toggled extends GameFailure {
  game?: string;
  enabled?: boolean;
}

// Carpeta distinta sugerida para un juego ya añadido (`suggest_changes`) y detalle de un juego (`game_detail`)
interface ChangedItem {
  game: string;
  name: string;
  path: string;
  size?: number | null;
  files?: number | null;
  mtime?: number | null;
}
interface GameDetailData {
  ok: boolean;
  path?: string | null;
  folder?: { exists: boolean; size?: number | null; files?: number | null; mtime?: number | null; truncated?: boolean };
  last?: { at: number; state: string; files?: number } | null;
}

const EMPTY_SYNC: SyncState = {
  running: false, kind: null, game: null, phase: null, done: 0, total: 0, index: 0, count: 0, error: null, error_params: {}, error_detail: null,
  summary: null, plan: [], results: {}, games: [], unconfigured: [],
};

const getSyncState = callable<[], SyncState>("get_sync_state");
const refreshLibrary = callable<[], SyncState>("refresh_library");
const listGames = callable<[], SyncState>("list_games");
const syncGame = callable<[game: string], SyncState>("sync_game");
const resolveConflict = callable<[game: string, winner: "hub" | "device"], SyncState>("resolve_conflict");
const syncAll = callable<[], SyncState>("sync_all");
const cancelSync = callable<[], SyncState>("cancel_sync");
const suggestGame = callable<[appid: number], Suggestion>("suggest_game");
const pickerStart = callable<[path: string], { ok: boolean; path: string }>("picker_start");
const configureGame = callable<[appid: number, name: string, path: string], Configured>("configure_game");
const setGameEnabled = callable<[game: string, enabled: boolean], Toggled>("set_game_enabled");
const gameEvent = callable<[appid: number, running: boolean], { ok: boolean }>("game_event");
const diagGameEvent = callable<[unAppID: string, tipo: string, bRunning: string], { ok: boolean }>("diag_game_event");
const takeNotices = callable<[], Notice[]>("take_notices");
const getPrefs = callable<[], { ok: boolean; show_unconfigured: boolean; lutris_lookup?: boolean }>("get_prefs");
const setPref = callable<[key: string, value: boolean], { ok: boolean; show_unconfigured?: boolean; lutris_lookup?: boolean }>("set_pref");
const suggestSaves = callable<[], SaveResult>("suggest_saves");
const resolveSaveTarget = callable<[source: string, ident: number | string], SaveTarget>("resolve_save_target");
const applySaveSuggestion = callable<[source: string, ident: number | string, path: string], SaveApplied>("apply_save_suggestion");
const getCompat = callable<[], { compat: string | null }>("get_compat");
const ackVersion = callable<[], { ok: boolean; current?: string | null; previous?: string | null }>("ack_version");
const getGamePaths = callable<[], { ok: boolean; paths: Record<string, string | null> }>("get_game_paths");
const suggestChanges = callable<[], { ok: boolean; error?: string; items?: ChangedItem[] }>("suggest_changes");
const ignoreSuggestion = callable<[game: string, path: string], { ok: boolean; error?: string }>("ignore_suggestion");
const gameDetail = callable<[game: string], GameDetailData>("game_detail");
const reportError = callable<[message: string], { ok: boolean }>("report_error");

// ---- captura de fallos (mismo patrón que el hub: crashwatch + avisos con detalles saneados) ----
// Error global, promesa rechazada o llamada al backend que falla: aviso en el panel y línea en el log de Decky.
let watch: CrashWatch | null = null;
let crashes: CrashItem[] = [];
const crashListeners = new Set<(c: CrashItem[]) => void>();

const pickerListeners = new Set<() => void>(); // formularios abiertos que esperan el fallo conocido del selector de Decky

function startCapture(): void {
  if (watch) return;
  watch = startCrashWatch(window, {
    onChange: (l) => {
      crashes = l;
      crashListeners.forEach((f) => f(l));
    },
    onPickerError: () => pickerListeners.forEach((f) => f()),
    // Al log de Decky; si el propio envío falla no se reporta (evita el bucle)
    onReport: (it) => {
      reportError(it.details).catch(() => undefined);
      toaster.toast({ title: "Checkpoint: fallo detectado", body: it.title });
    },
  });
}

function stopCapture(): void {
  watch?.stop();
  watch = null;
  crashes = [];
  crashListeners.clear();
}

/** Para `.catch(...)` de cualquier llamada: antes se tragaba con `() => undefined`; ahora se ve y se registra. */
const capture = (context: string) => (e: unknown) => {
  const src = (e && typeof e === "object" ? e : { message: e }) as { name?: string; message?: unknown; stack?: string };
  const err = new Error(`${context}: ${String(src.message ?? "")}`);
  err.name = src.name || "Error";
  err.stack = src.stack;
  watch?.report(err);
};

function useCrashes(): [CrashItem[], (id: number) => void] {
  const [items, setItems] = useState<CrashItem[]>(crashes);
  useEffect(() => {
    crashListeners.add(setItems);
    setItems(crashes);
    return () => {
      crashListeners.delete(setItems);
    };
  }, []);
  return [items, (id) => watch?.dismiss(id)];
}

function CrashNotices() {
  const [items, dismiss] = useCrashes();
  if (items.length === 0) return null;
  return (
    <PanelSection title="Fallos detectados">
      {items.map((it) => (
        <div key={it.id}>
          <PanelSectionRow>
            <LongText label={it.title}>
              <b>{it.title}</b>
              {it.details ? `\n${it.details}` : ""}
            </LongText>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => dismiss(it.id)}>
              Descartar
            </ButtonItem>
          </PanelSectionRow>
        </div>
      ))}
    </PanelSection>
  );
}

// ---- textos (español) ----
const URL_ERRORS: Record<UrlError, string> = {
  empty: "Escribe la dirección del hub.",
  scheme: "La dirección debe empezar por http:// o https://",
  credentials: "La dirección no puede llevar usuario ni contraseña.",
  path: "Escribe solo el servidor y el puerto, sin ruta (por ejemplo http://192.168.1.10:8088).",
  invalid: "La dirección no es válida.",
};

const PAIR_ERRORS: Record<PairError, string> = {
  connection: "No se pudo conectar con el hub. Revisa la dirección y que la Deck tenga red.",
  rate_limited: "El hub pide esperar antes de otra solicitud.",
  busy: "El hub tiene demasiadas solicitudes pendientes. Inténtalo más tarde.",
  hub_error: "El hub respondió con un error inesperado. Mira sus registros.",
  bad_response: "La respuesta del hub no es la esperada. ¿Es un hub de Checkpoint?",
  settings: "No se pudo guardar la clave en la Deck.",
  name_invalid: "El hub no acepta el nombre de este dispositivo. Cámbialo y vuelve a vincular.",
};

// Mismas reglas que el hub para el nombre de un dispositivo (las valida main.py; aquí solo se explican)
const NAME_ERRORS: Record<NameError, string> = {
  empty: "Escribe un nombre para este dispositivo.",
  spaces: "El nombre no puede llevar espacios dobles.",
  too_long: "El nombre es demasiado largo (máximo 64 caracteres).",
  slash: "El nombre no puede llevar «/» ni «\\».",
  control: "El nombre lleva caracteres no permitidos.",
  dots: "El nombre no puede ser solo puntos.",
};

const NAME_HELP =
  "Si tienes varias Decks, usa un nombre distinto en cada una; con el mismo nombre el hub las trataría como el mismo dispositivo y la clave de una dejaría sin acceso a la otra";

function describe(s: State): string {
  switch (s.status) {
    case "unlinked":
      return "Sin vincular.";
    case "waiting":
      return "Esperando aceptación en el hub.";
    case "linked":
      return `Vinculado a ${s.device ?? "este dispositivo"}.`;
    case "rejected":
      return "El hub rechazó la solicitud.";
    case "expired":
      return "La solicitud caducó. Vuelve a vincular.";
    case "error":
      return (PAIR_ERRORS[s.error ?? "hub_error"] ?? PAIR_ERRORS.hub_error) + wait(s.wait_s);
  }
}

function describePing(p: Ping): string {
  switch (p.result) {
    case "ok": {
      const base = p.device ? `Conectado como ${p.device}.` : "Conectado (la clave no es de un dispositivo).";
      const warn = describeCompat(p.compat, p);
      return warn ? `${base} ${warn}` : base;
    }
    case "not_linked":
      return "Primero vincula la Deck con el hub.";
    case "unauthorized":
      return "El hub no acepta la clave. Quizá se revocó: desvincula y vuelve a vincular.";
    case "rate_limited":
      return "Demasiados intentos." + wait(p.wait_s);
    case "connection":
      return "No se pudo conectar con el hub. Revisa la dirección y la red.";
    case "hub_error":
      return "El hub respondió con un error inesperado.";
  }
}

// Texto que se parte en varias líneas (direcciones y rutas largas) en vez de cortarse

const GAME_STATES: Record<Exclude<GameStatus, "error">, string> = {
  unknown: "Sin comprobar",
  up_to_date: "Al día",
  upload: "Hay cambios en la Deck: se subirán",
  download: "Hay cambios en el hub: se bajarán",
  conflict: "Conflicto: cambios en los dos lados, no se toca nada",
  no_path: "Sin ruta en el hub",
  missing_dir: "Carpeta no encontrada",
  disabled: "Desactivado",
};

function gameText(g: GameRow): string {
  if (g.state === "conflict") return conflictText(g);
  return g.state === "error" ? syncError(g.code ?? "hub_error", g.params as { wait_s?: number }) : GAME_STATES[g.state];
}

function lastText(g: GameRow): string | null {
  if (!g.last) return null;
  const n = g.last.files !== undefined ? ` (${g.last.files} ficheros)` : "";
  if (g.last.state === "uploaded") return `Última sincronización: subido${n}.`;
  if (g.last.state === "downloaded")
    return `Última sincronización: bajado${n}. Tu carpeta anterior quedó como copia de seguridad.`;
  return null;
}

function progressText(s: SyncState, games: GameRow[]): string {
  const name = games.find((g) => g.id === s.game)?.name;
  const prefix = s.kind === "sync_all" && s.count > 0 ? `Juego ${s.index}/${s.count}${name ? ` (${name})` : ""}: ` : "";
  if (s.kind === "refresh") return "Buscando juegos de Steam…";
  if (s.kind === "resolve" && !s.phase) return "Resolviendo el conflicto…";
  if (s.phase === "upload") return `${prefix}Subiendo ${s.done}/${s.total} ficheros…`;
  if (s.phase === "download") return `${prefix}Bajando ${s.done}/${s.total} ficheros…`;
  if (s.phase === "scan") return `${prefix}Leyendo la carpeta…`;
  if (s.kind === "check" || s.kind === "check_one") return `Comprobando${s.count > 0 ? ` ${s.index}/${s.count}` : ""}…`;
  return `${prefix}Trabajando…`;
}

const mmss = (s: number) =>
  `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

// Un juego instalado en la Deck que el hub aún no tiene: «Configurar» rellena nombre y ruta (lo detectado) y pide confirmar
function UnconfiguredGame({ appid, name, source, disabled, onDone, onClose }: { appid: number; name: string; source?: string; disabled: boolean; onDone: (s: SyncState) => void; onClose?: () => void }) {
  // El selector de carpetas de Decky cierra la Quick Access y desmonta el panel: el formulario se recupera del borrador
  // (src/drafts.ts, a nivel de módulo) para no perder la carpeta elegida al volver.
  const [saved] = useState(() => drafts.get(appid));
  const [open, setOpen] = useState(saved?.open ?? false);
  const [busy, setBusy] = useState(false);
  const [gname, setGname] = useState(saved?.gname ?? name);
  const [path, setPath] = useState(saved?.path ?? "");
  const [sug, setSug] = useState<Suggestion | null>((saved?.sug as Suggestion | null | undefined) ?? null);
  const [pick, setPick] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pickerFailed, setPickerFailed] = useState(false); // el selector de Decky no pudo abrir la carpeta (fallo conocido)

  // Mientras el formulario está abierto se guarda el borrador; al cerrarlo (Cancelar) se borra. Al desmontar no se toca.
  useEffect(() => {
    if (open) drafts.set(appid, { open, gname, path, sug });
    else drafts.delete(appid);
  }, [appid, open, gname, path, sug]);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = await suggestGame(appid);
      if (!s.ok) {
        setError(gameError(s));
        return;
      }
      setSug(s);
      setGname(s.name ?? name);
      setPath(s.path ?? "");
      setPick(0);
      setOpen(true);
    } catch (e) {
      capture("preparar la configuración del juego")(e);
      setError(gameError({ error: "unexpected" }));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await configureGame(appid, gname, path);
      if (!r.ok) {
        setError(gameError(r) + (r.error_detail ? ` (${r.error_detail})` : ""));
        return;
      }
      if (r.game?.joined) toaster.toast({ title: "Checkpoint", body: joinedText(r.game.name) });
      onDone(await getSyncState()); // el juego pasa a la lista de «Juegos en el hub»
      drafts.delete(appid);
    } catch (e) {
      capture("configurar el juego")(e);
      setError(gameError({ error: "unexpected" }));
    } finally {
      setBusy(false);
    }
  };

  // Selector nativo de Decky (`openFilePicker`). Su frontend revienta con «TypeError: theError.match is not a function» si su
  // backend no puede listar la carpeta: la ruta inicial se valida antes (`picker_start`: existe, es carpeta y se lee; si no, el
  // home o `/`), los argumentos van explícitos (`pickerArgs`) y ese fallo concreto se muestra aquí en vez de «Fallos detectados».
  useEffect(() => {
    const f = () => setPickerFailed(true);
    pickerListeners.add(f);
    return () => {
      pickerListeners.delete(f);
    };
  }, []);
  const browse = async () => {
    setError(null);
    setPickerFailed(false);
    let start = "/";
    setBusy(true);
    try {
      // Atajo de Lutris: «Examinar…» abre en el prefijo (`browse_start`) salvo que la carpeta escrita sea propia (ni candidata ni vacía).
      const typed = path.trim();
      const own = typed !== "" && !(sug?.candidates ?? []).includes(typed);
      const r = await pickerStart(sug?.browse_start && !own ? sug.browse_start : (sug?.candidates ?? []).includes(path) ? path : typed);
      if (r.ok && typeof r.path === "string" && r.path.startsWith("/")) start = r.path;
    } catch (e) {
      capture("ruta inicial del selector")(e);
    } finally {
      setBusy(false);
    }
    try {
      const picked = await openFilePicker(FileSelectionType.FOLDER, ...pickerArgs(start));
      if (picked?.path) {
        // El panel puede estar desmontado cuando el selector resuelve: setPath no llega a nadie, así que la ruta va también
        // al borrador (este closure sigue vivo) y el formulario remontado sale abierto con ella.
        drafts.patch(appid, { path: picked.path }, { open: true, gname, path: picked.path, sug });
        setPath(picked.path);
      }
    } catch (e) {
      if (e !== "User canceled") capture("selector de carpetas")(e); // cancelar rechaza con ese texto: no es un fallo
    }
  };

  const others = sug?.candidates ?? [];
  return (
    <div>
      <PanelSectionRow>
        <Field label={name} description={unconfiguredDescription(appid, source)} focusable>
          {open ? "Sin configurar" : ""}
        </Field>
      </PanelSectionRow>
      {!open && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={disabled || busy} onClick={start}>
            Configurar
          </ButtonItem>
        </PanelSectionRow>
      )}
      {open && (
        <>
          <PanelSectionRow>
            <TextField label="Nombre en el hub" value={gname} onChange={(e) => setGname(e.target.value)} />
          </PanelSectionRow>
          <PanelSectionRow>
            <TextField
              label="Carpeta de guardado"
              description={pathHelp(path, sug?.source)}
              value={path}
              onChange={(e) => setPath(e.target.value)}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" description={BROWSE_HELP} disabled={busy} onClick={browse}>
              {BROWSE_LABEL}
            </ButtonItem>
          </PanelSectionRow>
          {pickerFailed && <PanelSectionRow>{PICKER_FAIL}</PanelSectionRow>}
          {others.length > 1 && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy}
                onClick={() => {
                  const n = (pick + 1) % others.length;
                  setPick(n);
                  setPath(others[n]);
                }}
              >
                Probar otra ruta detectada ({pick + 1}/{others.length})
              </ButtonItem>
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <Field label="Juego de Steam / plataforma">{`${appid} · Steam Deck (Linux)`}</Field>
          </PanelSectionRow>
          {error && <PanelSectionRow>{error}</PanelSectionRow>}
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy || disabled || !gname.trim() || !path.trim()} onClick={save}>
              Guardar en el hub
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy}
              onClick={() => {
                setOpen(false);
                onClose?.();
              }}
            >
              Cancelar
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
      {!open && error && <PanelSectionRow>{error}</PanelSectionRow>}
    </div>
  );
}

// «Sugerencias de guardado»: una tarjeta por juego sin configurar con su mejor carpeta (manifiesto propio) y UN botón grande:
// «Añadir al hub» (segura: confirma, aplica y guarda), «Revisar y añadir» (dudosa: abre «Configurar» sin guardar) o nada
// (carpeta no encontrada). «Añadir manualmente» abre «Configurar» vacío. Nunca se guarda sin confirmación explícita.
interface SuggestionProps {
  sync: SyncState;
  setSync: (s: SyncState) => void;
  editing: Record<number, number>; // formularios «Configurar» abiertos aquí (appid -> remontaje)
  openForm: (appid: number, name: string, path: string) => void;
  closeForm: (appid: number) => void;
}
function SaveSuggestions({ sync, setSync, editing, openForm, closeForm }: SuggestionProps) {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<SaveResult | null>(null); // última respuesta (null = aún no se ha pulsado)
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [cardErr, setCardErr] = useState<Record<string, string>>({});
  const [added, setAdded] = useState<ReadonlySet<string>>(new Set());
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [appidOf, setAppidOf] = useState<Record<string, number>>({}); // tarjeta -> appid de su formulario abierto
  const [more, setMore] = useState<ReadonlySet<string>>(new Set()); // tarjetas con «otras rutas» desplegadas
  const [settings, setSettings] = useState(false);
  const [manualAll, setManualAll] = useState(false);
  const [lookup, setLookup] = useState(true); // se recuerda en prefs.json (main.py)

  useEffect(() => {
    getPrefs()
      .then((r) => {
        if (r?.ok && typeof r.lutris_lookup === "boolean") setLookup(r.lutris_lookup);
      })
      .catch(capture("preferencias"));
  }, []);

  const changeLookup = (on: boolean) => {
    setLookup(on);
    setPref("lutris_lookup", on)
      .then((r) => {
        if (!r.ok) setLookup(!on);
      })
      .catch((e) => {
        capture("guardar la preferencia")(e);
        setLookup(!on);
      });
  };

  const withKey = <T,>(set: ReadonlySet<T>, k: T): ReadonlySet<T> => new Set([...set, k]);
  const fail = (k: string, code?: string, detail?: string | null) => setCardErr((e) => ({ ...e, [k]: saveError(code) + (detail ? ` (${detail})` : "") }));

  const suggest = async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    setCardErr({});
    setAdded(new Set());
    setHidden(new Set());
    setMore(new Set());
    try {
      const r = await suggestSaves();
      setRes(r);
      if (!r.ok && r.error !== "no_manifest") setError(saveError(r.error));
    } catch (e) {
      capture("sugerir carpetas de guardado")(e);
      setRes(null);
      setError(saveError("unexpected"));
    } finally {
      setBusy(false);
    }
  };

  // El juego ya no está «Sin configurar»: sale de la lista con un aviso (no se queda un error que no se puede arreglar)
  const gone = (g: SaveGame, k: string) => {
    setHidden((h) => withKey(h, k));
    setNote(`«${g.name}» ya no está en «Sin configurar en el hub»: se quita de la lista.`);
  };

  // Segura: tras el modal, aplica (vuelve a verificar la carpeta) y configura el juego con el mismo camino que «Guardar en el hub».
  const addToHub = async (g: SaveGame, k: string, path: string) => {
    setBusy(true);
    setNote(null);
    setCardErr((e) => ({ ...e, [k]: "" }));
    try {
      const r = await applySaveSuggestion(g.source, g.id, path);
      if (!r.ok || typeof r.appid !== "number") {
        if (r.error === "not_unconfigured") gone(g, k);
        else fail(k, r.error);
        return;
      }
      const c = await configureGame(r.appid, r.name ?? g.name, r.path ?? path);
      if (!c.ok) {
        setCardErr((e) => ({ ...e, [k]: gameError(c) + (c.error_detail ? ` (${c.error_detail})` : "") }));
        return;
      }
      if (c.game?.joined) toaster.toast({ title: "Checkpoint", body: joinedText(c.game.name) });
      drafts.delete(r.appid);
      setAdded((a) => withKey(a, k));
      setSync(await getSyncState());
    } catch (e) {
      capture("añadir la carpeta sugerida al hub")(e);
      fail(k, "unexpected");
    } finally {
      setBusy(false);
    }
  };

  const confirmAdd = (g: SaveGame, k: string, path: string) => {
    const c = saveConfirm(g.name, path);
    showModal(
      <ConfirmModal
        strTitle={c.title}
        strDescription={c.description}
        strOKButtonText={c.ok}
        strCancelButtonText="Cancelar"
        onOK={() => {
          addToHub(g, k, path).catch(capture("añadir la carpeta sugerida al hub"));
        }}
      />,
    );
  };

  // Dudosa («Revisar y añadir», con la carpeta) o manual (sin carpeta): abre «Configurar» en la tarjeta; no guarda nada.
  const review = async (g: SaveGame, k: string, path: string | null) => {
    setBusy(true);
    setNote(null);
    setCardErr((e) => ({ ...e, [k]: "" }));
    try {
      const r: SaveTarget = path === null ? await resolveSaveTarget(g.source, g.id) : await applySaveSuggestion(g.source, g.id, path);
      if (!r.ok || typeof r.appid !== "number") {
        if (r.error === "not_unconfigured") gone(g, k);
        else fail(k, r.error);
        return;
      }
      setAppidOf((m) => ({ ...m, [k]: r.appid as number }));
      openForm(r.appid, r.name ?? g.name, path === null ? "" : ((r as SaveApplied).path ?? path));
    } catch (e) {
      capture("abrir el formulario de la sugerencia")(e);
      fail(k, "unexpected");
    } finally {
      setBusy(false);
    }
  };

  const formFor = (appid: number, onDone?: () => void) => {
    const u = sync.unconfigured.find((x) => x.appid === appid);
    if (!u) return null;
    return (
      <UnconfiguredGame
        key={`${appid}:${editing[appid] ?? 0}`}
        appid={appid}
        name={u.name}
        source={u.source}
        disabled={sync.running}
        onDone={(st) => {
          setSync(st);
          closeForm(appid);
          onDone?.();
        }}
        onClose={() => closeForm(appid)}
      />
    );
  };

  const games = res?.ok ? unconfiguredOnly(res.games ?? [], sync.games.map((x) => x.appid), hidden, added) : [];
  const owned = new Set(Object.values(appidOf));
  const orphan = Object.keys(editing).map(Number).filter((a) => !owned.has(a));
  const pickable = sync.unconfigured.filter((u) => !(u.appid in editing));

  const card = (g: SaveGame) => {
    const k = gameKey(g);
    const best = bestPath(g.paths);
    const kind: CardKind = cardKind(g, best);
    const others = otherPaths(g.paths, best);
    const open = more.has(k);
    const formAppid = appidOf[k];
    const editingHere = formAppid !== undefined && formAppid in editing;
    const done = added.has(k);
    return (
      <div key={k}>
        <PanelSectionRow>
          <Field label={g.name} description={g.source === "lutris" ? "Lutris" : `N.º de Steam: ${g.id}`} focusable>
            {done ? SAVES_ADDED : SAVES_BADGES[kind]}
          </Field>
        </PanelSectionRow>
        {best && (
          <PanelSectionRow>
            <Field label={best.path} description={savePathDetail(best)} focusable />
          </PanelSectionRow>
        )}
        {!done && kind === "doubtful" && <PanelSectionRow>{SAVES_DOUBTFUL_GAME}</PanelSectionRow>}
        {!done && kind === "not_found" && <PanelSectionRow>{SAVES_NOT_FOUND_GAME}</PanelSectionRow>}
        {cardErr[k] && <PanelSectionRow>{cardErr[k]}</PanelSectionRow>}
        {!done && editingHere && formFor(formAppid, () => setAdded((a) => withKey(a, k)))}
        {!done && !editingHere && (
          <>
            {kind === "safe" && best && (
              <PanelSectionRow>
                <ButtonItem layout="below" disabled={busy || sync.running} onClick={() => confirmAdd(g, k, best.path)}>
                  {SAVES_ADD}
                </ButtonItem>
              </PanelSectionRow>
            )}
            {kind === "doubtful" && best && (
              <PanelSectionRow>
                <ButtonItem layout="below" disabled={busy || sync.running} onClick={() => review(g, k, best.path)}>
                  {SAVES_REVIEW}
                </ButtonItem>
              </PanelSectionRow>
            )}
            {others.length > 0 && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  onClick={() =>
                    setMore((m) => {
                      const n = new Set(m);
                      if (n.has(k)) n.delete(k);
                      else n.add(k);
                      return n;
                    })
                  }
                >
                  {savesOthers(others.length, open)}
                </ButtonItem>
              </PanelSectionRow>
            )}
            {open &&
              others.map((p) => (
                <PanelSectionRow key={p.path}>
                  <Field label={p.path} description={savePathDetail(p)} focusable />
                </PanelSectionRow>
              ))}
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={busy || sync.running} onClick={() => review(g, k, null)}>
                {SAVES_MANUAL}
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </div>
    );
  };

  return (
    <PanelSection title={SAVES_TITLE}>
      <PanelSectionRow>{SAVES_INTRO}</PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={suggest}>
          {res ? SAVES_AGAIN : SAVES_BUTTON}
        </ButtonItem>
      </PanelSectionRow>
      {busy && <PanelSectionRow>{SAVES_LOADING}</PanelSectionRow>}
      {error && <PanelSectionRow>{error}</PanelSectionRow>}
      {note && <PanelSectionRow>{note}</PanelSectionRow>}
      {res && !res.ok && res.error === "no_manifest" && <PanelSectionRow>{saveError("no_manifest")}</PanelSectionRow>}
      {res?.ok && (res.lookups_pending ?? 0) > 0 && <PanelSectionRow>{lookupsPendingText(res.lookups_pending ?? 0)}</PanelSectionRow>}
      {res?.ok && games.length === 0 && <PanelSectionRow>{SAVES_EMPTY}</PanelSectionRow>}
      {res?.ok && games.length > 0 && <PanelSectionRow>{savesSummary(games.length)}</PanelSectionRow>}
      {games.map(card)}
      {orphan.map((a) => formFor(a))}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} description={manualAll ? SAVES_MANUAL_ALL_HELP : undefined} onClick={() => setManualAll((v) => !v)}>
          {manualAll ? SAVES_MANUAL_ALL_HIDE : SAVES_MANUAL_ALL}
        </ButtonItem>
      </PanelSectionRow>
      {manualAll && pickable.length === 0 && <PanelSectionRow>{SAVES_MANUAL_EMPTY}</PanelSectionRow>}
      {manualAll &&
        pickable.map((u) => (
          <PanelSectionRow key={u.appid}>
            <ButtonItem layout="below" disabled={busy || sync.running} description={unconfiguredDescription(u.appid, u.source)} onClick={() => openForm(u.appid, u.name, "")}>
              {u.name}
            </ButtonItem>
          </PanelSectionRow>
        ))}
      <PanelSectionRow>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <DialogButton
            style={{ width: 44, minWidth: 44, padding: "10px 0", display: "flex", justifyContent: "center" }}
            aria-label={SAVES_SETTINGS}
            onClick={() => setSettings((v) => !v)}
          >
            <FaCog />
          </DialogButton>
        </div>
      </PanelSectionRow>
      {settings && (
        <PanelSectionRow>
          <ToggleField label={SAVES_LOOKUP_LABEL} description={SAVES_LOOKUP_HELP} checked={lookup} disabled={busy} onChange={changeLookup} />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}



// ============================================================================================================
// Panel por pestañas (1.3.0). Todo lo que debe seguir vivo con el plugin cargado (no solo con el panel abierto) vive en
// este almacén de módulo; los componentes lo leen con `useShared`.
// ============================================================================================================
interface Shared {
  tab: TabId;
  online: boolean; // última noticia de conexión con el hub (ping, tarea o aviso del backend)
  compat: string | null; // `plugin_outdated` = este plugin no vale para el hub
  update: UpdateInfo | null; // última comprobación de versión (manual o automática)
  version: string | null;
  firstSync: boolean; // esta Deck se acaba de vincular en esta sesión: falta la primera sincronización
  summary: Tally | null; // resumen de la última «Sincronizar todo» (banner hasta cerrarlo)
}
const shared: Shared = { tab: "home", online: true, compat: null, update: null, version: null, firstSync: false, summary: null };
const sharedListeners = new Set<() => void>();
function setShared(p: Partial<Shared>): void {
  Object.assign(shared, p);
  sharedListeners.forEach((f) => f());
}
function useShared(): Shared {
  const [, tick] = useState(0);
  useEffect(() => {
    const f = () => tick((n) => n + 1);
    sharedListeners.add(f);
    return () => {
      sharedListeners.delete(f);
    };
  }, []);
  return shared;
}

const runningApps = new RunningApps(); // juegos de Steam abiertos ahora (los eventos de `startGameWatch`)
const versionNotifier = new VersionNotifier();

// ---- versión: aviso automático y «Checkpoint actualizado a X» ----
function applyUpdate(u: UpdateInfo, auto: boolean): void {
  setShared({ update: u, ...(u.compat ? { compat: u.compat } : {}) });
  if (auto && hasUpdate(u) && versionNotifier.shouldToast(u.latest)) showToast("info", VER_AUTO_TOAST(u.latest ?? "?"));
}
async function autoCheckUpdate(): Promise<void> {
  const s = await getState();
  if (s.status !== "linked") return;
  applyUpdate(await checkUpdate(), true);
}
async function announceVersion(): Promise<void> {
  const r = await ackVersion();
  setShared({ version: r.current ?? null });
  const to = updatedTo(r.previous, r.current);
  if (to) showToast("ok", UPDATED_TOAST(to));
}

// ---- vinculación recién hecha: toast y primera sincronización pendiente ----
let pairTimer: ReturnType<typeof setInterval> | null = null;
function stopPairWatch(): void {
  if (pairTimer) clearInterval(pairTimer);
  pairTimer = null;
}
/** Mientras se espera la aceptación en el hub; al aceptarse avisa y, si la Deck no estaba vinculada antes, marca la primera sincronización. */
function trackPairing(wasLinked: boolean): void {
  if (pairTimer) return;
  pairTimer = setInterval(() => {
    getState()
      .then((s) => {
        if (s.status === "waiting") return;
        stopPairWatch();
        if (s.status !== "linked") return;
        setShared({ online: true, ...(wasLinked ? {} : { firstSync: true, summary: null }) });
        showToast("ok", LINKED_TOAST(s.device ?? s.device_name));
      })
      .catch(capture("estado de la vinculación"));
  }, 1500);
}

// ---- «Sincronizar todo»: resultado al terminar (toast y banner), aunque el panel esté cerrado ----
let runWatch: ReturnType<typeof setInterval> | null = null;
let userCancelled = false;
function stopRunWatch(): void {
  if (runWatch) clearInterval(runWatch);
  runWatch = null;
}
function finishRun(s: SyncState): void {
  const plan = s.plan ?? [];
  const results = s.results ?? {};
  if (userCancelled) {
    userCancelled = false;
    setShared({ summary: null });
    showToast("info", SYNC_CANCELLED_TOAST);
    return;
  }
  if (s.error === "plugin_outdated") {
    setShared({ compat: "plugin_outdated" });
    showToast("error", HOME_STATUS.outdated);
    return;
  }
  if (plan.length === 0) {
    if (s.error === "connection") setShared({ online: false });
    if (s.error) showToast(s.error === "connection" ? "warn" : "error", s.error === "connection" ? HOME_STATUS.offline : BANNER.failedTitle.replace(/\.$/, ""));
    return;
  }
  const t = tally(plan, results);
  const offline = Object.values(results).some((r) => r.code === "connection");
  setShared({ summary: t, online: !offline, ...(t.interrupted ? {} : { firstSync: false }) });
  if (t.interrupted) showToast("warn", SYNC_CUT_TOAST);
  else showToast(LEVEL_KIND[summaryLevel(t)], summaryToast(t));
}
function watchRun(): void {
  if (runWatch) return;
  runWatch = setInterval(() => {
    getSyncState()
      .then((s) => {
        if (s.running) return;
        stopRunWatch();
        finishRun(s);
      })
      .catch(capture("seguimiento de la sincronización"));
  }, 1000);
}
const LEVEL_KIND: Record<Level, ToastKind> = { ok: "ok", info: "info", warn: "warn", error: "error" };
/** Lanza `sync_all` (también «los demás juegos»: el backend deja el juego abierto como «game_running», que no cuenta como error). */
function startAll(): Promise<SyncState> {
  userCancelled = false;
  setShared({ summary: null });
  const p = syncAll();
  watchRun();
  return p;
}
function cancelAll(): Promise<SyncState> {
  userCancelled = true;
  return cancelSync();
}

// ---- estado de la tarea de fondo, compartido por todas las pestañas (una sola consulta por segundo) ----
function useSync(enabled: boolean): [SyncState | null, (s: SyncState) => void, MutableRefObject<boolean>] {
  const [sync, setSync] = useState<SyncState | null>(null);
  const started = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!enabled) return;
    const poll = async () => {
      const s = await getSyncState();
      if (!mounted.current) return;
      setSync(s);
      // La primera vez que se abre el panel, se comprueba el estado de los juegos
      if (!started.current && !s.running && s.games.length === 0 && !s.error) {
        started.current = true;
        const l = await listGames();
        if (mounted.current) setSync(l);
      }
    };
    poll().catch(capture("estado de los juegos"));
    const t = setInterval(() => poll().catch(capture("estado de los juegos")), 1000);
    return () => clearInterval(t);
  }, [enabled]);
  return [sync, setSync, mounted];
}

async function waitIdle(mounted: MutableRefObject<boolean>): Promise<SyncState | null> {
  for (let i = 0; i < 600 && mounted.current; i++) {
    const s = await getSyncState();
    if (!s.running) return s;
    await new Promise((r) => setTimeout(r, 500));
  }
  return null;
}

interface Ctx {
  state: State;
  sync: SyncState;
  setSync: (s: SyncState) => void;
  sh: Shared;
  playing: string | null;
  outdated: boolean;
  online: boolean;
  gate: SyncGate;
  preparing: boolean;
  setTab: (t: TabId) => void;
  syncAllClick: () => void;
  syncRestClick: () => void;
  cancel: () => void;
  run: (f: () => Promise<SyncState>) => () => void;
  names: Record<string, string>;
}

// Tarjeta de una tarea en marcha: texto, barra, lista por juego (solo en «Sincronizar todo») y Cancelar
function RunCard({ ctx }: { ctx: Ctx }) {
  const { sync } = ctx;
  const pct = sync.total > 0 ? (sync.done / sync.total) * 100 : 0;
  const all = sync.kind === "sync_all" && (sync.plan?.length ?? 0) > 1;
  return (
    <PanelSection title={SYNC_PROGRESS_TITLE}>
      <PanelSectionRow>
        <div style={WRAP}>{progressText(sync, sync.games)}</div>
      </PanelSectionRow>
      <PanelSectionRow>
        <Bar pct={pct} />
      </PanelSectionRow>
      {all && (
        <PanelSectionRow>
          <div style={{ width: "100%" }}>
            <div style={MUTED}>{SYNC_PER_GAME}</div>
            <RunList rows={progressRows(sync.plan ?? [], sync.results ?? {}, sync.game, ctx.names, false)} />
          </div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={ctx.cancel}>
          {SYNC_CANCEL}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

// «Sincronizar todo» + qué hay pendiente + «Sincronizar los demás juegos» si hay un juego abierto
function SyncBlock({ ctx }: { ctx: Ctx }) {
  const why = syncBlockReason(ctx.gate);
  const c = countStates(ctx.sync.games);
  const parts = pendingParts(c);
  const syncable = ctx.sync.games.some((g) => g.enabled);
  return (
    <PanelSection>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={!!why || ctx.preparing || !syncable} onClick={ctx.syncAllClick} description={why ?? (parts.length ? parts.join(" · ") : HOME_PENDING_NONE)}>
          {ctx.preparing ? FIRST_CHECKING : SYNC_ALL}
        </ButtonItem>
      </PanelSectionRow>
      {canSyncRest(ctx.gate) && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={ctx.syncRestClick}>
            {SYNC_REST}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

// ---- Inicio ----
function HomeTab({ ctx, form }: { ctx: Ctx; form: ReactNode }) {
  const { state, sync, sh } = ctx;
  const [ping, setPing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(getLastNotice());
  useEffect(() => {
    const t = setInterval(() => setNotice(getLastNotice()), 1000);
    return () => clearInterval(t);
  }, []);
  const check = async () => {
    setBusy(true);
    setPing(VER_CHECKING);
    try {
      const p = await testConnection();
      setPing(describePing(p));
      setShared({ ...(p.result === "connection" ? { online: false } : p.result === "ok" ? { online: true } : {}), ...(p.compat ? { compat: p.compat } : {}) });
    } catch (e) {
      capture("probar la conexión")(e);
    } finally {
      setBusy(false);
    }
  };
  const badge = homeStatus({
    link: state.status,
    online: ctx.online,
    outdated: ctx.outdated,
    playing: ctx.playing,
    running: sync.running,
    conflicts: conflictGames(sync.games).length,
    errors: errorGames(sync.games).length,
  });
  const pend = sync.unconfigured.length;
  return (
    <>
      <CrashNotices />
      <PanelSection title="Dispositivo">
        <PanelSectionRow>
          <Field label={state.device ?? state.device_name} description={describe(state)} focusable>
            <StatusBadge badge={badge} />
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={MUTED}>{HOME_HUB(state.hub_url)}</div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={MUTED}>{(() => { const at = latestSync(sync.games); return at === null ? HOME_NEVER_SYNCED : HOME_LAST_SYNC(whenText(at)); })()}</div>
        </PanelSectionRow>
      </PanelSection>
      {sync.running ? <RunCard ctx={ctx} /> : sh.firstSync && !sh.summary ? (
        <PanelSection title={FIRST_TITLE}>
          <PanelSectionRow>
            <div style={WRAP}>{FIRST_TEXT}</div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={!!syncBlockReason(ctx.gate) || ctx.preparing} onClick={ctx.syncAllClick} description={syncBlockReason(ctx.gate) ?? undefined}>
              {ctx.preparing ? FIRST_CHECKING : SYNC_ALL}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      ) : <SyncBlock ctx={ctx} />}
      {pend > 0 && (
        <PanelSection title={HOME_UNCONF_TITLE(pend)}>
          <PanelSectionRow>
            <div style={WRAP}>{HOME_UNCONF_HELP}</div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => ctx.setTab("sugg")}>
              {HOME_SEE_SUGGESTIONS}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}
      <PanelSection title="Avisos">
        <PanelSectionRow>
          <LongText>{lastNoticeText(notice)}</LongText>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title={HOME_CONNECTION}>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={check}>
            Probar conexión
          </ButtonItem>
        </PanelSectionRow>
        {ping && (
          <PanelSectionRow>
            <div role="status" style={WRAP}>{ping}</div>
          </PanelSectionRow>
        )}
      </PanelSection>
      {form}
    </>
  );
}

// ---- Juegos ----
type Changed = ChangedItem;

function GameDetail({ ctx, g, changed, onBack, onIgnore, toggle }: { ctx: Ctx; g: GameRow; changed: Changed | undefined; onBack: () => void; onIgnore: (c: Changed) => void; toggle: (g: GameRow, on: boolean) => void }) {
  const [d, setD] = useState<GameDetailData | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    gameDetail(g.id)
      .then((r) => {
        if (live) (r.ok ? setD(r) : setFailed(true));
      })
      .catch((e) => {
        capture("detalle del juego")(e);
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, [g.id]);
  const busy = ctx.sync.running;
  const badge = gameBadge(g.state, g.enabled);
  const f = d?.folder;
  const can = !busy && g.enabled && ctx.playing !== g.name && !syncBlockReason({ ...ctx.gate, playing: null }) && ["unknown", "up_to_date", "upload", "download", "error"].includes(g.state);
  return (
    <>
      <PanelSection title={g.name}>
        <PanelSectionRow>
          <Field label={badge.label} description={g.enabled ? gameText(g) : "Desactivado"} focusable>
            <StatusBadge badge={badge} />
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label={GAME_ENABLED} description={GAME_ENABLED_HELP} checked={g.enabled} disabled={busy} onChange={(on: boolean) => toggle(g, on)} />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title={GAME_FOLDER}>
        <PanelSectionRow>
          <div style={MONO}>{d?.path ?? "—"}</div>
        </PanelSectionRow>
        {!d && !failed && <PanelSectionRow>{DETAIL_LOADING}</PanelSectionRow>}
        {failed && <PanelSectionRow>{DETAIL_ERROR}</PanelSectionRow>}
        {d && f && !f.exists && <PanelSectionRow>{DETAIL_FOLDER_MISSING}</PanelSectionRow>}
        {f?.exists && (
          <PanelSectionRow>
            <Field label={DETAIL_SIZE} focusable>
              {`${formatSize(f.size)} · ${f.files ?? 0}${f.truncated ? "+" : ""} ${f.files === 1 && !f.truncated ? "fichero" : "ficheros"}`}
            </Field>
          </PanelSectionRow>
        )}
        {f?.exists && (
          <PanelSectionRow>
            <Field label="Modificada" focusable>
              {formatDate(f.mtime)}
            </Field>
          </PanelSectionRow>
        )}
        {d && (
          <PanelSectionRow>
            <Field label={DETAIL_LAST_COPY} focusable>
              {d.last ? whenText(d.last.at) : DETAIL_NO_COPY}
            </Field>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <div style={MUTED}>{DETAIL_HISTORY_NOTE}</div>
        </PanelSectionRow>
      </PanelSection>
      {changed && (
        <PanelSection>
          <PanelSectionRow>
            <div style={{ ...WRAP, borderLeft: `4px solid ${TONE_COLOR.info}`, paddingLeft: 8 }}>
              <b>{CHANGED_TITLE}</b>
              <div style={MONO}>{changed.path}</div>
              <div style={MUTED}>{`${formatSize(changed.size)} · ${changed.files ?? 0} ficheros · ${formatDate(changed.mtime)}`}</div>
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => onIgnore(changed)}>
              {CHANGED_IGNORE}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!can} onClick={ctx.run(() => syncGame(g.id))}>
            Sincronizar
          </ButtonItem>
        </PanelSectionRow>
        {/* FASE 2: cambiar la carpeta de un juego ya configurado necesita backend y hub; el hueco queda desactivado a propósito */}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled description={CHANGE_FOLDER_HELP} onClick={() => undefined}>
            {`${CHANGE_FOLDER} · ${COMING_SOON}`}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onBack}>
            {GAME_BACK}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

// Tarjetas de «Juegos» desplegadas o plegadas por el usuario (solo en memoria: se pierde al recargar el plugin)
const gameOpen = new Map<string, boolean>();

function GamesTab({ ctx }: { ctx: Ctx }) {
  const { sync, setSync } = ctx;
  const [toggleError, setToggleError] = useState<string | null>(null);
  const [paths, setPaths] = useState<Record<string, string | null>>({});
  const [changes, setChanges] = useState<Record<string, Changed>>({});
  const [detail, setDetail] = useState<string | null>(null);
  const [, setTick] = useState(0); // repinta al plegar o desplegar (el estado vive en `gameOpen`)
  const busy = sync.running;

  // Carpetas configuradas (se piden aparte: el estado de la tarea no lleva rutas) y carpetas distintas sugeridas
  const ids = sync.games.map((g) => g.id).join(",");
  const askedChanges = useRef("");
  useEffect(() => {
    if (busy || ids === "") return;
    let live = true;
    getGamePaths()
      .then((r) => {
        if (live && r.ok) setPaths(r.paths);
      })
      .catch(capture("carpetas de los juegos"));
    if (askedChanges.current === ids) return () => { live = false; }; // el escaneo del manifiesto es lo más caro: una vez por lista de juegos
    askedChanges.current = ids;
    suggestChanges()
      .then((r) => {
        if (live && r.ok) setChanges(Object.fromEntries((r.items ?? []).map((c) => [c.game, c])));
      })
      .catch(capture("carpetas distintas sugeridas"));
    return () => {
      live = false;
    };
  }, [ids, busy]);

  const toggle = (g: GameRow, on: boolean) => {
    setToggleError(null);
    const put = (enabled: boolean) => setSync({ ...sync, games: sync.games.map((x) => (x.id === g.id ? { ...x, enabled } : x)) });
    put(on); // se refleja ya en pantalla; si el hub no lo acepta se deshace y se explica
    setGameEnabled(g.id, on)
      .then((r) => {
        if (!r.ok) {
          setToggleError(`${g.name}: ${gameError(r)}`);
          put(!on);
        }
      })
      .catch((e) => {
        capture("activar o desactivar un juego")(e);
        setToggleError(`${g.name}: ${gameError({ error: "unexpected" })}`);
        put(!on);
      });
  };

  const ignore = (c: Changed) => {
    setChanges((m) => {
      const { [c.game]: _, ...rest } = m;
      return rest;
    });
    ignoreSuggestion(c.game, c.path).catch(capture("ignorar la sugerencia"));
  };

  // Conflicto de datos: pide confirmar (el cambio sobrescribe un lado) y entonces resuelve y sincroniza al momento
  const askResolve = (g: GameRow, winner: "hub" | "device") => {
    const c = resolveConfirm(winner, g.name);
    showModal(
      <ConfirmModal
        strTitle={c.title}
        strDescription={c.description}
        strOKButtonText={c.ok}
        strCancelButtonText="Cancelar"
        onOK={() => {
          ctx.run(() => resolveConflict(g.id, winner))();
        }}
      />,
    );
  };

  const open = detail ? sync.games.find((g) => g.id === detail) : undefined;
  if (open) return <GameDetail ctx={ctx} g={open} changed={changes[open.id]} onBack={() => setDetail(null)} onIgnore={ignore} toggle={toggle} />;

  // Con un juego abierto solo ese no se sincroniza a mano (se sincroniza solo al cerrarlo); el resto sí
  const canSync = (g: GameRow) => !busy && g.enabled && ctx.playing !== g.name && !syncBlockReason({ ...ctx.gate, playing: null }) && ["unknown", "up_to_date", "upload", "download", "error"].includes(g.state);
  return (
    <>
      <PanelSection title="Juegos en el hub">
        <PanelSectionRow>{GAMES_INTRO}</PanelSectionRow>
      </PanelSection>
      {busy ? <RunCard ctx={ctx} /> : <SyncBlock ctx={ctx} />}
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy || !ctx.online} onClick={ctx.run(refreshLibrary)} description={SEARCH_HELP}>
            {SEARCH_LABEL}
          </ButtonItem>
        </PanelSectionRow>
        {sync.summary && sync.kind === "refresh" && (
          <PanelSectionRow>
            Encontrados {sync.summary.found} juegos en la Deck. Asociados ahora: {sync.summary.associated}. Ya estaban asociados: {sync.summary.unchanged}. Pendientes de aceptar en el hub:{" "}
            {sync.summary.suggested}. Sin coincidencia en el hub: {sync.summary.ignored}.
          </PanelSectionRow>
        )}
        {!busy && sync.error && <PanelSectionRow>{syncError(sync.error, sync.error_params)}</PanelSectionRow>}
        {!busy && sync.error && sync.error_detail && <PanelSectionRow>Detalle: {sync.error_detail}</PanelSectionRow>}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy || !ctx.online} onClick={ctx.run(listGames)} description={CHECK_HELP}>
            {CHECK_LABEL}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection>
        {sync.games.length === 0 && !busy && !sync.error && (
          <PanelSectionRow>Ningún juego de esta Deck en el hub. Busca juegos de Steam: podrás configurar aquí los que falten.</PanelSectionRow>
        )}
        {sync.games.length > 0 && <PanelSectionRow>{TOGGLE_HELP}</PanelSectionRow>}
        {toggleError && <PanelSectionRow>{toggleError}</PanelSectionRow>}
      </PanelSection>
      {sync.games.map((g) => {
        const badge = gameBadge(g.state, g.enabled);
        const path = paths[g.id];
        const ch = changes[g.id];
        const openNow = ctx.playing === g.name;
        const expanded = gameExpanded(g, gameOpen.get(g.id));
        return (
          <PanelSection key={g.id}>
            {/* Cabecera: solo nombre + estado (+ «Abierto ahora»). Es un botón (foco de mando, A / toque) que pliega o despliega la tarjeta. */}
            <div style={{ borderBottom: "1px solid #ffffff22", paddingBottom: 6, marginBottom: 6 }}>
              <DialogButton
                aria-expanded={expanded}
                onClick={() => {
                  gameOpen.set(g.id, !expanded);
                  setTick((n) => n + 1);
                }}
                style={{ width: "100%", height: "auto", minHeight: 52, padding: "8px 12px", display: "flex", alignItems: "center", gap: 8, textAlign: "left" }}
              >
                <span style={{ ...WRAP, flex: "1 1 120px", minWidth: 0, fontWeight: 600, lineHeight: 1.3 }}>{g.name}</span>
                <span style={{ display: "flex", flex: "0 1 auto", flexWrap: "wrap", justifyContent: "flex-end", alignItems: "center", gap: 6, rowGap: 6 }}>
                  {openNow && <StatusBadge badge={{ tone: "info", label: OPEN_NOW }} />}
                  <StatusBadge badge={badge} />
                </span>
                <span aria-hidden="true" style={{ flex: "0 0 auto", display: "flex" }}>{expanded ? <FaChevronUp /> : <FaChevronDown />}</span>
              </DialogButton>
            </div>
            {expanded && (
              <>
                <PanelSectionRow>
                  <ToggleField
                    label={GAME_ENABLED}
                    description={`${g.appid ? `N.º de Steam: ${g.appid}. ` : "Sin juego de Steam asociado. "}${g.enabled ? gameText(g) : "Desactivado"}`}
                    checked={g.enabled}
                    disabled={busy}
                    onChange={(on: boolean) => toggle(g, on)}
                  />
                </PanelSectionRow>
                {path && (
                  <PanelSectionRow>
                    <div style={{ width: "100%" }}>
                      <div style={MUTED}>{GAME_FOLDER}</div>
                      <div style={MONO}>{path}</div>
                    </div>
                  </PanelSectionRow>
                )}
                {lastText(g) && <PanelSectionRow>{lastText(g)}</PanelSectionRow>}
                {g.last_at && (
                  <PanelSectionRow>
                    <div style={MUTED}>{GAME_LAST_SYNC(whenText(g.last_at))}</div>
                  </PanelSectionRow>
                )}
                {g.enabled && g.state === "conflict" && (
                  <>
                    <PanelSectionRow>{RESOLVE_HELP}</PanelSectionRow>
                    {(["hub", "device"] as const).map((w) => (
                      <PanelSectionRow key={w}>
                        <ButtonItem layout="below" disabled={busy} onClick={() => askResolve(g, w)}>
                          {w === "hub" ? RESOLVE_HUB_LABEL : RESOLVE_DEVICE_LABEL}
                        </ButtonItem>
                      </PanelSectionRow>
                    ))}
                  </>
                )}
                {ch && (
                  <>
                    <PanelSectionRow>
                      <div style={{ ...WRAP, borderLeft: `4px solid ${TONE_COLOR.info}`, paddingLeft: 8 }}>
                        <b>{CHANGED_TITLE}</b>
                        <div style={MONO}>{ch.path}</div>
                      </div>
                    </PanelSectionRow>
                    <PanelSectionRow>
                      <ButtonItem layout="below" onClick={() => setDetail(g.id)}>
                        {CHANGED_VIEW}
                      </ButtonItem>
                    </PanelSectionRow>
                    <PanelSectionRow>
                      <ButtonItem layout="below" onClick={() => ignore(ch)}>
                        {CHANGED_IGNORE}
                      </ButtonItem>
                    </PanelSectionRow>
                  </>
                )}
                <PanelSectionRow>
                  <ButtonItem layout="below" disabled={!canSync(g) || g.state === "conflict"} onClick={ctx.run(() => syncGame(g.id))}>
                    Sincronizar
                  </ButtonItem>
                </PanelSectionRow>
                {openNow && <PanelSectionRow>{GAME_OPEN_HINT}</PanelSectionRow>}
                <PanelSectionRow>
                  <ButtonItem layout="below" onClick={() => setDetail(g.id)}>
                    {GAME_DETAIL}
                  </ButtonItem>
                </PanelSectionRow>
              </>
            )}
          </PanelSection>
        );
      })}
      {sync.games.length > 1 && (
        <PanelSection>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy || !!syncBlockReason(ctx.gate) || ctx.preparing} onClick={ctx.syncAllClick}>
              {SYNC_ALL}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}
    </>
  );
}

// ---- Pendientes (sin configurar en el hub) ----
function PendTab({ ctx, showUnconfigured, onShow, editing }: { ctx: Ctx; showUnconfigured: boolean; onShow: () => void; editing: Record<number, number> }) {
  const { sync, setSync } = ctx;
  const list = sync.unconfigured.filter((u) => !(u.appid in editing));
  const view = unconfiguredView(showUnconfigured, sync.unconfigured.length);
  return (
    <PanelSection title={PEND_TITLE}>
      {view.hiddenNote && (
        <>
          <PanelSectionRow>{view.hiddenNote}</PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" description={PEND_HIDDEN_HELP} onClick={onShow}>
              {PEND_SHOW_LIST}
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
      {!view.showList && !view.hiddenNote && <PanelSectionRow>{PEND_NONE}</PanelSectionRow>}
      {view.showList && (
        <>
          <PanelSectionRow>{UNCONFIGURED_HELP}</PanelSectionRow>
          {sync.unconfigured.some((u) => u.source === "shortcut") && <PanelSectionRow>{SHORTCUT_HELP}</PanelSectionRow>}
          {list.map((u) => (
            <div key={u.appid}>
              <UnconfiguredGame appid={u.appid} name={u.name} source={u.source} disabled={sync.running} onDone={setSync} />
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => ctx.setTab("sugg")}>
                  {PEND_SEE_SUGGESTION}
                </ButtonItem>
              </PanelSectionRow>
            </div>
          ))}
        </>
      )}
    </PanelSection>
  );
}

// ---- Versión ----
function VersionTab({ ctx }: { ctx: Ctx }) {
  const { sh } = ctx;
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<boolean | null>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (copyTimer.current) clearTimeout(copyTimer.current); }, []);
  const info = sh.update;
  const copy = async (url: string) => {
    const ok = await copyText(url);
    setCopied(ok);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(null), 6000);
  };
  const offer = info?.state === "available" && !info.reason && !!info.hub_url;
  const avail = hasUpdate(info);
  const check = async () => {
    setBusy(true);
    setText(VER_CHECKING);
    try {
      const u = await checkUpdate();
      applyUpdate(u, true);
      setText(describeUpdate(u));
    } catch (e) {
      capture("buscar actualizaciones")(e as Error);
      setText(describeUpdate({ state: "error", error: "unexpected" }));
    } finally {
      setBusy(false);
    }
  };
  return (
    <PanelSection title={VER_TITLE}>
      {avail ? (
        <PanelSectionRow>
          <Focusable style={{ display: "flex", gap: 16, alignItems: "center", justifyContent: "center", width: "100%" }}>
            <div style={{ textAlign: "center" }}>
              <div style={MUTED}>{VER_INSTALLED}</div>
              <b style={{ fontFamily: "monospace" }}>{info?.current ?? sh.version ?? "?"}</b>
            </div>
            <span aria-hidden="true">→</span>
            <div style={{ textAlign: "center" }}>
              <div style={MUTED}>{VER_AVAILABLE}</div>
              <b style={{ fontFamily: "monospace", color: TONE_COLOR.info }}>{info?.latest}</b>
            </div>
          </Focusable>
        </PanelSectionRow>
      ) : (
        <PanelSectionRow>
          <Field label={VER_PLUGIN} focusable>
            {sh.version ?? info?.current ?? "?"}
          </Field>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={check}>
          {VER_CHECK}
        </ButtonItem>
      </PanelSectionRow>
      {(text ?? (info ? describeUpdate(info) : null)) && (
        <PanelSectionRow>
          <div role="status" style={WRAP}>{text ?? describeUpdate(info as UpdateInfo)}</div>
        </PanelSectionRow>
      )}
      {ctx.outdated && !avail && (
        <PanelSectionRow>
          <div style={{ ...WRAP, color: TONE_COLOR.err }}>{describeCompat("plugin_outdated")}</div>
        </PanelSectionRow>
      )}
      {(offer || ctx.outdated) && info?.hub_url && (
        <>
          <PanelSectionRow>
            <div style={{ ...WRAP, fontWeight: 700 }}>{VER_HOW}</div>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={WRAP}>{UPDATE_STEPS[0]}</div>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={WRAP}>{UPDATE_STEPS[1]}</div>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ ...WRAP, fontFamily: "monospace", userSelect: "all" }}>{pluginUrl(info.hub_url)}</div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" description={copied === null ? undefined : copied ? COPY_OK : COPY_FAIL} onClick={() => copy(pluginUrl(info.hub_url!))}>
              {COPY_BUTTON}
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={WRAP}>{UPDATE_STEPS[2]}</div>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={MUTED}>{VER_NOT_SELF}</div>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
}

// ---- Ajustes ----
function SettingsTab(p: {
  ctx: Ctx;
  url: string;
  setUrl: (v: string) => void;
  urlError: string | null;
  name: string;
  setName: (v: string) => void;
  nameError: string | null;
  busy: boolean;
  saveName: () => void;
  showUnconfigured: boolean;
  changeShowUnconfigured: (on: boolean) => void;
  lookup: boolean;
  changeLookup: (on: boolean) => void;
  link: () => void;
  check: () => void;
  ping: string | null;
  askUnlink: () => void;
}) {
  const { state } = p.ctx;
  const waiting = state.status === "waiting";
  const linked = state.status === "linked";
  return (
    <>
      <PanelSection title="Juegos">
        <PanelSectionRow>
          <ToggleField label={SHOW_UNCONFIGURED_LABEL} description={SHOW_UNCONFIGURED_HELP} checked={p.showUnconfigured} onChange={p.changeShowUnconfigured} />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title={SAVES_TITLE}>
        <PanelSectionRow>
          <ToggleField label={SAVES_LOOKUP_LABEL} description={SAVES_LOOKUP_HELP} checked={p.lookup} onChange={p.changeLookup} />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Hub">
        <PanelSectionRow>
          <TextField label="Dirección del hub" description="Por ejemplo http://192.168.1.10:8088" value={p.url} disabled={waiting} onChange={(e) => p.setUrl(e.target.value)} />
        </PanelSectionRow>
        {p.urlError && <PanelSectionRow>{p.urlError}</PanelSectionRow>}
      </PanelSection>
      <PanelSection title="Este dispositivo">
        <PanelSectionRow>
          <TextField label="Nombre de este dispositivo" description={NAME_HELP} value={p.name} disabled={waiting} onChange={(e) => p.setName(e.target.value)} />
        </PanelSectionRow>
        {p.nameError && <PanelSectionRow>{p.nameError}</PanelSectionRow>}
        {!waiting && p.name !== state.device_name && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={p.busy} onClick={p.saveName}>
              Guardar nombre
            </ButtonItem>
          </PanelSectionRow>
        )}
        {linked && state.name_changed && (
          <PanelSectionRow>
            Has cambiado el nombre, pero el nombre de este dispositivo en el hub se cambia desde el hub: no se renombra solo. La clave sigue valiendo.
          </PanelSectionRow>
        )}
      </PanelSection>
      <PanelSection title="Vinculación">
        <PanelSectionRow>
          <Field label="Estado">{describe(state)}</Field>
        </PanelSectionRow>
        {!waiting && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={p.busy} onClick={p.link}>
              {linked ? "Volver a vincular" : "Vincular con el hub"}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {linked && (
          <>
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={p.busy} onClick={p.check}>
                Probar conexión
              </ButtonItem>
            </PanelSectionRow>
            {p.ping && <PanelSectionRow>{p.ping}</PanelSectionRow>}
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={p.busy} onClick={p.askUnlink}>
                Desvincular
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>Desvincular solo borra la clave de esta Deck. La revocación real se hace en el hub (Dispositivos).</PanelSectionRow>
          </>
        )}
      </PanelSection>
    </>
  );
}

// ---- Vincular (Inicio sin vincular o esperando) ----
function PairingForm(p: {
  state: State;
  url: string;
  setUrl: (v: string) => void;
  urlError: string | null;
  name: string;
  setName: (v: string) => void;
  nameError: string | null;
  busy: boolean;
  link: () => void;
  cancel: () => void;
}) {
  const { state } = p;
  const waiting = state.status === "waiting";
  return (
    <PanelSection title={waiting ? "Vinculación" : "Vincular con el hub"}>
      <PanelSectionRow>
        <Field label="Estado">{describe(state)}</Field>
      </PanelSectionRow>
      {!waiting && (
        <>
          <PanelSectionRow>
            <TextField label="Dirección del hub" description="Por ejemplo http://192.168.1.10:8088" value={p.url} onChange={(e) => p.setUrl(e.target.value)} />
          </PanelSectionRow>
          {p.urlError && <PanelSectionRow>{p.urlError}</PanelSectionRow>}
          <PanelSectionRow>
            <TextField label="Nombre de este dispositivo" description={NAME_HELP} value={p.name} onChange={(e) => p.setName(e.target.value)} />
          </PanelSectionRow>
          {p.nameError && <PanelSectionRow>{p.nameError}</PanelSectionRow>}
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={p.busy} onClick={p.link}>
              Vincular con el hub
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
      {waiting && (
        <>
          <PanelSectionRow>
            <div style={{ textAlign: "center" }}>
              <div>Comprueba que este código coincide con el del hub y acepta allí:</div>
              <div style={{ fontSize: "3em", fontWeight: "bold", letterSpacing: "0.15em" }}>{state.code}</div>
              <div>Caduca en {mmss(state.seconds_left ?? 0)}</div>
              {state.retrying && <div>Sin conexión con el hub, reintentando…</div>}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={p.cancel}>
              Cancelar
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
}

// Avisos de Steam y del backend: viven mientras el plugin esté cargado (no solo con el panel abierto)
let stopAuto: Array<() => void> = [];

function startAuto(): void {
  if (stopAuto.length) return;
  const problem = (context: string) => (e: Error) => capture(context)(e);
  const first = setTimeout(() => autoCheckUpdate().catch(capture("comprobación automática de versión")), 20_000);
  const every = setInterval(() => autoCheckUpdate().catch(capture("comprobación automática de versión")), 6 * 3600 * 1000);
  announceVersion().catch(capture("versión instalada"));
  stopAuto = [
    () => clearTimeout(first),
    () => clearInterval(every),
    stopPairWatch,
    stopRunWatch,
    startGameWatch(
      (globalThis as { SteamClient?: Parameters<typeof startGameWatch>[0] }).SteamClient,
      (appid, running) => {
        runningApps.set(appid, running);
        gameEvent(appid, running).catch(capture("aviso de abrir o cerrar un juego"));
      },
      problem("detección de juegos"),
      (a, t, r) => {
        // diagnóstico: si falla (p. ej. backend antiguo) se ignora, para no inundar «Fallos detectados»
        diagGameEvent(a, t, r).catch(() => undefined);
      },
    ),
    startNoticePump(
      takeNotices,
      (t) => {
        if (t.code === "queued" || t.code === "offline_open") setShared({ online: false });
        else if (t.kind === "ok") setShared({ online: true });
        showToast(t.kind, t.body, t.title);
      },
      problem("avisos de sincronización"),
    ),
  ];
}

function stopAutoAll(): void {
  stopAuto.forEach((f) => f());
  stopAuto = [];
}

function Content() {
  const sh = useShared();
  const [state, setState] = useState<State | null>(null);
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [ping, setPing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [running, setRunning] = useState<ReadonlySet<number>>(runningApps.snapshot());
  const [showUnconfigured, setShowUnconfigured] = useState(true); // se recuerda en prefs.json (main.py)
  const [lookup, setLookup] = useState(true);
  const [editing, setEditing] = useState<Record<number, number>>({}); // formularios «Configurar» abiertos desde las sugerencias (appid -> remontaje)
  const urlLoaded = useRef(false);
  const linked = state?.status === "linked";
  const [syncState, setSync, mounted] = useSync(linked);
  const sync: SyncState = syncState ?? EMPTY_SYNC;

  useEffect(() => runningApps.subscribe(() => setRunning(runningApps.snapshot())), []);

  const refresh = useCallback(async () => {
    const s = await getState();
    setState(s);
    if (s.status === "waiting") trackPairing(false);
    if (!urlLoaded.current) {
      urlLoaded.current = true;
      setUrl(s.hub_url);
      setName(s.device_name);
    }
  }, []);

  // El panel consulta el estado cada segundo mientras está abierto (la vinculación avanza en main.py)
  useEffect(() => {
    refresh().catch(capture("estado de la vinculación"));
    const t = setInterval(() => refresh().catch(capture("estado de la vinculación")), 1000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    getCompat().then((r) => r?.compat && setShared({ compat: r.compat })).catch(capture("compatibilidad"));
    getPrefs()
      .then((r) => {
        if (r?.ok && typeof r.show_unconfigured === "boolean") setShowUnconfigured(r.show_unconfigured);
        if (r?.ok && typeof r.lutris_lookup === "boolean") setLookup(r.lutris_lookup);
      })
      .catch(capture("preferencias"));
    getVersion().then((v) => v.version && setShared({ version: v.version })).catch(capture("versión del plugin"));
  }, []);

  // El estado de la tarea también dice si hay conexión y si el plugin es demasiado antiguo
  const lastError = useRef<string | null>(null);
  useEffect(() => {
    if (!syncState) return;
    const err = syncState.running ? null : syncState.error;
    if (err === lastError.current) return; // solo cuando el error cambia: tras «Probar conexión» no vuelve a marcarse sin red por un error viejo
    lastError.current = err;
    if (err === "plugin_outdated") setShared({ compat: "plugin_outdated" });
    else if (err === "connection") setShared({ online: false });
  }, [syncState]);

  const changePref = (key: "show_unconfigured" | "lutris_lookup", set: (b: boolean) => void) => (on: boolean) => {
    set(on);
    setPref(key, on)
      .then((r) => {
        if (!r.ok) set(!on);
      })
      .catch((e) => {
        capture("guardar la preferencia")(e);
        set(!on);
      });
  };

  // «Revisar y añadir» / «Añadir manualmente»: abre el formulario del juego sin configurar con nombre y carpeta (vacía) y lo remonta; no guarda nada.
  const openForm = (appid: number, gname: string, path: string) => {
    drafts.set(appid, { open: true, gname, path, sug: path ? { ok: true, appid, name: gname, path, candidates: [path], source: "manifest" } : null });
    setEditing((r) => ({ ...r, [appid]: (r[appid] ?? 0) + 1 }));
  };
  const closeForm = (appid: number) =>
    setEditing((r) => {
      const { [appid]: _, ...rest } = r;
      return rest;
    });

  // Sin fugas: los borradores de juegos que ya no están en «Sin configurar» se descartan (los que siguen no se tocan)
  const unconfiguredIds = syncState?.unconfigured?.map((u) => u.appid);
  useEffect(() => {
    if (unconfiguredIds) drafts.prune(unconfiguredIds);
  }, [unconfiguredIds?.join(",")]);

  const link = async () => {
    setBusy(true);
    setUrlError(null);
    setNameError(null);
    setPing(null);
    try {
      const n = await setDeviceName(name);
      if (!n.ok) {
        setNameError(NAME_ERRORS[n.name_error ?? "empty"]);
        return;
      }
      setName(n.device_name ?? name);
      const a = await setHubUrl(url);
      if (!a.ok) {
        setUrlError(URL_ERRORS[a.url_error ?? "invalid"]);
        return;
      }
      setUrl(a.hub_url ?? url);
      const wasLinked = state?.status === "linked";
      const b = await startPairing();
      if (!b.ok) setUrlError(URL_ERRORS[b.url_error ?? "invalid"]);
      else trackPairing(wasLinked);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const saveName = async () => {
    setBusy(true);
    setNameError(null);
    try {
      const n = await setDeviceName(name);
      if (!n.ok) {
        setNameError(NAME_ERRORS[n.name_error ?? "empty"]);
        return;
      }
      setName(n.device_name ?? name);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const check = async () => {
    setBusy(true);
    setPing(VER_CHECKING);
    try {
      const p = await testConnection();
      setPing(describePing(p));
      setShared({ ...(p.result === "connection" ? { online: false } : p.result === "ok" ? { online: true } : {}), ...(p.compat ? { compat: p.compat } : {}) });
    } finally {
      setBusy(false);
    }
  };

  // Desvincular borra la clave: pide confirmar antes
  const askUnlink = () => {
    showModal(
      <ConfirmModal
        strTitle={UNLINK_CONFIRM.title}
        strDescription={UNLINK_CONFIRM.description}
        strOKButtonText={UNLINK_CONFIRM.ok}
        strCancelButtonText="Cancelar"
        onOK={() => {
          setPing(null);
          unlink()
            .then((s) => {
              setState(s);
              setSync(EMPTY_SYNC);
              setShared({ tab: "home", summary: null, firstSync: false });
              showToast("warn", UNLINK_TOAST);
            })
            .catch(capture("desvincular"));
        }}
      />,
    );
  };

  const playingName = playingGame(running, sync.games)?.name ?? null;
  const outdated = sh.compat === "plugin_outdated";
  const gate: SyncGate = { link: state?.status ?? "unlinked", online: sh.online, outdated, playing: playingName, running: sync.running };
  const names = Object.fromEntries(sync.games.map((g) => [g.id, g.name]));
  const setTab = (t: TabId) => setShared({ tab: t });
  const tab: TabId = state && state.status !== "linked" && tabDisabled(sh.tab, false) ? "home" : sh.tab;

  const run = (f: () => Promise<SyncState>) => () => f().then(setSync).catch(capture("acción sobre los juegos"));

  // «Sincronizar todo». Con una Deck recién vinculada, antes se comprueba qué se bajaría y qué se subiría y se pide confirmar.
  const syncAllClick = () => {
    if (!shared.firstSync) {
      startAll().then(setSync).catch(capture("sincronizar todo"));
      return;
    }
    setPreparing(true);
    (async () => {
      try {
        setSync(await listGames());
        const s = await waitIdle(mounted);
        if (!s) return;
        setSync(s);
        if (s.error) return;
        const c = firstConfirm(firstPlan(s.games));
        showModal(
          <ConfirmModal
            strTitle={c.title}
            strDescription={c.description}
            strOKButtonText={c.ok}
            strCancelButtonText="Cancelar"
            onOK={() => {
              startAll().then(setSync).catch(capture("sincronizar todo"));
            }}
          />,
        );
      } finally {
        if (mounted.current) setPreparing(false);
      }
    })().catch(capture("primera sincronización"));
  };

  if (!state) {
    return (
      <>
        <CrashNotices />
        <PanelSection title="Checkpoint">
          <PanelSectionRow>Cargando…</PanelSectionRow>
        </PanelSection>
      </>
    );
  }

  const ctx: Ctx = {
    state,
    sync,
    setSync,
    sh,
    playing: playingName,
    outdated,
    online: sh.online,
    gate,
    preparing,
    setTab,
    syncAllClick,
    syncRestClick: () => startAll().then(setSync).catch(capture("sincronizar los demás juegos")),
    cancel: () => cancelAll().then(setSync).catch(capture("cancelar")),
    run,
    names,
  };

  const conflict = conflictGames(sync.games)[0];
  const bannerItems = banners({
    tab,
    link: state.status,
    online: sh.online,
    outdated,
    outdatedText: describeCompat("plugin_outdated") ?? "",
    running: sync.running,
    summary: sh.summary,
    playing: playingName,
    conflict: conflict?.name ?? null,
    failed: errorGames(sync.games).length > 0 && !sync.running,
    failedText: (() => {
      const g = errorGames(sync.games)[0];
      return g ? `${g.name}: ${gameText(g)}` : "";
    })(),
    firstSync: sh.firstSync,
    update: hasUpdate(sh.update) ? { latest: sh.update?.latest ?? "?", current: sh.update?.current ?? sh.version ?? "?" } : null,
    connectionText: describePing({ result: "connection" }),
  });
  const onBanner = (b: Banner) => {
    switch (b.action?.kind) {
      case "go_home":
        return setTab("home");
      case "go_games":
        return setTab("games");
      case "go_ver":
        return setTab("ver");
      case "sync_all":
        return syncAllClick();
      case "ping":
        return check();
      case "retry":
        // Reintentar tras un corte repite «Sincronizar todo»; tras un error de un juego, comprueba de nuevo
        if (sh.summary?.interrupted) return ctx.syncAllClick();
        {
          const bad = errorGames(sync.games)[0];
          return bad ? run(() => syncGame(bad.id))() : run(listGames)();
        }
    }
  };

  const tabInput: TabInput = {
    link: state.status,
    conflicts: conflictGames(sync.games).length,
    errors: errorGames(sync.games).length,
    pending: sync.unconfigured.length,
    showPending: showUnconfigured,
    updateAvailable: hasUpdate(sh.update) || outdated,
  };

  const form = (
    <PairingForm state={state} url={url} setUrl={setUrl} urlError={urlError} name={name} setName={setName} nameError={nameError} busy={busy} link={link} cancel={() => cancelPairing().then(setState).catch(capture("cancelar la vinculación"))} />
  );
  const settings = (
    <SettingsTab
      ctx={ctx}
      url={url}
      setUrl={setUrl}
      urlError={urlError}
      name={name}
      setName={setName}
      nameError={nameError}
      busy={busy}
      saveName={saveName}
      showUnconfigured={showUnconfigured}
      changeShowUnconfigured={changePref("show_unconfigured", setShowUnconfigured)}
      lookup={lookup}
      changeLookup={changePref("lutris_lookup", setLookup)}
      link={link}
      check={check}
      ping={ping}
      askUnlink={askUnlink}
    />
  );

  return (
    // L1 / R1 cambian de pestaña (best effort: Steam puede reservarlos en el menú rápido; los botones de las pestañas siempre valen)
    <Focusable
      noFocusRing
      onButtonDown={(e) => {
        if (e.detail.button === GamepadButton.BUMPER_LEFT) setTab(stepTab(tab, -1, linked));
        else if (e.detail.button === GamepadButton.BUMPER_RIGHT) setTab(stepTab(tab, 1, linked));
      }}
    >
      <TabBar tab={tab} onTab={setTab} disabled={(t) => tabDisabled(t, linked)} dots={(t) => tabDot(t, tabInput)} />
      <BannerList items={bannerItems} onAction={onBanner} />
      {tab === "home" && (linked ? <HomeTab ctx={ctx} form={null} /> : <>
        <CrashNotices />
        {form}
      </>)}
      {tab === "games" && linked && <GamesTab ctx={ctx} />}
      {tab === "sugg" && linked && <SaveSuggestions sync={sync} setSync={setSync} editing={editing} openForm={openForm} closeForm={closeForm} />}
      {tab === "pend" && linked && <PendTab ctx={ctx} showUnconfigured={showUnconfigured} onShow={() => changePref("show_unconfigured", setShowUnconfigured)(true)} editing={editing} />}
      {tab === "set" && settings}
      {tab === "ver" && <VersionTab ctx={ctx} />}
    </Focusable>
  );
}

export default definePlugin(() => {
  startCapture();
  startAuto();
  return {
    name: "Checkpoint",
    titleView: <div className={staticClasses.Title}>Checkpoint</div>,
    content: <Content />,
    icon: <FaCloud />,
    onDismount() {
      // El intervalo del panel se para al desmontar el componente; aquí se quitan los manejadores globales de fallos
      stopAutoAll();
      stopCapture();
    },
  };
});
