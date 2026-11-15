import { useEffect, useMemo, useState } from 'react';
import { getWatches } from '#src/lib/api/sync.js';

export const WATCH_POLL_MS = 5000; // el backend no emite eventos de vigilancia: se consulta /api/watches (los SSE existentes son de config y de ejecuciones)
export const NO_WATCHES = { now: null, watches: [], playing: [], results: [], conflicts: [], resolutions: [] };

// Lo que guarda el estado a partir de la respuesta de /api/watches (tolerante a respuestas raras).
// `playing` («jugando» de dispositivos http), `results` (último resultado de su sync), `conflicts` (conflictos de datos
// registrados) y `resolutions` (resoluciones pendientes) no existen en un hub antiguo: listas vacías.
const list = (v) => (Array.isArray(v) ? v : []);
export const watchState = (r) => ({
  now: (r && r.now) || null,
  watches: list(r && r.watches),
  playing: list(r && r.playing),
  results: list(r && r.results),
  conflicts: list(r && r.conflicts),
  resolutions: list(r && r.resolutions),
});

// Una sola consulta periódica de /api/watches para toda la app (la usan la cabecera y las tarjetas de Sincronizar).
// Solo con la pestaña visible; al volver a verla refresca al momento. Sin sesión (`enabled` falso) no consulta.
// Un fallo de red nunca molesta: se conserva el último estado.
export function useWatches(enabled = true) {
  const [watch, setWatch] = useState(NO_WATCHES);
  const [refresh, setRefresh] = useState(() => () => {}); // consulta al momento (tras resolver un conflicto, sin esperar al sondeo)
  useEffect(() => {
    if (!enabled) {
      setWatch(NO_WATCHES);
      return undefined;
    }
    let alive = true;
    const load = () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      getWatches()
        .then((r) => alive && setWatch(watchState(r)))
        .catch(() => {});
    };
    setRefresh(() => load);
    load();
    const timer = setInterval(load, WATCH_POLL_MS);
    document.addEventListener('visibilitychange', load);
    return () => {
      alive = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', load);
    };
  }, [enabled]);
  return useMemo(() => ({ ...watch, refresh }), [watch, refresh]);
}
