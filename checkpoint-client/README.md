# checkpoint-client

Cliente de [Checkpoint](../README.md) para Linux: sincroniza los guardados de tus juegos con el hub por HTTP, con una clave de dispositivo `ckd_` y **sin SSH**. Es una CLI (sin interfaz gráfica ni bandeja). Windows y el modo «Solo cliente» van aparte.

Estado: núcleo (`0.1.0`, sin publicar). Todavía no hay vigilante de procesos, arranque automático, llavero ni comprobación de versiones nuevas.

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
checkpoint-client status                    # vinculación, conexión y versión
```

`<juego>` es el id que muestra `games`. Códigos de salida: 0 correcto, 1 error, 2 uso, 3 conflicto (no se toca nada).

Al bajar, la carpeta anterior queda en `<carpeta>.checkpoint-backup` (una copia). Cada ruta que da el hub se valida antes de tocar nada: no se aceptan el directorio personal ni carpetas del sistema.

## Desarrollo

```bash
pip install -e '.[dev]'
pytest            # tests con un hub falso
pytest -m integration   # contra el hub real; se omite sin las dependencias del backend
ruff check . && ruff format --check .
```
