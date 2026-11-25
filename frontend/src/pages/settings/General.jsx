import React from 'react';
import AutoSync from '#src/components/autosync/AutoSync.jsx';
import UpdateCheck from '#src/components/updates/UpdateCheck.jsx';
import Autostart from '#src/components/updates/Autostart.jsx';
import Orphans from '#src/components/config/Orphans.jsx';
import { useI18n } from '#src/hooks/useI18n.js';
import { updatesApplicable } from '#src/lib/updates.js';

// Subpestaña «General» de Configuración: sincronización automática (con su registro de ejecuciones), actualizaciones y
// arranque al iniciar sesión (solo Windows), datos sin dispositivo ni juego (solo se pinta si los hay).
// Con el hub sin login (`noLogin`) muestra su aviso en una tarjeta (antes era un banner global).
// No usa el borrador de configuración: sus ajustes se guardan por su cuenta.
export default function General({ updates, onUpdates, noLogin = false }) {
  const { t } = useI18n();
  return (
    <>
      <AutoSync />
      <Autostart />
      {noLogin && (
        <section className="card" aria-label={t('app.noLogin')}>
          <p role="note">{t('app.noLogin')}</p>
        </section>
      )}
      {updatesApplicable(updates) && <UpdateCheck info={updates} onInfo={onUpdates} />}
      <Orphans />
    </>
  );
}
