import React from 'react';
import AutoSync from '#src/components/autosync/AutoSync.jsx';
import UpdateCheck from '#src/components/updates/UpdateCheck.jsx';
import Orphans from '#src/components/config/Orphans.jsx';
import { updatesApplicable } from '#src/lib/updates.js';

// Subpestaña «General» de Configuración: sincronización automática (con su registro de ejecuciones), actualizaciones y
// datos sin dispositivo ni juego (solo se pinta si los hay).
// No usa el borrador de configuración: sus ajustes se guardan por su cuenta.
export default function General({ updates, onUpdates }) {
  return (
    <>
      <AutoSync />
      {updatesApplicable(updates) && <UpdateCheck info={updates} onInfo={onUpdates} />}
      <Orphans />
    </>
  );
}
