// Lógica pura del panel por pestañas (sin Decky ni React): estado del dispositivo, avisos fijos, puntos de las pestañas,
// resumen y progreso de «Sincronizar todo», plan de la primera sincronización y avisos de versión.
import {
  BANNER,
  CHANGE_FOLDER_OPEN,
  FirstPlan,
  GAME_BADGES,
  HOME_STATUS,
  SYNC_BLOCKED,
  SYNC_ROW,
  TAB_ORDER,
  TabId,
  Tone,
  tabDotCount,
} from "./texts";

export interface Badge {
  tone: Tone;
  label: string;
}

// ---- insignias ----
export interface HomeInput {
  link: string; // estado de la vinculación (`State.status`)
  online: boolean;
  outdated: boolean;
  playing: string | null; // nombre del juego del hub abierto ahora, si lo hay
  running: boolean; // hay una tarea de sincronización en marcha
  conflicts: number;
  errors: number;
}
/** Estado del dispositivo para la tarjeta de Inicio. Prioridad: plugin antiguo, sin conexión, juego abierto, sincronizando, conflicto, errores. */
export function homeStatus(i: HomeInput): Badge {
  if (i.link === "waiting") return { tone: "info", label: HOME_STATUS.waiting };
  if (i.link !== "linked") return { tone: "nf", label: HOME_STATUS.unlinked };
  if (i.outdated) return { tone: "err", label: HOME_STATUS.outdated };
  if (!i.online) return { tone: "warn", label: HOME_STATUS.offline };
  if (i.playing) return { tone: "info", label: HOME_STATUS.playing };
  if (i.running) return { tone: "info", label: HOME_STATUS.syncing };
  if (i.conflicts > 0) return { tone: "warn", label: HOME_STATUS.conflict };
  if (i.errors > 0) return { tone: "err", label: HOME_STATUS.error };
  return { tone: "ok", label: HOME_STATUS.ok };
}

const GAME_TONES: Record<string, Tone> = {
  up_to_date: "ok",
  upload: "info",
  download: "info",
  conflict: "warn",
  error: "err",
  disabled: "nf",
  unknown: "nf",
  no_path: "warn",
  missing_dir: "warn",
};
export function gameBadge(state: string, enabled = true): Badge {
  const s = enabled ? state : "disabled";
  return { tone: GAME_TONES[s] ?? "nf", label: GAME_BADGES[s] ?? GAME_BADGES.unknown };
}

export interface GameLike {
  id: string;
  name: string;
  appid: number | null;
  enabled: boolean;
  state: string;
}
export interface Counts {
  upload: number;
  download: number;
  conflict: number;
  error: number;
}
export function countStates(games: GameLike[]): Counts {
  const c: Counts = { upload: 0, download: 0, conflict: 0, error: 0 };
  for (const g of games) if (g.enabled && g.state in c) c[g.state as keyof Counts]++;
  return c;
}
export const conflictGames = <T extends GameLike>(games: T[]): T[] => games.filter((g) => g.enabled && g.state === "conflict");
export const errorGames = <T extends GameLike>(games: T[]): T[] => games.filter((g) => g.enabled && g.state === "error");

/** Juego del hub que está abierto ahora (por appid de Steam), o null. */
export function playingGame<T extends GameLike>(running: ReadonlySet<number>, games: T[]): T | null {
  return games.find((g) => g.enabled && typeof g.appid === "number" && running.has(g.appid)) ?? null;
}

// ---- «Sincronizar todo»: resultados por juego ----
export interface RunResult {
  state: string;
  code?: string;
  files?: number;
}
export interface Tally {
  up: number;
  down: number;
  conf: number;
  err: number;
  skipped: number; // juego abierto: se sincroniza al cerrarlo, no es un error
  left: number; // sin sincronizar (no se llegó o se cortó)
  interrupted: boolean; // se cortó por falta de conexión o por cancelar
}
const CUT_CODES = new Set(["connection", "cancelled"]);
/** Cuenta lo ocurrido en una tarea `sync_all`. Un conflicto o un error de un juego no cuenta como corte del resto. */
export function tally(plan: string[], results: Record<string, RunResult>): Tally {
  const t: Tally = { up: 0, down: 0, conf: 0, err: 0, skipped: 0, left: 0, interrupted: false };
  for (const id of plan) {
    const r = results[id];
    if (!r) {
      t.left++;
      continue;
    }
    if (r.state === "uploaded") t.up++;
    else if (r.state === "downloaded") t.down++;
    else if (r.state === "conflict") t.conf++;
    else if (r.state === "error") {
      if (r.code === "game_running") t.skipped++;
      else if (r.code && CUT_CODES.has(r.code)) t.left++;
      else t.err++;
    }
  }
  t.interrupted = t.left > 0;
  return t;
}

export type RowKind = "done" | "run" | "wait" | "fail" | "conflict" | "skip" | "left";
export interface ProgressRow {
  id: string;
  name: string;
  kind: RowKind;
  text: string;
}
/** Una fila por juego del plan: hecho (subido/bajado/al día), en curso, en espera, con error, en conflicto o saltado. */
export function progressRows(
  plan: string[],
  results: Record<string, RunResult>,
  current: string | null,
  names: Record<string, string>,
  finished: boolean,
): ProgressRow[] {
  return plan.map((id) => {
    const r = results[id];
    const name = names[id] ?? id;
    if (r) {
      if (r.state === "uploaded") return { id, name, kind: "done", text: SYNC_ROW.done_up };
      if (r.state === "downloaded") return { id, name, kind: "done", text: SYNC_ROW.done_down };
      if (r.state === "conflict") return { id, name, kind: "conflict", text: SYNC_ROW.conflict };
      if (r.state === "error") {
        if (r.code === "game_running") return { id, name, kind: "skip", text: SYNC_ROW.skip };
        if (r.code && CUT_CODES.has(r.code)) return { id, name, kind: "left", text: SYNC_ROW.left };
        return { id, name, kind: "fail", text: SYNC_ROW.fail };
      }
      return { id, name, kind: "done", text: SYNC_ROW.done_ok };
    }
    if (!finished && id === current) return { id, name, kind: "run", text: SYNC_ROW.run };
    return finished ? { id, name, kind: "left", text: SYNC_ROW.left } : { id, name, kind: "wait", text: SYNC_ROW.wait };
  });
}

export type Level = "ok" | "info" | "warn" | "error";
export const LEVEL_TONE: Record<Level, Tone> = { ok: "ok", info: "info", warn: "warn", error: "err" };
/** Nivel del aviso de fin de «Sincronizar todo»: errores o conflictos = aviso; corte = aviso; si no, éxito. */
export function summaryLevel(t: Tally): Level {
  if (t.err > 0) return "error";
  if (t.conf > 0 || t.interrupted) return "warn";
  return "ok";
}

// ---- bloqueos de «Sincronizar» ----
export interface SyncGate {
  link: string;
  online: boolean;
  outdated: boolean;
  playing: string | null;
  running: boolean;
}
/** Por qué no se puede sincronizar a mano ahora (texto) o null si se puede. */
export function syncBlockReason(g: SyncGate): string | null {
  if (g.link !== "linked") return BANNER.unlinkedText;
  if (g.running) return SYNC_BLOCKED.busy;
  if (g.outdated) return SYNC_BLOCKED.outdated;
  if (!g.online) return SYNC_BLOCKED.offline;
  if (g.playing) return SYNC_BLOCKED.playing(g.playing);
  return null;
}
/** Con un juego abierto no se sincroniza todo, pero sí «los demás». */
export function canSyncRest(g: SyncGate): boolean {
  return g.link === "linked" && !g.running && !g.outdated && g.online && g.playing !== null;
}

// ---- primera sincronización de un dispositivo recién vinculado ----
/** Qué se bajaría y qué se subiría, a partir de los estados tras «Comprobar cambios pendientes». */
export function firstPlan(games: GameLike[]): FirstPlan {
  const p: FirstPlan = { down: 0, up: 0, conflicts: 0, skipped: 0 };
  for (const g of games) {
    if (!g.enabled || g.state === "no_path" || g.state === "missing_dir") p.skipped++;
    else if (g.state === "download") p.down++;
    else if (g.state === "upload") p.up++;
    else if (g.state === "conflict") p.conflicts++;
  }
  return p;
}

// ---- avisos fijos bajo las pestañas ----
export type BannerAction = "go_home" | "go_games" | "go_ver" | "retry" | "ping" | "sync_all";
export interface Banner {
  id: string;
  tone: Tone;
  title: string;
  text: string;
  action?: { label: string; kind: BannerAction };
}
export interface BannerInput {
  tab: TabId;
  link: string;
  online: boolean;
  outdated: boolean;
  outdatedText: string;
  running: boolean;
  summary: Tally | null; // resumen de la última «Sincronizar todo»; solo un corte (interrupted) genera aviso fijo
  playing: string | null;
  conflict: string | null; // nombre del primer juego en conflicto
  failed: boolean; // algún juego con error
  failedText: string;
  firstSync: boolean;
  update: { latest: string; current: string } | null;
  connectionText: string;
}
const MAX_BANNERS = 2;
/** Avisos fijos, por prioridad (máx. 2). Sin vincular: solo uno y solo fuera de Inicio. */
export function banners(i: BannerInput): Banner[] {
  if (i.link !== "linked") {
    return i.link === "unlinked" && i.tab !== "home"
      ? [{ id: "unlinked", tone: "warn", title: BANNER.unlinkedTitle, text: BANNER.unlinkedText, action: { label: BANNER.goHome, kind: "go_home" } }]
      : [];
  }
  const out: Banner[] = [];
  const s = i.summary;
  if (s && !i.running) {
    if (s.interrupted) {
      out.push({
        id: "cut",
        tone: "warn",
        title: BANNER.cutTitle,
        text: BANNER.cutText(s.left),
        action: i.online ? { label: BANNER.retry, kind: "retry" } : { label: BANNER.ping, kind: "ping" },
      });
    }
    // Sin banner de éxito ni de resumen con conflictos o errores: el toast ya lo dice y «conflict» / «failed» siguen fijos
  }
  if (i.outdated) out.push({ id: "outdated", tone: "err", title: BANNER.outdatedTitle, text: i.outdatedText, action: { label: BANNER.howToUpdate, kind: "go_ver" } });
  if (!i.online) out.push({ id: "offline", tone: "warn", title: BANNER.offlineTitle, text: `${i.connectionText} ${BANNER.offlineText}`, action: { label: BANNER.ping, kind: "ping" } });
  if (i.playing) out.push({ id: "playing", tone: "info", title: BANNER.playingTitle(i.playing), text: BANNER.playingText });
  if (i.conflict) out.push({ id: "conflict", tone: "warn", title: BANNER.conflictTitle(i.conflict), text: BANNER.conflictText, action: { label: BANNER.resolve, kind: "go_games" } });
  if (i.failed) out.push({ id: "failed", tone: "err", title: BANNER.failedTitle, text: i.failedText, action: { label: BANNER.retry, kind: "retry" } });
  if (i.firstSync && !i.running && i.online && !s) out.push({ id: "first", tone: "info", title: BANNER.newDeviceTitle, text: BANNER.newDeviceText, action: { label: "Sincronizar todo", kind: "sync_all" } });
  if (i.update) out.push({ id: "update", tone: "info", title: BANNER.updateTitle(i.update.latest), text: BANNER.updateText(i.update.current), action: { label: BANNER.howToUpdate, kind: "go_ver" } });
  return out.slice(0, MAX_BANNERS);
}

// ---- tarjetas de «Juegos»: plegadas por defecto ----
/** ¿Está desplegada la tarjeta? Lo que elige el usuario (`override`) manda; sin elección, solo se despliega un juego activado
 *  con conflicto o error (lo único urgente: sus acciones están dentro de la tarjeta). Lo demás sale plegado: nombre + estado. */
export function gameExpanded(g: { enabled: boolean; state: string }, override?: boolean): boolean {
  if (override !== undefined) return override;
  return g.enabled && (g.state === "conflict" || g.state === "error");
}

// ---- pestañas ----
export type TabDot = { kind: "attention" } | { kind: "count"; n: number; label: string } | { kind: "update" };
export interface TabInput {
  link: string;
  conflicts: number;
  errors: number;
  pending: number; // juegos sin configurar
  showPending: boolean;
  updateAvailable: boolean; // versión nueva o plugin antiguo
}
const NEEDS_LINK: TabId[] = ["games", "sugg", "pend"];
export const tabDisabled = (id: TabId, linked: boolean): boolean => !linked && NEEDS_LINK.includes(id);
export function tabDot(id: TabId, i: TabInput): TabDot | null {
  if (tabDisabled(id, i.link === "linked")) return null;
  if (id === "games" && (i.conflicts > 0 || i.errors > 0)) return { kind: "attention" };
  if (id === "pend" && i.pending > 0 && i.showPending) return { kind: "count", n: i.pending, label: tabDotCount(i.pending) };
  if (id === "ver" && i.updateAvailable) return { kind: "update" };
  return null;
}
/** `scrollLeft` que deja el botón de una pestaña centrado en la barra, sin pasarse de los extremos (la primera queda a 0).
 *  Si las pestañas caben en el ancho no hay nada que desplazar (0). */
export function tabScrollLeft(offsetLeft: number, width: number, viewport: number, scrollWidth: number): number {
  const max = Math.max(0, scrollWidth - viewport);
  if (max === 0) return 0;
  return Math.max(0, Math.min(max, Math.round(offsetLeft - (viewport - width) / 2)));
}
/** Pestaña anterior o siguiente (L1 / R1), saltando las desactivadas y sin dar la vuelta. */
export function stepTab(cur: TabId, dir: -1 | 1, linked: boolean): TabId {
  let i = TAB_ORDER.indexOf(cur);
  for (let n = 0; n < TAB_ORDER.length; n++) {
    i += dir;
    if (i < 0 || i >= TAB_ORDER.length) return cur;
    if (!tabDisabled(TAB_ORDER[i], linked)) return TAB_ORDER[i];
  }
  return cur;
}

// ---- versión ----
/** `YYYY-MM-DD hh:mm` o texto relativo corto de una época en segundos. */
export function whenText(epoch: number | null | undefined, now: Date = new Date()): string {
  if (typeof epoch !== "number" || !isFinite(epoch) || epoch <= 0) return "ninguna todavía";
  const d = new Date(epoch * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`;
  const same = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  if (same(d, now)) return `hoy ${hm}`;
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (same(d, y)) return `ayer ${hm}`;
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${hm}`;
}
/** Última sincronización de todos los juegos (la más reciente de `last_at`), o null. */
export function latestSync(games: { last_at?: number }[]): number | null {
  let best: number | null = null;
  for (const g of games) if (typeof g.last_at === "number" && (best === null || g.last_at > best)) best = g.last_at;
  return best;
}

/** Recuerda las versiones ya avisadas: un solo toast por versión nueva. */
export class VersionNotifier {
  private seen = new Set<string>();
  shouldToast(latest: string | null | undefined): boolean {
    if (!latest || this.seen.has(latest)) return false;
    this.seen.add(latest);
    return true;
  }
}
/** Hay versión nueva anunciada por el hub (también con el hub antiguo: solo se avisa). */
export const hasUpdate = (u: { state?: string; latest?: string | null } | null | undefined): boolean => u?.state === "available" && !!u.latest;
/** «Checkpoint actualizado a X» solo si la versión vista antes existía y cambió. */
export const updatedTo = (prev: string | null | undefined, cur: string | null | undefined): string | null =>
  prev && cur && prev !== cur ? cur : null;

// ---- textos largos (avisos, fallos): se ven enteros, con salto de línea; solo si son muy largos tienen scroll interno ----
/** Alto máximo (px) de un bloque de texto largo; por encima hay scroll con el mando (foco). Nunca se corta con «…». */
export const LONG_TEXT_MAX_HEIGHT = 200;
export const LONG_TEXT_STYLE = {
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
  wordBreak: "break-word",
  maxHeight: LONG_TEXT_MAX_HEIGHT,
  overflowY: "auto",
} as const;

// ---- cambiar la carpeta de un juego ya configurado ----
/** Botones «Cambiar carpeta», «Usar esta carpeta» y «Deshacer»: con el juego abierto se desactivan y dicen por qué; con una tarea en marcha, sin texto. */
export function changeFolderBlock(i: { playing: boolean; busy: boolean }): { disabled: boolean; hint: string | null } {
  return { disabled: i.playing || i.busy, hint: i.playing ? CHANGE_FOLDER_OPEN : null };
}

export interface FolderChange {
  path: string;
  previous: string;
}
/** Memoria de módulo (el detalle se desmonta al «Volver» y el panel entero al abrir el selector): último cambio de carpeta por
 *  juego, para «Deshacer», y último error. Solo recuerda el último cambio; sin ruta anterior (o misma ruta) no hay Deshacer. */
export class FolderChanges {
  private undo = new Map<string, FolderChange>();
  private errors = new Map<string, string>();
  private listeners = new Set<(kind: "changed" | "error") => void>();
  private emit(kind: "changed" | "error"): void {
    this.listeners.forEach((f) => f(kind));
  }
  subscribe(f: (kind: "changed" | "error") => void): () => void {
    this.listeners.add(f);
    return () => {
      this.listeners.delete(f);
    };
  }
  undoOf(game: string): FolderChange | undefined {
    return this.undo.get(game);
  }
  errorOf(game: string): string | undefined {
    return this.errors.get(game);
  }
  applied(game: string, r: { path: string; previous: string | null }): void {
    this.errors.delete(game);
    if (r.previous === null) this.undo.delete(game);
    else if (r.previous !== r.path) this.undo.set(game, { path: r.path, previous: r.previous });
    this.emit("changed");
  }
  undone(game: string): void {
    this.undo.delete(game);
    this.errors.delete(game);
    this.emit("changed");
  }
  fail(game: string, text: string): void {
    this.errors.set(game, text);
    this.emit("error");
  }
  clearError(game: string): void {
    if (this.errors.delete(game)) this.emit("error");
  }
}
