import { startPolling } from '#src/lib/poll.js';

export const VERSIONS_POLL_MS = 15000; // sin SSE para esto: se consulta la versión más reciente (barato: GET /api/versions/{game}/limit)

// Vigila la versión más reciente de un juego (`latest` de /limit) y el «Actual» del hub (`current.id`) para recargar la lista
// cuando aparece una versión nueva (p. ej. el checkpoint de cierre) o cambia el contenido del hub.
// La primera respuesta fija la base; después, si `latest` o `current.id` cambian se llama a `onChange(limit)`.
// Se compara el id y no `count`: la rotación a `max_versions` deja `count` constante. Solo trabaja con la pestaña visible
// (startPolling). Un fallo de red se ignora y se conserva la base; no solapa consultas. Devuelve la función que lo detiene.
export function watchLatest(fetchLimit, onChange, ms = VERSIONS_POLL_MS, doc, timers) {
  let alive = true;
  let busy = false;
  let base; // undefined = aún sin respuesta; null = el juego no tiene versiones
  let baseCur; // id del «Actual» del hub (`current.id`); null = hub vacío o hub antiguo sin `current`
  const load = () => {
    if (busy) return;
    busy = true;
    fetchLimit()
      .then((limit) => {
        if (!alive || !limit || !('latest' in limit)) return; // sin `latest`: hub antiguo
        const latest = typeof limit.latest === 'string' ? limit.latest : null;
        const cur = typeof limit.current?.id === 'string' ? limit.current.id : null;
        const changed = base !== undefined && (latest !== base || cur !== baseCur);
        base = latest;
        baseCur = cur;
        if (changed) onChange(limit);
      })
      .catch(() => {})
      .finally(() => {
        busy = false;
      });
  };
  const stop = doc === undefined && timers === undefined ? startPolling(load, ms) : startPolling(load, ms, doc, timers);
  return () => {
    alive = false;
    stop();
  };
}
