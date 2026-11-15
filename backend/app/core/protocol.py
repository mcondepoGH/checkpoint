"""Versión del protocolo plugin de Steam Deck <-> hub (entero, NO semver).

`PROTOCOL` sube cuando el hub cambia el contrato que usa el plugin (`/api/hook/*`, `/api/pairing/*`, `/api/steam/*`);
`MIN_PLUGIN_PROTOCOL` es el protocolo más viejo de plugin que este hub sigue atendiendo. `GET /api/hook/ping` devuelve ambos
y el plugin se bloquea si su `checkpointProtocol` (package.json) es menor que `min_plugin_protocol`.
Súbelos solo con un cambio incompatible; un cambio compatible no toca ninguno."""

PROTOCOL = 1
MIN_PLUGIN_PROTOCOL = 1
