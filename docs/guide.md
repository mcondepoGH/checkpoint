# Guía de uso

Comportamiento de Checkpoint en el día a día. Instalación y primeros pasos: [`README.md`](../README.md). Rutas de la API y de los hooks: [`api.md`](api.md).

## Sincronización automática

En **Configuración > General > Sincronización automática** activa la opción y elige cada cuántas horas se ejecuta (de 0.25 a 168). Cada ciclo sincroniza todos los juegos **activos** (los desactivados se omiten en silencio; ver «Desactivar un juego»); si uno falla, los demás continúan. Debajo se muestra el **Registro de ejecuciones** (las últimas 200, límite fijo; cada una con su origen en una etiqueta de color: Manual, Programado o Launcher; incluye las sincronizaciones manuales reales, no las simulaciones) con resultado por juego y detalle al hacer clic. Sin ajustes guardados, está desactivada y el intervalo es de 24 horas.

## Nuevas versiones

Checkpoint comprueba si hay una versión nueva consultando las Releases públicas de GitHub (solo HTTPS, por defecto solo versiones estables: se ignoran borradores y pre-releases). Si la hay, aparece la insignia **Nueva versión disponible** en la cabecera, con la versión instalada, la nueva y sus notas. No actualiza nada: en Docker, actualiza la imagen (`docker compose pull` si usas la imagen publicada, o reconstruye si la construyes tú) y recrea el contenedor; en instalación nativa, descarga la nueva versión y reinicia.

**Solo en instalación nativa.** En Docker la versión la fija la imagen: la comprobación no se aplica (no hace ninguna petición a internet, no lee ni escribe caché y no aparecen la insignia ni la tarjeta «Comprobar actualizaciones»). La versión instalada se muestra siempre en el pie de la interfaz. Cómo se decide Docker o nativo: ver el README, «Instalación sin Docker».

- La versión instalada sale del fichero `VERSION` de la raíz del repositorio (la imagen lo incluye). Sin él, o en desarrollo, es «desconocida» y no se ofrece ninguna actualización. El repositorio consultado es siempre el de este proyecto.
- El resultado se guarda en memoria y en `data/update_cache.json` durante 6 horas. Un fallo de red es silencioso: se conserva el último resultado y se reintenta pasados unos minutos.
- Se desactiva en **Configuración > General > Comprobar actualizaciones** (viene activada). Desactivada, no se hace ninguna petición a internet. El botón **Comprobar ahora** fuerza la consulta (máximo una por minuto).
- **Canal** (Configuración > General > Comprobar actualizaciones): **Estable** (por defecto) solo ofrece Releases normales; **Pruebas** (`beta`) ofrece también pre-releases (nunca borradores), que pueden fallar. En Pruebas se ofrece la versión más alta entre estables y preliminares, con el orden de semver: `1.0.0-rc.1` < `1.0.0-rc.2` < `1.0.0`. Un tag con sufijo (`-rc.1`) cuenta como preliminar aunque GitHub no lo marque. Cambiar de canal descarta el resultado guardado y vuelve a consultar. Nunca se ofrece bajar de versión: desde una preliminar en canal Estable solo se avisa cuando haya una estable mayor. La insignia y el diálogo marcan «preliminar» cuando procede.
- La etiqueta de imagen `beta` la publica el workflow de release (ver [`development.md`](development.md#publicación-de-versiones)); el canal solo cambia qué avisos se muestran, no la imagen que ejecutas.
- API (requiere sesión): `GET /api/updates[?refresh=true]` (incluye `actual`, la versión instalada, `aplicable`, `canal` y `prerelease`, si la versión ofrecida es preliminar) y `PUT /api/updates` con `{"enabled": true|false, "channel": "stable"|"beta"}` (parcial: basta uno de los dos; valor no válido, 422). En Docker, `GET` devuelve `aplicable: false` con campos neutros (sin error, sin red) y `PUT` responde 409.

## Un solo dispositivo

Un juego puede tener un único dispositivo (el dispositivo 2 es opcional en el formulario; en `config.yaml`, `devices` con un solo id). Es el modo «solo checkpoint»: no hay copia entre equipos, el hub guarda la partida y sus versiones. La tarjeta del juego en Sincronizar lleva la etiqueta «Solo checkpoint».

- **Guardar:** al sincronizar (a mano, cada X horas, con el aviso de apertura o al cerrarse el juego) la partida del dispositivo pasa al hub. Antes de sustituir la copia anterior del hub se guarda como versión, como con dos dispositivos. La última partida está en el hub y se ve en la tarjeta «Actual» de Versiones; la lista son las copias anteriores. El límite es `max_versions` o `keep_versions` del juego, igual que siempre.
- **Restaurar:** como siempre. En Versiones, restaura la versión al hub y sincroniza después; el hub (ahora distinto del dispositivo) gana y se copia al dispositivo.
- **Conflictos:** si el hub y el dispositivo difieren sin estado guardado (primera sincronización con datos en ambos), se trata como conflicto, igual que con dos dispositivos.
- **Partida local ausente:** si la ruta de guardado del dispositivo **no existe** (juego desinstalado o carpeta borrada) y el hub tiene datos, la sincronización automática (cada X horas, al arrancar) y el aviso de apertura del lanzador **no** recrean la carpeta ni restauran nada: se omiten con `err.sync.local_missing_manual_required` y quedan en el historial como omitidas. Solo una sincronización **manual** (botón Sincronizar o `checkpoint sync`) restaura la copia del hub en el dispositivo. Una carpeta que existe pero está vacía se trata como siempre. Con dos dispositivos nada cambia.
- **Aviso de apertura:** `?device=` es opcional (se deduce el único dispositivo).

## Desactivar un juego

Un juego se puede desactivar sin borrarlo: en **Configuración > Biblioteca**, el interruptor **Juego activo** del formulario del juego (visible sin pulsar «Mostrar más»); en `config.yaml`, `enabled: false` (sin el campo, el juego está activo). Un juego desactivado **no se sincroniza por ninguna vía**:

- La sincronización automática (cada X horas y al arrancar) lo omite en silencio: ni entrada en el registro ni cuenta en los resúmenes.
- `POST /api/sync/{juego}` responde `409` con `err.sync.game_disabled`, también con `dry_run: true`; la CLI (`checkpoint sync`) aborta con ese mismo código. Es una guarda central de la sincronización: para sincronizarlo hay que reactivarlo.
- El aviso de apertura (`opened`) y el cierre automático lo omiten (ver [`api.md`](api.md#hooks)).
- En **Sincronizar** el juego sigue visible pero atenuado, con la etiqueta «Desactivado», sin botón «Sincronizar» ni «Simulación» y con un acceso a Configuración. En **Lanzadores** sigue con su fila, con la etiqueta «Desactivado» y una nota («Desactivado: el aviso se omitirá»). `checkpoint list` lo marca «(desactivado)».
- **Versiones:** se conservan y siguen visibles (con el sufijo «(desactivado)») y restaurables. Restaurar solo copia al hub: no se propaga a los dispositivos mientras el juego esté desactivado.

Al guardar solo se escribe `enabled: false`; reactivarlo quita la línea.

## Datos sin dispositivo asignado

Al borrar un dispositivo o un juego de la configuración, sus datos en el hub **no se borran**. Qué pasa con cada cosa:

- **Metadatos del dispositivo** (línea base de `data/state/<juego>.json`, `data/staging/<juego>/<dispositivo>/` y sus conflictos o resoluciones pendientes de `data/resolutions/<juego>.json`): se limpian solos al guardar (o restaurar) la configuración sin ese dispositivo. Nunca se tocan las versiones ni el hub.
- **Versiones de un dispositivo que ya no existe** (o de un nombre antiguo, como `SteamDeck`): siguen en Versiones con la etiqueta «dispositivo desconocido (id)» y se pueden **restaurar al hub** igual que las demás.
- **Limpieza manual**: Configuración > General > «Datos sin dispositivo asignado» lista lo que ya no pertenece a ningún dispositivo ni juego de la configuración: versiones de un origen desconocido y todo lo que queda en disco de un juego borrado (`hub`, `versions`, `state`, `status`, `logs`, `staging`, `resolutions`), con su tamaño, nº de versiones y fechas (más antigua y más reciente). Si el hub de un juego borrado tiene datos, sale marcado como **única copia**. Pestaña Versiones avisa con un enlace cuando hay algo.
- **Papelera, no borrado**: elegir elementos y confirmar (diálogo con casilla obligatoria) los **mueve** a `data/trash/<AAAA-MM-DD_HHMMSS>/` con un `manifest.json` (qué era, cuándo, tamaño y de dónde salió). Se conservan `CHECKPOINT_TRASH_TTL_DAYS` días (30 por defecto) y el mantenimiento programado (cada hora) vacía lo caducado. Desde la misma pantalla se pueden **restaurar** (si el destino ya existe, no se pisa nada). No hay retención automática de partidas ni borrado directo.
- **Reubicar un juego huérfano en un juego existente**: en cada tarjeta de «juego fuera de la configuración», «Reubicar…» pide elegir un juego de la configuración y confirmar en un diálogo (origen, destino, versiones y tamaño). El destino **conserva sus partidas actuales** (`data/hub/<destino>` no se toca); las versiones del huérfano (`data/versions/<huérfano>/<fecha>/<origen>/`) se **suman** al historial del destino como carpetas enteras, sin mezclarlas ni pisar nada: si la `<fecha>` ya existe en el destino, la versión llega como `<fecha>-<n>` (el menor `n` libre). El hub actual del huérfano (`data/hub/<huérfano>`) tampoco se descarta: pasa a ser una versión más del destino (fecha de la reubicación, origen `hub`) y se puede restaurar desde Versiones. El resto (`state`, `status`, `logs`, `staging`, `resolutions`) va a la papelera como cualquier otro elemento. Se toma el lock de los dos juegos (ocupado: `409` `err.orphans.busy`) y, si un movimiento falla, se deshacen los anteriores (`err.orphans.relocate_failed`). Solo para juegos huérfanos (`err.orphans.not_game` con un origen desconocido) y con un destino que esté en la configuración (`err.orphans.target_unknown`).
- **Seguridad**: solo con sesión. El cliente confirma con el `token` de cada elemento (huella de su contenido en el listado); el hub revalida con la configuración actual y bajo el lock del juego, y nunca mueve un juego de la configuración ni un origen válido (`hub` o un dispositivo de la configuración), aunque se le pida. Si hay una sincronización en curso en ese juego, se salta. Las rutas se resuelven dentro de `data/` y no se siguen enlaces simbólicos.

API (sesión): `GET /api/orphans` → `{items, ttl_days, games}` (`games` = `[{id, name}]` de la configuración, para elegir destino); `POST /api/orphans/relocate` con `{id, token, target}` → `{ok, target, versions, hub, size}`; `POST /api/orphans/trash` con `{items: [{id, token}]}` → `{moved, skipped}`; `GET /api/orphans/trash`; `POST /api/orphans/trash/restore` con `{entry, item}`. Errores `err.orphans.*`.

## Conflictos

Hay conflicto cuando los dos dispositivos han cambiado desde la última sincronización y su contenido es distinto (o, en la primera sincronización, ya difiere). Checkpoint nunca lo decide por la fecha a ciegas.

- **Sincronización automática**: `on_conflict` en Configuración > General > Sincronización automática. `skip` (por defecto) no guarda nada y marca el juego como «Conflicto»; `newest` hace ganar el save más reciente (si las fechas difieren menos de 2 s, se omite). Un juego puede sustituirlo con `on_conflict` en `config.yaml`.
- **Sincronización manual**: siempre pregunta. Un popup ofrece cancelar, «Gana el más reciente» o elegir qué dispositivo gana, con fecha y tamaño de cada uno. En la CLI: `checkpoint sync JUEGO --resolve newest|device:DISPOSITIVO` (sale con código 3 si hay conflicto).

En todos los casos la copia perdedora se guarda antes en versiones. En la primera sincronización de cada juego (aún sin estado guardado) el hub es la única referencia: si ambos lados difieren, se trata como conflicto.

## Cierre automático

Tras `opened`, el hub **vigila el proceso del juego en ese dispositivo** (el `process` del juego; mismo sondeo que usa la sincronización: `pgrep -f` por SSH en Linux, `tasklist` en Windows, `/proc` en «Este equipo») y, cuando se cierra, hace el checkpoint solo. El lanzador no necesita ningún hook de cierre: basta la línea de `opened` de Steam o Lutris.

1. `opened` sincroniza y arma la vigilancia (una por juego; un nuevo `opened` del mismo juego **reemplaza** la anterior).
2. Sondeo cada **15 s**. No se da el juego por cerrado hasta haberlo visto abierto al menos una vez. Si en **2 min** no se ve nunca, se descarta la vigilancia (suele ser un `process` mal puesto) y queda en el historial como omitido (`err.hook.never_seen`) y en el log del hub (`vigilante never_seen`).
3. Al dejar de verse el proceso, o si el dispositivo deja de responder (SSH caído, suspensión), espera **10 s** (para que se liberen los ficheros) y lanza el checkpoint.
4. El checkpoint usa la política de conflictos `skip` (nunca resuelve solo), el mismo lock y la misma lógica que `opened`, y aparece en el historial con el disparador «Cierre del juego» (`trigger: "hook_closed"`). Si aborta o el lock está tomado **no se reintenta**; el cron de la sincronización automática sigue como red de seguridad.

**Por qué no hubo checkpoint (historial).** Cuando la vigilancia termina sin checkpoint, queda una entrada con el disparador «Cierre del juego», el dispositivo y el juego, con icono y texto en el registro y el motivo en «Último aviso» (`GET /api/games/{juego}/hook-status` añade `code` y `params` a `last` si los hay). Solo se registra, no cambia lo que se sincroniza:

| Código | Resultado | Cuándo |
|---|---|---|
| `err.hook.never_seen` | omitido | El proceso no se vio abierto en el tiempo previsto (`CHECKPOINT_HOOK_FIRST_SEEN`); vigilancia descartada. |
| `err.hook.busy` | omitido | Al cerrarse, ya había una ejecución de ese juego en curso o el lock estaba tomado. Sin reintento. |
| `err.hook.game_removed` | omitido | El juego ya no está en la configuración al cerrarse. |
| `err.sync.game_disabled` | omitido | El juego se desactivó con la vigilancia ya armada: al cerrarse no hay checkpoint (y el chip de vigilancia desaparece). |
| `err.hook.checkpoint_failed` | error | El checkpoint lanzó una excepción antes de sincronizar; solo se guarda el tipo de excepción. |

Un sondeo fallido aislado no se registra (se trata como dispositivo sin respuesta, ver arriba). Una vigilancia reemplazada por un nuevo `opened`, o cancelada al apagar el hub, tampoco deja entrada. Las vigilancias no se persisten: si el hub se reinicia se pierden y lo cubre el cron.

Tiempos configurables con variables de entorno (en segundos):

| Variable | Por defecto | Qué es |
|---|---|---|
| `CHECKPOINT_HOOK_POLL` | `15` | Cada cuánto se sondea el proceso |
| `CHECKPOINT_HOOK_SETTLE` | `10` | Espera tras dejar de verlo, antes del checkpoint |
| `CHECKPOINT_HOOK_FIRST_SEEN` | `120` | Tiempo máximo para verlo abierto por primera vez |

Limitaciones:

- La vigilancia **vive en memoria**: si el hub se reinicia se pierde y solo la cubre el cron.
- `process` debe coincidir con el proceso real del juego (en Proton/Wine, el `.exe` bajo Wine). Con `pgrep -f` basta un fragmento del nombre o de la línea de comandos.

## Idioma

La interfaz está en español e inglés. El selector de idioma está en el menú del perfil (el icono redondo del extremo derecho de la cabecera, una vez iniciada la sesión; la pantalla de acceso no lleva selectores y usa el idioma y tema ya guardados). Ofrece **Automático**, **Español** y **English**, y recuerda la elección en ese navegador (`localStorage`, clave `checkpoint.lang`); se aplica al instante, sin recargar. El mismo menú tiene el cambio de tema (automático, claro, oscuro; muestra un sol o una luna según el tema efectivo) y **Salir**.

Orden de prioridad:

1. La elección manual guardada en el navegador (`Español` o `English`).
2. Si se eligió **Automático**, el idioma del navegador (si no es uno soportado, el de 3).
3. El idioma por defecto del servidor: `CHECKPOINT_LANG` (`es` o `en`) o español si no está marcado.

Es decir, sin elección guardada manda el servidor, no el navegador: así una instalación se puede dejar en inglés para todos los usuarios que no hayan elegido. Para fijarlo en Docker, descomenta `CHECKPOINT_LANG` en el `environment:` de `docker-compose.yml` (o añádelo al `.env`).

El backend no traduce nada: devuelve códigos y parámetros (`{"code": "err.sync.dry_run", "params": {...}}`) y la traducción vive en `frontend/src/locales/*.json`. Para añadir un idioma, crea `<código>.json` con las mismas claves que `es.json` (el test `frontend/test/locales/locales.test.mjs` lo comprueba), regístralo en `frontend/src/locales/index.js` y añade el código a `SUPPORTED_LANGS` de `backend/app/core/settings.py`.

Se mantienen en español a propósito: la CLI, los logs internos del servidor, el log técnico de cada ejecución (las líneas del registro en vivo de «Sincronizar») y los textos de estado antiguos guardados en `data/` antes de este cambio.

API: `GET /api/public` (sin sesión) devuelve `{"default_lang": "es"|"en"}`.

## Perfil y foto

El icono redondo del extremo derecho de la cabecera abre el menú del perfil: foto, nombre (el usuario del login, `CHECKPOINT_USER`), idioma, tema, **Salir** y la versión instalada. Sin foto se ve una silueta.

La foto se guarda en el servidor (`data/profile/<id>/photo.jpg|png|webp`, nombre fijo; `<id>` es un hash SHA-256 truncado del nombre de usuario, nunca el nombre en crudo), así que se ve igual desde cualquier dispositivo. El navegador la recorta al centro, la reduce a 256x256 y la sube como WebP (JPEG si no puede). Entrada máxima: 2 MB, solo JPG, PNG o WebP; se valida en el navegador y en el servidor (tipo real por los bytes, sin dependencias nuevas: firma y estructura mínima, no se decodifica la imagen). Se sirve con el tipo fijado por el servidor, `nosniff`, `Content-Security-Policy: sandbox` y `ETag`.

API (requiere sesión; las escrituras comprueban el origen como el resto):

- `GET /api/profile`: `{"name": "...", "photo": {"version": "..."} | null}`. `version` sirve de cache-busting (`/api/profile/photo?v=<version>`).
- `GET /api/profile/photo`: la imagen (`404` si no hay; `304` con `If-None-Match`).
- `PUT /api/profile/photo`: cuerpo = la imagen en bruto con su `Content-Type` (`image/jpeg`, `image/png` o `image/webp`). `415` si el tipo o los bytes no cuadran, `413` por encima de 2 MB, `400` si está vacía. Responde `{"ok": true, "photo": {"version": "..."}}`.
- `DELETE /api/profile/photo`: borra la foto (idempotente).

Todos operan sobre el usuario de la sesión (sin ids en la URL). Hoy solo existe el usuario de `CHECKPOINT_USER`; el almacenamiento por carpeta de usuario y un único punto de código que resuelve el usuario de la sesión dejan el diseño listo para un futuro registro de usuarios (aún no hay roles ni registro). Una foto antigua en `data/profile/photo.<ext>` se mueve sola a la carpeta del usuario al arrancar o en el primer acceso.

## Instalar como app (PWA)

Checkpoint sigue siendo instalable desde el menú del navegador (manifest, iconos y service worker incluidos), pero el hub ya no muestra un botón ni un aviso propio de instalación.

- **iOS (Safari):** funciona también por `http://`. Compartir, «Añadir a pantalla de inicio».
- **Android (Chrome):** la opción de instalar del menú de Chrome y el service worker exigen contexto seguro: **HTTPS** (o `localhost`). Con `http://IP-LAN` Chrome no ofrece instalarla. Pon Checkpoint detrás de un proxy inverso con TLS (Caddy, Traefik, nginx) y entra por el dominio HTTPS.
- Para probarlo sin certificado propio: en el móvil, `chrome://flags/#unsafely-treat-insecure-origin-as-secure` con tu `http://IP-LAN:8088` (solo para pruebas), o un túnel HTTPS al puerto 8088.
- El service worker no cachea nada: la app sigue necesitando el servidor, y las actualizaciones se ven al recargar.
- Los iconos se regeneran con `node frontend/scripts/make-icons.mjs` (sin dependencias).
