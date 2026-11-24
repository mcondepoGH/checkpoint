# API, keys y hooks

Referencia de la API que usan lanzadores y plugins (API keys, vinculación, Steam, dispositivos `http` y avisos de apertura y cierre). Uso general: [`README.md`](../README.md); comportamiento: [`guide.md`](guide.md).

## API key de usuario

Una sola API key por usuario, para que lanzadores y plugins avisen al hub sin iniciar sesión. Se gestiona en la sección «API key» del menú del perfil: **Generar** (nunca se crea sola), verla siempre (campo de solo lectura con botón **Copiar**), **Regenerar** (con confirmación: la anterior deja de valer y hay que actualizar los comandos y plugins ya vinculados) y **Revocar**. Formato: `ck_` + 32 bytes aleatorios en base64 urlsafe (46 caracteres).

- **Alcance mínimo:** esta key de **usuario** sirve para `GET /api/hook/ping`, `GET /api/hook/watches`, `POST /api/hook/{juego}/opened` y `GET /api/games` (todos los juegos). **No** vale en las rutas de los dispositivos `http` (`fingerprint`, `manifest`, `files`, `commit`, `resolution`, `closed`): esas piden la key del dispositivo (ver «API key de dispositivo `http`»). No da acceso al login, ajustes, versiones ni a restaurar, y la cookie de sesión no vale en esas rutas.
- **Autenticación:** cabecera `Authorization: Bearer ck_...`, sin cookie ni comprobación de `Origin`. Cualquier fallo (sin cabecera, mal formada, inválida, revocada o regenerada) es el mismo `401` con `err.apikey.invalid`; la comparación es en tiempo constante (`hmac.compare_digest`). Tras 3 fallos seguidos desde una IP, `429` con `Retry-After` (misma escala que el login, con contador propio: un lanzador mal configurado no bloquea el login web).
- **Dónde se guarda:** como la key se vuelve a mostrar, no vale guardar solo un hash. Se guarda cifrada en `data/profile/<id>/apikey.enc` (permisos 0600, misma carpeta por usuario que la foto). La clave de cifrado se deriva del **secreto del hub**, `hub.secret` (32 bytes aleatorios, 0600), que se crea la primera vez junto a `config.yaml` (en Docker, el volumen `/config`; sin Docker, `config/` del directorio de datos de la app), **fuera de `data/`**: una copia de seguridad solo de `data/` no expone la key. Haz copia de `hub.secret` si quieres conservar la key; sin él (o si lo cambias) la key guardada no se puede descifrar, la interfaz muestra «sin key» y basta generar una nueva.
- **Cifrado:** [Fernet](https://cryptography.io/en/latest/fernet/) de la librería `cryptography` (AES-128-CBC + HMAC-SHA256). La clave Fernet se deriva del secreto del hub con HMAC-SHA256. Fernet no admite datos asociados, así que el id de usuario va dentro del payload cifrado y se verifica al descifrar: un fichero manipulado, copiado a otro usuario o cifrado con otro secreto no descifra (la interfaz muestra «sin key»).
- **Copias de seguridad:** si tu copia cubre `/config` y `/data` juntos, el secreto viaja con la key cifrada y la protección frente a un backup se pierde. Excluye `hub.secret` de la copia (y guárdalo aparte si quieres poder restaurar la key).
- **HTTP en LAN:** la key viaja en claro; la interfaz lo avisa. Usa HTTPS (proxy inverso) o una VPN fuera de tu red de confianza.

API (con sesión de cookie, como el resto del perfil; las escrituras comprueban el origen; respuestas con `Cache-Control: no-store`):

- `GET /api/profile/apikey`: `{"exists": true, "key": "ck_..."}` o `{"exists": false, "key": null}`.
- `POST /api/profile/apikey`: genera o regenera; devuelve `{"exists": true, "key": "ck_..."}`.
- `DELETE /api/profile/apikey`: revoca (idempotente); devuelve `{"exists": false, "key": null}`.
- `GET /api/hook/ping` (Bearer): `{"ok": true, "user": "<nombre>", "protocol": 1, "min_plugin_protocol": 1}`. `protocol` y `min_plugin_protocol` son la versión (entera) del protocolo plugin de Steam Deck ↔ hub y la más vieja de plugin que este hub atiende (`backend/app/core/protocol.py`); los clientes que no los conocen los ignoran.

```bash
curl -H "Authorization: Bearer ck_..." http://HOST:PORT/api/hook/ping
```

## API key de dispositivo `http`

Cada dispositivo con `http: true` tiene **su propia key**, distinta de la de usuario y de la de los demás dispositivos. Formato: `ckd_` + 32 bytes aleatorios en base64 urlsafe (47 caracteres); el prefijo distinto (`ck_` usuario, `ckd_` dispositivo) le dice al hub qué comprobar sin ambigüedad. Se genera, se ve, se copia, se regenera (la anterior deja de valer al instante) y se revoca por sesión de cookie, desde la tarjeta del dispositivo en Configuración → Biblioteca (ver «Vincular un dispositivo http desde la web») o con la API. Se guarda igual que la de usuario (Fernet con `hub.secret`, 0600, comparación en tiempo constante) en `data/profile/<id>/devices/<id de dispositivo>.enc`; el id del dispositivo va dentro del payload cifrado: un fichero copiado a otro dispositivo no descifra.

API (sesión de cookie; escrituras con comprobación de `Origin`; `Cache-Control: no-store`; `404` `err.hook.device_unknown` si el id no existe, `400` `err.hook.device_not_http` si el dispositivo no es `http`):

- `GET /api/devices/{id}/apikey`: `{"exists": true, "key": "ckd_..."}` o `{"exists": false, "key": null}`.
- `POST /api/devices/{id}/apikey`: genera o regenera; devuelve `{"exists": true, "key": "ckd_..."}`.
- `DELETE /api/devices/{id}/apikey`: revoca (idempotente); devuelve `{"exists": false, "key": null}`.

Con la sesión web (cookie, no una key; `COOKIE` = archivo de cookies del login, `ID` = id del dispositivo; las escrituras llevan `Origin`):

```bash
curl -fsS -b COOKIE "http://HOST:8088/api/devices/ID/apikey"
curl -fsS -b COOKIE -H "Origin: http://HOST:8088" -X POST "http://HOST:8088/api/devices/ID/apikey"
curl -fsS -b COOKIE -H "Origin: http://HOST:8088" -X DELETE "http://HOST:8088/api/devices/ID/apikey"
```

La key **identifica al dispositivo**: `?device=` pasa a ser opcional en sus endpoints y, si se pasa (id o nombre) y no es el de la key, `403` `err.apikey.device_mismatch` (también con un dispositivo desconocido, para no revelar cuáles existen). El juego solo se busca entre los que incluyen ese dispositivo: uno que no lo incluye responde el mismo `404` `err.main.game_unknown` que uno inexistente.

**Ciclo de vida con la config.** La key va ligada al **id** del dispositivo, no al nombre: **renombrar un dispositivo no cambia su key**. Borrar el dispositivo o quitarle `http` borra su key (al guardar o restaurar la config y al arrancar el hub, por si se editó `config.yaml` a mano); además, una key de un dispositivo que ya no es `http` no autentica aunque su fichero siguiera en disco. Un dispositivo nuevo con el mismo id no hereda la key anterior.

### Qué key acepta cada endpoint

| Endpoint | Key de usuario (`ck_`) | Key de dispositivo (`ckd_`) |
|---|---|---|
| `GET /api/hook/ping` | sí | sí (añade `"device": "<id>"`) |
| `GET /api/hook/watches` | sí | no (`401`) |
| `POST /api/hook/{juego}/opened` | sí: sync previa y vigilancia de cierre (dispositivos SSH o «Este equipo»; con un dispositivo `http`, `400` `err.hook.device_push_only`) | sí: solo marca «jugando» en ese dispositivo (no sincroniza ni vigila; ver «`POST /api/hook/{juego}/opened`») |
| `GET /api/games` | sí: todos los juegos | sí: solo los juegos que tienen ese dispositivo, cada uno con `path` (la ruta del guardado en ese dispositivo, o `null`) y `process` (el proceso del juego, o `null`) |
| `POST /api/steam/library` | no (`401`) | sí: solo toca los juegos que tienen ese dispositivo (ver «Asociar juegos de Steam desde la Deck») |
| `POST /api/steam/games`, `PUT /api/steam/games/{juego}/enabled`, `PUT /api/steam/games/{juego}/path` | no (`401`) | sí: crear un juego de ese dispositivo, activar o desactivar uno de sus juegos y cambiar su carpeta de guardado (ver «Asociar juegos de Steam desde la Deck») |
| `POST /api/hook/{juego}/fingerprint`, `GET /manifest`, `GET`/`PUT /files`, `POST /commit`, `PUT /resolution` | no (`401`) | sí, solo en juegos que incluyen el dispositivo |
| `POST /api/hook/{juego}/closed` | no (`401`) | sí, solo en juegos que incluyen el dispositivo (limpia «jugando») |

Una clase de key no admitida es el **mismo `401`** (`err.apikey.invalid`) que una key inválida, y cuenta como fallo para el límite por IP (`429`); `403` y `404` de alcance no cuentan.

**Aviso de seguridad.** Las keys de dispositivo dan acceso de lectura y escritura a los saves de sus juegos: trátalas como contraseñas (HTTPS o VPN fuera de tu red de confianza, no las subas a repositorios) y regenera o revoca la que se filtre o del dispositivo que pierdas. La de dispositivo limita el daño: en `opened` solo marca «jugando» (no sincroniza ni vigila), no sirve para `watches` ni para otros dispositivos, y no da acceso a ajustes. Excluye `hub.secret` de las copias, como con la de usuario.

## Vinculación de dispositivos por solicitud y código

Para que el plugin de un dispositivo `http` (p. ej. la Steam Deck) se vincule con solo conocer la URL del hub, sin copiar keys a mano. **Es el único endpoint de Checkpoint que se llama sin key ni sesión previas**; por eso lleva las mitigaciones de más abajo. Se usa por API (`/api/docs`, tags «Vinculación de dispositivos») y, para aceptar o rechazar, desde la web (ver «Vincular un dispositivo http desde la web»).

Flujo:

1. **El dispositivo pide acceso** (sin key): `POST /api/pairing/requests` con `{"name": "Steam Deck", "os": "linux"}` (nombre con las reglas de los dispositivos, `os` = `linux` o `windows`). Responde `201` con `{"id", "code", "secret", "expires_in": 600}`: `code` son 6 dígitos que el dispositivo **enseña al usuario**; `secret` solo lo guarda el dispositivo.
2. **El usuario**, con sesión web, ve `GET /api/pairing/pending` (`[{"id", "name", "os", "code", "ip", "expires_in", "existing": "none"|"http"|"other"}]`) y acepta con `POST /api/pairing/pending/{id}/accept` y `{"code": "<el código que enseña el dispositivo>"}` (responde `{"id", "device", "name", "created"}`), o rechaza con `POST /api/pairing/pending/{id}/reject` (`{"id", "rejected": true}`). Un código erróneo es `400` `err.pairing.code_mismatch`; tres seguidos anulan la solicitud.
3. **El dispositivo consulta** `GET /api/pairing/requests/{id}` con la cabecera `X-Pairing-Secret: <secret>`: `{"status": "pending", "expires_in"}`, `{"status": "rejected"}` o `{"status": "accepted", "device": "<id>", "key": "ckd_..."}`. La key se entrega **una sola vez** (se genera en ese momento) y la solicitud se borra; después, `404`.

Al aceptar se crea el dispositivo `http` en `config.yaml` si no existe (por el mismo camino que `PUT /api/config`: versión base, validación completa, copia de seguridad, comentarios conservados). Si ya hay un dispositivo `http` con ese nombre (sin distinguir mayúsculas) se **reutiliza** y, al recoger, se **regenera su key** (la anterior deja de valer: quien se vincula de nuevo ha perdido la key o es otro equipo, y regenerar es lo que invalida una key filtrada; solo se regenera cuando el dispositivo recoge, no al aceptar). Si ya hay uno que **no** es `http` con ese nombre, `409` `err.pairing.device_not_http` (no se suplanta).

Mitigaciones del endpoint público:

- **Límites por IP:** 5 solicitudes por 10 min y 3 pendientes a la vez (`429`); **10 pendientes en todo el hub** (`503`). Los fallos de secreto en la consulta cuentan para un bloqueo por IP (3 gratis, luego 5 s, 10 s... hasta 15 min; contador propio, no bloquea el login ni las keys).
- **Caducidad de 10 min** y solo **en memoria** (reiniciar el hub borra las pendientes; el plugin vuelve a pedir; una purga periódica del scheduler limpia las caducadas).
- **Aleatorios criptográficos** (`secrets`): código de 6 dígitos, id y secreto de 32 bytes; el secreto se guarda solo como hash y se compara en tiempo constante. **El código no recoge la key**, solo el secreto.
- **El secreto nunca va en la URL**, sino en la cabecera `X-Pairing-Secret`: las URL acaban en logs de accesos, de proxies inversos y en el historial; una cabecera no.
- **404 uniforme:** id desconocido, solicitud caducada o ya entregada, secreto ausente o erróneo dan la misma respuesta (`err.pairing.request_unknown`): no se revela si una solicitud existe.
- Listar, aceptar y rechazar exigen sesión (cookie y, al escribir, `Origin`). Respuestas con `Cache-Control: no-store`. Ningún log ni error incluye secretos, keys ni códigos. Cuerpo máximo de 2048 bytes.
- **Límite conocido:** quien pueda llegar al hub puede ocupar las 10 plazas pendientes durante 10 min (denegación de vinculación, no acceso). Compara siempre el código y el nombre; rechaza lo que no reconozcas.

## Asociar juegos de Steam desde la Deck

El plugin de la Deck envía al hub la lista de juegos de Steam que tiene instalados, para no escribir el `steam_appid` a mano. El hub lo compara con **los juegos activos que tienen ese dispositivo** y solo escribe el appid cuando está seguro; lo dudoso queda como sugerencia para que decidas tú.

`POST /api/steam/library` con key de **dispositivo** (`ckd_`; una `ck_`, la sesión o nada es el mismo `401`, y los fallos cuentan para el `429` por IP). Cuerpo (máx. 5000 entradas y 1 MiB; nada más en el objeto ni en cada entrada, o `422` `err.steam.body_invalid`/`err.steam.entry_invalid`; `413` `err.steam.too_many_games`/`err.steam.body_too_large`):

```json
{"games": [{"appid": 1145360, "name": "Hades"}, {"appid": 292030, "name": "The Witcher® 3: Wild Hunt"}]}
```

Respuesta (solo habla de los juegos de ese dispositivo; cada entrada cuenta en una sola casilla, y los `appid` repetidos en la lista cuentan una vez):

```json
{"associated": [{"appid": 1145360, "game": "hades"}], "suggested": 1, "unchanged": 0, "ignored": 0}
```

**Crear y activar desde la Deck.** Con la misma key, el plugin puede configurar un juego instalado que el hub aún no tiene y activar o desactivar los que ya tiene:

- `POST /api/steam/games` con `{"appid": 504230, "name": "Celeste", "path": "/home/deck/.local/share/Celeste/Saves"}` (nada más; máx. 8192 bytes). Crea el juego **solo con ese dispositivo**, activo y con ese `steam_appid`; el id lo genera el hub a partir del nombre y la plataforma sale del dispositivo. Mismas validaciones que la config: nombre y ruta válidos, nombre y appid únicos. Respuesta `{"id", "name", "appid", "path"}`. **Unión automática:** si el hub ya tiene UN juego con ese nombre (comparación normalizada, la de la asociación por nombre), con hueco (menos de 2 dispositivos), sin este dispositivo, sin que otro juego use ese appid, no crea otro (si tiene otro `steam_appid` general, el de este dispositivo se guarda en `steam_appids[dispositivo]` sin tocar el general ni otros dispositivos; si no tenía, se le pone el general): añade el dispositivo de la key (y su ruta, validada igual) al existente y responde `200` con `{"id", "name", "appid", "path", "joined": true, "devices", "enabled"}` (un juego desactivado se une pero sigue desactivado). Si el dispositivo ya estaba en el juego con ese appid, es idempotente: `joined: false` y nada cambia. Una key solo puede añadirse a sí misma: nunca quita ni cambia otros dispositivos ni rutas. Un valor no válido es `422 err.steam.game_invalid` con `params: {field: "name"|"path"|"appid"|"game", reason: "err.config.…"}` (solo el campo y la causa, nunca datos de otros juegos). Si no se puede unir, el nombre repetido es `422` con `field: "name"` y `reason`: `err.steam.no_free_slot` (ya tiene 2 dispositivos), `err.steam.appid_in_use` (otro juego usa ese appid) o `err.config.name_duplicate` (genérico: dispositivo ya dentro con otro appid, o varios juegos con ese nombre).
- `PUT /api/steam/games/{juego}/enabled` con `{"enabled": false}`. Pone el campo `enabled` del juego, que **vale para todo el hub**: un juego desactivado no se sincroniza por ninguna vía en ningún dispositivo. Solo juegos que tienen ese dispositivo (otro, o inexistente: `404 err.steam.game_unknown`).
- `PUT /api/steam/games/{juego}/path` con `{"path": "/home/deck/otra/carpeta"}` (nada más; texto de hasta 1024 caracteres; cuerpo máx. 8192 bytes, si no `413`/`422 err.steam.game_body_invalid`). Cambia la carpeta de guardado de **este dispositivo** en un juego que ya la tiene (solo `paths[dispositivo]`: no toca la ruta de otros dispositivos, no mueve ni borra ficheros y no cambia la huella del hub ni sus versiones). Respuesta `{"game", "path"}` con la ruta normalizada. Solo juegos que tienen ese dispositivo (otro, o inexistente: `404 err.steam.game_unknown`). La ruta se valida como en la config: una no válida es `422 err.steam.game_invalid` con `params: {field: "path", reason: "err.config.…"}`. Si es la misma que la actual (ya normalizada), responde `200` sin escribir ni soltar nada. Al cambiarla, y bajo el lock del juego, el hub olvida la línea base de ese dispositivo y juego y su conflicto y resolución pendientes (los de otros dispositivos y la huella del hub no se tocan), de modo que una carpeta nueva con otra partida dé conflicto en la siguiente sincronización en vez de subirse sin aviso; la sincronización la lanza quien llama, el hub no cambia el estado del juego. Vale con el juego desactivado. Con una ejecución del juego en curso o el lock del juego tomado: `409 err.main.run_in_progress` y no cambia nada (`409 err.main.config_changed` si `config.yaml` cambia sin parar durante el guardado). «Deshacer» es la misma llamada con la ruta anterior.

**Reglas de coincidencia.** Los nombres se **normalizan** antes de compararse: minúsculas, sin tildes, sin `™ ® ©`, `&` = `and` y cualquier signo o espacio repetido reducido a un espacio (`The Witcher® 3: Wild Hunt` = `the witcher 3 wild hunt`).

- **Asociación automática** (escribe `steam_appid` por `ConfigStore.save`: versión base, validación completa y copia de seguridad, como `PUT /api/config`; si el fichero cambia a mitad reintenta 3 veces y si no `409` `err.main.config_changed`). Solo si se cumplen **todas**: el juego está activo y tiene ese dispositivo, **no tiene appid**, hay **exactamente una** entrada de Steam con su mismo nombre normalizado, **ningún otro juego del hub** tiene ese mismo nombre normalizado (ni activo ni no, ni de otro dispositivo) y el appid no lo usa otro juego. Un appid es dato del juego: se fija una vez y los demás dispositivos del juego lo reutilizan sin cambios.
- **Appid por dispositivo.** Un atajo que no es de Steam tiene un appid distinto en cada dispositivo, así que el juego puede llevar `steam_appids` (`{dispositivo: appid}`) además del `steam_appid` general. Para el dispositivo D de la key: si el juego ya tiene `steam_appids[D]`, el mismo appid es `unchanged` y uno distinto no se toca ni se sugiere. Si no tiene entrada de D: un general igual al de Steam es `unchanged`; un general **distinto** con coincidencia exacta de nombre normalizado, única entre los juegos activos de D, escribe solo `steam_appids[D]` (el general y los otros dispositivos no se tocan); sin general ni entrada, se escribe `steam_appid` como siempre. Nunca se asigna un appid que ya sea el efectivo de otro juego en D. Las sugerencias de un juego que ya tiene general se aceptan también por dispositivo (`steam_appids[D]`).
- **Nunca se pisa un appid existente.** Si el juego ya tiene el mismo appid, no se hace nada (`unchanged`); si tiene otro, no se toca ni se sugiere (salvo añadir la entrada de D cuando solo existe el general, como arriba).
- **Sugerencia** (nunca asociación automática): mismo nombre normalizado pero ambiguo (dos juegos del hub, o dos entradas de Steam con ese nombre), o nombre **parecido** (`difflib.SequenceMatcher.ratio() >= 0,85` sobre los nombres normalizados; la entrada no se compara si ya coincide exactamente con algún juego; `Hades` y `Hades II` no llegan al umbral, `The Witcher 3 Wild Hunt` y `... GOTY` sí). No se sugiere un appid que ya usa otro juego ni a un juego que ya tiene appid.
- **Ignorado:** juegos de otro dispositivo, juegos desactivados, nombres sin coincidencia y lo descartado.

**Sugerencias y descartes.** Las sugerencias viven solo en memoria (caducan a las 24 h, máx. 50 en el hub y 25 por dispositivo; la Deck reenvía su lista al abrir; las limpia el mantenimiento periódico del scheduler). En **Configuración → Biblioteca**, arriba de **Dispositivos** y junto a las solicitudes de vinculación, aparece el bloque **Sugerencias de Steam** (solo si hay sugerencias o descartes): cada una muestra el nombre de Steam, el id, el juego propuesto y quién la envió, con **Aceptar** (escribe el appid; con el borrador limpio la pantalla se recarga sola, con **cambios sin guardar** no toca tu borrador y avisa; si la configuración cambia a mitad, vuelve a pulsar **Aceptar**) y **Descartar**. Un descarte guarda el par appid + juego en `data/state/_steam/dismissed.json` (sin secretos, escritura atómica, máx. 1000) y no se vuelve a proponer; el bloque lo lista, plegado, con **Olvidar**. Aceptar da `409` `err.steam.game_has_appid` o `err.steam.appid_in_use` si entre tanto el juego ya tiene appid o el appid se usa en otro, y `404` `err.steam.suggestion_unknown`/`err.steam.game_unknown` si ya no existen.

API de sesión (cookie y `Origin` en las escrituras, `Cache-Control: no-store`; una key no vale): `GET /api/steam/suggestions`, `POST /api/steam/suggestions/{id}/accept`, `POST /api/steam/suggestions/{id}/dismiss`, `GET /api/steam/dismissed`, `DELETE /api/steam/dismissed/{id}`. Documentadas en `/api/docs`.

**Aviso de seguridad.** La clave de dispositivo puede **fijar el appid de SUS juegos que aún no tienen appid efectivo propio** (los de ese dispositivo, activos y con coincidencia exacta y única; si el juego solo tenía el general, se añade el suyo en `steam_appids`), y nada más: no pisa appids, no toca juegos de otros dispositivos ni desactivados, no cambia ningún otro ajuste y no ve ni recibe datos de otros juegos. Un dispositivo comprometido podría asignar un appid equivocado a uno de esos juegos; se corrige en Configuración. Regenera o revoca la clave que se filtre.

## Documentación de la API (OpenAPI)

La API que usa la API key (la de usuario y la de dispositivo `http`: `/api/hook/*` y `GET /api/games`) se documenta con OpenAPI y se puede probar desde el navegador con Swagger UI:

- **Abrir:** enlace «Documentación de la API» en el menú del perfil, bajo «API key» (`/api/docs`, pestaña nueva). El esquema está en `/api/openapi.json`.
- **Solo con sesión:** `/api/docs`, `/api/openapi.json` y los ficheros de Swagger UI exigen la sesión de la web; sin ella responden `401` como el resto de rutas protegidas. La API key sola no abre la documentación.
- **Alcance:** solo las rutas de la API key (tag «Avisos del lanzador» las de `/api/hook/*` y «Juegos» la de `/api/games`), la vinculación y la asociación de Steam (tags «Steam (key de dispositivo)» y «Steam (sesión)»); cada operación indica qué clase de key acepta («solo `ck_`», «solo `ckd_`» o «`ck_` o `ckd_`»). En «Authorize» hay un único esquema Bearer (`bearerAuth`) donde se pega la key de usuario (`ck_...`) o la de dispositivo (`ckd_...`; el hub las distingue por el prefijo); el secreto de vinculación (`X-Pairing-Secret`) y la sesión (cookie) son esquemas aparte. El resto de `/api/*` (login, perfil, configuración, sincronización, versiones...) es interno de la web, no está en el esquema y puede cambiar sin aviso.
- **Probar:** pulsa «Authorize», pega tu API key (sin el prefijo `Bearer`; hay un campo por clase de key) y usa «Try it out». Ojo: `POST .../opened` con una key de usuario (`ck_`) **ejecuta de verdad** una sincronización previa y arma el vigilante de cierre del juego; con una de dispositivo (`ckd_`) solo marca el juego como «jugando».
- **Sin internet:** Swagger UI va empaquetada en la imagen (`swagger-ui-dist`, versión fijada en `frontend/package.json`; el build de Vite la copia a `docs-assets/` y el backend la sirve en `/api/docs-assets/`). No se carga nada de CDNs ni de terceros.
- **Idioma:** los textos de la documentación están en español; los códigos `err.*` van sin traducir.
- **Mantenimiento:** toda ruta `/api/*` nueva queda fuera del esquema por defecto; para publicarla hay que ponerle un tag público (`TAG` o `GAMES_TAG` en `backend/app/api/docs/install.py`). `backend/tests/test_apidocs.py` falla si el esquema deja de tener exactamente las rutas de la API key.

## Descargar el plugin de Steam Deck

El hub sirve el zip del plugin de Decky (`Checkpoint.zip`) sin sesión ni key, solo lectura: `GET /api/deck/plugin` (zip, con la suma en la cabecera `X-Checkpoint-Plugin-Sha256`), `GET /api/deck/plugin.sha256` (para `sha256sum -c`) y `GET /api/deck/plugin/info` (`available`, `version`, `protocol`, `sha256`, `size`, `filename`; `protocol` es el `checkpointProtocol` del plugin o `null`). La web lo ofrece en **Configuración → Lanzadores** (abajo del todo) con el botón **Descargar plugin**, la versión y el tamaño; la suma SHA-256 sigue disponible por API. La imagen Docker construye el zip en la etapa `deck`; en modo nativo hay que generarlo antes con `pnpm run zip` en `checkpoint-deck/`. Sin zip, `plugin` y `plugin.sha256` responden `404` `err.deck.plugin_missing` e `info` responde `200` con `{"available": false}`. El plugin sincroniza solo al abrir y cerrar cada juego asociado (versión propia semver y protocolo de compatibilidad; ver `checkpoint-deck/README.md`). **Instalación y actualización solo por URL de Decky**: en la Deck, «Ajustes > Desarrollador > Instalar plugin desde URL» y pega `<hub>/api/deck/plugin` (el plugin ofrece «Copiar dirección»; la suma SHA-256 está en `<hub>/api/deck/plugin.sha256`). El plugin no se actualiza con un botón del hub: para actualizarlo se vuelve a instalar desde esa URL. También vale «Instalar plugin desde ZIP» con el zip descargado.

## Vincular un dispositivo http desde la web

Cómo se vincula una Steam Deck (o cualquier dispositivo con el plugin):

1. En el dispositivo, abre el plugin, escribe la URL del hub y pide acceso. El plugin muestra un **código de 6 dígitos**.
2. En Checkpoint, ve a **Configuración → Biblioteca**. Arriba de la lista de **Dispositivos** aparece el bloque **Solicitudes de vinculación** (solo si hay alguna pendiente; se actualiza solo cada 5 segundos mientras la pestaña está a la vista). Cada solicitud muestra el nombre, el código, la dirección desde la que llega y el tiempo que le queda (caduca a los 10 minutos).
3. **Comprueba que el código es el que muestra tu dispositivo** y pulsa **Aceptar** (un solo clic: la web envía ella misma el código; no hay que teclearlo). **Rechazar** la descarta. Si ya existe un dispositivo http con ese nombre se reutiliza y se regenera su clave; si existe uno con ese nombre que no es http, solo se puede rechazar.
4. El dispositivo nuevo aparece en la lista de dispositivos y recoge su clave él solo. Aceptar escribe `config.yaml` en el servidor: con el borrador limpio la lista se recarga sola; con **cambios sin guardar** la web no toca tu borrador y avisa (guarda o descarta tus cambios para ver el dispositivo; si al guardar avisa de que la configuración cambió, recarga y repite). Si la configuración cambia justo mientras se acepta, sale un aviso y basta con volver a pulsar **Aceptar**.

No se pueden crear dispositivos http a mano: **Añadir dispositivo** crea solo dispositivos SSH o «Este equipo». La tarjeta de un dispositivo http lleva la etiqueta **Plugin**, no muestra host, puerto, usuario ni **Probar conexión**, enseña el sistema operativo en solo lectura y deja editar el nombre; **Eliminar** también borra su clave. No se muestra «último contacto» ni estado de conexión: el hub no los guarda.

En la misma tarjeta, el bloque **Clave del dispositivo** indica si **tiene clave** o no, y permite **Ver** (la clave no se muestra hasta pulsarlo), **Copiar**, **Regenerar** (la clave anterior deja de valer y hay que ponerla de nuevo en el dispositivo; pide confirmación) y **Revocar** (pide confirmación). Con cambios sin guardar en esa tarjeta las acciones de clave quedan bloqueadas.

## Hooks

Rutas `/api/hook/*` para que un lanzador avise al hub con la API key de usuario (ver «API key de usuario») o, en las de los dispositivos `http` (y en `opened`, que con ella solo marca «jugando»), con la del dispositivo (ver «API key de dispositivo `http`»). Hoy: el aviso de apertura (que además arma el **cierre automático**), la comparación de saves de un dispositivo `http` (`fingerprint`) y su subida y bajada fichero a fichero (`manifest`, `files`, `commit`), la consulta de vigilancias y, con la misma key, la lista de juegos (`GET /api/games`). Con la key de dispositivo, cada juego incluye `path`: la «Ruta del save en <dispositivo>» configurada en el hub para ese dispositivo (cadena tal cual, o `null` si no tiene; nunca las rutas de otros dispositivos) y `process`: el proceso del juego configurado en el hub (cadena, o `null` si no tiene; sirve a un cliente sin SSH para saber qué vigilar); con la de usuario no hay `path` ni `process`.

### `POST /api/hook/{juego}/opened?device=<dispositivo>`

Se llama justo antes de arrancar el juego. El hub hace una **sincronización previa y bloqueante** de ese juego: si tiene un save más nuevo, lo copia al dispositivo antes de que el juego arranque; si no toca, termina sin copiar. Usa **siempre** la política de conflictos `skip`, ignorando la del juego y el ajuste global de la sincronización automática: ante un conflicto **no se toca nada**, la respuesta lo indica y queda en el historial; nunca se pregunta ni se resuelve solo.

- **Autenticación:** `Authorization: Bearer ck_...` (nada de cookie). Con la key de dispositivo `ckd_` el comportamiento es otro, el de «Con key de dispositivo (`ckd_`)» más abajo.
- **Juego:** id o nombre, como `POST /api/sync/{juego}`.
- **Dispositivo (`?device=`):** id o nombre. Se valida que pertenezca al juego; es el dispositivo donde se vigila el proceso del juego (ver [`guide.md`](guide.md#cierre-automático)). Es obligatorio si el juego está en más de un dispositivo; si el juego tiene uno solo, se deduce y puede omitirse.
- **Respuesta `200`:** `{"ok": bool, "outcome": "...", "game": "<id>", "device": "<id>", "run_id": "...", "code": "err.sync....", "params": {...}}`. `outcome` es `ok`, `conflict`, `aborted` (dispositivo sin conexión, proceso del juego abierto...), `skipped` (juego de un dispositivo con la partida local ausente: `err.sync.local_missing_manual_required`), `partial`, `error` o `timeout`. Un juego **desactivado** responde `outcome: skipped` con `code: err.sync.game_disabled` (ver [`guide.md`](guide.md#desactivar-un-juego)). `ok` es `true` solo con `outcome: ok`. `code`/`params` detallan qué pasó (p. ej. `err.sync.done`, `err.sync.already_synced`, `err.sync.conflict`). Un fallo de la sincronización **no** es un 5xx y no se reintenta: el cron de la sincronización automática sigue como red de seguridad. `timeout`: la sincronización superó los 55 s del servidor; sigue ejecutándose en segundo plano y deja su entrada en el historial al acabar.
- **Errores:** `401` `err.apikey.invalid` (sin key, inválida, revocada o cookie de sesión; se comprueba antes que nada, así que no revela si el juego existe), `404` `err.main.game_unknown` o `err.hook.device_unknown`, `400` `err.hook.device_required` (falta `?device=` y es ambiguo) o `err.hook.device_ambiguous`, `409` `err.main.run_in_progress` (ya hay una ejecución de ese juego: cron, manual u otro aviso), `429` tras varios fallos de key seguidos desde una IP.
- **Historial:** la ejecución aparece en el registro de la sincronización automática con el disparador «Aviso del juego» (`trigger: "hook"`).
- **`watching`:** la respuesta añade `watching: true` si se armó la vigilancia de cierre, o `watching: false` con `watch_reason: "no_process"` si el juego no tiene `process`, o `"disabled"` si el juego está desactivado (en ese caso no se sincroniza ni se vigila, y se deja una entrada `skipped` en el historial con disparador «Aviso del juego»; los `400`/`404` no cambian y se comprueban antes). Se arma con cualquier `200` (también `conflict`, `aborted` o `timeout`), nunca con `400`/`401`/`404`/`409`.

```bash
curl -fsS -m 60 -X POST -H "Authorization: Bearer ck_..." "http://HOST:8088/api/hook/MiJuego/opened?device=MiPC"
```

Pon la URL **entre comillas**: el `?` lo interpretaría el shell como comodín.

**Con key de dispositivo (`ckd_`)**, para un dispositivo `http` (p. ej. la Deck): el hub **no sincroniza ni vigila** (el dispositivo ya sincronizó él) y solo marca el juego como «jugando» en ese dispositivo, en memoria y con caducidad de 12 h (`HOOK_PLAYING_TTL`, constante de `settings.py`, no una variable de entorno); un `closed` lo limpia. Deja una entrada `hook_opened` en el historial. `?device=` es opcional (si se pasa y no es el de la key, `403` `err.apikey.device_mismatch`).

- **Cuerpo opcional:** `{"result": {"state": "...", "code": "..."}}` con el resultado de la sync local del plugin. `state` es obligatorio y uno de `uploaded`, `downloaded`, `up_to_date`, `missing_dir`, `no_path`, `conflict`, `error`; `code` es opcional (motivo de un error, de una lista cerrada; uno desconocido se descarta). Máx. 1 KiB; un cuerpo mayor, con campos no previstos, un `state` fuera de la lista o tipos incorrectos da `400` `err.hook.result_invalid`. Sin cuerpo, no JSON o sin `result`, no cambia nada. El resultado queda en el historial como `hook.sync.<estado>` (sin rutas ni nombres de fichero).
- **Respuesta `200`:** `{"game": "<id>", "device": "<id>", "recorded": true, "outcome": "ok", "playing": true, "expires": "<UTC ISO 8601>"}`. Un juego **desactivado** responde `{"game", "device", "recorded": true, "outcome": "skipped", "code": "err.sync.game_disabled", "params": {}}` y no queda «jugando».
- **Errores:** los de siempre (`401`/`429`, `404` `err.main.game_unknown` si el juego no incluye el dispositivo, `400` `err.hook.device_required` o `err.hook.device_ambiguous` si hace falta `?device=`), más `400` `err.hook.result_invalid`.
- Con la key de **usuario** (`ck_`) y un dispositivo `http`, `400` `err.hook.device_push_only`.

```bash
curl -fsS -m 10 -X POST -H "Authorization: Bearer ckd_..." -H "Content-Type: application/json" \
  -d '{"result": {"state": "up_to_date"}}' "http://HOST:8088/api/hook/MiJuego/opened"
```

### Dispositivos `http` (sin SSH)

Un dispositivo con `http: true` no lleva `host`, `user` ni `port` (ni `local`; son excluyentes, `os` sigue siendo obligatorio) y funciona también en Docker: el hub **nunca lo contacta**, es el dispositivo quien llama a la API con **su propia key** (`ckd_...`, ver «API key de dispositivo `http`»), que ya lo identifica (`?device=` es opcional). Queda fuera de la sincronización clásica (manual y automática), del aviso `opened` con key de usuario (`400` `err.hook.device_push_only`; con su propia key `ckd_` `opened` solo marca «jugando») y de la vigilancia de cierre; en un juego con un dispositivo `http` y otro SSH o local, la sync clásica solo trata al segundo. Un juego con solo dispositivos `http` no entra en la sync automática y una sync manual responde `err.sync.push_only`. «Probar conexión» con un dispositivo `http` no intenta SSH: responde `err.transport.push_only`.

**En la pestaña Sincronizar**, un juego cuyos dispositivos son todos `http` no muestra «Sincronizar» ni «Simulación (dry-run)»: dice «Se sincroniza desde el propio dispositivo» y conserva la barra verde «Jugando en <dispositivo>» (de `opened` con `ckd_`). Muestra el bloque «Última sync» (hora, fecha y «Detalle») con el último resultado que mandó el plugin (`results` de `GET /api/watches`) y una insignia derivada de él (subido, bajado o sin cambios = «OK»; «Conflicto»; «Error»; carpeta inexistente o sin ruta = aviso amarillo; sin resultado, sin insignia). Ante un conflicto de datos, la tarjeta ofrece «Usar los datos del hub» o «Usar los de <dispositivo>» (con confirmación) y, con una resolución ya pedida, «Resolución pendiente» con «Cancelar resolución». Un juego mixto (clásicos + http) mantiene el botón; `POST /api/sync/{juego}` sigue dando `err.sync.push_only` en los juegos solo http.

```yaml
devices:
  deck-1a2b3c4d: {name: "Steam Deck", http: true, os: linux}   # sin host, user ni port
```

#### `POST /api/hook/{juego}/fingerprint?device=<dispositivo>`

El dispositivo envía el manifiesto de su carpeta de saves y el hub responde qué debe hacer, comparándolo con su copia (`data/hub/<juego>`) y con la línea base de la última sync, con la misma lógica que la sync clásica (nunca decide por fecha; un lado vacío no gana a uno con datos). **Única escritura**: con `action: none` (`reason: same`, huella igual a la del hub y no vacía) fija la línea base del dispositivo y del hub, verificada contra el manifiesto real, con el lock del juego (ocupado: `409` `err.main.run_in_progress`) y sin reescribirla si ya es esa. Con el lock tomado vuelve a comprobar que el hub sigue teniendo esa huella: si un `commit` lo cambió entre medias, **no escribe la línea base** (la respuesta sigue siendo `none`; el siguiente `fingerprint` decidirá con el hub nuevo); con `upload` o `download` no escribe nada ni toma el lock; con `conflict` **registra el conflicto** (ver «Conflicto y resolución» más abajo) y toma el lock del juego (ocupado: `409` `err.main.run_in_progress`). Nunca toca ficheros ni historial.

Parámetro opcional `?manifest=1` (aditivo): con `action: download`, la respuesta incluye además `hub_manifest` (`[{path, sha256, size, mtime}]`, la misma forma que `GET /manifest`), calculado de la misma lectura del hub que la decisión (sin segunda pasada ni carrera). Sin el parámetro, o con otra acción, la respuesta no cambia; `GET /manifest` sigue igual.

**Conflicto y resolución.** Cuando `fingerprint` da `conflict`, el hub **registra** el conflicto de ese juego y dispositivo (`data/resolutions/<juego>.json`: motivo, huellas de los dos lados y hora; sin rutas ni nombres de fichero), con el lock del juego (ocupado: `409`). La web lo ve en `GET /api/watches` (`conflicts`, `resolutions`) y puede resolverlo; el propio dispositivo, con `PUT /api/hook/{juego}/resolution`. Un hub antiguo no tiene estas rutas y sigue dando `conflict`.

#### `PUT /api/hook/{juego}/resolution?device=<dispositivo>`

Key de dispositivo (`ckd_`); `?device=` opcional y, si se pasa, debe ser el de la key (`403`). Cuerpo (máx. 2 KiB, solo estos campos): `{"winner": "hub"|"device", "expect": {"hub": "<hub.hash>", "device": "<device_state.hash>"}}` con las huellas del `fingerprint` en conflicto (sha256 hexadecimal en minúsculas o `null` si ese lado estaba vacío); `device` también puede ir en el cuerpo (debe ser el de la key). Respuesta `200`: `{"game", "device", "winner", "by": "device", "expires"}`. Errores: `400` cuerpo no JSON o de más de 2 KiB, `422 err.resolution.invalid` (ganador fuera de la lista, `expect` mal formado o campos de más), `409 err.resolution.no_conflict` (no hay conflicto registrado), `409 err.resolution.stale` (las huellas ya no son las del conflicto: vuelve a comparar), `409 err.resolution.side_empty` (el lado ganador no tiene datos), `409 err.main.run_in_progress`, `409 err.sync.game_disabled`, `404 err.main.game_unknown`. No cambia ficheros: deja una **resolución pendiente** (caduca a las 24 h, `settings.HOOK_RESOLUTION_TTL`) que aplica el siguiente `fingerprint`: si las huellas siguen siendo las de `expect`, devuelve `upload` (`winner: device`) o `download` (`winner: hub`) con `reason: resolution`; si no, `conflict` con `reason: resolution_stale` y la descarta. Con `upload`, `commit` acepta la subida (el hub actual se guarda antes como versión) solo con esa resolución vigente y las mismas huellas (si no, `409 err.hook.commit_rejected`). Al terminar (`commit` o `fingerprint` con `none`) el conflicto y la resolución se borran. 
**Rutas de sesión (las usa la web; cookie y `Origin` en las escrituras).** `PUT /api/sync/{juego}/resolution`: cuerpo `{"device": "<id o nombre>", "winner": "hub"|"device", "expect": {"hub", "device"}}` (máx. 2 KiB, solo esos campos; `device` es obligatorio aquí). Respuesta `200`: `{"game", "device", "winner", "by": "web", "expires"}`. Errores: `400` `err.resolution.invalid` (cuerpo de más de 2 KiB) o `err.main.json_body_required` (no es un objeto JSON), `422 err.resolution.invalid` (ganador, `expect` o campos mal formados), `409 err.resolution.no_conflict`, `err.resolution.stale`, `err.resolution.side_empty`, `err.main.run_in_progress` o `err.sync.game_disabled`, `404 err.main.game_unknown` o `err.hook.device_unknown`, y `400` `err.hook.device_not_http` si el dispositivo no es `http`. `DELETE /api/sync/{juego}/resolution?device=<dispositivo>` cancela la resolución pendiente (el conflicto registrado se conserva) y responde `200` `{"game", "device", "cancelled": true|false}` (`cancelled` = si había alguna). El dispositivo la aplica en su próxima sincronización (al abrir o cerrar el juego, o desde su plugin).

Petición (`Content-Type: application/json`): lista de ficheros, máximo 50 000; `path` relativa con `/` (se rechazan `..`, las rutas absolutas, el carácter NUL, las vacías y las repetidas; cualquier otro carácter vale: `'`, `&`, `:` o espacios, para que el save pueda igualar al del hub), `sha256` hexadecimal de 64, `size` en bytes y `mtime` en segundos Unix; `[]` es una carpeta vacía.

```json
[{"path": "slot1/save.dat", "sha256": "9f86d0...0a08", "size": 10240, "mtime": 1768501812}]
```

Respuesta `200`:

```json
{"game": "g1", "device": "deck", "action": "upload", "reason": null,
 "hub": {"hash": "…", "files": 2, "size": 20480, "mtime": 1768501000},
 "device_state": {"hash": "…", "files": 2, "size": 20480, "mtime": 1768501812}}
```

`action`: `upload` (manda el dispositivo), `download` (manda el hub), `none` (iguales, `reason: "same"`) o `conflict` (`reason`: `both-changed`, `no-baseline` o `inconsistent`; no se hace nada).

- **Errores:** `401`/`429` como el resto (la key de usuario es un `401`); `403` `err.apikey.device_mismatch` (`?device=` distinto del de la key); `404` `err.main.game_unknown` (juego inexistente o que no incluye el dispositivo); `400` `err.main.json_body_required` (el cuerpo no es una lista JSON); `409` `err.main.run_in_progress` (ejecución del juego en curso) o `err.sync.game_disabled`; `422` `err.hook.manifest_path_invalid`, `err.hook.manifest_sha_invalid`, `err.hook.manifest_duplicate`, `err.hook.manifest_invalid` o `err.hook.manifest_too_large`.

```bash
curl -fsS -X POST -H "Authorization: Bearer ckd_..." -H "Content-Type: application/json" \
  -d '[{"path": "slot1/save.dat", "sha256": "9f86d0...0a08", "size": 10240, "mtime": 1768501812}]' \
  "http://HOST:8088/api/hook/MiJuego/fingerprint?device=Steam%20Deck"
# con el listado del hub si la acción es download:
curl -fsS -X POST -H "Authorization: Bearer ckd_..." -H "Content-Type: application/json" \
  -d '[{"path": "slot1/save.dat", "sha256": "9f86d0...0a08", "size": 10240, "mtime": 1768501812}]' \
  "http://HOST:8088/api/hook/MiJuego/fingerprint?device=Steam%20Deck&manifest=1"
```

#### `POST /api/hook/{juego}/closed?device=<dispositivo>`

El dispositivo `http` avisa de que cerró el juego (el hub no puede sondear su proceso por SSH). **Limpia su «jugando»** (el de `opened` con `ckd_`) y deja constancia en el historial (disparador `hook_closed`, con el dispositivo); devuelve el estado: no hay pull ni push ni sync clásica; el dispositivo hará después `fingerprint` y subirá o bajará por su cuenta. Cuerpo opcional `{"result": {"state", "code"?}}` con el resultado de la sync local, con los mismos valores y límites que en `opened` (máx. 1 KiB, `400` `err.hook.result_invalid` si no es válido; sin cuerpo no cambia nada).

Respuesta `200`:

```json
{"game": "g1", "device": "deck", "recorded": true, "outcome": "ok"}
```

Un juego **desactivado** responde `200` con `outcome: "skipped"`, `code: "err.sync.game_disabled"` y `params: {}` (queda `skipped` en el historial, como en `opened`).

- **Errores:** `401`/`429` como el resto (la key de usuario es un `401`); `400` `err.hook.result_invalid`; `403` `err.apikey.device_mismatch`; `404` `err.main.game_unknown` (juego inexistente o que no incluye el dispositivo); `409` `err.main.run_in_progress` (ejecución del juego en curso; el cierre queda `skipped` con `err.hook.busy`).

```bash
curl -fsS -m 10 -X POST -H "Authorization: Bearer ckd_..." "http://HOST:8088/api/hook/MiJuego/closed?device=Steam%20Deck"
```

#### Subida y bajada de saves (dispositivos `http`)

Tras `fingerprint`, el dispositivo sube o baja sus saves **fichero a fichero** (reanudable, con sha256 de cada fichero y del conjunto). Todas llevan `Authorization: Bearer ckd_...` (key del dispositivo; `401`/`429` como el resto; `?device=` opcional, `403` `err.apikey.device_mismatch` si no es el de la key; juego que no incluye el dispositivo, `404` `err.main.game_unknown`) y el id o nombre del juego. Política de conflicto: siempre `skip` (nunca se sobrescribe al perdedor de un conflicto).

**Rutas.** La `path` de los ficheros se normaliza (`\` pasa a `/`) y se **revalida cada vez** contra el directorio donde se lee o escribe (staging o hub): se rechazan `..`, las rutas absolutas, NUL, vacías, los enlaces simbólicos (nunca se siguen) y cualquier ruta que acabe fuera (`400` `err.hook.file_path_invalid`). El manifiesto acepta caracteres raros (`C:/x`, `a;b`, `'`), pero como ruta relativa dentro de esa carpeta, nada más.

**Bloqueo y límites.** `PUT files` **no toma el lock del juego**: una subida lenta no bloquea la sync clásica. Al entrar solo comprueba que no haya una ejecución del juego en curso (`409` `err.main.run_in_progress`) y reserva ese fichero del dispositivo (otro `PUT` simultáneo al mismo fichero: `409` `err.hook.upload_busy`; el staging es de cada juego y dispositivo). El resto (`commit`, `manifest`, `GET files`, y `fingerprint` al fijar la línea base) toma el lock del juego (el de la sync) mientras dura, sin esperar: ocupado, `409` `err.main.run_in_progress` (reintenta luego). El `commit` reserva además todo el staging de ese dispositivo (después del lock del juego, siempre en ese orden, y sin esperar: no hay interbloqueo) mientras verifica `tree/` y lo copia al hub, para que un `PUT` concurrente del mismo dispositivo no pueda cambiar un fichero entre la verificación y la escritura (el hub quedaría distinto del hash guardado en la línea base). Decisión: no espera, responde `409` `err.hook.upload_busy` en ambos sentidos y sin tocar nada: un `PUT files` que llegue durante el commit, o un `commit` que llegue con un `PUT` del mismo dispositivo aún en curso (que no se corta). Reintenta después. Tras un `409` el staging queda intacto (la purga recoge lo que no se reintente); si el commit termina bien, se borra entero, incluidos los restos que no estaban en el manifiesto. Los `PUT` de otros dispositivos no se ven afectados. Un juego desactivado da `409` `err.sync.game_disabled`. No hay sesiones ni tokens: la coherencia entre `fingerprint` y `commit` la da `expect`. Máximo por fichero: `CHECKPOINT_HOOK_MAX_FILE_MB` (512 MiB por defecto): `413` `err.hook.file_too_large` con `params.max_mb`; se comprueba con `size`, con `Content-Length` y mientras llega el cuerpo (`size` y `Content-Length` son falsificables y con chunked no hay `Content-Length`). La subida va en streaming a disco: nunca se carga el cuerpo en memoria. **Staging:** todo el de un juego (todos sus dispositivos) tiene un tope, `CHECKPOINT_HOOK_STAGING_MAX_MB` (2048 MiB por defecto): al superarlo, `413` `err.hook.staging_full` con `params.max_mb` (se comprueba con `size` y mientras llega el cuerpo). El staging sin escrituras en `CHECKPOINT_HOOK_STAGING_TTL_H` horas (24 por defecto) se borra solo, al arrancar, cada hora (tarea de mantenimiento del scheduler, aunque la sync automática esté apagada) y de forma oportunista al subir; nunca el de un juego con el lock tomado o una ejecución en curso.

**Flujo de subida** (`fingerprint` dio `action: upload`):

1. Por cada fichero del manifiesto: `PUT /api/hook/{juego}/files?device=..&path=slot1/save.dat&size=10240&sha256=<sha256 del fichero entero>&offset=0` con el contenido en bruto (`Content-Type: application/octet-stream`). Respuesta `200` `{"game", "device", "path", "received", "size", "complete"}`. Los ficheros van a `data/staging/<juego>/<dispositivo>/`; **`data/hub/<juego>` no se toca**. Si se corta, repite con `offset` = bytes ya recibidos; si `offset` no coincide con lo que el hub tiene (o `sha256`/`size` cambiaron), `409` `err.hook.upload_offset_mismatch` con `params.received` (continúa desde ahí, o `offset=0` para reiniciar). Al completar los `size` bytes se verifica el sha256 (`422` `err.hook.sha_mismatch`: se descarta) y `complete` pasa a `true`. Más bytes que `size`: `422` `err.hook.upload_size_mismatch`. `size`, `offset` o `sha256` mal formados: `422` `err.hook.param_invalid`.
2. `POST /api/hook/{juego}/commit?device=..` con `{"expect": "<hub.hash de fingerprint, o null si el hub estaba vacío>", "manifest": [ ...el manifiesto completo... ]}`. Con el lock del juego comprueba, en orden: el hub no cambió (`409` `err.hook.hub_changed`: repite `fingerprint`); sigue mandando el dispositivo con la misma lógica que `fingerprint` (conflicto o hub más nuevo: `409` `err.hook.commit_rejected`, `params.reason` = `both-changed`, `no-baseline`, `inconsistent` o `hub`; no se toca nada); están todos los ficheros (`422` `err.hook.upload_incomplete`, con `params.missing` y `params.paths`, hasta 10); y el conjunto da la huella del manifiesto (`422` `err.hook.set_mismatch`). Entonces: guarda el hub actual en una versión nueva (`hub`), lo **reemplaza por el manifiesto entero** (lo que el hub tuviera de más desaparece; los ficheros de staging que no estén en el manifiesto se ignoran), aplica el `mtime` del manifiesto, fija la línea base del dispositivo y del hub, poda las versiones antiguas y deja una entrada en el historial (disparador `hook`, con el dispositivo). Respuesta `200`: `{"game", "device", "outcome": "ok", "hash", "files", "size", "version"}`; `outcome: "unchanged"` (sin `version`) si el hub ya era igual. El staging del dispositivo se borra.

**Flujo de bajada** (`fingerprint` dio `action: download`):

1. `GET /api/hook/{juego}/manifest?device=..`: `{"game", "device", "hash", "files", "size", "mtime", "manifest": [{"path", "sha256", "size", "mtime"}, ...]}` (el mismo formato que el manifiesto de `fingerprint`; `hash` es el `hub.hash`). Con el lock del juego. Decisión: es un endpoint aparte (y no se reutiliza `fingerprint`) para no obligar a hashear el hub entero en cada comparación ni a enviar el listado cuando no hace falta.
2. `GET /api/hook/{juego}/files?device=..&path=slot1/save.dat` por cada fichero que difiera de lo que el dispositivo tiene: cuerpo en bruto, `Content-Length` y `Accept-Ranges: bytes`. Con `Range: bytes=a-b` (un solo rango; `a-` y `-n` valen) responde `206` con `Content-Range`; un rango inválido, múltiple o fuera del fichero, `416` `err.hook.range_invalid` con `Content-Range: bytes */tamaño`. Fichero que no existe, `404` `err.hook.file_unknown`. El lock solo se toma para abrir el fichero.
3. El dispositivo verifica el sha256 de cada fichero y la huella del conjunto contra el `hash` del manifiesto, borra lo que le sobre y vuelve a llamar a `POST /api/hook/{juego}/fingerprint` con su manifiesto: si ahora es igual al hub (`none`/`same`), el hub fija esa huella como línea base del dispositivo (sin ella, su siguiente cambio local daría un conflicto falso). No hay endpoint de confirmación aparte.

```bash
curl -fsS -H "Authorization: Bearer ckd_..." "http://HOST:8088/api/hook/MiJuego/manifest?device=Steam%20Deck"
curl -fsS -X PUT -H "Authorization: Bearer ckd_..." --data-binary @save.dat \
  "http://HOST:8088/api/hook/MiJuego/files?device=Steam%20Deck&path=slot1/save.dat&size=10240&sha256=9f86d0...0a08&offset=0"
curl -fsS -X POST -H "Authorization: Bearer ckd_..." -H "Content-Type: application/json" \
  -d '{"expect": null, "manifest": [{"path": "slot1/save.dat", "sha256": "9f86d0...0a08", "size": 10240, "mtime": 1768501812}]}' \
  "http://HOST:8088/api/hook/MiJuego/commit?device=Steam%20Deck"
curl -fsS -H "Authorization: Bearer ckd_..." -H "Range: bytes=1048576-" "http://HOST:8088/api/hook/MiJuego/files?device=Steam%20Deck&path=slot1/save.dat"
```

Todos aparecen en el Swagger (`/api/docs`) con ejemplos y los errores `401`, `403`, `404`, `429`, `409`, `413` y `422`.

### `GET /api/games/{juego}/hook-status`

Con **sesión de cookie** (la usa la web; la API key no vale aquí). Por cada dispositivo del juego: el último evento de hook y la vigilancia activa, sin datos sensibles: `{"devices": [{"device": "<id>", "last": {"trigger": "hook|hook_closed", "at": "<UTC ISO 8601>", "outcome": "ok|conflict|..."} | null, "watching": {"state": "waiting|running|settling", "since": "..."} | null}]}`. `404` si el juego no existe. Las entradas de historial de `hook` y `hook_closed` guardan ahora el dispositivo (campo `device`); las anteriores no lo tienen y no cuentan como «último aviso».

### `GET /api/games`

Con **API key** (Bearer; mismo 401 único y 429 por IP que `/api/hook/*`; la cookie de sesión no vale). Con la key de **usuario** devuelve todos los juegos; con la de **dispositivo** `http`, solo los que tienen ese dispositivo en su lista. Lista de juegos y su último estado, para consultar desde un dispositivo sin SSH. Solo lectura; no devuelve dispositivos ni ajustes, ni mensajes del resultado, y solo con la key de dispositivo añade `path` y `process` (ver más abajo). `steam_appid` es el id de Steam del juego (entero) o `null` si no tiene; con la key de dispositivo es el **efectivo en ese dispositivo** (`steam_appids[dispositivo]` y, si no hay, el general) y no se exponen los appids de otros dispositivos; con la key de usuario es el general y, si el juego lo tiene, se añade `steam_appids` (`{dispositivo: appid}`). El plugin solo lee `steam_appid`. Con la key de dispositivo solo se ven los juegos de ese dispositivo, como siempre. `status` es `null` si el juego nunca se ha sincronizado; `started`/`finished` son hora local del hub (ISO 8601 sin zona). No confundir con `GET /api/games/{juego}/hook-status` (sesión, interna).

```json
[
  {"id": "g1", "name": "Mi Juego", "enabled": true, "steam_appid": 1245620,
   "status": {"result": "ok", "code": "err.sync.done", "started": "2026-01-15T18:30:12", "finished": "2026-01-15T18:30:14"}},
  {"id": "g2", "name": "Otro Juego", "enabled": true, "steam_appid": null, "status": null}
]
```

Con la key de usuario, un juego con appid por dispositivo añade el mapa: `{"id": "dq7", ..., "steam_appid": 2389644016, "steam_appids": {"omarchy-1a2b3c4d": 3928137182}, ...}`; con la key de ese dispositivo, `steam_appid` vale `3928137182` y no hay `steam_appids`. Con la key de dispositivo, cada juego añade además `path` (ruta del guardado en ese dispositivo o `null`) y `process` (cadena o `null`: p. ej. `"MiJuego.exe"`); con la de usuario, ninguno de los dos.

```bash
curl -fsS -H "Authorization: Bearer ck_..." "http://HOST:8088/api/games"
```

### `GET /api/hook/watches`

Con `Authorization: Bearer ck_...` (sin cookie; `401` sin key). Lista las vigilancias activas, sin datos sensibles: `[{"game": "<id>", "device": "<id>", "state": "waiting|running|settling", "since": "<UTC ISO 8601>", "last_poll": "<UTC ISO 8601>", "poll": <segundos>}]`. `since` es el inicio del estado actual; `last_poll`, el último sondeo completado (latido); `poll`, el intervalo de sondeo. `waiting`: aún no se ha visto el proceso; `running`: visto abierto; `settling`: cerrado, esperando antes del checkpoint.

```bash
curl -fsS -H "Authorization: Bearer ck_..." "http://HOST:8088/api/hook/watches"
```

### `GET /api/watches`

Con **sesión de cookie** (la usa la web). Mismas vigilancias que `/api/hook/watches`, solo de juegos existentes, más la hora del servidor para medir el latido: `{"now": "<UTC ISO 8601>", "watches": [{"game", "device", "state", "since", "last_poll", "poll"}], "playing": [...], "results": [...], "conflicts": [...], "resolutions": [...]}`. Los cuatro campos añadidos son de dispositivos `http` (sin rutas ni claves): `playing` = «jugando ahora» (`{game, device, since, expires, result?}`; caduca a las 12 h o con su `closed`), `results` = último resultado de sync por juego y dispositivo (`{game, device, at, trigger, state, code?}`, del historial), `conflicts` = conflictos de datos registrados (`{game, device, reason, hub, device_hash, at}`, con huellas y no con nombres de fichero) y `resolutions` = resoluciones pendientes y vigentes (`{game, device, winner, by, at, expires}`). La pestaña Sincronizar la consulta cada 5 s (solo con la pestaña visible) y marca cada juego vigilado con un borde del color de su estado y una franja inferior con icono + texto (esperando a que arranque / jugando desde HH:MM / cerrando / sin latido); en la cabecera, un contador «● Vigilando · N» que despliega la lista. Si `last_poll` tiene más de 3 × `poll` de antigüedad, pasa a ámbar (borde discontinuo) con el texto «Sin latido». El «jugando» de un dispositivo `http` usa la misma barra verde «Jugando en <dispositivo>».
