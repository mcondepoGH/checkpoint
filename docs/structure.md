# Estructura del código

Mapa de carpetas del backend y del frontend, qué hace cada una, qué puede importar de qué y cómo añadir un módulo nuevo. Las reglas de dependencia las comprueban dos tests (`backend/tests/test_architecture.py` y `frontend/test/architecture.test.mjs`): si rompes una, el test falla y dice qué import sobra.

## Backend (`backend/app/`)

```
backend/app/
├── main.py              fábrica de la app (create_app / app_factory): monta middleware, routers y docs
├── cli.py               CLI (`python -m app.cli`): list, sync...
├── api/                 capa web (FastAPI)
│   ├── auth.py          sesiones, login, API key en cabecera
│   ├── deps.py          dependencias de FastAPI (require, usuario actual; keys Bearer: `hook_user` = usuario, `hook_device` = dispositivo http, `hook_any` = las dos, todas devuelven `Principal(user, device|None)`)
│   ├── middleware.py    log de depuración de cada petición
│   ├── docs/            OpenAPI y Swagger de la API key (install, models, examples, pairing, steam)
│   └── routers/         un router por área: hook, games, session, profile, devices (API key por dispositivo http, con sesión), config, sync,
│                        versions, orphans (datos sin dispositivo ni juego: `GET /api/orphans`, `POST /api/orphans/trash`, `GET /api/orphans/trash` y `POST /api/orphans/trash/restore`, solo con sesión), scheduler, updates, pairing (vinculación por solicitud y código: la parte pública es el ÚNICO endpoint con escritura sin key ni sesión), deck (descarga PÚBLICA y de solo lectura del zip del plugin: `GET /api/deck/plugin`, `/api/deck/plugin.sha256` y `/api/deck/plugin/info`; sin parámetros, ruta fija `settings.DECK_ZIP`), steam (asociación de `steam_appid` desde la Deck: `POST /api/steam/library` solo `ckd_`, y sugerencias/descartes con sesión) y spa (catch-all, siempre el último)
├── services/            lógica de negocio sin FastAPI
│   ├── context.py       AppContext: objetos compartidos de la app (auth, scheduler, watcher...)
│   └── runs, pairing, deckplugin (lee el zip UNA vez, calcula SHA-256 y versión de `Checkpoint/package.json`; caché por mtime y tamaño; se sirven los mismos bytes que se hashearon), hooks (aviso `opened`, cierre y, para dispositivos http, `fingerprint`, `closed`, `manifest`, subida `files` y `commit`, purga y tope del staging), steam (normalización y coincidencia de nombres, sugerencias en memoria y descartes en `data/state/_steam/dismissed.json`; `purge` en `scheduler.maintenance`), orphans (detección de datos de un origen desconocido o de un juego fuera de la config, con `token` por elemento; mover a la papelera revalidando con la config actual y bajo el lock del juego; listar, restaurar y vaciar lo caducado: `purge_expired` en `scheduler.maintenance`), hookfiles (staging reanudable, `part_lock` por fichero y `stage_lock` del dispositivo durante el commit, tope y lectura por rangos de las subidas/bajadas http), devices, games, status, versions
├── sync/                motor de sincronización
│   ├── engine.py        run_sync, restore_version, resolve_game; `write_winner_to_hub` y `finish_hub_update` (aplicar un ganador al hub, compartido con el commit HTTP)
│   ├── safepath.py      `resolve_inside`: ruta relativa segura dentro de una raíz (sin `..`, ni enlaces simbólicos); obligatoria al leer o escribir con rutas de un dispositivo http
│   ├── decide.py        decisión pura de quién manda y resolución de conflictos
│   ├── fingerprint.py   huella de un directorio o de un manifiesto (`fingerprint_from_manifest`)
│   ├── versions.py      versiones guardadas, `current_state` (estado del hub solo con `stat`, para `current` de `/limit`) y reemplazo casi atómico de directorios
│   ├── baseline.py      huella de cada participante tras la última sync completa (`drop_baseline` quita un origen)
│   ├── cleanup.py       `purge_device_metadata`: al borrar un dispositivo, limpia SOLO sus metadatos (baseline, staging, resoluciones), con el lock del juego; nunca versiones ni hub
│   ├── trash.py         papelera `data/trash/<fecha>/` con `manifest.json` (rutas relativas), caducidad (`settings.TRASH_TTL_DAYS`), mover y restaurar sin pisar ni seguir enlaces
│   ├── resolution.py    conflictos de datos de dispositivos http y su resolución pendiente (`data/resolutions/<juego>.json`)
│   ├── errors.py        SyncAbort
│   ├── locking.py       lock por juego
│   ├── scheduler.py     sincronización automática + tareas de mantenimiento periódicas (`maintenance`: purga del staging)
│   ├── watcher.py       vigilancia del cierre del juego
│   └── transport/       acceso a dispositivos: base (interfaz y utilidades), posix (ssh + rsync),
│                        windows (ssh + tar) y local («Este equipo»); __init__ reexporta lo público
├── config/              modelo (models.py) y almacén (store.py) de config.yaml; `Game.steam_appid` (opcional; entero > 0, único entre juegos) lo expone `GET /api/games`
├── users/               datos por usuario: apikey (key de usuario `ck_` y de dispositivo http `ckd_`, mismo almacén cifrado), avatar, history
└── core/                utilidades base: settings, errors, hosts, bootstrap, redact, runtime, updates
```

### Reglas de dependencia (backend)

Las capas se apilan: `api` → `services` → `sync` / `config` / `users` → `core`. Nunca se importa hacia arriba.

| Capa | Puede importar de | No puede importar de |
|---|---|---|
| `core` | solo de sí misma | ninguna otra capa |
| `sync`, `config`, `users` | `core` y entre ellas | `api`, `services` |
| `services` | `sync`, `config`, `users`, `core` | `api` |
| `api` | todas | (ninguna) |

Excepción documentada: `sync/scheduler` importa `users/history` (registra en el historial de cada usuario el resultado de sus ejecuciones). Está en la lista `ALLOWED` del test; si deja de hacer falta, el test pide borrarla.

Para repartir los imports públicos de un paquete sin romper a quien ya importa de él, el `__init__.py` reexporta (por ejemplo `sync/transport/__init__.py`, o `sync/engine.py` con las funciones que viven en `decide`, `fingerprint`, `versions` y `baseline`). Los tests que sustituyen una función con `monkeypatch` deben apuntar al módulo donde se *usa* (p. ej. `app.sync.engine.get_transport`, `app.sync.transport.base._run`).

### Añadir un módulo al backend

1. Decide la capa por la regla de arriba: ¿habla HTTP? `api`. ¿Orquesta casos de uso sin conocer FastAPI? `services`. ¿Es del motor de sincronización? `sync`. ¿Es del fichero de configuración? `config`. ¿Es dato de un usuario? `users`. ¿Lo usan todas las capas y no depende de ninguna? `core`.
2. Un endpoint nuevo: crea `api/routers/<area>.py` con un `APIRouter`, regístralo en la lista de `main.py` (antes del router `spa`) y pon la lógica en `services/`. Por defecto queda fuera del esquema público de OpenAPI; solo las rutas con el tag `TAG` de `api/docs/install.py` salen en Swagger.
   Autenticación de `/api/hook/*` y `/api/games`: no hay dependencia global; cada endpoint declara la suya según la key que acepta (`deps.hook_user` usuario: `watches`; `deps.hook_device` dispositivo: `fingerprint`, `manifest`, `files`, `commit`, `closed`; `deps.hook_any`: `ping`, `GET /api/games` y `opened`: con `ckd_` es el aviso de apertura de un http (`HookService.opened_device`), con `ck_` el de siempre; `GET /api/games` que con key de dispositivo filtra por sus juegos y añade `path` = `Game.paths[<ese dispositivo>]` o `null`, vía `routers/games.device_path`; con key de usuario no hay `path`). La clase equivocada es el mismo 401 que una inválida y cuenta para `hook_fail`. Un endpoint nuevo debe elegir una; `docs/install.KEY_KINDS` la declara para el Swagger (un único esquema Bearer `bearerAuth` para `ck_` y `ckd_`; la clase aceptada va en la nota «Key aceptada» de cada operación) y `test_apidocs`/`test_device_apikey` fallan si falta o no coincide. Con key de dispositivo, `HookService.scope` fija dispositivo y juego (403 `err.apikey.device_mismatch` si `?device=` no es el de la key; 404 `err.main.game_unknown` si el juego no lo incluye). Las keys de dispositivo viven en `users/apikey` (`devices/<id>.enc`, ligadas al id de dispositivo) y se podan con `services/devices.prune_device_keys` al guardar/restaurar la config y al arrancar.
   Vinculación de dispositivos (`routers/pairing.py` + `services/pairing.py`, docs en `api/docs/pairing.py`): dos routers en `/api/pairing`. `POST /requests` y `GET /requests/{id}` son PÚBLICOS (sin key ni sesión; el único caso: `KEY_KINDS` = `public` y `pairing_secret`, secreto en la cabecera `X-Pairing-Secret`, nunca en la URL) y limitados por IP (`Auth.pair_fails`, `pair_wait/pair_fail/pair_ok`, más los topes y la caducidad de `PairingService`, con el reloj de `Auth`); `GET /pending` y `POST /pending/{id}/accept|reject` exigen sesión (`session`). Las solicitudes viven solo en memoria (`ctx.pairing`, `purge` en `scheduler.maintenance`). Aceptar da de alta el dispositivo por `ConfigStore.save` (mismas validaciones que `PUT /api/config`) y la key `ckd_` se genera al recogerla, no al aceptar. Una ruta pública nueva sin credencial debe justificarse y pasar por los mismos límites.
   Descarga del plugin (`routers/deck.py` + `services/deckplugin.py`): pública sin credencial pero de SOLO LECTURA, justificada porque el zip es el plugin de código abierto del repositorio y la Deck lo baja sin cuenta; la integridad la da la suma SHA-256 (cabecera `X-Checkpoint-Plugin-Sha256`, `.sha256` para `sha256sum -c` e `info`). Ruta fija (`settings.DECK_ZIP`: Docker `/app/deck/Checkpoint.zip`, que construye el Dockerfile; nativo `checkpoint-deck/out/Checkpoint.zip` tras `pnpm run zip`); sin zip, 404 `err.deck.plugin_missing`. Fuera del Swagger de la API key.
   Asociación de Steam (`routers/steam.py` + `services/steam.py`, docs en `api/docs/steam.py`): `device` (`POST /api/steam/library`, `POST /api/steam/games` y `PUT /api/steam/games/{game}/enabled`, `deps.hook_device`, `KEY_KINDS` = `device`) solo toca juegos activos que tienen ese dispositivo y solo escribe `steam_appid` con coincidencia exacta y única de nombre normalizado en un juego sin appid y con el appid libre (`plan_matches`, pura); lo dudoso (parecido con `SIMILARITY` = 0,85, o ambiguo) son sugerencias en memoria; `session` (`/api/steam/suggestions*`, `/api/steam/dismissed*`, `KEY_KINDS` = `session`). Escribe config por `ConfigStore.save` con la versión de la misma lectura y reintentos. Nunca pisa un appid existente. `POST /api/steam/games` (`SteamService.create_game`) crea un juego con SOLO el dispositivo de la key, activo, con `steam_appid`, nombre y ruta que da la Deck: el id lo genera el hub (`slug` del nombre, con el appid detrás si colisiona y `steam-<appid>` sin slug), valida con `validate_config` (las mismas reglas que `PUT /api/config`: nombre y ruta válidos, nombre y appid únicos; un fallo es `422 err.steam.game_invalid` con solo `field` y `reason`, sin datos de otros juegos), la plataforma sale del dispositivo. Si ya existe UN juego con ese nombre normalizado (`normalize`, la de `plan_matches`; `SteamService._twins`), `_join` le AÑADE el dispositivo (`devices` + `paths[dispositivo]` validados con `validate_config`, misma versión y reintentos que la creación; pone `steam_appid` si faltaba) y responde `{id, name, appid, path, joined, devices, enabled}`; condiciones: hueco (<2 dispositivos), dispositivo fuera, appid igual o juego sin appid, appid no usado por otro juego; un juego desactivado se une y sigue desactivado; dispositivo ya dentro con el mismo appid = `joined: false` sin escribir; el resto es `422 err.steam.game_invalid` (`field: name`, `reason`: `err.steam.no_free_slot`, `err.steam.appid_mismatch`, `err.steam.appid_in_use` o `err.config.name_duplicate` si es ambiguo o el dispositivo ya estaba con otro appid). La key solo se añade a sí misma. `PUT /api/steam/games/{game}/enabled` (`SteamService.set_enabled`) pone el campo `enabled` del juego: es de TODO el hub (un juego desactivado no se sincroniza por ninguna vía en ningún dispositivo), solo para juegos que tienen ese dispositivo (otro caso, el mismo `404 err.steam.game_unknown`). Cuerpos de máx. 8192 bytes con forma exacta (`422 err.steam.game_body_invalid`).
   Los dispositivos `http: true` (`Device.http`) no tienen transporte: `get_transport` lanza `err.transport.push_only` y quedan fuera de `_do_sync`, del scheduler, de `opened` y de la vigilancia (`config.models.classic_devices` lista los que el hub sí contacta; la UI usa el mismo criterio en `components/config/draft.js`: `isHttpOnly` oculta «Sincronizar» y «Simulación» en Sincronizar). Los atiende la API de `routers/hook.py` con `services/hooks.py` (`fingerprint`: no toca ficheros ni historial; escribe la línea base con `none`/`same` y el registro del conflicto con `conflict` (`sync/resolution.py`, que `PUT /resolution` convierte en resolución pendiente y `fingerprint`/`commit` honran si las huellas coinciden), siempre bajo el lock del juego; `closed`: limpia el «jugando» y registra el cierre en el historial, sin sync; `opened_device` (key `ckd_` en `opened`): sin sync ni vigilancia, marca «jugando» en `HookService._playing` (en memoria, caduca a `settings.HOOK_PLAYING_TTL`) y anota `hook_opened`; ambos aceptan el cuerpo opcional `{result: {state, code?}}` (`parse_sync_result`: lista cerrada, 1 KiB, `err.hook.result_invalid`), que queda en el historial como `code` `hook.sync.<estado>`; `GET /api/watches` expone `playing` y `results` (`active_playing`, `last_sync_results`; la UI pinta `playing` con `components/watch/PlayingBars.jsx`, que reutiliza `WatchBar` como la vigilancia clásica; `results` alimenta el Registro y la tarjeta de un juego solo http en Sincronizar: `lastHttpResult` elige el último, `httpRunStatus` lo adapta a `LastRun` (bloque «Última sync») y `httpBadge` deriva la insignia del título, en vez del estado antiguo del hub, en `components/watch/watch.js`); subida: `PUT files` escribe solo en `data/staging/<juego>/<dispositivo>/` SIN el lock del juego (solo guarda `game_busy` y un lock por fichero, `hookfiles.part_lock`) y únicamente `commit` toca `data/hub/<juego>`, con el lock del juego, comprobando `expect`; el staging se purga por antigüedad (`CHECKPOINT_HOOK_STAGING_TTL_H`, al arrancar y cada hora vía `Scheduler.maintenance`, sin tocar juegos con lock o run) y tiene tope por juego (`CHECKPOINT_HOOK_STAGING_MAX_MB`, `err.hook.staging_full`); `fingerprint?manifest=1` devuelve `hub_manifest` de la misma lectura (`fingerprint_with_manifest`); bajada: `manifest`, `GET files` con `Range`; la línea base del dispositivo la fija después un `fingerprint` igual). `/api/devices/test` con un `http` responde `err.transport.push_only` sin intentar SSH. El manifiesto solo rechaza rutas que escapan (`..`, absolutas, NUL, vacías, repetidas): no usa `PATH_CHARS_RE`, que queda para rutas de dispositivo. Como esas reglas son relajadas, toda ruta que se lea o escriba en disco (staging o hub) debe pasar por `sync/safepath.resolve_inside`.
3. Un transporte nuevo: módulo en `sync/transport/` que implemente `Transport` (de `base.py`) y exporta en `__init__.py`; engánchalo en `get_transport`.
4. Textos para el usuario: el backend no traduce; devuelve códigos `err.<módulo>.<causa>` con `params` y la traducción va en `frontend/src/locales/*.json`.
5. Ejecuta `pytest`: `test_architecture.py` confirma que no has roto las reglas.

## Frontend (`frontend/src/`)

```
frontend/src/
├── main.jsx, App.jsx        arranque y raíz (pestañas, sesión, cabecera)
├── pages/                   Login, Sync, Versions, Settings (una por pestaña; Settings es el contenedor de las subpestañas)
│   └── settings/            paneles de las subpestañas de Configuración: General, Library (Biblioteca) y Launchers
│                        (la separación entre bloques la da solo el `gap` del panel en `ui/_tabs.scss`; los bloques no llevan margen vertical, lo vigila `test/pages/settings-spacing.test.mjs`)
├── components/
│   ├── ui/                  componentes genéricos (Button, Badge, Alert, Pill, Select, Checkbox, Switch,
│   │                        Tabs (con variante subnav y paneles conservados), CopyBox, WatchBar, WatchStatus, Input, Icon, Modal, Field,
│   │                        EmptyState, AppIcon, ErrorBoundary, CrashToasts) con su parcial SCSS al lado (_button.scss...)
│   ├── profile/             Avatar, ProfileMenu, ApiKeySection, LanguageSelect, photo.js, _profile.scss
│   ├── updates/             UpdateBadge, UpdateDialog, UpdateCheck
│   ├── watch/               WatchSummary, watch.js
│   ├── config/              DeviceCard (con rama para dispositivos http), DeviceKey (clave de un dispositivo http), PairingRequests (solicitudes de
│   │                        vinculación pendientes), SteamSuggestions (sugerencias y descartes de appid de Steam), Orphans (datos sin dispositivo ni juego en Configuración > General: lista, papelera y restaurar; `OrphanList` solo pinta), DeckPlugin (botón «Descargar plugin», versión y tamaño; se deshabilita si el hub no lleva el zip), GameCard, IdNote, SaveDialog, YamlDialog, BackupsDialog,
│   │                        DiffView, draft.js, useConfigDraft.js, _config.scss
│   ├── autosync/            AutoSync, AutoSyncLog, runLog.js, _autosync.scss
│   ├── launchers/           LauncherBlock (una fila por juego), launchers.js
│   ├── keyhelp/             PublicKey, keyhelpSteps.js
│   ├── sync/                ConflictDialog, HttpConflicts (aviso de conflicto/resolución de un juego solo http), httpConflict.js
│   └── versions/            VersionList (tarjeta «Actual» del hub, sin Restaurar, y versiones anteriores; un origen que ya no es un dispositivo sale como «dispositivo desconocido (id)»)
├── hooks/                   useI18n, useWatches, usePairing (consulta cada 5 s las solicitudes pendientes), useSteam (ídem con las sugerencias de Steam), useTheme
├── lib/                     lógica sin React: api.js (cliente y ApiError), api/<recurso>.js, i18n, errors,
│                            format, clipboard, tabs, names, pwa, updates, apikey,
│                            pairing, orphans (lógica pura de la selección y del aviso de la papelera), steam (lógica pura de sugerencias), devicekey (lógica pura de solicitudes y de la clave de dispositivo), crash (detalles saneados de un fallo), crashtext (textos de respaldo sin contexto de i18n), crashwatch (captura global de fallos), poll (consulta con pestaña visible), versionsWatch (vigila la versión más reciente y el «Actual» del hub de un juego), api/pairing.js, api/steam.js, api/orphans.js, deck (URLs y normalización de la información del plugin), api/deck.js
├── locales/                 es.json, en.json e index.js
├── assets/                  imágenes
└── styles/                  _variables, _themes, _base, _layout, _components y main.scss
```

`styles/main.scss` solo ordena los `@use`; los parciales de cada componente viven junto a él (`components/ui/`, `components/config/`, `components/autosync/`, `components/profile/`). El orden de los `@use` en `main.scss` importa (cascada): no lo reordenes sin comprobar el CSS resultante. `_components.scss` queda en `styles/`: mezcla reglas globales de varias pantallas (tarjetas, rejilla, modal, conflictos).

Los imports entre carpetas usan el alias `#src/` (`package.json` → `imports`: `#src/lib/api.js`); dentro de una misma carpeta, rutas relativas (`./Button.jsx`). Se usa `#src/` y no `#/` porque Node no admite subpaths que empiecen por `#/`. Funciona igual en Vite, en esbuild (tests) y en Node.

### Reglas de dependencia (frontend)

| Carpeta | Puede importar de | No puede importar de |
|---|---|---|
| `lib` | solo de `lib` (y recursos) | React, `hooks`, `components`, `pages` |
| `hooks` | `lib`, `hooks` | `components`, `pages` |
| `components/ui` | `lib`, `hooks`, `ui` | zonas, `pages` |
| `components/<zona>` | `lib`, `hooks`, `ui` y su propia zona | otra zona, `pages` |
| `pages`, `App.jsx` | todo | (ninguna) |

`assets/`, `locales/` y `styles/` son recursos: los puede importar cualquiera. Si dos zonas comparten algo, súbelo a `ui` (si es de interfaz) o a `lib` (si es lógica): por eso `updates.js` y `apikey.js` viven en `lib/` (los usan varias zonas). Algunos módulos de `lib` usan el navegador (`clipboard`, `pwa`, `launchers`), pero ninguno importa React.

Todas las llamadas a la API pasan por `lib/api/<recurso>.js` (`session`, `config`, `sync`, `versions`, `updates`, `profile`); los componentes no llaman a `api()` directamente. Dos componentes (`ApiKeySection`, `LauncherBlock`) reciben el cliente por prop `api` para poder sustituirlo en los tests.

`components/ui/index.js` reexporta los componentes de uso común; `Icon`, `Modal`, `Field`, `EmptyState` y `AppIcon` se importan directamente desde su fichero.

### Añadir un módulo al frontend

1. Componente genérico y reutilizable (varios usos, sin lógica de negocio): `components/ui/<Nombre>.jsx`, su parcial `_<nombre>.scss` al lado, y la línea en `components/ui/index.js` y en `components/ui/_index.scss`. Con tres o más usos de un mismo patrón, conviértelo en componente.
2. Componente propio de una funcionalidad: en la zona que corresponda (`components/<zona>/`), con sus ayudas puras (`.js`) al lado. Zona nueva: carpeta nueva con su parcial SCSS y su `@use` en `styles/main.scss` en el sitio correcto de la cascada.
3. Una llamada nueva a la API: función en `lib/api/<recurso>.js`; el componente importa la función, no `api()`.
4. Lógica compartida sin React: `lib/`. Estado compartido con React: `hooks/`.
5. Textos: claves en `locales/es.json` y `en.json` con las mismas claves (`locales.test.mjs` lo comprueba). Tamaños de texto con los tokens `$fs-*` de `styles/_variables.scss`.
6. Tests: en `frontend/test/` en el mismo sitio que el fichero (`test/components/<zona>/...`), con `test/helpers/bundle.mjs` para renderizar componentes y `test/helpers/locales.mjs` para los catálogos. Ejecuta `npm test`: `architecture.test.mjs` comprueba las reglas de dependencia.

## Plugin de Steam Deck (`checkpoint-deck/`)

Plugin de Decky Loader, aparte del backend y del frontend: no lo importa ni lo ejecuta el hub, y los linters y tests del hub no lo recorren. Se empaqueta a zip con `checkpoint-deck/scripts/package.sh` (el zip no se commitea). El Dockerfile lo construye en la etapa `deck` y lo copia a `/app/deck/Checkpoint.zip`; el hub lo sirve en `/api/deck/plugin` y la web lo ofrece en Configuración > Lanzadores, abajo del todo (no existe aún una página «Herramientas»). Versiones y actualizaciones (decisión cerrada): el plugin tiene versión propia semver (`checkpoint-deck/package.json`, arranca en `1.0.0`; el hub la lee del zip) y declara `checkpointProtocol` (entero). La compatibilidad va por protocolo, no por versión: `backend/app/core/protocol.py` fija `PROTOCOL` y `MIN_PLUGIN_PROTOCOL` (ambos 1), `GET /api/hook/ping` los devuelve como `protocol` y `min_plugin_protocol` (campos nuevos: los clientes viejos los ignoran) y `GET /api/deck/plugin/info` añade `protocol`. «Probar conexión» avisa si el protocolo del plugin es menor que `min_plugin_protocol` (plugin bloqueado: no sincroniza hasta actualizar), si el hub no anuncia protocolo (hub viejo: aviso sin bloquear) o si el plugin no puede leer el suyo. Actualizar es SOLO por URL de Decky (decisión cerrada; el plugin no descarga ni instala nada ni escribe en su carpeta): «Buscar actualizaciones» consulta `/api/deck/plugin/info` (público, sin clave `ckd_`), solo ofrece una versión estrictamente mayor (semver propio con solo la biblioteca estándar; una pre-release como `1.0.0-rc.1` es MENOR que su release `1.0.0`) y el panel da los pasos: Ajustes de Decky > Desarrollador > «Instalar plugin desde URL», pegar `<hub>/api/deck/plugin` y reiniciar Decky si no se recarga solo. Probado en una Deck real: la instalación por URL de Decky, el selector de carpetas y el panel. Sin comprobar: el comportamiento exacto en otras versiones de Decky.

```
checkpoint-deck/
├── plugin.json            nombre, autor, flags (vacío: sin permisos de administrador) y api_version 1
├── package.json, tsconfig.json, rollup.config.js, pnpm-lock.yaml    build con pnpm 9 y rollup (plantilla oficial de Decky)
├── src/index.tsx          panel del menú rápido (React + @decky/ui); solo pinta el estado que le da main.py; en «Configurar» un juego, «Examinar…» abre el selector nativo de Decky (`openFilePicker`, argumentos explícitos de `pickerArgs`) en la ruta que valida `picker_start` (detectada, si no el home, si no `/`); el `TypeError` conocido de Decky se sustituye por un mensaje corto junto al botón
├── src/clipboard.ts       `copyText`: copia al portapapeles (botón «Copiar dirección»); `navigator.clipboard` y, si no, `execCommand("copy")`; nunca lanza
├── src/autosync.ts        escucha abrir/cerrar juegos de Steam (`SteamClient.GameSessions`, API interna sin contrato estable: no hay garantía entre versiones de Steam) y convierte los avisos del backend en toasts
├── src/texts.ts           textos de error y de actualizaciones compartidos por el panel y los toasts, los textos y `pickerArgs` del selector de carpetas y los de «Avisos» (último aviso) y los del interruptor «Mostrar juegos sin configurar» (`unconfiguredView`)
├── src/crash.ts, crashwatch.ts    captura de fallos del panel (port del hub)
├── main.py                clase `Plugin` (`_main`, `_unload`): métodos que llama la interfaz (`get_version` y `check_update` son solo lectura; no hay `install_update`); `get_prefs`/`set_pref` guardan las preferencias de la interfaz (p. ej. «Mostrar juegos sin configurar») en `prefs.json`, aparte de `settings.json` (que lleva la clave `ckd_`); `resolve_conflict` resuelve un conflicto de datos; delega en py_modules
├── py_modules/            lógica sin Decky, solo biblioteca estándar; los nombres llevan el prefijo `checkpoint_` porque
│   │                      Decky comparte `sys.path` entre plugins
│   ├── checkpoint_hub.py       validación de URL, HTTP con `urllib`, ajustes con permisos 0600, máquina de estados de la vinculación
│   ├── checkpoint_steam.py     lector de VDF/ACF y de las bibliotecas de Steam (`appmanifest_*.acf`, incluida la SD): solo appid y nombre; `scan_games` suma los atajos (techo de ACF `2**31-1`) y devuelve cuáles son
│   ├── checkpoint_shortcuts.py lector de `userdata/<id>/config/shortcuts.vdf` (VDF binario) de los atajos de Steam (juegos que no son de Steam): appid (32 bits sin signo, techo `2**32-1`), nombre, `Exe`, `StartDir` y `LaunchOptions`; solo appid y nombre salen de la Deck; `find_launch_options` busca las de un atajo por appid; `derive_appid` (crc32 de Exe + nombre, no verificado) solo si se pide
│   ├── checkpoint_client.py    `HubClient` con la clave `ckd_`: juegos, fingerprint, descarga con Range, subida reanudable, commit, reintentos; `refresh_library`
│   ├── checkpoint_manifest.py  manifiesto local `[{path,sha256,size,mtime}]` con las mismas reglas que `backend/app/sync/fingerprint.py`
│   ├── checkpoint_sync.py      motor de sincronización manual (`check_game`, `sync_game`, `sync_all`) y validación de rutas
│   ├── checkpoint_version.py   versión propia (semver, comparación) y protocolo, leídos en ejecución del `package.json` instalado
│   ├── checkpoint_update.py    consulta de versión nueva, SOLO LECTURA (`fetch_info` a `/api/deck/plugin/info` sin clave y `evaluate`: solo una versión estrictamente mayor; `reason: hub_old` si el hub no anuncia protocolo); no descarga ni instala: el panel (`src/index.tsx`, textos en `src/texts.ts`) da los pasos de «Instalar plugin desde URL» con `<hub>/api/deck/plugin` y la SHA-256 abreviada
│   ├── checkpoint_jobs.py      tareas de fondo del panel: una a la vez, estado en memoria, cancelables; tras buscar juegos lista los del hub (con `enabled`) y los instalados sin juego en el hub (`unconfigured`)
│   ├── checkpoint_browse.py    ruta inicial segura del selector de Decky (`usable_start`, tras `picker_start`): existe, es carpeta, se lista y no es de sistema; si no, home y `/`
│   ├── checkpoint_lutris.py    carpeta sugerida para un atajo de Lutris, solo lectura y sin dependencias: `LaunchOptions` `lutris:rungameid/N` -> fila `N` de `pga.db` (sqlite `mode=ro`, Flatpak `~/.var/app/net.lutris.Lutris/data/lutris` y nativo `~/.local/share/lutris`, este último no verificado) -> `games/<configpath>.yml` (analizador mínimo de `game.prefix`) -> prefijo (o `directory` de respaldo), donde busca CANDIDATOS de carpeta de guardado en `drive_c/users/*/` (`find_saves`: solo carpetas con ficheros, `SaveGames`/`Saves`/... preferidas, ruido de Wine filtrado, orden por parecido de nombre y luego por mtime, máximo 8, topes de recorrido, sin seguir enlaces); las rutas pasan por `validate_game_path` y deben estar en el home; fallos = sin sugerencia
│   ├── checkpoint_games.py     configurar juegos desde el panel: ruta de saves sugerida con lo que existe en la Deck (prefijo de Proton y Steam Cloud; para un atajo de Lutris, los candidatos del prefijo y `browse_start` vía `suggest_shortcut`), crear el juego en el hub y activar o desactivar uno (`GameTools`)
│   └── checkpoint_auto.py      avisos automáticos de abrir y cerrar (toast siempre al abrir y al cerrar: `uploaded`, `downloaded`, `up_to_date`, `no_path`, `missing_dir`, `conflict`, error; `disabled` y los juegos sin `steam_appid` no avisan): sincroniza al abrir y avisa `opened` con el resultado (no crítico, un solo intento), sube y avisa `closed` al cerrar, cola en disco (`auto.json`, solo appid/id/nombre) con reintento; cada rama deja su línea `auto: …` en el log (sin rutas ni claves)
├── scripts/package.sh     crea `Checkpoint.zip` (carpeta `Checkpoint/` en la raíz del zip)
└── tests/                 pytest: hub falso por HTTP, y `test_integration_hub.py` contra el hub real (se omite sin las dependencias del backend); `test_main_resolve.py` (`Plugin.resolve_conflict`), `test_main_prefs.py` (`get_prefs`/`set_pref`) y las pruebas de node `clipboard.test.mjs`, `texts.test.mjs`, `autosync.test.mjs` y `crashwatch.test.mjs`

Pruebas del hub de esta zona (en `backend/tests/`): `test_deck_plugin.py` (descarga del zip, `.sha256` e `info`), `test_hook_resolution.py` (conflictos y resolución de dispositivos http), `test_hook_opened_http.py` (`opened`/`closed` con `ckd_`, «jugando» y `result`) y `test_steam_games.py` (`POST /api/steam/games` y `PUT .../enabled`, con la unión automática).
```

Reglas: el secreto de la solicitud viaja solo en `X-Pairing-Secret` y la clave `ckd_` solo en `Authorization: Bearer`; ninguno sale en logs ni en el estado que ve la interfaz; la clave se guarda en `settings.json` (directorio de ajustes de Decky) con 0600. Sincronización manual (con el juego abierto se rechaza con `game_running`; abrir y cerrar los trata `checkpoint_auto`, que al cerrar avisa con `POST /api/hook/{game}/closed` y deja los cierres sin red en una cola en disco): la ruta del save la da el hub (`GET /api/games`, campo `path`) y es dato no confiable; `checkpoint_sync.validate_game_path` y `validate_rel` la validan antes de tocar nada, y una descarga va a `<carpeta>.checkpoint-new`, se verifica y reemplaza la carpeta dejando UNA copia `<carpeta>.checkpoint-backup`. El manifiesto local debe describir la carpeta igual que `fingerprint()` del hub: si cambian las reglas allí, cambian en `checkpoint_manifest.py` y lo vigila el test de equivalencia.
