"""Nombre visible del dispositivo: las mismas reglas que `name_error` del hub."""

import unicodedata
from typing import Any

NAME_MAX = 64  # igual que `NAME_MAX` del hub (backend/app/config/models.py)


class DeviceNameError(ValueError):
    """`code`: empty | spaces | too_long | slash | control | dots (las mismas reglas que `name_error` del hub)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_device_name(raw: Any) -> str:
    """Recorta los bordes y aplica las reglas del hub para un nombre visible; lanza DeviceNameError."""
    if not isinstance(raw, str) or not raw.strip():
        raise DeviceNameError("empty")
    name = raw.strip()
    if "  " in name:
        raise DeviceNameError("spaces")
    if len(name) > NAME_MAX:
        raise DeviceNameError("too_long")
    if "/" in name or "\\" in name:
        raise DeviceNameError("slash")
    for ch in name:
        cat = unicodedata.category(ch)
        if ch == "‍":  # unión de emojis compuestos
            continue
        if cat[0] == "C" or cat in ("Zl", "Zp") or (cat == "Zs" and ch != " "):
            raise DeviceNameError("control")
    if not name.strip("."):
        raise DeviceNameError("dots")
    return name
