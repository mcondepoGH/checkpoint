"""Redacción: ninguna clave de Checkpoint ni secreto sale en un log, un mensaje o el detalle de un fallo."""

import re
from typing import Iterable, Optional, Pattern

DETAIL_MAX = 1500  # el detalle de un fallo se ve entero (saneado antes de recortar)

# Claves de Checkpoint (ck_/ckd_...). Cada cliente suma sus propios patrones con `extra` (p. ej. el plugin, los steamid).
_SENSITIVE = re.compile(r"\bckd?_[A-Za-z0-9_-]+")


def redact(text: str, *secrets: Optional[str], extra: Iterable[Pattern] = ()) -> str:
    """Sustituye por `***` cada secreto literal, las claves `ck_`/`ckd_` y lo que case con los patrones de `extra`."""
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    text = _SENSITIVE.sub("***", text)
    for pattern in extra:
        text = pattern.sub("***", text)
    return text


def describe_error(
    e: BaseException, *secrets: Optional[str], limit: int = DETAIL_MAX, extra: Iterable[Pattern] = ()
) -> str:
    """`Tipo: mensaje` de una excepción, saneado y recortado, para el log y para el detalle que ve la interfaz.
    Un HubApiError/HubNetworkError añade el endpoint (método y ruta, sin servidor ni consulta) y el estado."""
    status = getattr(e, "status", None)
    if status is not None:
        code = getattr(e, "code", None)
        detail = f"estado {status}" + (f", código {code}" if code else "")
    else:
        detail = str(e)
    text = type(e).__name__ + (f": {detail}" if detail else "")
    endpoint = getattr(e, "endpoint", None)
    if endpoint:
        text += f" [{endpoint}]"
    return redact(text, *secrets, extra=extra)[:limit]
