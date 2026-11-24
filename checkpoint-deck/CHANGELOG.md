# Registro de cambios del plugin

## Sin publicar

Sin cambios de comportamiento ni de protocolo.

### Cambios

- **Código común:** el manifiesto local, la URL del hub, el nombre del dispositivo, la redacción de claves y `compat` pasan a `checkpoint_core` (carpeta `checkpoint-core/`, compartida con el cliente de Linux, sin copias). `scripts/package.sh` lo copia al zip como `py_modules/checkpoint_core/` (el zip sigue siendo autocontenido y solo stdlib) y falla si falta `../checkpoint-core`; la etapa `deck` del Dockerfile lo copia al build. Por probar: el zip construido por Docker en una Deck real.
- **Semver al core:** `parse_semver`, `compare` e `is_newer` pasan a `checkpoint_core.version` (con sus pruebas en `checkpoint-core/`); `checkpoint_version.py` conserva `plugin_dir` y `read_version`. Sin cambios de comportamiento.

## 1.4.0 - 2026-11-24

Interfaz de «Cambiar carpeta». Necesita el hub con `PUT /api/steam/games/{juego}/path`.

### Cambios

- **Detalle del juego:** «Cambiar carpeta» deja de estar desactivado («Próximamente»): abre «Examinar…» y, al elegir, un modal con la carpeta actual y la nueva. Con el juego abierto sale desactivado («Cierra el juego para cambiar la carpeta»). Tras aplicar, fila «Deshacer cambio de carpeta» bajo el botón (sin confirmar; solo el último cambio, en memoria; también desactivada con el juego abierto) y toasts «Carpeta cambiada correctamente» / «Carpeta anterior restaurada».
- **Carpeta distinta sugerida** (detalle y tarjeta): nuevo «Usar esta carpeta» (mismo modal, con tamaño, ficheros y fecha de la sugerida); se mantiene «Ignorar la sugerencia». En la tarjeta se quita «Ver y cambiar carpeta»: «Ver detalle» ya estaba debajo.
- **Errores propios** del cambio (hub sincronizando, juego abierto, carpeta inexistente o desaparecida, hub no compatible, hub que no acepta la carpeta).
- **Selector:** «Examinar…» se extrae del formulario de alta para reutilizarlo; si el panel se desmonta con el selector abierto, vuelve al detalle del juego.

## 1.3.3 - 2026-11-16

`checkpointProtocol: 1` (sin cambios). Toasts sin nombre de juego (por probar en una Deck real).

### Cambios

- **Toasts de Decky:** ya no llevan el nombre del juego (era largo y el mensaje salía cortado). Solo mensaje, más descriptivo y entero dentro de 45 caracteres, p. ej. «Partida actualizada desde el hub» en lugar de «Hades: cargada». Afecta a subida, bajada, sin cambios, conflicto, error, carpeta, unión a un juego, sin conexión, clave no válida, resumen de «Sincronizar todo», cancelación, corte, versión nueva o actualizada, vinculación y desvinculación. El resumen de «Sincronizar todo» conserva su forma («n subidos, n bajados, n conflictos») y, si no cabe en 45 caracteres, dice «Terminó con incidencias: mira Juegos» en lugar de recortarse con «…». Solo se recorta con «…» la versión en los toasts de versión nueva o actualizada.
- **Avisos del panel:** «Último aviso» sigue llevando el nombre completo del juego (sin recorte) y el motivo del fallo; los avisos que no son de un juego (conexión, clave) no llevan nombre ni se inventan uno. Los avisos del panel repiten la redacción del toast tras el nombre (p. ej. «Hades: partida actualizada desde el hub»). Los avisos fijos y el detalle de cada juego ya nombraban el juego entero.
- **Fallo detectado:** el toast dice «Mira «Fallos detectados» en Inicio»; el título y los detalles completos siguen en Inicio.

## 1.3.2 - 2026-11-16

`checkpointProtocol: 1` (sin cambios). Los avisos se ven completos (por probar en una Deck real).

### Cambios

- **Inicio, «Último aviso»:** el recorte venía del propio texto, que era el del toast (máx. 45 caracteres, con el nombre del juego cortado a 22 con «…»). Ahora se guarda el aviso entero (nombre completo y, en un fallo de sincronización, el motivo conocido); los toasts de Decky siguen limitados a 45.
- **Inicio, «Fallos detectados»:** el título y los detalles se pintan enteros con salto de línea (antes iban en un `Field` de Decky, que los acorta). El título del fallo llega hasta 1000 caracteres (antes 200), siempre saneado.
- **Textos largos:** salto de línea sin elipsis; si pasan de 200 px de alto, scroll interno con el mando.
- **Detalle de errores del hub:** `describe_error` recorta a 1500 caracteres (antes 300), después de ocultar claves y secretos.

## 1.3.1 - 2026-11-16

`checkpointProtocol: 1` (sin cambios). Con semver, `1.3.1` es mayor que `1.3.0`. Ajustes tras probar la 1.3.0 en la Deck (sin verificar en una Deck real).

### Cambios

- **Juegos:** cada tarjeta muestra solo el nombre y la insignia de estado; carpeta, última sincronización, interruptor, «Sincronizar», «Ver detalle» y la carpeta distinta sugerida van plegados (botón con flecha, foco de mando; se recuerda solo en memoria). «Sincronizar todo» sigue arriba. Un juego activado con conflicto o error sale desplegado por defecto (sus acciones están dentro).
- **Insignias de estado:** ya no se solapan con la línea divisora (altura de línea y márgenes propios).
- **Sin banner «Sincronización terminada»:** el resumen va solo por toast. Siguen los avisos de problema (interrumpida, conflicto, fallo).
- **Pendientes:** textos más cortos.
- **Pestañas:** la activa se centra siempre en la barra (también con L1 / R1 y con el foco del mando); si caben todas no hay scroll.

## 1.3.0 - 2026-11-16

`checkpointProtocol: 1` (sin cambios). Con semver, `1.3.0` es mayor que `1.2.1`.

### Novedades

- **Panel por pestañas** (Inicio, Juegos, Sugerencias, Pendientes, Ajustes y Versión) en lugar de una sola lista larga. Sin vincular solo están activas Inicio, Ajustes y Versión. L1 / R1 cambian de pestaña (sin verificar en una Deck real). Punto en la pestaña cuando hay algo: conflicto o error en Juegos, número de juegos sin configurar en Pendientes y actualización en Versión.
- **Inicio:** tarjeta de estado con insignia de forma, color y texto (sin vincular, esperando aceptación, sin conexión, plugin antiguo, juego abierto, sincronizando, conflicto, con errores, todo al día), hub, última sincronización, «Sincronizar todo», juegos sin configurar, último aviso y «Probar conexión».
- **Avisos fijos bajo las pestañas** (máximo 2, por prioridad) y **toasts con icono por nivel** (éxito, info, aviso, error; Decky solo deja controlar título, cuerpo, icono y duración; el cuerpo sigue en 45 caracteres como máximo).
- **«Sincronizar todo» global** (Inicio y Juegos): progreso «Juego i/n» con la lista por juego y «Cancelar»; resumen «n subidos, n bajados, n conflictos» en toast y banner; los conflictos y errores no frenan al resto; «Sincronización interrumpida» con los juegos que quedaron sin sincronizar y «Reintentar» o «Probar conexión»; con un juego abierto, «Sincronizar los demás juegos». Una Deck recién vinculada pide confirmar antes la primera sincronización, con el recuento de lo que baja y lo que sube. La tarea `sync_all` deja ahora `plan` y `results` (por juego) en `get_sync_state`.
- **Juegos del hub:** carpeta configurada (callable `get_game_paths`, aparte del estado: este sigue sin rutas), insignia de estado, última sincronización (`last_at`, recordada en `lastsync.json`, también al abrir y cerrar un juego), «Ver detalle» (`game_detail`: tamaño, ficheros y fecha de la carpeta medidos en la Deck y la última copia). El historial del hub no se muestra: el hub no se lo da a un dispositivo.
- **«Hay una carpeta distinta sugerida»** para juegos de Steam ya añadidos (`suggest_changes`), con «Ver y cambiar carpeta» e «Ignorar la sugerencia» (`ignore_suggestion`, en `ignored.json`). **«Cambiar carpeta» de un juego ya configurado queda para la fase 2** (necesita backend y hub): el botón sale desactivado con «Próximamente».
- **Desvincular** pide confirmación.
- **Versión:** tarjeta instalada → disponible, comprobación automática (a los 20 s y cada 6 h, vinculada), un solo toast por versión nueva, punto en la pestaña y toast «Checkpoint actualizado a X.Y.Z» tras actualizar (`ack_version`). El plugin sigue sin instalarse solo: los tres pasos y «Copiar dirección» no cambian. `get_compat` expone si el plugin es demasiado antiguo para el hub.
- Los interruptores «Mostrar juegos sin configurar» y «Consultar lutris.net…» están también en Ajustes.

## 1.2.1 - 2026-11-16

`checkpointProtocol: 1` (sin cambios). Con semver, `1.2.1` es mayor que `1.2.0`.

### Cambios

- **«Sugerencias de guardado» rediseñadas: una tarjeta por juego.** Solo salen los juegos «Sin configurar en el hub» (se quitan los de Steam que ya están en el hub) con su MEJOR carpeta (la que existe, la no dudosa y la modificada más recientemente), con tamaño, número de ficheros y fecha; el resto de rutas queda plegado en «Ver otras rutas (n)». Un botón grande según la confianza:
  - Sugerencia segura (confianza alta y carpeta que existe): **«Añadir al hub»**. Abre un modal con el juego y la carpeta; al confirmar se aplica la sugerencia (`apply_save_suggestion`, que vuelve a verificar la carpeta) y se configura el juego en el hub con el mismo camino que «Guardar en el hub» (`configure_game`: `validate_game_path`, nombre repetido, unirse a un juego existente). La tarjeta pasa a «Añadido». Nunca se guarda sin esa confirmación.
  - Sugerencia dudosa: **«Revisar y añadir»**: abre el formulario «Configurar» en la propia tarjeta con la carpeta rellena, sin guardar.
  - Carpeta no encontrada aún: sin botón de aplicar, solo «No encontrada aún» y la opción manual.
  - En todas, **«Añadir manualmente»** (formulario con el nombre del juego y la carpeta vacía). Además, **«Añadir un juego manualmente»** (lista de juegos sin configurar para abrir un formulario) y **«Buscar de nuevo»**.
- El interruptor «Consultar lutris.net…» pasa a un icono de ajustes (engranaje) con su explicación («solo se envía el nombre interno del juego»).
- Estados: cargando, vacío, error, sin manifiesto (mensaje claro) y el aviso de juegos por consultar a lutris.net. Un error al añadir (p. ej. nombre repetido) sale en la tarjeta del juego.
- Callable nuevo `resolve_save_target(source, ident)`: devuelve el `appid` y el nombre del juego sin configurar al que corresponde una sugerencia, sin carpeta ni cambios (lo usa «Añadir manualmente»).

## 1.2.0 - 2026-11-16

`checkpointProtocol: 1` (sin cambios). Con semver, `1.2.0` es mayor que `1.1.0`.

### Novedades

- **«Sugerencias de guardado» (panel Juegos).** Botón «Sugerir carpeta»: busca la carpeta de guardado EXACTA de los juegos de Steam y Lutris instalados con un manifiesto propio de rutas (generado desde el de Ludusavi con `scripts/gen_save_manifest.py`). Por juego muestra cada ruta candidata con tamaño, número de ficheros y fecha de modificación; «dudosa» cuando la coincidencia o la ruta lo son (p. ej. juegos LÖVE) y «No encontrada aún» cuando la carpeta todavía no existe. Nunca se aplica solo: «Usar esta carpeta» pide confirmación en un modal y solo rellena el formulario «Configurar» de «Sin configurar en el hub»; guardar en el hub sigue el flujo de siempre (`validate_game_path`, la carpeta debe existir). Nuevo callable `apply_save_suggestion`, que vuelve a verificar la ruta (`verified_dir`) y que sea una de las sugeridas. Sin manifiesto sale un mensaje claro.
- **Consulta opcional a lutris.net.** Interruptor «Consultar lutris.net para identificar juegos de Lutris» (preferencia `lutris_lookup`, activada por defecto): solo se envía el slug del juego, una vez por juego y con caché; sirve para casar un juego de Lutris con su appid de Steam. Los callables `suggest_saves` y `suggest_saves_for` devuelven las sugerencias.
- **El manifiesto va dentro del zip** (`data/save_manifest.json`, solo lectura). `ManifestStore` lee primero el de la carpeta de ajustes (si existe y es válido) y, si no, el empaquetado. `scripts/package.sh` lo recibe con `--save-manifest <json>` o `SAVE_MANIFEST`, lo valida (`v` 1, juegos y el commit de Ludusavi en `src`) y falla con mensaje claro si falta (`--no-save-manifest` o `SAVE_MANIFEST=none` empaqueta sin él, con aviso; la imagen Docker del hub solo lo usa con `--build-arg SKIP_SAVE_MANIFEST=1`: por defecto su build genera el manifiesto). El JSON no se commitea. Ver el README, «Manifiesto de rutas de guardado».

## 1.1.0 - 2026-11-15

`checkpointProtocol: 1`. Con semver, `1.1.0` es mayor que `1.0.0` y que las pruebas `1.1.0-rc.1` a `1.1.0-rc.6` (el hub la ofrece a quien tenga cualquiera de ellas). Reúne todo lo de esas pruebas.

### Novedades

- **Atajos de Steam (juegos que no son de Steam, p. ej. Lutris) en la biblioteca.** «Buscar juegos de Steam» lee también `userdata/<id>/config/shortcuts.vdf` (VDF binario, todos los usuarios de Steam de la Deck). Los atajos salen en «Sin configurar en el hub» marcados «Atajo» y se pueden crear en el hub; el número de un atajo puede pasar de `2**31-1` (techo propio `2**32-1`; el de los juegos de Steam no cambia). El hub ya acepta esos números (sin techo, solo > 0; con test). **Abrir y cerrar un atajo sincroniza** como un juego de Steam: el `appid` de `shortcuts.vdf` es el `unAppID` del evento de `SteamClient.GameSessions` (verificado en una Deck real con un juego de Lutris).
- Un `shortcuts.vdf` ausente, corrupto o enorme se omite sin romper la biblioteca y sin rutas ni steamid en el log.
- **Log de diagnóstico del evento de Steam.** Cada evento de `SteamClient.GameSessions` deja, antes del filtro que descarta los que no son de un juego con `unAppID` entero > 0 y `bRunning` booleano, una línea `auto: evento crudo unAppID=<a> tipo=<t> bRunning=<r>` en el log de Decky (método `diag_game_event`). Solo esos tres campos, saneados y de 64 caracteres como máximo; no depende de la vinculación ni del hub; los repetidos seguidos no se repiten y hay un tope de 20 líneas distintas por minuto. Sirve para saber qué número manda Steam al abrir un juego o un atajo. No cambia la lógica de abrir y cerrar.
- El panel de actualización ya no muestra la SHA-256 abreviada (`check_update` deja de devolver `sha256`).
- El puerto de ejemplo de la dirección del hub es 8088.
- El último aviso del panel Avisos se muestra completo, en varias líneas, en lugar de cortarse con elipsis (pendiente de probar en la Deck).
- **Carpeta de guardado sugerida para los atajos de Lutris: candidatos dentro del prefijo.** Al configurar un atajo cuyas opciones de lanzamiento son `lutris:rungameid/N`, el plugin busca en Lutris (solo lectura) la fila `N` de `pga.db` y el `.yml` del juego para localizar el prefijo de Wine (`game.prefix`; si no existe, `directory` de la base) y no sugiere el prefijo entero (demasiado amplio) sino que busca dentro de `drive_c/users/<usuario>/` (todos los usuarios no de sistema; excluye `Public`) carpetas que existen en `Documents/My Games/*`, `Documents/*`, `Saved Games/*`, `AppData/Local/*`, `AppData/LocalLow/*/*` y `AppData/Roaming/*`, y dentro de cada una subcarpetas `SaveGames`, `Saves`, `Save` o `savedata` (sin distinguir mayúsculas, hasta 6 niveles), que se prefieren a la carpeta del juego. Criterios: solo carpetas con al menos un fichero; se filtra el ruido de Wine y Windows (`Microsoft`, `Wine`, `Temp`, `Packages`, `Programs`, `Windows`, `INetCache`, `Crashpad`, `Cache`, `Logs`...); orden: primero los que se parecen por nombre al juego (Jaccard >= 0,5 sobre tokens normalizados del nombre, el slug y el nombre del atajo, sin «reimagined», «edition»...), luego los modificados más recientemente; máximo 8, sin duplicados ni anidados (se queda el más específico salvo que el contenedor tenga más ficheros propios). Todo en solo lectura, sin seguir enlaces simbólicos y con topes de carpetas, entradas, profundidad y tiempo. El primer candidato se rellena en «Carpeta de guardado» y «Probar otra ruta detectada» recorre los demás. Módulo nuevo `checkpoint_lutris.py`: abre `pga.db` con `mode=ro` (no escribe ni deja `-journal`), lee el `.yml` con un analizador mínimo (sin PyYAML) y ficheros ausentes, corruptos o bloqueados dan «sin sugerencia» sin error y sin rutas ni usuarios en el log. Busca en Lutris Flatpak (`~/.var/app/net.lutris.Lutris/data/lutris`, verificado en una Deck real) y en Lutris nativo (`~/.local/share/lutris`, `.yml` en `games/` o `~/.config/lutris/games/`; no verificado). `LaunchOptions` se lee solo en local, no se envía al hub. Los demás atajos (emuladores, Epic...) y los juegos de Steam no reciben sugerencia nueva ni cambian. Caso real que lo motivó: Dragon Quest VII Reimagined guarda en `<prefijo>/drive_c/users/deck/Documents/My Games/DRAGON QUEST VII/Steam/<steamid64>/release/Saved/SaveGames`, cuyo nombre no coincide con el slug.
- **Sin candidatos, nada inventado.** La carpeta queda vacía con el texto «No se encontró ninguna carpeta de partidas en el prefijo; usa Examinar…» y «Examinar…» abre en `<prefijo>/drive_c/users` (o en el prefijo si no existe, o en el comportamiento de antes). `suggest_game` devuelve para estos atajos `source: "lutris"`, `candidates` y `browse_start`.
- **Solo se sugiere lo que existe, comprobado en el momento de sugerir.** Una comprobación común, `verified_dir` (`checkpoint_sync.py`), se aplica a TODA carpeta sugerida (candidatos de Lutris, `drive_c/users`, prefijo, Proton y Steam Cloud de los juegos de Steam): existe, es carpeta (no fichero), se puede listar, está normalizada y sin enlaces simbólicos, está dentro del home o de la biblioteca de Steam (tarjeta SD), pasa la validación de la sincronización (sin carpetas protegidas) y el filtro de caracteres del hub. Falla cerrado: cualquier excepción o permiso denegado significa que no se sugiere. Antes, las rutas de Steam solo comprobaban que fueran carpeta y los candidatos de Lutris no comprobaban que se pudieran listar; los de Lutris se vuelven a verificar justo antes de devolverlos, por si una carpeta desapareció durante el recorrido.
- **Se comprueba otra vez al guardar.** Si la carpeta sugerida ya no existe (o ya no es una carpeta) al pulsar «Guardar en el hub», sale «La carpeta sugerida ya no existe o ya no es una carpeta. No se ha creado el juego…» y no se llama al hub: no queda un juego a medias. (Una ruta escrita a mano que no existía se rechaza igual: ver «Cambios».)
- **«Examinar…» más cerca en Steam.** Si no hay carpeta que sugerir pero existe parte de la ruta esperada (el prefijo de Proton o `userdata/<id>/<appid>`), «Examinar…» abre en su ancestro existente más profundo y validado. La ruta que aún no existe no se sugiere ni se crea.
- El texto «No se detectó la carpeta de guardado» pasa a «No se encontró ninguna carpeta de guardado que exista…».

### Arreglo

- Arreglo: el botón Examinar ya no pierde la carpeta elegida al volver del selector (el formulario se recuerda al remontar el panel; no verificado en una Deck real). El formulario «Configurar» guarda un borrador por juego fuera del componente (`src/drafts.ts`) y el selector de Decky escribe en él la carpeta elegida; se borra al cancelar o guardar y se descartan los de juegos que dejan de estar en «Sin configurar». Ya fallaba en la `1.0.0`.

### Cambios

- **La carpeta de guardado debe existir siempre al configurar un juego.** «Guardar en el hub» rechaza cualquier carpeta que no exista o no sea una carpeta, también la escrita a mano o elegida con «Examinar…» (antes solo la ofrecida por el plugin), y no llama al hub ni crea nada. Vale igual al unirse a un juego que el hub ya tiene (pasa por el mismo guardado). Sale «La carpeta no existe o no es una carpeta. No se ha creado el juego…», o «La carpeta sugerida ya no existe…» (código `path_vanished`) si era una sugerencia que desapareció; el formulario sigue abierto con lo escrito. La sincronización ya no crea la carpeta raíz del juego desde «Sin configurar».
- Interno: `GameTools.create` ya no tiene el parámetro `must_exist` (la comprobación es siempre); `_offered` solo distingue el mensaje.

### Sin verificar

- La derivación del número de un atajo sin `appid` en `shortcuts.vdf` (`crc32(Exe + nombre)` con el bit alto): implementada pero desactivada.
- Lutris nativo (`~/.local/share/lutris`): no verificado en una Deck real. Los candidatos de carpeta se probaron con prefijos sintéticos modelados sobre el de Dragon Quest VII; el flujo completo se probó en una Deck con Lutris Flatpak.
- No hay tope de tiempo propio en la comprobación de una sola carpeta (son llamadas locales; un montaje colgado podría bloquearla, aunque el recorrido de Lutris sí tiene tope).
- Los tipos de TypeScript y la compilación (`tsc`, `rollup`) no se han ejecutado con estos cambios.

## 1.0.0 - 2026-11-15

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
