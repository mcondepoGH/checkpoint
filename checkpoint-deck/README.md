# Checkpoint para Steam Deck (plugin de Decky)

Plugin de [Decky Loader](https://decky.xyz) que vincula tu Steam Deck con tu hub de Checkpoint. Vincula la Deck con el hub, reconoce los juegos de Steam instalados y sincroniza sus partidas guardadas, a mano y de forma automática al abrir y cerrar cada juego.

## Instalación

1. Necesitas Decky Loader en la Deck y el modo desarrollador de Decky activo (Decky > Ajustes > General > Modo desarrollador).
2. Descarga el zip desde el hub (Configuración > Biblioteca > Dispositivos > «Descargar plugin») o usa su URL.
3. En Decky > Ajustes > Desarrollador, usa «Instalar plugin desde URL» (o «desde ZIP») y pega `http://<hub>/api/deck/plugin`.
4. Abre el menú rápido (botón `...`) y busca Checkpoint.

## Probar en un Linux de escritorio (sin Steam Deck)

Pasos para Arch u otro Linux de escritorio con Steam. Fuentes oficiales: [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader), [instalador](https://github.com/SteamDeckHomebrew/decky-installer) y la [wiki de Deckbrew](https://wiki.deckbrew.xyz). Lo marcado «no verificado» no se pudo confirmar en la documentación oficial (la wiki no se pudo leer entera).

1. **Instalar Steam** (en Arch, paquete `steam` con el repositorio `multilib` activo) e iniciar sesión.
2. **Instalar Decky Loader.** El instalador oficial está pensado para la Deck (descarga `decky_installer.desktop` o el script `curl -L https://github.com/SteamDeckHomebrew/decky-installer/releases/latest/download/install_release.sh | sh`). En un escritorio, no verificado que funcione igual. Alternativa en Arch, no verificada: el paquete de AUR [`decky-loader`](https://aur.archlinux.org/packages/decky-loader) (no oficial; léelo antes de instalarlo) y activar su servicio con `systemctl` (nombre del servicio no verificado; el de la Deck es `plugin_loader.service`). Decky necesita libres los puertos 1337 y 8080.
3. **Abrir Steam en modo Big Picture** (Ver → Modo Big Picture, o `steam -gamepadui`). Decky solo aparece en esa interfaz. Reinicia Steam tras instalar Decky.
4. **Abrir el menú rápido sin mando:** botón `...` en pantalla si la interfaz lo muestra, o el atajo de teclado `Ctrl+2` (no verificado; viene de un comentario de usuario, no de la documentación). El icono de Decky (enchufe) está al final de ese menú.
5. **Activar el modo desarrollador:** Decky > Ajustes > General > Modo desarrollador.
6. **Instalar el plugin:** Decky > Ajustes > Desarrollador > «Instalar plugin desde ZIP» y elige `Checkpoint.zip` (también existe instalar desde URL; no lo uses con direcciones que no controles). Alternativa manual, no verificada: descomprimir el zip en `~/homebrew/plugins/` (queda `~/homebrew/plugins/Checkpoint/`) y reiniciar el servicio de Decky.
7. **Comprobar que aparece:** Checkpoint debe verse en el menú rápido. Si no, reinicia Decky (menú de Decky o su servicio) y revisa los registros: la salida del cargador va al diario del sistema (`journalctl -u plugin_loader`, nombre de unidad no verificado) y los de cada plugin se esperan en `~/homebrew/logs/Checkpoint/` (no verificado).
8. **Tras cambiar el plugin:** vuelve a generar el zip (ver «Desarrollo») e instálalo otra vez, o recarga el plugin desde el menú de Decky (no verificado si hay botón de recarga en tu versión) o reinicia el servicio de Decky.
9. **Vincular con el hub de pruebas:** en el panel escribe la dirección del hub (`http://IP:puerto`, solo servidor y puerto), pulsa «Vincular con el hub», y en el hub acepta la solicitud en Configuración → Biblioteca de juegos → «Solicitudes de vinculación» tras comprobar que el código coincide. Luego «Probar conexión».

**Aviso:** en la primera sincronización usa un juego de prueba y una carpeta de prueba, no guardados reales: la bajada reemplaza la carpeta (queda copia en `<ruta>.checkpoint-backup`, solo una).

**Lo que no se puede probar fuera de una Deck:** el mando, el teclado en pantalla de la Deck, y las rutas reales de la tarjeta SD (`/run/media/...`). Los juegos de Steam del escritorio sí se leen (`~/.local/share/Steam`).

## Uso

1. En la web del hub, ten a mano Configuración → pestaña «Biblioteca de juegos»: el bloque «Solicitudes de vinculación» (encima de la lista de Dispositivos) muestra las solicitudes pendientes.
2. En el panel de Checkpoint, si quieres, cambia el «Nombre de este dispositivo» (por defecto «Steam Deck»; máximo 64 caracteres, sin «/» ni «\»). Si tienes varias Decks, usa un nombre distinto en cada una: con el mismo nombre el hub las trataría como el mismo dispositivo y la clave de una dejaría sin acceso a la otra. Si lo cambias estando vinculado, el hub no lo renombra solo: se cambia desde el hub y la clave se conserva. Escribe la dirección del hub, solo servidor y puerto (por ejemplo `http://192.168.1.10:8080`), sin usuario, contraseña ni ruta.
3. Pulsa «Vincular con el hub». La Deck muestra un código de 6 dígitos y cuánto falta para que caduque (10 minutos).
4. En ese bloque del hub, comprueba que el código es el mismo y pulsa «Aceptar». La Deck recoge sola la clave y muestra «Vinculado a ...».
5. «Probar conexión» pregunta al hub con la clave y responde «Conectado como ...».
6. «Desvincular» borra la clave de la Deck. Para que la clave deje de valer de verdad, revócala también en el hub.

## Juegos y sincronización manual

Con la Deck vinculada, el panel muestra la sección «Juegos».

**Biblioteca de Steam.** «Buscar juegos de Steam» (recomendado tras instalar un juego) lee en la Deck los ficheros `appmanifest_*.acf` de Steam (raíces habituales `~/.local/share/Steam` y `~/.steam/steam`, y las bibliotecas adicionales que indica `libraryfolders.vdf`, como la tarjeta SD) y envía al hub únicamente el número de Steam y el nombre de cada juego, hasta 5000. El hub asocia los que coinciden de forma exacta con un juego suyo y deja el resto como sugerencias que se aceptan en su web (Configuración → Biblioteca). El panel muestra el resumen y, debajo, dos listas:

- **Juegos en el hub.** Cada juego de esta Deck que ya está en el hub, con un interruptor para activarlo o desactivarlo. Es el campo `enabled` del hub y **vale para todos tus dispositivos**: un juego desactivado no se sincroniza (ni a mano, ni al abrir o cerrar). «Comprobar cambios pendientes» (que no es lo mismo que buscar) compara tus guardados con los del hub sin cambiar nada y dice qué juegos tienen algo que subir o bajar.
- **Sin configurar en el hub.** El interruptor «Mostrar juegos sin configurar» del panel «Juegos» muestra u oculta toda esta sección (lista y formulario); oculta, queda solo «N juegos sin configurar ocultos». Se recuerda entre sesiones (en `prefs.json`, aparte de la clave). Los juegos instalados que el hub aún no tiene (sin las herramientas de Steam: Proton, runtimes). «Configurar» rellena el nombre de Steam y la carpeta de guardado y pide confirmar: la carpeta solo se sugiere si existe en la Deck (dentro del prefijo de Proton del juego, `…/compatdata/<appid>/pfx/drive_c/users/steamuser/{AppData,Documents,Saved Games}/<nombre>`, o los guardados de Steam Cloud `userdata/<id>/<appid>/remote`); si no se detecta nada, la eliges con «Examinar…» (el selector de carpetas de Decky, que abre en la ruta detectada o, si esta no existe o no se puede leer, en el home de la Deck) o la escribes tú. Si Decky no puede listar la carpeta que eliges, sale «Decky no puede abrir esa carpeta; escribe la ruta.» . El número de Steam es el del juego y la plataforma sale del dispositivo (Linux). Al guardar, el hub crea el juego con solo esta Deck; si ya hay un juego con ese nombre (p. ej. el del PC) y tiene hueco (menos de 2 dispositivos), el hub **une esta Deck a ese juego** automáticamente (con la ruta del formulario, que sigue siendo obligatoria; si el hub ya tenía otro número de Steam para ese juego, o ese número lo usa otro juego, no se une). El plugin avisa «<Juego>: este dispositivo se ha unido al juego existente del hub» y el juego pasa a «Juegos en el hub» (un juego desactivado en el hub se une igual y sigue desactivado). Sin hueco: «El juego ya tiene 2 dispositivos.»; otro número de Steam: «Ese nombre ya existe con otro juego de Steam.». Un hub anterior sigue respondiendo «Ya hay un juego con ese nombre…».

**Ruta del guardado.** La da el hub (la que tengas configurada para este dispositivo). Un juego sin ruta no se sincroniza.

**Estado de cada juego:**

| Texto del panel | Qué pasa al sincronizar |
| --- | --- |
| Al día | nada |
| Hay cambios en la Deck: se subirán | se suben todos los ficheros y el hub los aplica |
| Hay cambios en el hub: se bajarán | se bajan, se verifican y se reemplaza la carpeta |
| Conflicto: cambios en los dos lados, no se toca nada | no se toca nada, ni en la Deck ni en el hub; resuélvelo desde el panel («Usar datos del hub» / «Usar datos de este equipo») o desde la web del hub |
| Sin ruta en el hub / Carpeta no encontrada / Desactivado | no se puede sincronizar |

«Sincronizar» actúa sobre un juego y «Sincronizar todo» sobre todos, uno tras otro. Mientras trabaja muestra el progreso («Subiendo 3/12 ficheros…») y se puede cancelar.

**Con el juego abierto no se sincroniza a mano.** El plugin detecta que el juego está abierto y rechaza «Sincronizar» (sus ficheros pueden estar a medio escribir); cierra el juego y se sincroniza solo (ver «Abrir y cerrar juegos»).

**Copia de seguridad.** Al bajar cambios del hub, el plugin descarga todo a una carpeta temporal junto a la del juego (`<carpeta>.checkpoint-new`), comprueba cada fichero (sha256 y tamaño) y el conjunto, y solo entonces reemplaza la carpeta. Tu carpeta anterior se conserva como `<carpeta>.checkpoint-backup`. Hay UNA sola copia: cada descarga correcta sustituye la anterior. Si algo falla, tu carpeta queda intacta y el temporal se borra.

**Límites.** Máximo 512 MB por fichero y 50 000 ficheros por juego (si se superan, no se sincroniza nada y el panel lo explica). No se suben ni bajan enlaces simbólicos, ficheros especiales ni carpetas vacías. Con «Hay cambios en el hub» y una carpeta que aún no existe, el plugin la crea (y sus carpetas padre solo si cuelgan de tu directorio personal; fuera de él, p. ej. una tarjeta SD no montada, no crea nada y avisa «Carpeta no encontrada»).

**Rutas que el plugin rechaza** («Ruta no permitida», sin tocar nada): no absolutas, con `..`, la raíz `/`, tu directorio personal o un padre suyo, `/home`, `/run`, `/usr`, `/etc`, `/var`, `/tmp` y otras carpetas del sistema, la carpeta del propio plugin y los ajustes de Decky, las carpetas de configuración del usuario (`~/.config`, `~/.local`, `~/.steam`...), la raíz de Steam y sus `steamapps`, y cualquier carpeta que sea un enlace simbólico (o resuelva a una de las anteriores). El hub se trata como un dato no confiable: cada ruta de fichero que manda también se valida antes de escribir.

Estados posibles de la vinculación: sin vincular, esperando aceptación, vinculado, rechazado, caducado y error (por ejemplo, sin conexión con el hub).

## Abrir y cerrar juegos (automático)

Con la Deck vinculada y un juego asociado en el hub (con su número de Steam y su ruta), no hay que tocar nada:

- **Al abrir:** el plugin sincroniza ese juego. Si el hub tiene un save más reciente, lo baja (y deja tu carpeta anterior como copia de seguridad); si la Deck tiene cambios, los sube; con conflicto no toca nada. **No pausa el juego**: el juego puede leer el save antiguo antes de que acabe la sincronización (pausarlo con `SIGSTOP` queda para después de probar en una Deck real). Avisa SIEMPRE con un toast del resultado, también cuando todo está al día («<Juego>: al día»), no hay carpeta de guardado en este equipo o la carpeta no existe; un juego desactivado en el hub se ignora sin aviso. Al cerrar, igual: un toast con lo que subió o, si no hay cambios, «al día».
- **Al cerrar:** sube los cambios y avisa al hub (`POST /api/hook/{juego}/closed`, con el resultado de la sync), que quita el «jugando» y lo deja en su historial.
- **Aviso de apertura:** tras sincronizar al abrir, avisa al hub (`POST /api/hook/{juego}/opened` con `{"result": {"state", "code"?}}`) para que su pestaña «Sincronizar» muestre «Jugando en <este dispositivo>» y el resultado (subido, bajado, sin cambios, carpeta no existe, sin ruta, conflicto, error). No es crítico: un solo intento, sin avisos en pantalla; si el hub es antiguo o falla, queda en el log de Decky (`auto: aviso de apertura de <juego>: hub sin soporte | error`) y no se reintenta. Solo viajan el estado y el código del error, nunca rutas ni nombres de fichero. El protocolo (`checkpointProtocol`) sigue en 1: un hub antiguo con este plugin, o un hub nuevo con un plugin antiguo, funcionan.
- **Sin red al cerrar** (o con el hub ocupado): el cierre queda en una cola guardada en la Deck (`auto.json` en la carpeta de ajustes, solo número de Steam, id y nombre del juego) y se reintenta cada minuto y al arrancar el plugin; aparece un toast «queda en cola». Si al abrir no hay red, el juego se abre sin sincronizar y avisa.
- **Conflicto** (cambios en la Deck y en el hub): toast «<Juego>: conflicto, resuélvelo» y no se toca nada. Se resuelve desde el panel (ver «Resolver un conflicto»): en «Juegos en el hub», pulsa «Comprobar cambios pendientes»; el juego en conflicto muestra «Usar datos del hub» y «Usar datos de este equipo», cada uno con confirmación (`ConfirmModal` de Decky). Con «hub», la Deck baja los datos del hub y su carpeta actual queda en `<carpeta>.checkpoint-backup`; con «este equipo», el hub guarda antes una versión de los suyos y luego los de la Deck. El plugin deja la resolución en el hub (`PUT /api/hook/{juego}/resolution`) y sincroniza al momento (no con el juego abierto); si los datos cambiaron entretanto, dice que vuelvas a elegir. Un hub antiguo (sin la función) sigue dando conflicto y el plugin responde «El hub no admite esta función: actualízalo.». También se puede resolver desde la web del hub (la Deck lo aplica al abrir o cerrar el juego).
- Un juego de Steam que no está en el hub no hace nada ni avisa. Los juegos que no son de Steam no se detectan todavía.
- **Toasts cortos:** el cuerpo no pasa de 45 caracteres (Decky cortaba los largos) y no lleva punto final; el nombre del juego se recorta a unos 22 caracteres con «…». Textos: «<Juego>: guardado subido» / «guardado bajado» / «al día» / «sin carpeta de guardado» / «carpeta no encontrada» / «conflicto, resuélvelo» / «error al sincronizar» / «unido a este equipo»; sin nombre: «Sin conexión: cierre en cola», «Sin conexión: no se sincronizó» y «Clave no válida: vuelve a vincular». Los detalles del fallo están en el panel «Juegos» y en el log de Decky. Un test de `noticeText` con nombres larguísimos vigila el máximo (`TOAST_MAX` en `src/texts.ts`).
- Detalles de los toasts (cada 2 s, aunque el panel esté cerrado): un toast por apertura y uno por cierre (el evento repetido seguido de Steam se descarta, así que no se duplican). Estados con aviso: `uploaded`, `downloaded`, `up_to_date`, `no_path`, `missing_dir`, `conflict` y los errores; `disabled` no avisa.
- **Sección «Avisos» del panel** (para saber por qué no salió un toast): «Último aviso» dice cuándo y qué se entregó la última vez (desde que cargó la interfaz). Cada decisión del auto-sync (también las que no avisan, con su motivo) deja una línea `auto: …` en el log de Decky; sin rutas ni claves. Cada aviso entregado deja también `auto: aviso entregado <código>` en el log de Decky.

Limitación conocida: la detección usa `SteamClient`, una API interna de Steam sin contrato estable; una actualización de Steam puede romperla (el panel muestra un aviso de fallo si no está disponible).

## Qué significan los avisos

Cada toast lleva «Checkpoint» de título y un cuerpo de como mucho 45 caracteres (el nombre del juego se recorta a unos 22 con «…»).

| Estado | Texto del toast | Significado |
| --- | --- | --- |
| `uploaded` | «<Juego>: guardado subido» | La Deck tenía cambios y se subieron al hub |
| `downloaded` | «<Juego>: guardado bajado» | El hub tenía un guardado más reciente; tu carpeta anterior quedó en `<carpeta>.checkpoint-backup` |
| `up_to_date` | «<Juego>: al día» | Nada que subir ni bajar |
| `no_path` | «<Juego>: sin carpeta de guardado» | El hub no tiene ruta de guardado para este equipo |
| `missing_dir` | «<Juego>: carpeta no encontrada» | La carpeta de guardado no existe en la Deck |
| `conflict` | «<Juego>: conflicto, resuélvelo» | Cambios en los dos lados; no se tocó nada (ver «Resolver un conflicto») |
| `joined` | «<Juego>: unido a este equipo» | Esta Deck se unió a un juego existente del hub |
| `queued` | «Sin conexión: cierre en cola» | Sin red al cerrar; se reintenta solo |
| `offline_open` | «Sin conexión: no se sincronizó» | Sin red al abrir; el juego se abrió sin sincronizar |
| `unauthorized` | «Clave no válida: vuelve a vincular» | El hub no reconoce la clave de esta Deck |
| `sync_failed` | «<Juego>: error al sincronizar» | Falló la sincronización; el detalle está en el panel «Juegos» y en el log de Decky |

## Resolver un conflicto

- **Desde el panel:** en «Juegos en el hub», pulsa «Comprobar cambios pendientes»; el juego en conflicto muestra «Usar datos del hub» y «Usar datos de este equipo». Elige uno y confirma.
- **Desde la web del hub:** resuelve el conflicto allí; la Deck lo aplica al abrir o cerrar el juego.

No se puede resolver con el juego abierto.

## Fallos detectados

El panel captura los errores globales, las promesas rechazadas y las llamadas al backend que fallan, y los muestra como aviso «Fallos detectados» (el mismo patrón que la web del hub). Los detalles van saneados, sin claves ni steamid, y cada fallo queda también como una línea en el log de Decky (`report_error` en `main.py`). Los fallos de las tareas de fondo y de la biblioteca llevan tipo, mensaje, estado y endpoint, así que no se pierden en silencio.

## Descargar el plugin desde el hub

Si el hub lleva el zip (la imagen Docker lo construye sola), en **Configuración > Biblioteca > Dispositivos** hay un botón **Descargar plugin** con la versión y la suma SHA-256. Por API, sin credenciales y de solo lectura: `GET /api/deck/plugin` (zip), `GET /api/deck/plugin.sha256` (para `sha256sum -c`) y `GET /api/deck/plugin/info`. Comprueba la suma antes de instalarlo.

## Versión y actualizaciones

El plugin tiene versión propia (`version` de `package.json`, semver) y declara el protocolo con el hub (`checkpointProtocol`, entero). El panel **Actualizaciones** muestra la versión instalada.

- **Compatibilidad.** «Probar conexión» compara el protocolo del plugin con el del hub (`protocol` y `min_plugin_protocol` de `GET /api/hook/ping`). Si el plugin es más viejo que el mínimo del hub, avisa y **no sincroniza** (ni a mano ni al abrir y cerrar juegos) hasta que lo actualices. Si el hub es de una versión vieja y no anuncia protocolo, solo avisa (no bloquea).
- **Aviso de versión nueva.** «Buscar actualizaciones» consulta `GET /api/deck/plugin/info` del hub (público, sin clave) y avisa si hay una versión estrictamente mayor. Solo lectura: no descarga ni instala nada. Orden de versiones: semver; una pre-release (`0.2.0-rc.1`) es menor que su release (`0.2.0`) y los metadatos `+build` no cuentan.
- **Actualizar es solo por URL de Decky.** El plugin no se instala ni se actualiza a sí mismo (no hay botón «Actualizar» ni descarga del zip dentro del plugin). Con versión nueva, el panel muestra «Actualización disponible: X (instalada: Y)» y tres pasos: 1) Ajustes de Decky > Desarrollador > Instalar plugin desde URL; 2) pegar `<hub>/api/deck/plugin` (el botón «Copiar dirección» la copia al portapapeles; si falla, el panel lo dice y la dirección sigue visible para escribirla) (con la SHA-256 abreviada para comparar con `GET /api/deck/plugin.sha256`); 3) reiniciar Decky si no se recarga solo. Si el hub es viejo (no anuncia protocolo), el panel solo avisa de ello.
- **Sin verificar:** el comportamiento exacto con otras versiones de Decky (por ejemplo, si el plugin se recarga solo tras instalar).
- **Integridad.** La SHA-256 que se muestra es la del propio hub, solo para comparar a mano: protege de descargas cortadas o corruptas, no de un hub comprometido.
- Al publicar una versión nueva del plugin sube `version` en `package.json`; sube `checkpointProtocol` (y `PROTOCOL`/`MIN_PLUGIN_PROTOCOL` del hub) solo con un cambio incompatible del contrato.

## Actualizar

1. En el panel «Actualizaciones», pulsa «Buscar actualizaciones».
2. Si hay versión nueva, pulsa «Copiar dirección» (`<hub>/api/deck/plugin`).
3. En Decky > Ajustes > Desarrollador > «Instalar plugin desde URL», pega la dirección e instala. Si el plugin no se recarga solo, reinicia Decky.

## Límites conocidos

- Máximo 512 MB por fichero y 50 000 ficheros por juego.
- No pausa el juego al abrirlo: puede leer el guardado antiguo antes de que acabe la sincronización.
- Los juegos que no son de Steam no se detectan.
- `SteamClient` es una API interna; una actualización de Steam puede romperla.
- Los textos del panel están solo en español.

## Seguridad

- La clave se guarda en `~/homebrew/settings/Checkpoint/settings.json` con permisos 0600 (solo tu usuario). No aparece en la interfaz ni en los registros.
- El secreto de la solicitud viaja siempre en una cabecera, nunca en la dirección.
- El plugin no se ejecuta como administrador y no sigue redirecciones ni usa proxies del sistema.
- La consulta de actualizaciones (`/api/deck/plugin/info`) es pública y nunca envía la clave `ckd_`.

## Desarrollo

Para generar el zip hace falta Node.js 16.14 o superior, pnpm 9 y Python 3:

```bash
cd checkpoint-deck
pnpm i
pnpm run zip                   # compila y empaqueta en un paso: crea out/Checkpoint.zip
```

Sin pnpm: `npm i && npm run zip` (`npm run build` y `bash scripts/package.sh` por separado también valen). Si falta `dist/index.js` o `py_modules/`, el empaquetado se detiene con un mensaje claro. El zip no se guarda en el repositorio; lleva una carpeta `Checkpoint/` con `dist/index.js` (sin sourcemap), `main.py`, `plugin.json`, `package.json`, `py_modules/`, `LICENSE` y este `README.md`.

Pruebas:

```bash
pip install pytest            # pruebas de Python (biblioteca estándar en el plugin)
pytest -q                     # desde checkpoint-deck/ (con el entorno del hub, también las pruebas contra el hub real)
pnpm run typecheck            # tipos de TypeScript
```

Las pruebas `tests/test_integration_hub.py` y `tests/test_sync_engine.py` arrancan el hub real del repositorio, y `tests/test_local_manifest.py` compara el manifiesto local con `fingerprint()` del hub; se omiten solas si faltan las dependencias del backend (ejecútalas con el entorno del hub). Los módulos de `py_modules/` llevan el prefijo `checkpoint_` porque Decky comparte el `sys.path` entre plugins.


## Licencia

MIT, igual que Checkpoint.
