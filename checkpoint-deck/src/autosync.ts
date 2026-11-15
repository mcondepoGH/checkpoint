// Avisos automáticos de abrir y cerrar juegos (Tramo 5). Dos piezas sin dependencias de Decky, para probarlas con Node:
// - `startGameWatch` (con `onRaw` opcional para diagnosticar los eventos que el filtro descarta): escucha a Steam (`SteamClient.GameSessions.RegisterForAppLifetimeNotifications`, API INTERNA sin
//   contrato estable: una actualización de Steam puede romperla; los toasts confirman que funciona en una Deck real) y avisa al backend con (appid, abierto).
// - `startNoticePump` + `noticeText`: recoge los avisos que deja el backend (`take_notices`) y los convierte en toasts.
import { LastNotice, TOAST_MAX, toastLine } from "./texts";

export { TOAST_MAX };

interface Registration {
  unregister?: () => void;
}
interface SteamLike {
  GameSessions?: {
    RegisterForAppLifetimeNotifications?: (cb: (n: unknown) => void) => Registration | undefined;
  };
}

/** Registra el escuchador. Devuelve la función que lo quita (idempotente). `onProblem` recibe lo que falle. */
export function startGameWatch(
  steam: SteamLike | undefined,
  send: (appid: number, running: boolean) => void,
  onProblem: (e: Error) => void,
  onRaw?: (unAppID: string, tipo: string, bRunning: string) => void,
): () => void {
  const register = steam?.GameSessions?.RegisterForAppLifetimeNotifications;
  if (typeof register !== "function") {
    onProblem(new Error("SteamClient.GameSessions no está disponible: no se detectará abrir ni cerrar juegos"));
    return () => undefined;
  }
  let last = "";
  let reg: Registration | undefined;
  try {
    reg = register.call(steam!.GameSessions, (raw: unknown) => {
      const n = raw as { unAppID?: unknown; bRunning?: unknown } | null | undefined;
      // Diagnóstico: el evento crudo (solo estos tres campos, como texto) antes del filtro; nunca debe lanzar
      try {
        onRaw?.(String(n?.unAppID), typeof n?.unAppID, String(n?.bRunning));
      } catch {
        /* el diagnóstico no puede romper la detección */
      }
      const appid = n?.unAppID;
      // appid 0 = juego que no es de Steam (sin soportar en el MVP); lo demás mal formado se ignora
      if (typeof appid !== "number" || !Number.isInteger(appid) || appid <= 0 || typeof n?.bRunning !== "boolean") return;
      const key = `${appid}:${n.bRunning}`;
      if (key === last) return; // Steam repite el aviso (una vez por instancia)
      last = key;
      try {
        send(appid, n.bRunning);
      } catch (e) {
        onProblem(e instanceof Error ? e : new Error(String(e)));
      }
    });
  } catch (e) {
    onProblem(e instanceof Error ? e : new Error(String(e)));
    return () => undefined;
  }
  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    try {
      reg?.unregister?.();
    } catch {
      /* al descargar el plugin no hay nada más que hacer */
    }
  };
}

// ---- avisos del backend ----
export interface Notice {
  id: number;
  code: string;
  game: string | null;
  level: "info" | "warning" | "error";
  params: { files?: number; reason?: string };
}
export interface Toast {
  title: string;
  body: string;
  level: Notice["level"];
}

/** Cuerpo del toast: corto (máx. `TOAST_MAX` caracteres, sin punto final); Decky corta los largos. Los detalles de un
 *  fallo van al panel «Juegos» y al log, no aquí. */
export function noticeText(n: Notice): Toast {
  const g = n.game ?? "Juego";
  const line = (rest: string) => toastLine(g, rest);
  const body = ((): string => {
    switch (n.code) {
      case "downloaded":
        return line("guardado bajado");
      case "uploaded":
        return line("guardado subido");
      case "up_to_date":
        return line("al día");
      case "no_path":
        return line("sin carpeta de guardado");
      case "missing_dir":
        return line("carpeta no encontrada");
      case "conflict":
        return line("conflicto, resuélvelo");
      case "joined":
        return line("unido a este equipo");
      case "queued":
        return "Sin conexión: cierre en cola";
      case "offline_open":
        return "Sin conexión: no se sincronizó";
      case "unauthorized":
        return "Clave no válida: vuelve a vincular";
      case "sync_failed":
        return line("error al sincronizar");
      default:
        return line("aviso de Checkpoint");
    }
  })();
  return { title: "Checkpoint", body, level: n.level };
}

type Timers = { setInterval: (f: () => void, ms: number) => unknown; clearInterval: (id: unknown) => void };
const defaultTimers: Timers = {
  setInterval: (f, ms) => globalThis.setInterval(f, ms),
  clearInterval: (id) => globalThis.clearInterval(id as number),
};

// Último aviso entregado, solo en memoria del front (el panel lo lee con `getLastNotice`)
let lastNotice: LastNotice | null = null;
export function getLastNotice(): LastNotice | null {
  return lastNotice;
}
const hhmm = (d: Date) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

/** Consulta cada `ms` los avisos del backend y los muestra. Nunca se solapa: una consulta a la vez. */
export function startNoticePump(
  take: () => Promise<Notice[]>,
  show: (t: Toast) => void,
  onProblem: (e: Error) => void,
  ms = 2000,
  timers: Timers = defaultTimers,
  now: () => Date = () => new Date(),
): () => void {
  let busy = false;
  const tick = async () => {
    if (busy) return;
    busy = true;
    try {
      const list = await take();
      for (const n of Array.isArray(list) ? list : []) {
        const t = noticeText(n);
        lastNotice = { time: hhmm(now()), text: t.body }; // entregado por el backend, aunque el toast falle
        try {
          show(t);
        } catch (e) {
          onProblem(e instanceof Error ? e : new Error(String(e)));
        }
      }
    } catch (e) {
      onProblem(e instanceof Error ? e : new Error(String(e)));
    } finally {
      busy = false;
    }
  };
  const id = timers.setInterval(tick, ms);
  return () => timers.clearInterval(id);
}
