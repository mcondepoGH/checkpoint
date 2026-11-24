# Registro de cambios del cliente

## 0.1.0 - sin publicar

Primer núcleo del cliente de Checkpoint para Linux (sin SSH).

### Cambios

- **Vinculación:** `checkpoint-client link <hub>` pide una solicitud con código de 6 dígitos, espera a que se acepte en el hub y guarda la clave `ckd_` en `~/.config/checkpoint-client/settings.json` (0600).
- **Juegos y sincronización:** `games`, `sync <juego>|--all [--dry-run] [--resolve hub|device]` y `status`, con el motor del plugin de la Deck (huella, subida y bajada reanudables, commit, conflicto sin tocar nada).
- **Lanzador:** `run <juego> -- <comando>` baja el guardado, lanza el comando y lo sube al cerrarlo.
- **Vigilante:** `watch` detecta con `psutil` la apertura y el cierre de cada juego por su `process` en el hub y sube el guardado al cerrar (espera unos segundos a que se liberen los ficheros) y avisa `opened`/`closed`. No baja antes de abrir; si el juego ya estaba abierto al arrancar, sube al cerrarlo. Con el hub caído al cerrar, el cierre queda en una cola en disco y se reintenta. Un juego sin `process` se avisa y se omite. `sync` a mano rechaza con el juego abierto.
- **Exclusión mutua:** ficheros de lock en el directorio de configuración: un solo `watch` y un solo proceso del cliente por juego a la vez (`run`, `sync` y `watch`).
- **Dependencia:** `psutil`.
- **Código común:** el manifiesto local, la URL del hub, el nombre del dispositivo, la redacción de claves y la compatibilidad por protocolo salen de `checkpoint_core` (carpeta `checkpoint-core/`, compartida con el plugin de la Deck, sin copias). El wheel lo lleva dentro; se construye con `python -m build --wheel`. Sin cambios de comportamiento.
- **Textos:** aprobados por el usuario los que estaban pendientes: salida de `games` (tabuladores), claves de `status`, mensajes de `--dry-run`, errores de uso, «No se pudo lanzar el comando: {motivo}.», «--name: » y el inglés de argparse.
- **Textos del vigilante (aprobados por el usuario):** «Ya hay un vigilante en marcha.» (segundo `watch`); `status` gana la línea `vigilante: activo` o `vigilante: parado` (mira el lock sin tomarlo); con un vigilante activo, `sync` a mano con el juego abierto dice «{juego} está abierto: no se sincroniza. El vigilante lo sincronizará al cerrarlo.» (sin vigilante, se mantiene «Ciérralo y vuelve a intentarlo.»).
