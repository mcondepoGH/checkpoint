# checkpoint-client

Cliente de [Checkpoint](../README.md) para Linux: sincroniza los guardados de tus juegos con el hub por HTTP, con una clave de dispositivo `ckd_` y **sin SSH**. Es una CLI (sin interfaz gráfica ni bandeja). Windows y el modo «Solo cliente» van aparte.

Estado: núcleo, vigilante y arranque automático en Linux (`0.1.0`, sin publicar). Todavía no hay llavero ni comprobación de versiones nuevas.

## Instalación

Necesita Python 3.12 o superior. Desde esta carpeta:

```bash
pipx install .
```

## Vincular este equipo

```bash
checkpoint-client link http://192.168.1.10:8088
```

Muestra un código de 6 dígitos. Acéptalo en el hub (Configuración > Biblioteca > Solicitudes de vinculación). La clave `ckd_` se guarda una sola vez en `~/.config/checkpoint-client/settings.json` (permisos 0600); nunca se imprime. `checkpoint-client unlink` la borra de este equipo (la revocación real se hace en el hub, en Dispositivos).

## Uso

```bash
checkpoint-client games                     # juegos del hub para este equipo
checkpoint-client sync <juego>              # sincroniza un juego (o --all)
checkpoint-client sync <juego> --dry-run    # solo comprueba
checkpoint-client sync <juego> --resolve hub|device   # resuelve un conflicto
checkpoint-client run <juego> -- <comando>  # baja, lanza el juego y sube al cerrarlo
checkpoint-client watch                     # vigila los juegos y sube su guardado al cerrarse
checkpoint-client install                   # el vigilante arranca solo al iniciar sesión (systemd --user)
checkpoint-client uninstall                 # quita el arranque automático
checkpoint-client status                    # vinculación, conexión, vigilante y versión
```

`<juego>` es el id que muestra `games`. Códigos de salida: 0 correcto, 1 error, 2 uso, 3 conflicto (no se toca nada).

### Vigilante (`watch`)

Detecta con `psutil` cuándo se abre y se cierra cada juego, por el nombre de proceso (`process`) que el hub da para este equipo (se configura en el hub). Al cerrar espera unos segundos, sube el guardado y avisa al hub. No baja nada antes de abrir: si el juego ya estaba abierto al arrancar el vigilante, tampoco; sube al cerrarlo. Si el hub no responde al cerrar, el cierre queda en una cola en disco (`~/.config/checkpoint-client/watch.json`) y se reintenta cada minuto, también tras reiniciar. Un juego sin `process` se avisa y se omite (`run` sigue funcionando). Con el juego abierto, `sync` a mano lo rechaza.

Solo corre un `watch` por equipo, y `run`, `sync` y `watch` no tocan a la vez el mismo juego (ficheros de lock en `~/.config/checkpoint-client/locks`). Con Wine/Proton el proceso es un `.exe` bajo Linux: la detección está pensada para ello pero no verificada con un juego real.

Al bajar, la carpeta anterior queda en `<carpeta>.checkpoint-backup` (una copia). Cada ruta que da el hub se valida antes de tocar nada: no se aceptan el directorio personal ni carpetas del sistema.

### Arranque automático (Linux, `systemd --user`)

```bash
checkpoint-client install     # crea y activa la unidad; el vigilante arranca al iniciar sesión
systemctl --user status checkpoint-client
checkpoint-client uninstall   # detiene el vigilante, desactiva y borra la unidad
```

`install` escribe `~/.config/systemd/user/checkpoint-client.service` (o bajo `$XDG_CONFIG_HOME`), con `ExecStart` apuntando por ruta absoluta al `checkpoint-client` del entorno donde está instalado (sin shell), `Restart=on-failure` y `RestartSec=30`. La unidad no lleva claves ni la dirección del hub: el vigilante lee la vinculación de `~/.config/checkpoint-client` como siempre, así que hay que haber hecho `link` antes. Es idempotente: repetirlo reescribe la unidad y la reinicia solo si cambió; si falla, deja la unidad como estaba. Si se mueve o reinstala el cliente (otro entorno de pipx), vuelve a ejecutar `install`. `uninstall` no borra la vinculación ni los datos. Para parar, systemd manda SIGTERM: el vigilante termina limpio («Vigilante detenido.») y suelta su lock. Si `systemd --user` no está disponible (sin sesión de usuario de systemd), `install` y `uninstall` lo dicen y no cambian nada. Con el servicio activo, `status` muestra `vigilante: activo` y `sync` a mano con un juego abierto dice que el vigilante lo sincronizará al cerrarlo.

Los logs del servicio están en el diario: `journalctl --user -u checkpoint-client`. Para que arranque sin iniciar sesión en una pantalla (p. ej. tras un reinicio sin login) haría falta `loginctl enable-linger`: no lo hace `install`.

## Desarrollo

El código puro común con el plugin de la Deck (manifiesto local, URL del hub, nombre del dispositivo, redacción y compatibilidad por protocolo) vive en [`../checkpoint-core`](../checkpoint-core/README.md) y el wheel lo lleva dentro (`checkpoint_core`), sin dependencia aparte. Para construir un wheel: `python -m build --wheel` (el sdist por defecto no es posible, porque el core está fuera de esta carpeta).

```bash
pip install -e '.[dev]'
pytest            # tests con un hub falso
pytest -m integration   # contra el hub real; se omite sin las dependencias del backend
ruff check . && ruff format --check .
```
