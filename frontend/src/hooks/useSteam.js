import { useCallback, useEffect, useRef, useState } from 'react';
import { acceptSuggestion, dismissSuggestion, forgetDismissed, listDismissed, listSuggestions } from '#src/lib/api/steam.js';
import { STEAM_POLL_MS, failureOf, normalizeDismissed, normalizeSuggestions } from '#src/lib/steam.js';
import { afterAccept } from '#src/lib/pairing.js';
import { startPolling } from '#src/lib/poll.js';

// Sugerencias de Steam y descartes recordados: se consultan cada 5 s mientras `enabled` (página montada y subpestaña a la vista) y solo
// con la pestaña del navegador visible. Un fallo de red al consultar nunca molesta: se conserva la última lista.
// `dirty`: el borrador de Configuración tiene cambios sin guardar. `onReload`: recarga la config (solo se llama con el borrador limpio).
export default function useSteam({ enabled, dirty, onReload }) {
  const [rows, setRows] = useState([]);
  const [dismissed, setDismissed] = useState([]);
  const [busy, setBusy] = useState(null); // id de la sugerencia o del descarte en curso
  const [notice, setNotice] = useState(null); // {variant:'ok'|'warn'|'error', body:{code,params}}
  const alive = useRef(true);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  const refresh = useCallback(
    () =>
      Promise.all([listSuggestions(), listDismissed()])
        .then(([s, d]) => {
          if (!alive.current) return;
          setRows(normalizeSuggestions(s));
          setDismissed(normalizeDismissed(d));
        })
        .catch(() => {}),
    [],
  );

  useEffect(() => {
    alive.current = true;
    if (!enabled) {
      setRows([]);
      setDismissed([]);
      return () => {
        alive.current = false;
      };
    }
    const stop = startPolling(refresh, STEAM_POLL_MS);
    return () => {
      alive.current = false;
      stop();
    };
  }, [enabled, refresh]);

  const run = async (id, what, call, onOk) => {
    setBusy(id);
    setNotice(null);
    try {
      const r = await call();
      onOk(r);
      await refresh();
    } catch (e) {
      const f = failureOf(e, what);
      setNotice({ variant: 'error', body: f.body });
      if (f.refresh) refresh();
    } finally {
      if (alive.current) setBusy(null);
    }
  };

  const accept = (row) =>
    run(
      row.id,
      'accept',
      () => acceptSuggestion(row.id),
      (r) => {
        const keep = afterAccept(dirtyRef.current) === 'keep';
        setNotice({
          variant: keep ? 'warn' : 'ok',
          body: { code: keep ? 'steam.acceptedDirty' : 'steam.accepted', params: { game: r?.name || row.gameName, appid: row.appid } },
        });
        if (!keep) onReload();
      },
    );

  const discard = (row) =>
    run(
      row.id,
      'dismiss',
      () => dismissSuggestion(row.id),
      () => setNotice({ variant: 'ok', body: { code: 'steam.dismissedNow', params: { game: row.gameName } } }),
    );

  const forget = (d) =>
    run(
      d.id,
      'forget',
      () => forgetDismissed(d.id),
      () => setNotice({ variant: 'ok', body: { code: 'steam.forgotten', params: { game: d.gameName } } }),
    );

  return { rows, dismissed, busy, notice, closeNotice: () => setNotice(null), accept, discard, forget };
}
