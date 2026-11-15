import { useCallback, useEffect, useRef, useState } from "react";
import {
  ButtonItem,
  ConfirmModal,
  Field,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  showModal,
  staticClasses,
} from "@decky/ui";
import { FileSelectionType, callable, definePlugin, openFilePicker, toaster } from "@decky/api";
import { FaCloud } from "react-icons/fa";
import { CrashItem, CrashWatch, startCrashWatch } from "./crashwatch";
import { copyText } from "./clipboard";
import { Notice, getLastNotice, startGameWatch, startNoticePump } from "./autosync";
import {
  BROWSE_HELP,
  BROWSE_LABEL,
  CHECK_HELP,
  CHECK_LABEL,
  COPY_BUTTON,
  COPY_FAIL,
  COPY_OK,
  GAMES_INTRO,
  GameFailure,
  NO_PATH_FOUND,
  PATH_FOUND,
  PICKER_FAIL,
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
  UPDATE_SHA_LABEL,
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
  shortSha,
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
  games: GameRow[];
  unconfigured: { appid: number; name: string; source?: string }[]; // instalados en la Deck sin juego en el hub (tras buscar)
}
interface Suggestion extends GameFailure {
  appid?: number;
  name?: string;
  path?: string;
  home?: string; // home de la Deck: donde abre el selector si no hay ruta
  candidates?: string[];
  source?: "proton" | "cloud" | "";
}
interface Configured extends GameFailure {
  game?: { id: string; name: string; appid: number; joined?: boolean };
}
interface Toggled extends GameFailure {
  game?: string;
  enabled?: boolean;
}

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
const takeNotices = callable<[], Notice[]>("take_notices");
const getPrefs = callable<[], { ok: boolean; show_unconfigured: boolean }>("get_prefs");
const setPref = callable<[key: string, value: boolean], { ok: boolean; show_unconfigured?: boolean }>("set_pref");
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
            <Field label={it.title} description={it.details} focusable />
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
  path: "Escribe solo el servidor y el puerto, sin ruta (por ejemplo http://192.168.1.10:8080).",
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
const WRAP = { whiteSpace: "normal", overflowWrap: "anywhere", wordBreak: "break-all" } as const;

function Updates() {
  const [version, setVersion] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<boolean | null>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (copyTimer.current) clearTimeout(copyTimer.current); }, []);
  const copy = async (url: string) => {
    const ok = await copyText(url);
    setCopied(ok);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(null), 6000);
  };
  const offer = info?.state === "available" && !info.reason && !!info.hub_url;

  useEffect(() => {
    getVersion().then((v) => setVersion(v.version)).catch(capture("versión del plugin"));
  }, []);

  const check = async () => {
    setBusy(true);
    setText("Comprobando…");
    try {
      const u = await checkUpdate();
      setInfo(u);
      setText(describeUpdate(u));
    } catch (e) {
      capture("buscar actualizaciones")(e as Error);
      setText(describeUpdate({ state: "error", error: "unexpected" }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title="Actualizaciones">
      <PanelSectionRow>
        <Field label="Versión del plugin">{version ?? "?"}</Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={check}>
          Buscar actualizaciones
        </ButtonItem>
      </PanelSectionRow>
      {text && (
        <PanelSectionRow>
          <div style={WRAP}>{text}</div>
        </PanelSectionRow>
      )}
      {offer && info?.hub_url && (
        <>
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
            <ButtonItem
              layout="below"
              description={copied === null ? undefined : copied ? COPY_OK : COPY_FAIL}
              onClick={() => copy(pluginUrl(info.hub_url!))}
            >
              {COPY_BUTTON}
            </ButtonItem>
          </PanelSectionRow>
          {info.sha256 && (
            <PanelSectionRow>
              <div style={WRAP}>
                {UPDATE_SHA_LABEL}: {shortSha(info.sha256)}
              </div>
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <div style={WRAP}>{UPDATE_STEPS[2]}</div>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
}

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
function UnconfiguredGame({ appid, name, source, disabled, onDone }: { appid: number; name: string; source?: string; disabled: boolean; onDone: (s: SyncState) => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [gname, setGname] = useState(name);
  const [path, setPath] = useState("");
  const [sug, setSug] = useState<Suggestion | null>(null);
  const [pick, setPick] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pickerFailed, setPickerFailed] = useState(false); // el selector de Decky no pudo abrir la carpeta (fallo conocido)

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
      const r = await pickerStart((sug?.candidates ?? []).includes(path) ? path : path.trim());
      if (r.ok && typeof r.path === "string" && r.path.startsWith("/")) start = r.path;
    } catch (e) {
      capture("ruta inicial del selector")(e);
    } finally {
      setBusy(false);
    }
    try {
      const picked = await openFilePicker(FileSelectionType.FOLDER, ...pickerArgs(start));
      if (picked?.path) setPath(picked.path);
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
              description={path && sug?.source ? PATH_FOUND[sug.source] : NO_PATH_FOUND}
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
            <ButtonItem layout="below" disabled={busy} onClick={() => setOpen(false)}>
              Cancelar
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
      {!open && error && <PanelSectionRow>{error}</PanelSectionRow>}
    </div>
  );
}

function Games() {
  const [sync, setSync] = useState<SyncState | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);
  const [showUnconfigured, setShowUnconfigured] = useState(true); // se recuerda en prefs.json (main.py)
  const started = useRef(false);

  const poll = useCallback(async () => {
    const s = await getSyncState();
    setSync(s);
    // La primera vez que se abre el panel, se comprueba el estado de los juegos
    if (!started.current && !s.running && s.games.length === 0 && !s.error) {
      started.current = true;
      setSync(await listGames());
    }
  }, []);

  useEffect(() => {
    poll().catch(capture("estado de los juegos"));
    const t = setInterval(() => poll().catch(capture("estado de los juegos")), 1000);
    return () => clearInterval(t);
  }, [poll]);

  useEffect(() => {
    getPrefs()
      .then((r) => {
        if (r?.ok && typeof r.show_unconfigured === "boolean") setShowUnconfigured(r.show_unconfigured);
      })
      .catch(capture("preferencias"));
  }, []);

  const changeShowUnconfigured = (on: boolean) => {
    setShowUnconfigured(on);
    setPref("show_unconfigured", on)
      .then((r) => {
        if (!r.ok) setShowUnconfigured(!on);
      })
      .catch((e) => {
        capture("guardar la preferencia")(e);
        setShowUnconfigured(!on);
      });
  };

  const run = (f: () => Promise<SyncState>) => () => f().then(setSync).catch(capture("acción sobre los juegos"));

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
          run(() => resolveConflict(g.id, winner))();
        }}
      />,
    );
  };

  const toggle = (g: GameRow, on: boolean) => {
    setToggleError(null);
    // Se refleja ya en pantalla; si el hub no lo acepta se deshace y se explica
    setSync((s) => (s ? { ...s, games: s.games.map((x) => (x.id === g.id ? { ...x, enabled: on } : x)) } : s));
    setGameEnabled(g.id, on)
      .then((r) => {
        if (!r.ok) {
          setToggleError(`${g.name}: ${gameError(r)}`);
          setSync((s) => (s ? { ...s, games: s.games.map((x) => (x.id === g.id ? { ...x, enabled: !on } : x)) } : s));
        }
      })
      .catch((e) => {
        capture("activar o desactivar un juego")(e);
        setToggleError(`${g.name}: ${gameError({ error: "unexpected" })}`);
        setSync((s) => (s ? { ...s, games: s.games.map((x) => (x.id === g.id ? { ...x, enabled: !on } : x)) } : s));
      });
  };

  if (!sync) {
    return (
      <PanelSection title="Juegos">
        <PanelSectionRow>Cargando…</PanelSectionRow>
      </PanelSection>
    );
  }
  const busy = sync.running;
  const canSync = (g: GameRow) =>
    !busy && g.enabled && ["unknown", "up_to_date", "upload", "download", "error"].includes(g.state);
  const syncable = sync.games.some(canSync);
  const unconfigured = unconfiguredView(showUnconfigured, sync.unconfigured.length); // el conteo se sigue calculando

  return (
    <>
      <PanelSection title="Juegos">
        <PanelSectionRow>{GAMES_INTRO}</PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={run(refreshLibrary)} description={SEARCH_HELP}>
            {SEARCH_LABEL}
          </ButtonItem>
        </PanelSectionRow>
        {sync.summary && sync.kind === "refresh" && (
          <PanelSectionRow>
            Encontrados {sync.summary.found} juegos en la Deck. Asociados ahora: {sync.summary.associated}.
            Ya estaban asociados: {sync.summary.unchanged}. Pendientes de aceptar en el hub:{" "}
            {sync.summary.suggested}. Sin coincidencia en el hub: {sync.summary.ignored}.
          </PanelSectionRow>
        )}
        {busy && (
          <>
            <PanelSectionRow>{progressText(sync, sync.games)}</PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => cancelSync().then(setSync).catch(capture("cancelar"))}>
                Cancelar
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
        {!busy && sync.error && <PanelSectionRow>{syncError(sync.error, sync.error_params)}</PanelSectionRow>}
        {!busy && sync.error && sync.error_detail && <PanelSectionRow>Detalle: {sync.error_detail}</PanelSectionRow>}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={run(listGames)} description={CHECK_HELP}>
            {CHECK_LABEL}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label={SHOW_UNCONFIGURED_LABEL}
            description={SHOW_UNCONFIGURED_HELP}
            checked={showUnconfigured}
            onChange={changeShowUnconfigured}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Juegos en el hub">
        {sync.games.length === 0 && !busy && !sync.error && (
          <PanelSectionRow>
            Ningún juego de esta Deck en el hub. Busca juegos de Steam: podrás configurar aquí los que falten.
          </PanelSectionRow>
        )}
        {sync.games.length > 0 && <PanelSectionRow>{TOGGLE_HELP}</PanelSectionRow>}
        {toggleError && <PanelSectionRow>{toggleError}</PanelSectionRow>}
        {sync.games.map((g) => (
          <div key={g.id}>
            <PanelSectionRow>
              <ToggleField
                label={g.name}
                description={`${g.appid ? `N.º de Steam: ${g.appid}. ` : "Sin juego de Steam asociado. "}${g.enabled ? gameText(g) : "Desactivado"}`}
                checked={g.enabled}
                disabled={busy}
                onChange={(on: boolean) => toggle(g, on)}
              />
            </PanelSectionRow>
            {lastText(g) && <PanelSectionRow>{lastText(g)}</PanelSectionRow>}
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
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={!canSync(g)} onClick={run(() => syncGame(g.id))}>
                Sincronizar
              </ButtonItem>
            </PanelSectionRow>
          </div>
        ))}
        {sync.games.length > 1 && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={!syncable} onClick={run(syncAll)}>
              Sincronizar todo
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      {unconfigured.hiddenNote && (
        <PanelSection>
          <PanelSectionRow>{unconfigured.hiddenNote}</PanelSectionRow>
        </PanelSection>
      )}
      {unconfigured.showList && (
        <PanelSection title="Sin configurar en el hub">
          <PanelSectionRow>{UNCONFIGURED_HELP}</PanelSectionRow>
          {sync.unconfigured.some((u) => u.source === "shortcut") && <PanelSectionRow>{SHORTCUT_HELP}</PanelSectionRow>}
          {sync.unconfigured.map((u) => (
            <UnconfiguredGame key={u.appid} appid={u.appid} name={u.name} source={u.source} disabled={busy} onDone={setSync} />
          ))}
        </PanelSection>
      )}
    </>
  );
}

// Último aviso entregado por el auto-sync (solo texto: nunca rutas ni claves)
function AutoPanel() {
  const [last, setLast] = useState(getLastNotice());
  useEffect(() => {
    const t = setInterval(() => setLast(getLastNotice()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <PanelSection title="Avisos">
      <PanelSectionRow>
        <Field label={lastNoticeText(last)} focusable />
      </PanelSectionRow>
    </PanelSection>
  );
}

function Content() {
  const [state, setState] = useState<State | null>(null);
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [ping, setPing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const urlLoaded = useRef(false);

  const refresh = useCallback(async () => {
    const s = await getState();
    setState(s);
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
      const b = await startPairing();
      if (!b.ok) setUrlError(URL_ERRORS[b.url_error ?? "invalid"]);
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
    setPing("Comprobando…");
    try {
      setPing(describePing(await testConnection()));
    } finally {
      setBusy(false);
    }
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

  const waiting = state.status === "waiting";
  const linked = state.status === "linked";

  return (
    <>
      <CrashNotices />
      {linked && <Games />}
      <PanelSection title="Hub">
        <PanelSectionRow>
          <TextField
            label="Dirección del hub"
            description="Por ejemplo http://192.168.1.10:8080"
            value={url}
            disabled={waiting}
            onChange={(e) => setUrl(e.target.value)}
          />
        </PanelSectionRow>
        {urlError && <PanelSectionRow>{urlError}</PanelSectionRow>}
      </PanelSection>

      <PanelSection title="Este dispositivo">
        <PanelSectionRow>
          <TextField
            label="Nombre de este dispositivo"
            description={NAME_HELP}
            value={name}
            disabled={waiting}
            onChange={(e) => setName(e.target.value)}
          />
        </PanelSectionRow>
        {nameError && <PanelSectionRow>{nameError}</PanelSectionRow>}
        {!waiting && name !== state.device_name && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy} onClick={saveName}>
              Guardar nombre
            </ButtonItem>
          </PanelSectionRow>
        )}
        {linked && state.name_changed && (
          <PanelSectionRow>
            Has cambiado el nombre, pero el nombre de este dispositivo en el hub se cambia desde el
            hub: no se renombra solo. La clave sigue valiendo.
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Vinculación">
        <PanelSectionRow>
          <Field label="Estado">{describe(state)}</Field>
        </PanelSectionRow>
        {waiting && (
          <>
            <PanelSectionRow>
              <div style={{ textAlign: "center" }}>
                <div>Comprueba que este código coincide con el del hub y acepta allí:</div>
                <div style={{ fontSize: "3em", fontWeight: "bold", letterSpacing: "0.15em" }}>
                  {state.code}
                </div>
                <div>Caduca en {mmss(state.seconds_left ?? 0)}</div>
                {state.retrying && <div>Sin conexión con el hub, reintentando…</div>}
              </div>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => cancelPairing().then(setState).catch(capture("cancelar la vinculación"))}>
                Cancelar
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
        {!waiting && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy} onClick={link}>
              {linked ? "Volver a vincular" : "Vincular con el hub"}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {linked && (
          <>
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={busy} onClick={check}>
                Probar conexión
              </ButtonItem>
            </PanelSectionRow>
            {ping && <PanelSectionRow>{ping}</PanelSectionRow>}
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy}
                onClick={() => {
                  setPing(null);
                  unlink().then((s) => {
                    setState(s);
                    toaster.toast({
                      title: "Checkpoint",
                      body: "Clave borrada de la Deck. Para que deje de valer, revócala también en el hub.",
                    });
                  }).catch(capture("desvincular"));
                }}
              >
                Desvincular
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              Desvincular solo borra la clave de esta Deck. La revocación real se hace en el hub
              (Dispositivos).
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      <AutoPanel />

      <Updates />
    </>
  );
}

// Avisos automáticos (Tramo 5): Steam avisa de abrir/cerrar un juego -> backend; los avisos del backend -> toasts.
// Viven mientras el plugin esté cargado (no solo con el panel abierto).
let stopAuto: Array<() => void> = [];

function startAuto(): void {
  if (stopAuto.length) return;
  const problem = (context: string) => (e: Error) => capture(context)(e);
  stopAuto = [
    startGameWatch(
      (globalThis as { SteamClient?: Parameters<typeof startGameWatch>[0] }).SteamClient,
      (appid, running) => {
        gameEvent(appid, running).catch(capture("aviso de abrir o cerrar un juego"));
      },
      problem("detección de juegos"),
    ),
    startNoticePump(
      takeNotices,
      (t) => toaster.toast({ title: t.title, body: t.body, duration: t.level === "info" ? 6000 : 12000 }),
      problem("avisos de sincronización"),
    ),
  ];
}

function stopAutoAll(): void {
  stopAuto.forEach((f) => f());
  stopAuto = [];
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
