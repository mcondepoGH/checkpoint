import React, { useEffect, useState } from 'react';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { ui } from '#src/lib/errors.js';
import { Alert, Switch } from '#src/components/ui/index.js';
import { getAutostart, putAutostart } from '#src/lib/api/system.js';

// Tarjeta de Configuración «Arrancar al iniciar sesión»: crea o quita la Tarea Programada de Windows. Solo se pinta con
// el hub instalado en Windows (el backend dice `supported`); en Docker, Linux y macOS no hay nada que mostrar.
export default function Autostart() {
  const { t } = useI18n();
  const [state, setState] = useState(null); // {supported, enabled}
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null); // {kind:'ok'|'error', body}: error de la API o mensaje {code} (se traduce al pintar)

  useEffect(() => {
    let alive = true;
    getAutostart()
      .then((s) => alive && setState(s))
      .catch(() => {}); // un fallo aquí nunca molesta: la tarjeta simplemente no aparece
    return () => {
      alive = false;
    };
  }, []);
  if (!state || !state.supported) return null;

  const toggle = async (value) => {
    setBusy(true);
    setMsg(null);
    try {
      const s = await putAutostart(value);
      setState(s);
      setMsg({ kind: 'ok', body: ui(s.enabled ? 'autostart.savedOn' : 'autostart.savedOff') });
    } catch (e) {
      setMsg({ kind: 'error', body: e });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card" aria-labelledby="autostart-title">
      <h3 id="autostart-title">{t('autostart.title')}</h3>
      <p className="muted">{t('autostart.text')}</p>
      <Switch
        checked={state.enabled}
        disabled={busy}
        onChange={(e) => toggle(e.target.checked)}
        label={state.enabled ? t('common.on') : t('common.off')}
      />
      <div role="status" aria-live="polite">
        {msg && <Alert variant={msg.kind}>{errText(msg.body)}</Alert>}
      </div>
    </section>
  );
}
