// Captura global de fallos no capturados (`error`) y promesas rechazadas (`unhandledrejection`). Port de
// `frontend/src/lib/crashwatch.js` del hub, con la misma API: filtra ruido, agrupa repeticiones, limita los avisos
// visibles y nunca lanza ni entra en bucle. Añade `report(raw, kind?)` para las llamadas al backend que fallan
// (`callable` rechazadas), que en el hub no existen, y no repite un aviso que ya está en pantalla.
import { crashReport, redact } from "./crash";

export const MAX_VISIBLE = 3;
export const DEDUPE_MS = 5000;
export const TITLE_MAX = 1000; // el título del fallo se ve entero en «Fallos detectados» (antes 200); ya va saneado
const EXTENSION = /(chrome|moz|safari(-web)?|ms-browser)-extension:\/\//i;
const NETWORK = /^(Failed to fetch|Load failed|NetworkError|Network request failed)/i;

type Kind = "error" | "unhandledrejection";
export interface CrashItem {
  id: number;
  severity: "alert" | "status";
  title: string;
  details: string;
}
/* eslint-disable @typescript-eslint/no-explicit-any */
type Ev = any;
type Win = {
  navigator?: { userAgent?: string };
  addEventListener: (n: string, f: (ev: Ev) => void) => void;
  removeEventListener: (n: string, f: (ev: Ev) => void) => void;
};
export interface CrashWatch {
  stop(): void;
  list(): CrashItem[];
  dismiss(id: number): void;
  report(raw: unknown, kind?: Kind): void;
}

// Fallo conocido del selector de carpetas de Decky: su frontend hace `theError.match(...)` y el error del backend llega como objeto.
const PICKER_BUG = /theError\.match is not a function/;

const asError = (x: any): any => (x && typeof x === "object" ? x : { message: x == null ? "" : String(x) });

/** true si el evento no es un fallo de la propia app. */
export function isNoise(kind: Kind, ev: Ev): boolean {
  if (kind === "unhandledrejection") {
    const r = ev?.reason;
    if (r == null) return true;
    const e = asError(r);
    if (e.name === "AbortError") return true;
    return !String(e.message ?? "").trim();
  }
  const msg = String(ev?.message ?? "");
  if (/^ResizeObserver loop/.test(msg)) return true;
  if (ev?.target && ev.target !== ev.currentTarget && ev.target.tagName && !ev.error) return true; // recurso que no carga
  if (ev?.error?.name === "AbortError") return true;
  if (EXTENSION.test(`${ev?.filename ?? ""}\n${ev?.error?.stack ?? ""}`)) return true; // extensiones del navegador
  if (!ev?.error && (!msg.trim() || /^Script error\.?$/.test(msg))) return true; // sin mensaje útil (origen cruzado)
  return !msg.trim() && !ev?.error?.message;
}

// Quita la pila a errores de red y deja solo nombre y mensaje (ya saneados por crashReport).
const trim = (raw: unknown) => {
  const e = asError(raw);
  const base = { name: e.name, message: e.message ?? "", stack: e.stack as string | undefined };
  if (NETWORK.test(String(base.message))) delete base.stack;
  return base;
};

/**
 * Registra los dos manejadores una vez en `win`. Devuelve { stop, list, dismiss, report }.
 * Opciones: onChange(lista) al cambiar, onReport(item) con cada aviso NUEVO (para mandarlo al log del backend),
 * onPickerError() para el fallo conocido del selector de Decky (si se da, ese fallo no es un aviso; si no, se muestra),
 * version, now, max, dedupeMs.
 */
export function startCrashWatch(
  win: Win,
  {
    onChange = () => {},
    onReport = () => {},
    onPickerError,
    version = "",
    now = Date.now,
    max = MAX_VISIBLE,
    dedupeMs = DEDUPE_MS,
  }: {
    onChange?: (items: CrashItem[]) => void;
    onReport?: (item: CrashItem) => void;
    onPickerError?: () => void;
    version?: string;
    now?: () => number;
    max?: number;
    dedupeMs?: number;
  } = {},
): CrashWatch {
  let items: CrashItem[] = [];
  let nextId = 1;
  const seen = new Map<string, number>(); // clave de repetición -> última vez
  const shown = new Map<number, string>(); // id visible -> clave (no se repite un aviso que sigue en pantalla)
  let busy = false;

  const notify = () => {
    try {
      onChange(items.slice());
    } catch {
      /* un fallo al avisar no puede generar otro aviso */
    }
  };

  const add = (kind: Kind, raw: unknown) => {
    const e = trim(raw);
    if (onPickerError && PICKER_BUG.test(String(e.message))) {
      try {
        onPickerError();
      } catch {
        /* idem */
      }
      return;
    }
    const first = String(e.stack ?? "").split("\n")[1] ?? "";
    const key = `${e.name}|${e.message}|${first}`;
    const t = now();
    for (const [k, at] of seen) if (t - at > dedupeMs) seen.delete(k);
    if (seen.has(key) || [...shown.values()].includes(key)) return;
    seen.set(key, t);
    const details = crashReport(e, { version, nav: win.navigator });
    const title = redact(`${e.name || "Error"}: ${e.message}`).slice(0, TITLE_MAX);
    const item: CrashItem = { id: nextId++, severity: kind === "error" ? "alert" : "status", title, details };
    items = [...items, item].slice(-max);
    shown.set(item.id, key);
    for (const id of [...shown.keys()]) if (!items.some((x) => x.id === id)) shown.delete(id);
    notify();
    try {
      onReport(item);
    } catch {
      /* idem */
    }
  };

  const guarded = (fn: () => void) => {
    if (busy) return;
    busy = true;
    try {
      fn();
    } catch {
      /* el propio manejador nunca lanza */
    } finally {
      busy = false;
    }
  };

  const handle = (kind: Kind) => (ev: Ev) =>
    guarded(() => {
      if (isNoise(kind, ev)) return;
      add(kind, kind === "unhandledrejection" ? ev.reason : (ev.error ?? { message: ev.message }));
    });

  const onError = handle("error");
  const onRejection = handle("unhandledrejection");
  win.addEventListener("error", onError);
  win.addEventListener("unhandledrejection", onRejection);
  return {
    stop() {
      win.removeEventListener("error", onError);
      win.removeEventListener("unhandledrejection", onRejection);
    },
    list: () => items.slice(),
    dismiss(id) {
      items = items.filter((x) => x.id !== id);
      shown.delete(id);
      notify();
    },
    report(raw, kind = "unhandledrejection") {
      guarded(() => {
        if (isNoise(kind, kind === "error" ? { error: raw, message: asError(raw).message } : { reason: raw })) return;
        add(kind, raw);
      });
    },
  };
}
