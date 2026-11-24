# Registro de cambios del cliente

## 0.1.0 - sin publicar

Primer núcleo del cliente de Checkpoint para Linux (sin SSH).

### Cambios

- **Vinculación:** `checkpoint-client link <hub>` pide una solicitud con código de 6 dígitos, espera a que se acepte en el hub y guarda la clave `ckd_` en `~/.config/checkpoint-client/settings.json` (0600).
- **Juegos y sincronización:** `games`, `sync <juego>|--all [--dry-run] [--resolve hub|device]` y `status`, con el motor del plugin de la Deck (huella, subida y bajada reanudables, commit, conflicto sin tocar nada).
- **Lanzador:** `run <juego> -- <comando>` baja el guardado, lanza el comando y lo sube al cerrarlo.
