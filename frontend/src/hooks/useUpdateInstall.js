import { useCallback, useEffect, useRef, useState } from 'react';
import { ui } from '#src/lib/errors.js';
import { getInstallStatus, getUpdates, installUpdate } from '#src/lib/api/updates.js';
import { phaseFromStatus, reachedVersion } from '#src/lib/updates.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const reload = () => globalThis.location.reload();

// Actualización con un clic: arranca la instalación, sigue su progreso y, cuando el hub se reinicia, recarga la página.
// `phase`: idle | confirm | checking | downloading | installing | restarting | done | error. `error` es {code, params}
// (o un error de la API) y se traduce al pintar. Un fallo de red durante el reinicio es normal: el hub está parado.
export default function useUpdateInstall(target) {
  const [phase, setPhase] = useState('idle');
  const [error, setError] = useState(null);
  const alive = useRef(true);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );

  const fail = (e) => {
    setError(e);
    setPhase('error');
  };

  // Espera a que el hub vuelva (cualquier respuesta HTTP = ya está arriba; un 401 es solo la sesión, perdida al reiniciar).
  const waitRestart = useCallback(async () => {
    setPhase('restarting');
    while (alive.current) {
      await sleep(2000);
      try {
        const info = await getUpdates();
        if (reachedVersion(info, target)) {
          setPhase('done');
          await sleep(1500);
          return reload();
        }
      } catch (e) {
        if (e && e.status) return reload();
      }
    }
  }, [target]);

  const follow = useCallback(async () => {
    while (alive.current) {
      await sleep(1000);
      let st;
      try {
        st = await getInstallStatus();
      } catch {
        return waitRestart(); // sin respuesta: el hub ya se cerró para actualizarse (o la sesión se perdió: recarga)
      }
      if (st.state === 'error') return fail(st.error ? ui(st.error.code, st.error.params) : null);
      if (st.state === 'restarting') return waitRestart();
      setPhase((p) => phaseFromStatus(p, st));
    }
  }, [waitRestart]);

  const start = useCallback(async () => {
    setError(null);
    setPhase('checking');
    try {
      const st = await installUpdate();
      setPhase((p) => phaseFromStatus(p, st));
    } catch (e) {
      return fail(e);
    }
    return follow();
  }, [follow]);

  return { phase, error, ask: () => setPhase('confirm'), cancel: () => setPhase('idle'), start };
}
