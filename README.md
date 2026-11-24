<p align="center">
  <img src="docs/logo.svg" alt="Checkpoint" width="360">
</p>

# Checkpoint

![Licencia MIT](https://img.shields.io/badge/licencia-MIT-green)

Checkpoint sincroniza las partidas guardadas de un juego entre dos dispositivos, por SSH, desde una interfaz web. Con un solo dispositivo guarda versiones en el hub («solo checkpoint»). Corre en Docker o directamente en un equipo (modo nativo) y no instala nada en los dispositivos.

- Elige la copia más reciente y propaga el lado que cambió; ante un conflicto pregunta, nunca decide a ciegas.
- Versiones de cada guardado, con restauración desde la web, y copia perdedora guardada antes de sobrescribir.
- Sincronización manual, automática cada X horas o al abrir y cerrar el juego desde el lanzador.
- Modo simulación (dry-run), registro de ejecuciones y log en vivo.
- Interfaz en español e inglés, instalable como PWA, configuración editable desde la web o a mano.
- Plugin de Steam Deck (Decky Loader): se vincula con un código y sincroniza sin SSH.

## Índice

- [Cómo funciona](#cómo-funciona)
- [Instalación con Docker](#instalación-con-docker)
- [Instalación sin Docker](#instalación-sin-docker)
- [Primeros pasos](#primeros-pasos)
- [Lanzadores](#lanzadores)
- [Plugin de Steam Deck](#plugin-de-steam-deck)
- [Seguridad](#seguridad)
- [Más documentación](#más-documentación)

## Cómo funciona

```
 Dispositivo A  <--- SSH --->  Checkpoint           <--- SSH --->  Dispositivo B
 (ruta del save)               copias + versiones                  (ruta del save)
```

- **Dispositivos**: equipos con servidor SSH (Windows o Linux), el propio equipo donde corre Checkpoint («Este equipo», solo sin Docker) o dispositivos `http` que se conectan ellos (el plugin de la Deck). Checkpoint entra por SSH con una clave que genera él mismo.
- **Juegos**: cada juego enlaza uno o dos dispositivos y la carpeta de guardado en cada uno. Nombres libres (hasta 64 caracteres, sin `/` ni `\`); lo que identifica a cada uno es un ID interno que no cambia.
- **Sincronizar**: descarga los guardados, compara con el estado tras la última sincronización y propaga el lado que cambió. Si solo hay un dispositivo conectado, lo compara con la copia del hub.
- **Versiones**: se conservan las últimas N de cada juego (`max_versions`, 20 por defecto, 0 = sin límite; `keep_versions` lo sustituye por juego) y se restauran desde la pestaña Versiones.

Solo la opción «gana el más reciente» de los conflictos usa fechas de modificación: mantén la hora sincronizada (NTP) en el servidor y los dispositivos.

## Instalación con Docker

Requisitos: Docker y Docker Compose.

```bash
git clone https://github.com/mcondepoGH/checkpoint.git && cd checkpoint
cp .env.example .env          # edita CHECKPOINT_USER y CHECKPOINT_PASSWORD
docker compose up -d          # descarga ghcr.io/mcondepogh/checkpoint:latest
```

Abre `http://IP-DEL-SERVIDOR:8088`. Si la contraseña lleva `$`, ponla entre comillas simples.

- **Etiquetas de imagen**: `latest` = última estable, `:beta` = preliminares, `:X.Y.Z` = versión fija. Se cambia en `image:` de `docker-compose.yml`.
- **Actualizar**: `docker compose pull && docker compose up -d`.
- **Carpetas**: `config/`, `keys/` y `data/` junto al compose (bind mounts); no vienen en el repositorio y se crean solas.
- **Variables opcionales** (en `environment:` del compose): `CHECKPOINT_LANG` (`es`/`en`), `CHECKPOINT_SESSION_HOURS`, `CHECKPOINT_LOG_LEVEL`, `TZ`, `CHECKPOINT_COOKIE_SECURE` y `CHECKPOINT_TRUST_PROXY` (tras un proxy con HTTPS), y los topes de subida y papelera. Tabla completa en [`docs/configuration.md`](docs/configuration.md).

## Instalación sin Docker

Modo «nativo»: es la única forma de usar el dispositivo **Este equipo**.

Requisitos: Python 3.12, Node.js (solo para compilar la web) y, para dispositivos remotos, `rsync` y el cliente OpenSSH (`ssh`, `ssh-keygen`, `ssh-keyscan`) en el `PATH`.

```bash
git clone https://github.com/mcondepoGH/checkpoint.git && cd checkpoint
python3 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)            # genera frontend/dist, que se sirve solo
export CHECKPOINT_USER=usuario CHECKPOINT_PASSWORD='cámbiala'
cd backend && python -m app.cli serve               # http://127.0.0.1:8088
```

`serve` escucha solo en `127.0.0.1`; usa `--host 0.0.0.0` (o `CHECKPOINT_HOST`) y `--port` (o `CHECKPOINT_PORT`) para cambiarlo. La CLI también ofrece `list`, `versions` y `sync` (acepta id o nombre del juego; en Docker, `docker exec checkpoint checkpoint list`).

`config/`, `data/` y `keys/` se crean en la carpeta base del sistema (se cambia con `CHECKPOINT_HOME_DIR`):

| Sistema | Carpeta base |
|---|---|
| Linux | `$XDG_DATA_HOME/checkpoint` o `~/.local/share/checkpoint` |
| macOS | `~/Library/Application Support/checkpoint` |
| Windows | `%APPDATA%\checkpoint` |

Docker o nativo se decide por `CHECKPOINT_RUNTIME` (la imagen lo fija a `docker`) o, si no está, por la existencia de `/.dockerenv` o `/run/.containerenv`.

<details>
<summary>Arranque al iniciar sesión en Linux (unidad de usuario de systemd)</summary>

`~/.config/systemd/user/checkpoint.service` (ajusta las rutas):

```ini
[Unit]
Description=Checkpoint

[Service]
WorkingDirectory=/home/usuario/Checkpoint/backend
EnvironmentFile=/home/usuario/.config/checkpoint.env     # CHECKPOINT_USER=... y CHECKPOINT_PASSWORD=...
ExecStart=/home/usuario/Checkpoint/.venv/bin/python -m app.cli serve
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
chmod 600 ~/.config/checkpoint.env && systemctl --user enable --now checkpoint
```

</details>

### «Este equipo»

Un dispositivo puede marcarse como **Este equipo**: el mismo equipo donde corre Checkpoint. No usa SSH y el motor lee y escribe directamente en sus carpetas, con las mismas garantías que en remoto (copia a temporal, huellas, escritura atómica, fecha de modificación conservada, detección del proceso abierto, conflictos y versiones). Solo puede haber uno. En vez de «Probar conexión» hay **Comprobar carpeta**. Los enlaces simbólicos de la carpeta de saves no se siguen ni se sincronizan.

En Docker la casilla no aparece y un `config.yaml` con `local: true` se rechaza (allí «este equipo» sería el contenedor).

### Plataformas probadas

- **Linux**: probado (suite automática, incluido el motor con «Este equipo» sobre el sistema de ficheros real, y un arranque real con `serve`).
- **Windows nativo**: el motor de sincronización (bloqueos, transporte «Este equipo», detección de procesos, huellas y conflictos) está verificado en CI en un runner de Windows (`windows-latest`, Python 3.12). El resto (API y hub completos, instalación y uso real) sigue sin verificar y es experimental. En Windows como anfitrión no hay `rsync` de serie, así que los dispositivos remotos no están soportados; «Este equipo» sí está pensado para funcionar.
- **macOS**: experimental, no verificado; el código lo contempla pero solo se probó con simulaciones.
- El acceso SSH a dispositivos remotos no se prueba contra un servidor SSH real (las pruebas lo simulan).

## Primeros pasos

La pantalla **Configuración** tiene tres subpestañas: **General** (sincronización automática y comprobación de actualizaciones), **Biblioteca** (clave SSH, versiones guardadas, dispositivos y juegos) y **Lanzadores**. La primera vez, sin dispositivos, abre en Biblioteca.

1. En **Configuración > Biblioteca**, copia la **clave pública SSH** (solo hace falta con dispositivos remotos).
2. Añádela a `authorized_keys` de cada dispositivo. El botón **?** junto a la clave muestra los comandos para Linux y Windows, incluida la activación del servidor SSH.
3. Añade los **dispositivos** (nombre, host, puerto, usuario, sistema) y pulsa **Probar conexión**; la primera vez se guarda la huella del host.
4. Añade los **juegos**: uno o dos dispositivos y la carpeta de guardado en cada uno (ruta absoluta, p. ej. `/home/usuario/.local/share/Juego/Saves` o `C:\Users\Usuario\AppData\Local\Juego\Saves`).
5. Ve a **Sincronizar**: prueba primero con **Simulación (dry-run)** y después sin ella.

`config.yaml` se edita desde la web (valida, muestra diff y guarda copias) o a mano; ejemplo comentado en [`config.example.yaml`](config.example.yaml) y detalles en [`docs/configuration.md`](docs/configuration.md).

## Lanzadores

Los lanzadores avisan al hub justo antes de arrancar el juego (`POST /api/hook/{juego}/opened`): el hub sincroniza antes de que arranque y, al cerrarse el proceso del juego, hace el checkpoint solo ([cierre automático](docs/guide.md#cierre-automático)). En **Configuración > Lanzadores** hay una fila por juego con el comando ya completo (tu API key, el id del juego y el dispositivo), listo para copiar. Son estos (la API key de usuario se genera en el menú del perfil):

El cliente debe esperar (hasta 60 s) y arrancar el juego **aunque falle el aviso** (hub caído, conflicto...), por eso se encadena con `;` y no con `&&`. Pon la URL entre comillas.

- **Steam / Steam Deck** (Opciones de lanzamiento del juego):

  ```
  curl -fsS -m 60 --retry 3 -X POST -H "Authorization: Bearer <API_KEY>" "http://<HUB>:8088/api/hook/<JUEGO>/opened?device=<DISPOSITIVO>"; %command%
  ```

- **Lutris** (Configurar > Opciones del sistema > *Pre-launch script*, con «Wait for pre-launch completion» activado para que Lutris espere al aviso):

  ```
  curl -fsS -m 60 --retry 3 -X POST -H "Authorization: Bearer <API_KEY>" "http://<HUB>:8088/api/hook/<JUEGO>/opened?device=<DISPOSITIVO>"
  ```

- **Heroic** (ajustes del juego > Avanzado > script antes de lanzar): el mismo `curl` que Lutris.

- **Windows / Playnite** (script previo del juego, PowerShell 5.1):

  ```
  Invoke-WebRequest -Method Post -Uri "http://<HUB>:8088/api/hook/<JUEGO>/opened?device=<DISPOSITIVO>" -Headers @{Authorization='Bearer <API_KEY>'} -TimeoutSec 60 -UseBasicParsing
  ```

  Alternativa con `curl.exe` (incluido en Windows 10/11): el mismo comando que en Lutris.

El `process` de cada juego (para el cierre automático) debe coincidir con el proceso real; en Proton/Wine, el `.exe` bajo Wine. Con `pgrep -f` basta un fragmento del nombre. Las claves, los hooks y el resto de la API están en [`docs/api.md`](docs/api.md).

## Plugin de Steam Deck

[`checkpoint-deck/`](checkpoint-deck/README.md) es un plugin de [Decky Loader](https://decky.xyz) independiente del hub: la Deck se vincula con un código de 6 dígitos que se acepta en la web (**Configuración > Biblioteca**), asocia sus juegos de Steam, sincroniza al abrir y cerrar cada juego y resuelve conflictos, todo por HTTP con una key propia (dispositivo `http`, sin SSH).

- **Descarga e instalación**: el hub sirve el zip sin sesión ni key en `GET /api/deck/plugin` y la web lo ofrece en **Configuración > Lanzadores** (abajo del todo). En la Deck: Ajustes de Decky > Desarrollador > «Instalar plugin desde URL» y pega `<hub>/api/deck/plugin` (o «desde ZIP»). Para actualizar se reinstala desde la misma URL.
- **Dónde está el zip**: en Docker, `/app/deck/Checkpoint.zip` (lo construye la etapa `deck` del Dockerfile). En modo nativo hay que generarlo con `pnpm run zip` en `checkpoint-deck/`; sin zip, la descarga responde `404`.
- **Manifiesto del plugin en la imagen Docker**: el zip lleva `data/save_manifest.json` (rutas de guardado de Steam y Lutris, ~2 MB, no se commitea) para «Sugerir carpeta». El build lo genera solo en la etapa `savemanifest`: baja `manifest.yaml` de [ludusavi-manifest](https://github.com/mtkennerly/ludusavi-manifest) en un commit fijo (`ARG LUDUSAVI_MANIFEST_COMMIT` del `Dockerfile`) y ejecuta `checkpoint-deck/scripts/gen_save_manifest.py`. Hace falta red en el build; si algo falla, el build falla. Para actualizarlo cambia ese `ARG` (o `--build-arg LUDUSAVI_MANIFEST_COMMIT=<hash completo>`); `--build-arg SKIP_SAVE_MANIFEST=1` lo omite a propósito.
- **Versiones**: el plugin tiene versión propia y un protocolo de compatibilidad con el hub; detalles en su README y en [`docs/structure.md`](docs/structure.md).

## Seguridad

- Cambia el usuario y la contraseña del `.env` y restringe sus permisos (`chmod 600 .env`).
- No expongas el servicio a Internet sin un proxy inverso con TLS (activa `CHECKPOINT_COOKIE_SECURE=1` y `CHECKPOINT_TRUST_PROXY=1`).
- **Límite de intentos** en el login y en `/api/hook/*`, por IP de origen y en memoria: los 2 primeros fallos seguidos no esperan, el 3.º bloquea 5 s y cada nuevo fallo duplica la espera hasta 15 min, con `429` y `Retry-After`. Tras un proxy, `CHECKPOINT_TRUST_PROXY=1` hace que cuente la IP real (la última entrada de `X-Forwarded-For`): el proxy debe añadir esa cabecera y el hub no debe ser accesible sin pasar por él. Sin la variable, todos los clientes comparten la IP del proxy; con ella y sin proxy delante, un cliente podría falsear su IP.
- La clave privada vive en `keys/`; no la compartas ni la subas a un repositorio. Si cambia la huella de un dispositivo, la conexión falla: revisa `keys/known_hosts` antes de borrar la entrada.
- Las API keys se guardan cifradas en `data/`; su secreto, `hub.secret`, vive junto a `config.yaml`, fuera de `data/`. Trata las keys como contraseñas, regenera la que se filtre y excluye `hub.secret` de las copias de seguridad (ver [`docs/api.md`](docs/api.md)).
- Usa una cuenta limitada en los dispositivos. «Este equipo» da acceso al sistema de ficheros de quien ejecuta Checkpoint: no lo ejecutes como administrador o root; sin Docker, `serve` solo escucha en `127.0.0.1` hasta que lo abras a la red.

## Más documentación

| Documento | Contenido |
|---|---|
| [`docs/guide.md`](docs/guide.md) | Sincronización automática, nuevas versiones, un solo dispositivo, desactivar un juego, datos sin dispositivo, conflictos, cierre automático, idioma, perfil y PWA |
| [`docs/configuration.md`](docs/configuration.md) | Variables de entorno, carpetas y `config.yaml` |
| [`docs/api.md`](docs/api.md) | API keys, vinculación, Steam, OpenAPI, hooks y dispositivos `http` |
| [`docs/development.md`](docs/development.md) | Pruebas, lint, auditorías, publicación de versiones y componentes de UI |
| [`docs/structure.md`](docs/structure.md) | Estructura del código, reglas de dependencia y plugin de Steam Deck |
| [`checkpoint-deck/README.md`](checkpoint-deck/README.md) | Plugin de Steam Deck |
| [`CHANGELOG.md`](CHANGELOG.md) | Historial de cambios |

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
