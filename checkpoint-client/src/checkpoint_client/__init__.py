"""checkpoint-client: cliente de Checkpoint para Linux (sincroniza guardados con el hub por HTTP, sin SSH)."""

__version__ = "0.1.0"  # igual que `version` de pyproject.toml (lo comprueba tests/test_package.py)
PROTOCOL = 1  # protocolo con el hub (`GET /api/hook/ping`: `protocol` y `min_plugin_protocol`)
