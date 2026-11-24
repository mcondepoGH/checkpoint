"""Exclusión mutua entre procesos del cliente con ficheros de lock (`flock`) en `<config>/locks`.

Hay un lock `watch` (un solo vigilante) y uno por juego (`game-<huella del id>`): `run` y `sync` lo toman mientras
trabajan sobre ese juego y el vigilante lo toma al subir; así nunca dos procesos del cliente tocan la misma carpeta a
la vez. El lock lo suelta el sistema si el proceso muere. No se escribe nada dentro de los ficheros.
"""

import fcntl
import hashlib
import os
from contextlib import contextmanager
from typing import Iterator

WATCH = "watch"


class Busy(Exception):
    """Otro proceso del cliente tiene el lock."""


def game_name(game: str) -> str:
    """Nombre de lock de un juego: el id del hub no se usa tal cual en una ruta (puede traer `/` o `..`)."""
    return "game-" + hashlib.sha256(game.encode("utf-8")).hexdigest()[:16]


def _open(directory: str, name: str) -> int:
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    return os.open(os.path.join(directory, name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)


@contextmanager
def exclusive(directory: str, name: str) -> Iterator[None]:
    """Toma el lock sin esperar; `Busy` si ya lo tiene otro proceso (o este mismo en otro descriptor)."""
    fd = _open(directory, name)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise Busy(name) from None
    try:
        yield
    finally:
        os.close(fd)  # cerrar el descriptor suelta el lock


def is_locked(directory: str, name: str) -> bool:
    """¿Lo tiene alguien ahora? Prueba y suelta al momento."""
    try:
        with exclusive(directory, name):
            return False
    except Busy:
        return True
