# checkpoint-core

Paquete `checkpoint_core`: el código **puro** que comparten el [plugin de la Steam Deck](../checkpoint-deck/README.md) y el [cliente de Linux](../checkpoint-client/README.md) de Checkpoint, para no copiarlo. Solo biblioteca estándar y Python 3.8 o superior (Decky corre en su propio Python); sin asyncio, ni Decky, ni Steam, ni red.

| Módulo | Contenido |
| --- | --- |
| `manifest` | `build_manifest`: manifiesto local `[{path, sha256, size, mtime}]` con las mismas reglas que el hub |
| `urls` | `normalize_hub_url`, `HubUrlError` |
| `names` | `normalize_device_name`, `DeviceNameError`, `NAME_MAX` |
| `redaction` | `redact`, `describe_error` (claves `ckd_` y secretos fuera de logs y mensajes) |
| `protocol` | `KEY_PREFIX`, `parse_protocol`, `compat` |

No se publica por separado: el wheel del cliente lo trae dentro (`package-dir` en `checkpoint-client/pyproject.toml`) y `checkpoint-deck/scripts/package.sh` lo copia al zip del plugin. Mapa y reglas en [`docs/structure.md`](../docs/structure.md).

## Desarrollo

```bash
pip install -e '.[dev]'
pytest
ruff check . && ruff format --check .
```
