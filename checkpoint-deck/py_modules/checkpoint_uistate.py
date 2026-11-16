"""Estado pequeño que recuerda el plugin para el panel (solo biblioteca estándar, nunca claves ni contenido de ficheros).

- `Stamps`: cuándo se sincronizó por última vez cada juego (`lastsync.json`: id -> {at, state, files}).
- `Ignored`: carpetas sugeridas que el usuario descartó para un juego ya añadido (`ignored.json`: id -> ruta ignorada).
- `ack_version`: versión instalada vista por última vez (`seen_version.json`), para avisar «Checkpoint actualizado a X.Y.Z».
- `changed_suggestions`: juegos ya añadidos al hub cuya MEJOR carpeta del manifiesto no es la configurada.
- `folder_info`: tamaño, ficheros y fecha de la carpeta configurada (medición acotada; nunca lee contenido).
"""

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import checkpoint_savepaths as sp
from checkpoint_hub import load_settings, save_settings

STAMPS_FILE = "lastsync.json"
IGNORED_FILE = "ignored.json"
SEEN_VERSION_FILE = "seen_version.json"
OK_STATES = ("uploaded", "downloaded", "up_to_date")  # un resultado que cuenta como «sincronizado»
MAX_ENTRIES = 500  # tope de entradas guardadas por fichero (sin crecer sin límite)


class Stamps:
    """Última sincronización correcta por juego. `record` solo guarda estados correctos; nunca lanza."""

    def __init__(self, directory: str, now: Callable[[], float] = time.time, log: Callable[[str], None] = lambda _m: None):
        self._dir, self._now, self._log = directory, now, log
        self._lock = threading.Lock()
        raw = load_settings(directory, STAMPS_FILE)
        self._data: Dict[str, Dict[str, Any]] = {
            k: {"at": v["at"], "state": v["state"], **({"files": v["files"]} if isinstance(v.get("files"), int) else {})}
            for k, v in raw.items()
            if isinstance(k, str)
            and isinstance(v, dict)
            and isinstance(v.get("at"), (int, float))
            and not isinstance(v.get("at"), bool)
            and v.get("state") in OK_STATES
        }

    def record(self, game: str, res: Dict[str, Any]) -> None:
        state = res.get("state")
        if state not in OK_STATES or not isinstance(game, str):
            return
        entry: Dict[str, Any] = {"at": int(self._now()), "state": state}
        if isinstance(res.get("files"), int) and not isinstance(res.get("files"), bool):
            entry["files"] = res["files"]
        with self._lock:
            self._data[game] = entry
            if len(self._data) > MAX_ENTRIES:
                for k in sorted(self._data, key=lambda x: self._data[x]["at"])[: len(self._data) - MAX_ENTRIES]:
                    del self._data[k]
            snap = dict(self._data)
        try:
            save_settings(self._dir, snap, STAMPS_FILE)
        except OSError:
            self._log("lastsync: no se pudo guardar")

    def get(self, game: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            e = self._data.get(game)
            return dict(e) if e else None

    def latest(self) -> Optional[int]:
        with self._lock:
            return max((e["at"] for e in self._data.values()), default=None)


class Ignored:
    """Sugerencias de carpeta distinta que el usuario descartó: se ignora esa ruta para ese juego (otra ruta nueva sí avisa)."""

    def __init__(self, directory: str, log: Callable[[str], None] = lambda _m: None):
        self._dir, self._log = directory, log
        raw = load_settings(directory, IGNORED_FILE)
        self._data: Dict[str, str] = {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}

    def add(self, game: Any, path: Any) -> bool:
        if not isinstance(game, str) or not game or not isinstance(path, str) or not path.startswith("/"):
            return False
        if game not in self._data and len(self._data) >= MAX_ENTRIES:
            return False
        self._data[game] = path
        try:
            save_settings(self._dir, dict(self._data), IGNORED_FILE)
        except OSError:
            self._log("ignored: no se pudo guardar")
            return False
        return True

    def has(self, game: str, path: str) -> bool:
        return self._data.get(game) == path

    def as_dict(self) -> Dict[str, str]:
        return dict(self._data)


def ack_version(directory: str, current: Optional[str]) -> Dict[str, Optional[str]]:
    """Registra la versión instalada y devuelve `{current, previous}`; `previous` es None la primera vez (sin aviso)."""
    previous = load_settings(directory, SEEN_VERSION_FILE).get("version")
    previous = previous if isinstance(previous, str) else None
    if isinstance(current, str) and current and current != previous:
        try:
            save_settings(directory, {"version": current}, SEEN_VERSION_FILE)
        except OSError:
            pass
    return {"current": current, "previous": previous}


def best_existing(game: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Mejor ruta que EXISTE de una sugerencia: la no dudosa antes que la dudosa y la más reciente primero."""
    paths = [p for p in game.get("paths", []) if isinstance(p, dict) and p.get("exists") and isinstance(p.get("path"), str)]
    if not paths:
        return None
    return sorted(paths, key=lambda p: (bool(p.get("doubtful")), -(p.get("mtime") or 0.0)))[0]


def changed_suggestions(
    rows: List[Dict[str, Any]], suggestions: List[Dict[str, Any]], ignored: Optional[Ignored] = None
) -> List[Dict[str, Any]]:
    """Juegos YA en el hub (con appid de Steam y ruta) cuya mejor carpeta segura del manifiesto no es la configurada.
    Solo confianza alta y ruta no dudosa; lo ignorado se omite. Cada ítem: `{game, name, path, size, files, mtime}`."""
    by_appid = {s["id"]: s for s in suggestions if s.get("source") == "steam" and s.get("confidence") == "high"}
    out = []
    for r in rows:
        appid, cur = r.get("appid"), r.get("path")
        if not isinstance(appid, int) or not cur or appid not in by_appid:
            continue
        best = best_existing(by_appid[appid])
        if best is None or best.get("doubtful") or best["path"].rstrip("/") == str(cur).rstrip("/"):
            continue
        if ignored is not None and ignored.has(r["id"], best["path"]):
            continue
        out.append(
            {
                "game": r["id"],
                "name": r.get("name", ""),
                "path": best["path"],
                "size": best.get("size"),
                "files": best.get("files"),
                "mtime": best.get("mtime"),
            }
        )
    return out


def folder_info(path: Any, home: Path) -> Dict[str, Any]:
    """`{exists, size, files, mtime, truncated}` de la carpeta configurada de un juego. Solo carpetas bajo el home de la
    Deck (o `/run/media`, `/mnt`: la tarjeta SD); lo demás se mide como inexistente. No lee contenido."""
    if not isinstance(path, str) or not path.startswith("/") or ".." in Path(path).parts:
        return {"exists": False}
    real = os.path.realpath(path)
    allowed = (str(home), "/run/media", "/mnt")
    if not any(real == a or real.startswith(a.rstrip("/") + "/") for a in allowed) or not os.path.isdir(real):
        return {"exists": False}
    m = sp.measure(real)
    return {"exists": True, **m}
