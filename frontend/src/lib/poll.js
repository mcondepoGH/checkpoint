// Envueltos a propósito: el navegador exige this === window; llamados como `timers.setInterval(...)` lanzan
// "TypeError: Can only call Window.setInterval on instances of Window" (Safari) / "Illegal invocation" (Chrome).
const defaultTimers = {
  setInterval: (fn, ms) => globalThis.setInterval(fn, ms),
  clearInterval: (id) => globalThis.clearInterval(id),
};

// Consulta periódica que solo trabaja con la pestaña visible (patrón de useWatches, sin React para poder probarlo).
// `doc` es el document (o un doble en pruebas). Consulta al empezar, cada `ms` y al volver a ver la pestaña.
// Devuelve la función que lo detiene (limpia el temporizador y el escuchador).
export function startPolling(load, ms, doc = typeof document !== 'undefined' ? document : null, timers = defaultTimers) {
  const tick = () => {
    if (doc && doc.hidden) return;
    load();
  };
  tick();
  const timer = timers.setInterval(tick, ms);
  doc?.addEventListener('visibilitychange', tick);
  return () => {
    timers.clearInterval(timer);
    doc?.removeEventListener('visibilitychange', tick);
  };
}
