"""Versiones semver y su comparación (solo biblioteca estándar, Python >= 3.8).

Precedencia de semver.org: una pre-release (`1.0.0-rc.1`) es MENOR que su release (`1.0.0`) y los metadatos de build
(`+...`) no cuentan. Sin prefijo `v` y sin ceros a la izquierda. Lo usan el plugin de la Deck y el cliente de Linux."""

import re
from typing import Any, Optional, Tuple

MAX_LEN = 64

_NUM = r"(0|[1-9]\d*)"
_PRE = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER = re.compile(rf"^{_NUM}\.{_NUM}\.{_NUM}(?:-({_PRE}(?:\.{_PRE})*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")


def parse_semver(v: Any) -> Optional[Tuple[Tuple[int, int, int], Optional[Tuple[str, ...]]]]:
    """((mayor, menor, parche), pre-release|None), o None si no es un semver válido (sin prefijo `v`, sin ceros a la izquierda)."""
    if not isinstance(v, str) or not 0 < len(v) <= MAX_LEN:
        return None
    m = _SEMVER.match(v)
    if not m:
        return None
    pre = tuple(m.group(4).split(".")) if m.group(4) else None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))), pre


def _pre_key(pre: Tuple[str, ...]) -> list:
    # numérico < alfanumérico; los numéricos se comparan como números
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre]


def compare(a: str, b: str) -> int:
    """-1, 0 o 1 según la precedencia semver. Lanza ValueError si alguna no es válida."""
    pa, pb = parse_semver(a), parse_semver(b)
    if pa is None or pb is None:
        raise ValueError("semver no válido")
    if pa[0] != pb[0]:
        return -1 if pa[0] < pb[0] else 1
    if pa[1] == pb[1]:
        return 0
    if pa[1] is None:
        return 1  # la release va por encima de cualquier pre-release suya
    if pb[1] is None:
        return -1
    ka, kb = _pre_key(pa[1]), _pre_key(pb[1])
    return -1 if ka < kb else (1 if ka > kb else 0)


def is_newer(candidate: Any, current: Any) -> bool:
    """`candidate` es estrictamente mayor que `current`. Si cualquiera no es semver válido: False (no se ofrece nada a ciegas)."""
    if parse_semver(candidate) is None or parse_semver(current) is None:
        return False
    return compare(candidate, current) > 0
