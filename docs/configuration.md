# Configuración

Variables de entorno, carpetas y `config.yaml`. Instalación: [`README.md`](../README.md).

## Variables de entorno

Variables (todas con prefijo `CHECKPOINT_`, salvo `TZ`). El `docker-compose.yml` solo pasa las obligatorias (`CHECKPOINT_USER` y `CHECKPOINT_PASSWORD`, tomadas del `.env`); para usar una opcional, añádela en `environment:` del servicio (p. ej. `TZ: Europe/London` o `CHECKPOINT_SESSION_HOURS: 24`), con su valor o como `${VARIABLE:-valor}` si la defines en el `.env`. La sincronización automática y la comprobación de versiones se ajustan desde la pantalla Configuración, no con variables.

| Variable | Por defecto | Descripción |
|---|---|---|
| `CHECKPOINT_USER` | (obligatoria) | Usuario de acceso a la web. Solo con `serve` y host local (`127.0.0.1`, `::1`, `localhost`) puede faltar junto a la contraseña: el hub arranca sin login y solo se abre desde ese equipo; con otro host y sin credenciales, `serve` se niega a arrancar |
| `CHECKPOINT_PASSWORD` | (obligatoria) | Contraseña, en claro en el `.env` (ver `CHECKPOINT_USER` para el modo sin login) |
| `CHECKPOINT_PORT` | `8088` | Solo con `serve` (sin Docker): puerto de escucha. En Docker la web escucha siempre en el 8088 del contenedor; para cambiar el puerto del equipo edita `ports:` en el compose |
| `CHECKPOINT_HOST` | `127.0.0.1` | Solo con `serve` (sin Docker): dirección de escucha |
| `CHECKPOINT_HOME_DIR` | según el sistema | Solo sin Docker: carpeta base de `config/`, `data/` y `keys/` (ver más abajo) |
| `CHECKPOINT_NO_TRAY` | — | Solo instalador de Windows: `1` desactiva el icono de bandeja |
| `CHECKPOINT_SESSION_HOURS` | `12` | Horas de validez de la sesión |
| `CHECKPOINT_COOKIE_SECURE` / `CHECKPOINT_TRUST_PROXY` | `0` | Pon `1` tras un proxy inverso con HTTPS |
| `CHECKPOINT_HOOK_STAGING_TTL_H` | `24` | Horas sin escrituras tras las que se purga el staging de subidas (`data/staging/<juego>/<dispositivo>/`) al arrancar y cada hora; nunca el de un juego con el lock tomado o una ejecución en curso. Entre `1` y `720`; fuera de rango o no numérico, el arranque falla con un error claro |
| `CHECKPOINT_TRASH_TTL_DAYS` | `30` | Días que se conserva en la papelera (`data/trash/`) lo que se mueve desde «Datos sin dispositivo asignado» antes de que el mantenimiento programado lo borre del todo. Entre `1` y `3650`; fuera de rango o no numérico, el arranque falla con un error claro |
| `CHECKPOINT_HOOK_STAGING_MAX_MB` | `2048` | Tope (MiB) del staging de cada juego (todos sus dispositivos) en la subida de saves por la API; al superarlo, `413` `err.hook.staging_full`. Entre `1` y `1048576`; fuera de rango o no numérico, el arranque falla con un error claro |
| `CHECKPOINT_HOOK_MAX_FILE_MB` | `512` | Tamaño máximo por fichero (MiB) en la subida de saves de los dispositivos `http` por la API (ver [`api.md`](api.md#hooks)). Entre `1` y `16384` (16 GiB); fuera de rango o no numérico, el arranque falla con un error claro |
| `CHECKPOINT_RUNTIME` | automático | `docker` o `native`: fuerza el modo (la imagen lo fija a `docker`; la unidad de systemd de `install.sh` lo fija a `native`, porque en contenedores `/.dockerenv` haría creer al hub que corre en Docker) |
| `CHECKPOINT_LANG` | `es` | Idioma por defecto de la interfaz: `es` o `en` (también `en-US`, `EN`…). Opcional; sin marcar es español. Un valor no soportado se ignora (español) y se avisa en el log de arranque. Ver [Idioma](#idioma) |
| `CHECKPOINT_LOG_LEVEL` | `info` | Nivel de log de la app: `info` o `debug` (también `warning`, `error`). Con `debug` salen las trazas detalladas por petición. Un valor no válido se ignora (`info`) y se avisa en el log de arranque. Se aplica al reiniciar |
| `TZ` | `UTC` | Zona horaria de los registros y la sincronización automática (p. ej. `Europe/London`); solo Docker, se añade a `environment:` |

Si la contraseña lleva `$`, ponla entre comillas simples.

## Instalación nativa en Linux (`install.sh`)

La unidad `~/.config/systemd/user/checkpoint.service` que crea `install.sh` fija `Environment=CHECKPOINT_RUNTIME=native` y lee las credenciales de `~/.config/checkpoint/checkpoint.env` (0600). Variables de `install.sh` (para instalaciones a medida o pruebas; `SYSTEMCTL`, `LOGINCTL` y `PYTHON` son solo para pruebas):

| Variable | Por defecto | Descripción |
|---|---|---|
| `CHECKPOINT_INSTALL_PREFIX` | `~/.local/share/checkpoint-app` | Carpeta del código (una subcarpeta por versión y el enlace `current`) |
| `CHECKPOINT_MIN_PYTHON` | `3.12` | Versión mínima de Python que acepta el instalador |
| `CHECKPOINT_INSTALL_WAIT` | `20` | Segundos esperando a que el hub responda tras arrancar; `0` no espera |
| `SYSTEMCTL` | `systemctl` | Orden que se usa en lugar de `systemctl` (pruebas) |
| `LOGINCTL` | `loginctl` | Orden que se usa en lugar de `loginctl` (pruebas) |
| `PYTHON` | el del sistema | Intérprete con el que se crea el venv (pruebas) |

`CHECKPOINT_USER` y `CHECKPOINT_PASSWORD` también valen como alternativa a `--user`/`--password-file`. Se respetan `HOME`, `XDG_DATA_HOME` y `XDG_CONFIG_HOME`.

## Carpetas y `config.yaml`

| Carpeta | Contenido |
|---|---|
| `config/` | `config.yaml` (dispositivos y juegos) |
| `keys/` | clave SSH generada y `known_hosts` |
| `data/` | copias, versiones, logs, registro de la sync automática y la foto de perfil (`data/profile/`) |

Estas carpetas no vienen en el repositorio (están en `.gitignore`): se crean solas al arrancar, con Docker (bind mounts de `docker-compose.yml`) o sin Docker (`CHECKPOINT_HOME_DIR`, ver el README, «Instalación sin Docker»). Con Docker, si no existen en el clon, Docker las crea como root en el primer `docker compose up`; el contenedor arranca como root, las pasa a su usuario `checkpoint` (uid/gid 1000 por defecto, argumentos `PUID`/`PGID` del `Dockerfile`) y deja `keys/` en `0700`, así que funciona igual. Si prefieres que el propietario inicial en el host sea tu usuario, créalas antes del primer arranque:

```bash
mkdir -p config data keys && docker compose up -d
```

(El arranque vuelve a asignarlas al uid 1000 del contenedor; si tu usuario del host es el 1000, no cambia nada.) `config.yaml` se edita desde la UI (valida, muestra diff y guarda copias) o a mano; ver [`config.example.yaml`](../config.example.yaml). Ejemplo mínimo:

```yaml
devices:
  pc-1a2b3c4d:     {name: "Mi PC", host: 192.0.2.10, user: usuario, os: windows, port: 22}
  laptop-5e6f7a8b: {name: "Portátil", host: 192.0.2.11, user: usuario, os: linux, port: 22}
games:
  ejemplo-0a1b2c3d:
    name: "Ejemplo"
    devices: [pc-1a2b3c4d, laptop-5e6f7a8b]
    paths:
      pc-1a2b3c4d: "C:/Users/usuario/AppData/Local/Ejemplo/Saves"
      laptop-5e6f7a8b: "/home/usuario/.local/share/Ejemplo/Saves"
    keep_versions: 5           # opcional: sustituye a max_versions para este juego
    # enabled: false           # opcional: desactiva el juego (no se sincroniza por ninguna vía)
    # steam_appid: 1245620     # opcional: id de Steam del juego (ver abajo)
    # steam_appids:            # opcional: appid distinto por dispositivo (atajos que no son de Steam; ver abajo)
    #   pc-1a2b3c4d: 2389644016
    #   laptop-5e6f7a8b: 3928137182
```

**Appid de Steam (opcional).** `steam_appid` es el id de Steam del juego: un dato del juego, igual en todos los dispositivos, que el plugin de Steam Deck usa para saber qué juego del hub corresponde a cada juego de Steam. Se edita en Configuración, en el campo «Appid de Steam» de la tarjeta del juego (o en `config.yaml`); vacío o ausente = sin appid. Debe ser un número entero mayor que 0: `0`, negativos, decimales, texto (también `"440"` entre comillas) y `true`/`false` se rechazan con `err.config.steam_appid_invalid`. Dos juegos no pueden compartir el mismo appid (`err.config.steam_appid_duplicate`, indica el otro juego). Solo se pueden guardar juegos de Steam por ahora: no hay appid para los que no lo son. Las keys de la API solo lo leen (`GET /api/games`); no pueden cambiarlo.

**Appid por dispositivo (opcional).** Un atajo que no es de Steam (juego añadido a mano) recibe un appid distinto en cada dispositivo (p. ej. 2389644016 en el hub y 3928137182 en otro equipo). `steam_appids` es un mapa `{id de dispositivo: appid}` con el appid de ese juego en cada dispositivo; `steam_appid` sigue siendo el valor general. El appid **efectivo** de un juego en un dispositivo es `steam_appids[dispositivo]` si existe y, si no, `steam_appid`. Reglas: cada appid es un entero mayor que 0 (`err.config.steam_appid_invalid`); las claves deben ser dispositivos de la configuración (`err.config.steam_appids_device_unknown`) y estar en la lista `devices` del propio juego (`err.config.steam_appids_device_not_in_game`); el appid efectivo es único entre los juegos de un mismo dispositivo (`err.config.steam_appid_duplicate`), y el general sigue sin poder repetirse entre juegos. Si está vacío o ausente no se escribe. La Deck lo rellena sola al enviar su biblioteca (ver `POST /api/steam/library` en la API); también se puede escribir en `config.yaml`. El editor de la web todavía no lo muestra.

La clave de cada juego y dispositivo es su **ID interno**, que no cambia nunca; `name` es solo una etiqueta y se puede renombrar libremente sin perder saves, versiones ni logs. `name` es obligatorio en cada juego y dispositivo. La CLI y la API aceptan el ID o el nombre.
