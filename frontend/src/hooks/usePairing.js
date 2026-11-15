import { useCallback, useEffect, useRef, useState } from 'react';
import { acceptPending, listPending, rejectPending } from '#src/lib/api/pairing.js';
import { PAIRING_POLL_MS, afterAccept, failureOf, normalizePending } from '#src/lib/pairing.js';
import { startPolling } from '#src/lib/poll.js';

// Solicitudes de vinculación pendientes: se consultan cada 5 s mientras `enabled` (página montada y subpestaña a la vista) y solo con la
// pestaña del navegador visible. Un fallo de red al consultar nunca molesta: se conserva la última lista.
// `dirty`: el borrador de Configuración tiene cambios sin guardar. `onReload`: recarga la config (solo se llama con el borrador limpio).
export default function usePairing({ enabled, dirty, onReload }) {
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(null); // id de la solicitud en curso
  const [notice, setNotice] = useState(null); // {variant:'ok'|'warn'|'error', body:{code,params}}
  const alive = useRef(true);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  const refresh = useCallback(
    () =>
      listPending()
        .then((r) => alive.current && setRows(normalizePending(r, Date.now())))
        .catch(() => {}),
    [],
  );

  useEffect(() => {
    alive.current = true;
    if (!enabled) {
      setRows([]);
      return () => {
        alive.current = false;
      };
    }
    const stop = startPolling(refresh, PAIRING_POLL_MS);
    return () => {
      alive.current = false;
      stop();
    };
  }, [enabled, refresh]);

  const fail = (e, what) => {
    const f = failureOf(e, what);
    setNotice({ variant: 'error', body: f.body });
    if (f.refresh) refresh();
  };

  const accept = async (row) => {
    setBusy(row.id);
    setNotice(null);
    try {
      const r = await acceptPending(row.id, row.code);
      const keep = afterAccept(dirtyRef.current) === 'keep';
      setNotice({
        variant: keep ? 'warn' : 'ok',
        body: { code: keep ? 'pairing.acceptedDirty' : 'pairing.accepted', params: { name: r?.name || row.name } },
      });
      if (!keep) onReload();
      await refresh();
    } catch (e) {
      fail(e, 'accept');
    } finally {
      if (alive.current) setBusy(null);
    }
  };

  const reject = async (row) => {
    setBusy(row.id);
    setNotice(null);
    try {
      await rejectPending(row.id);
      setNotice({ variant: 'ok', body: { code: 'pairing.rejected', params: { name: row.name } } });
      await refresh();
    } catch (e) {
      fail(e, 'reject');
    } finally {
      if (alive.current) setBusy(null);
    }
  };

  return { rows, busy, notice, dismiss: () => setNotice(null), accept, reject };
}
