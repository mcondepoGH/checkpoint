// Captura global de fallos no capturados (`error`) y promesas rechazadas (`unhandledrejection`), sin React.
// Filtra ruido, agrupa repeticiones, limita los avisos visibles y nunca lanza ni entra en bucle.
// Los detalles salen de crashReport (todo saneado); en errores de red no hay pila y las URLs pierden sus parámetros.
import { crashReport, redact } from './crash.js';

export const MAX_VISIBLE = 3;
export const DEDUPE_MS = 5000;
const EXTENSION = /(chrome|moz|safari(-web)?|ms-browser)-extension:\/\//i;
const NETWORK = /^(Failed to fetch|Load failed|NetworkError|Network request failed)/i;

const asError = (x) => (x && typeof x === 'object' ? x : { message: x == null ? '' : String(x) });

/** true si el evento no es un fallo de la propia app. `kind`: 'error' | 'unhandledrejection'. */
export function isNoise(kind, ev) {
  if (kind === 'unhandledrejection') {
    const r = ev?.reason;
    if (r == null) return true;
    const e = asError(r);
    if (e.name === 'AbortError') return true;
    return !String(e.message ?? '').trim();
  }
  const msg = String(ev?.message ?? '');
  if (/^ResizeObserver loop/.test(msg)) return true;
  if (ev?.target && ev.target !== ev.currentTarget && ev.target.tagName && !ev.error) return true; // recurso que no carga
  if (ev?.error?.name === 'AbortError') return true;
  if (EXTENSION.test(`${ev?.filename ?? ''}\n${ev?.error?.stack ?? ''}`)) return true; // extensiones del navegador
  if (!ev?.error && (!msg.trim() || /^Script error\.?$/.test(msg))) return true; // sin mensaje útil (origen cruzado)
  return !msg.trim() && !ev?.error?.message;
}

// Quita la pila a errores de red y deja solo nombre y mensaje (ya saneados por crashReport).
const trim = (raw) => {
  const e = asError(raw);
  const base = { name: e.name, message: e.message ?? '', stack: e.stack };
  if (NETWORK.test(String(base.message)) || (base.name === 'TypeError' && NETWORK.test(String(base.message)))) delete base.stack;
  return base;
};

/**
 * Registra los dos manejadores una vez en `win`. Devuelve { stop, list, dismiss }.
 * Opciones: onChange(lista) al cambiar, version, now, max, dedupeMs.
 */
export function startCrashWatch(win, { onChange = () => {}, version = '', now = Date.now, max = MAX_VISIBLE, dedupeMs = DEDUPE_MS } = {}) {
  let items = [];
  let nextId = 1;
  const seen = new Map(); // clave de repetición -> última vez
  let busy = false;

  const notify = () => {
    try {
      onChange(items.slice());
    } catch {
      /* un fallo al avisar no puede generar otro aviso */
    }
  };

  const handle = (kind) => (ev) => {
    if (busy) return;
    busy = true;
    try {
      if (isNoise(kind, ev)) return;
      const raw = kind === 'unhandledrejection' ? ev.reason : (ev.error ?? { message: ev.message });
      const e = trim(raw);
      const first = String(e.stack ?? '').split('\n')[1] ?? '';
      const key = `${e.name}|${e.message}|${first}`;
      const t = now();
      for (const [k, at] of seen) if (t - at > dedupeMs) seen.delete(k);
      if (seen.has(key)) return;
      seen.set(key, t);
      const details = crashReport(e, { version, nav: win.navigator });
      const title = redact(`${e.name || 'Error'}: ${e.message}`).slice(0, 200);
      items = [...items, { id: nextId++, severity: kind === 'error' ? 'alert' : 'status', title, details }].slice(-max);
      notify();
    } catch {
      /* el propio manejador nunca lanza */
    } finally {
      busy = false;
    }
  };

  const onError = handle('error');
  const onRejection = handle('unhandledrejection');
  win.addEventListener('error', onError);
  win.addEventListener('unhandledrejection', onRejection);
  return {
    stop() {
      win.removeEventListener('error', onError);
      win.removeEventListener('unhandledrejection', onRejection);
    },
    list: () => items.slice(),
    dismiss(id) {
      items = items.filter((x) => x.id !== id);
      notify();
    },
  };
}
