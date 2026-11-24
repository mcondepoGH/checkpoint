# checkpoint-client

Cliente de [Checkpoint](../README.md) para Linux: sincroniza los guardados de tus juegos con el hub por HTTP, con una clave de dispositivo `ckd_` y **sin SSH**. Es una CLI (sin interfaz gráfica ni bandeja). Windows y el modo «Solo cliente» van aparte.

Estado: núcleo y vigilante (`0.1.0`, sin publicar). Todavía no hay arranque automático, llavero ni comprobación de versiones nuevas.

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
checkpoint-client status                    # vinculación, conexión y versión
```

`<juego>` es el id que muestra `games`. Códigos de salida: 0 correcto, 1 error, 2 uso, 3 conflicto (no se toca nada).

### Vigilante (`watch`)

Detecta con `psutil` cuándo se abre y se cierra cada juego, por el nombre de proceso (`process`) que el hub da para este equipo (se configura en el hub). Al cerrar espera unos segundos, sube el guardado y avisa al hub. No baja nada antes de abrir: si el juego ya estaba abierto al arrancar el vigilante, tampoco; sube al cerrarlo. Si el hub no responde al cerrar, el cierre queda en una cola en disco (`~/.config/checkpoint-client/watch.json`) y se reintenta cada minuto, también tras reiniciar. Un juego sin `process` se avisa y se omite (`run` sigue funcionando). Con el juego abierto, `sync` a mano lo rechaza.

Solo corre un `watch` por equipo, y `run`, `sync` y `watch` no tocan a la vez el mismo juego (ficheros de lock en `~/.config/checkpoint-client/locks`). Con Wine/Proton el proceso es un `.exe` bajo Linux: la detección está pensada para ello pero no verificada con un juego real.

Al bajar, la carpeta anterior queda en `<carpeta>.checkpoint-backup` (una copia). Cada ruta que da el hub se valida antes de tocar nada: no se aceptan el directorio personal ni carpetas del sistema.

## Desarrollo

```bash
pip install -e '.[dev]'
pytest            # tests con un hub falso
pytest -m integration   # contra el hub real; se omite sin las dependencias del backend
ruff check . && ruff format --check .
```
