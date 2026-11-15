# Registro de cambios del plugin

## Sin publicar

Primera versión estable (antes `0.2.9`). `checkpointProtocol: 1`. Con semver, `1.0.0` es mayor que `0.2.9`: el hub la ofrece a quien tenga una `0.2.x`.

### Novedades

- **Vinculación con el hub por código** de 6 dígitos: solicitud, espera de la aceptación, clave guardada en la Deck, rechazo, caducidad y errores de conexión. «Probar conexión» y «Desvincular».
- **Biblioteca de Steam.** «Buscar juegos de Steam» lee los `appmanifest_*.acf` (incluida la tarjeta SD, vía `libraryfolders.vdf`) y envía al hub solo el número y el nombre de cada juego.
- **Sincronización manual** por juego y de todos: sube, baja o avisa de conflicto (con conflicto no se toca nada). La subida es reanudable; la bajada se verifica (sha256 y tamaño de cada fichero y del conjunto) y deja la carpeta anterior como copia `<carpeta>.checkpoint-backup` (una sola). Progreso y cancelación. Se rechaza con el juego abierto (`game_running`).
- **Sincronización automática al abrir y cerrar.** Al abrir sincroniza (sin pausar el juego); al cerrar sube y avisa al hub (`closed`). Avisa del resultado con un toast, siempre, también «al día». Los toasts tienen como mucho 45 caracteres y no llevan punto final. Sección «Último aviso» en el panel. Sin red, el cierre queda en una cola en disco (`auto.json`, 0600) que se reintenta cada minuto y al arrancar. Tras sincronizar al abrir se avisa al hub (`opened`) con el resultado.
- **Juegos.** Interruptor por juego (campo `enabled` del hub, vale para todos los dispositivos). «Configurar» con el selector nativo de carpetas de Decky («Examinar…»). Unión automática a un juego existente del hub con el mismo nombre. «Mostrar juegos sin configurar» (se recuerda en `prefs.json`).
- **Resolución de conflictos desde el panel**: «Usar datos del hub» y «Usar datos de este equipo», con confirmación. También se puede resolver desde la web del hub.
- **Versión propia, protocolo y actualizaciones.** `version` semver y `checkpointProtocol` en `package.json`. «Probar conexión» compara el protocolo con el del hub. «Buscar actualizaciones» avisa de una versión mayor; se actualiza solo con «Instalar plugin desde URL» de Decky (`<hub>/api/deck/plugin`) y el botón «Copiar dirección».
- **Captura de fallos del panel**: errores globales, promesas rechazadas y llamadas al backend que fallan salen como aviso «Fallos detectados» y como línea en el log de Decky, sin claves ni steamid.
- Empaquetado: `pnpm run zip` compila y empaqueta; el hub sirve el zip en `/api/deck/plugin`.

### Seguridad

- Validación de rutas: la ruta del hub y cada ruta de fichero se validan antes de tocar nada (nunca la raíz, el directorio personal, carpetas del sistema, de Decky, la raíz de Steam ni enlaces simbólicos).
- Sin redirecciones ni proxies del sistema; el secreto viaja en cabecera, nunca en la dirección.
- La clave se guarda con permisos 0600 y no aparece en la interfaz ni en los registros.

### Sin verificar

- El comportamiento exacto con otras versiones de Decky.
- `SteamClient.GameSessions` es una API interna sin contrato estable: una actualización de Steam puede romperla.

### Historial

- `0.1.0`: esqueleto instalable por zip y vinculación con el hub.
- `0.2.x`: sincronización manual, sincronización automática al abrir y cerrar, selector de carpetas de Decky, resolución de conflictos y actualizaciones por URL.
- Se probó y se descartó: instalación dentro del plugin (el backend no puede escribir en la carpeta de plugins de Decky) y examinador de carpetas propio (se volvió al selector nativo con argumentos válidos y una ruta inicial comprobada).
