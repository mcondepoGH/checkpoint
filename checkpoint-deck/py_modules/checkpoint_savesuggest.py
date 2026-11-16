"""Sugerencias de carpeta de guardado exacta desde el manifiesto propio: emparejado, filtro por existencia y orden.

Solo lectura en disco y solo biblioteca estándar (la única red es la consulta opcional 3b). Orden de casado de un juego instalado con el manifiesto:
  1. Lutris con `service` = steam: `service_id` contra `steam`         (confianza `high`, `match.by` = lutris_service_steam)
  2. Steam: appid contra `steam`                                       (`high`, steam_appid)
  3. Lutris: `slug` local contra `lutris`                              (`high`, lutris_slug)
  3b. Lutris, si el slug no casó: appid de Steam del slug según lutris.net (`checkpoint_lutris_api`, una consulta por slug
      nuevo, cacheada) contra `steam`                                  (`high`, lutris_api_steam)
  4. Secundario, confianza `doubtful`: `slug` del manifiesto == slug local (slug_derived), o nombre normalizado igual a
     `games.name` (name).
NUNCA se sugiere sin confirmación del usuario: todo resultado lleva `needs_confirmation` = True (la UI de confirmación no
está hecha) y el plugin no configura nada aquí.

Resultado por juego: `{source, id, name, manifest_name, match: {by, id}, confidence, needs_confirmation, state, paths}`.
`state` = `found` (hay rutas que existen: solo esas, de la más reciente a la más antigua por mtime) o `not_found_yet` (ninguna
existe: `paths` son las candidatas con `exists` falso). Cada ruta: `{path, exists, mtime, size, files, truncated, rule, doubtful}`; `doubtful` = la ruta del manifiesto lleva `d: true`
(heurística, p. ej. LÖVE `love/<juego>`). La `confidence` del juego pasa a `doubtful` solo si TODAS las rutas del resultado son dudosas.
Las rutas `steamCloud` del manifiesto (`<steam>/userdata/*/<appid>/<subruta>`, normalmente `remote`) son rutas de guardado
normales: van en `paths` con el resto (hay juegos sin nube de Steam que guardan ahí, p. ej. DMC HD Collection). Una entrada por
cuenta con carpeta del appid (máx. 10). Ya no hay campo `cloud`: la UI no lo consumía.

Uso en la Deck sin interfaz: `python3 checkpoint_savesuggest.py save_manifest.json` (imprime el JSON de `suggest_all`).
"""

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import checkpoint_installed as ci
import checkpoint_savepaths as sp
from checkpoint_lutris_api import LutrisSteamLookup
from checkpoint_savemanifest import ManifestStore, SaveManifest, norm_name


def _noop(_m: str) -> None:
    pass


def match_game(
    m: SaveManifest, g: ci.InstalledGame, lookup: Optional[Callable[[str], Optional[int]]] = None
) -> Optional[Tuple[Dict[str, Any], str, Any, str]]:
    """(juego del manifiesto, `match.by`, id usado, confianza) o None. `lookup(slug)` = appid de Steam según lutris.net (solo Lutris)."""
    if g.source == "lutris" and g.steam_appid is not None and g.steam_appid in m.by_steam:
        return m.by_steam[g.steam_appid], "lutris_service_steam", g.steam_appid, "high"
    if g.source == "steam" and g.id in m.by_steam:
        return m.by_steam[g.id], "steam_appid", g.id, "high"
    if g.source == "lutris":
        if g.slug and g.slug in m.by_lutris:
            return m.by_lutris[g.slug], "lutris_slug", g.slug, "high"
        if g.slug and lookup is not None:
            sid = lookup(g.slug)
            if sid is not None and sid in m.by_steam:
                return m.by_steam[sid], "lutris_api_steam", sid, "high"
        if g.slug and g.slug in m.by_slug:
            return m.by_slug[g.slug], "slug_derived", g.slug, "doubtful"
        key = norm_name(g.name)
        if key and key in m.by_name:
            return m.by_name[key], "name", g.name, "doubtful"
    return None


def suggest_for(
    m: SaveManifest,
    g: ci.InstalledGame,
    home: Path,
    budget: Optional[sp.Budget] = None,
    lookup: Optional[Callable[[str], Optional[int]]] = None,
) -> Optional[Dict[str, Any]]:
    hit = match_game(m, g, lookup)
    if hit is None:
        return None
    mg, by, used, confidence = hit
    found: Dict[str, Dict[str, Any]] = {}
    missing: Dict[str, Dict[str, Any]] = {}
    for c in sp.candidates(mg, g, home):
        for e in sp.evaluate(c, budget):
            if e["exists"]:
                found.setdefault(e["path"], e)
            else:
                missing.setdefault(e["path"], e)
    by_mtime = lambda e: -(e["mtime"] or 0.0)  # noqa: E731  (más reciente primero)
    paths = sorted(found.values(), key=by_mtime)
    if paths and all(e["doubtful"] for e in paths):
        confidence = "doubtful"  # solo rutas de heurística (`d`): el juego baja a `doubtful`
    return {
        "source": g.source,
        "id": g.id,
        "name": g.name,
        "manifest_name": mg["n"],
        "match": {"by": by, "id": used},
        "confidence": confidence,
        "needs_confirmation": True,
        "state": "found" if paths else "not_found_yet",
        "paths": paths or list(missing.values()),
    }


def suggest_all(
    m: SaveManifest, home: Path, log: Callable[[str], None] = _noop, lookup: Optional[Callable[[str], Optional[int]]] = None
) -> List[Dict[str, Any]]:
    """Sugerencias de todos los juegos de Steam y Lutris instalados que están en el manifiesto (orden: Steam por appid, Lutris por id)."""
    budget = sp.Budget()
    steam, lutris = ci.installed_games(home, log)
    out = []
    for g in [*sorted(steam, key=lambda x: x.id), *sorted(lutris, key=lambda x: x.id)]:
        try:
            r = suggest_for(m, g, home, budget, lookup)
        except Exception:  # noqa: BLE001  (un juego raro no tumba el resto)
            log("guardado: fallo al resolver las rutas de un juego")
            continue
        if r:
            out.append(r)
    return out


def suggest_one(
    m: SaveManifest,
    home: Path,
    source: str,
    ident: Any,
    log: Callable[[str], None] = _noop,
    lookup: Optional[Callable[[str], Optional[int]]] = None,
) -> Optional[Dict[str, Any]]:
    """Sugerencia de un juego instalado: Steam por appid; Lutris por slug (texto) o por id de fila (entero). None si no está instalado o no casa."""
    steam, lutris = ci.installed_games(home, log)
    pool = steam if source == "steam" else lutris if source == "lutris" else []
    for g in pool:
        if (g.id == ident) if isinstance(ident, int) and not isinstance(ident, bool) else (source == "lutris" and g.slug == ident):
            return suggest_for(m, g, home, sp.Budget(), lookup)
    return None


class SaveSuggester:
    """Lo que usa `main.py`: manifiesto diferido y cacheado (`ManifestStore`) + las dos consultas.

    `lookup` (`LutrisSteamLookup`) es opcional: sin él (por defecto) no hay red. `lookup_enabled()` lo apaga en caliente (ajuste). Las
    consultas se serializan con un cerrojo: la cuota de red es por llamada. Se ejecutan en hilo aparte (`to_thread`), así
    la red bloqueante no frena el bucle de eventos."""

    def __init__(
        self,
        settings_dir: Any,
        home: Optional[Path] = None,
        log: Callable[[str], None] = _noop,
        lookup: Optional[LutrisSteamLookup] = None,
        lookup_enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        self.store = ManifestStore(settings_dir, log)
        self._home = home
        self._log = log
        self._api = lookup
        self._enabled = lookup_enabled
        self._lock = threading.Lock()

    def _manifest(self) -> Optional[SaveManifest]:
        return self.store.get()

    def home(self) -> Path:
        return Path(self._home) if self._home else Path.home()

    def _begin(self) -> Optional[Callable[[str], Optional[int]]]:
        if self._api is None:
            return None
        self._api.begin_call()
        try:
            on = bool(self._enabled())
        except Exception:  # noqa: BLE001
            on = True
        return self._api.lookup_steam_id if on else None

    def _net(self) -> Dict[str, int]:
        """`network_lookups`: peticiones a lutris.net de esta llamada; `lookups_pending`: slugs sin consultar (se harán en la siguiente)."""
        return {"network_lookups": self._api.requests if self._api else 0, "lookups_pending": self._api.pending if self._api else 0}

    def all(self) -> Dict[str, Any]:
        m = self._manifest()
        if m is None:
            return {"ok": False, "error": "no_manifest"}
        with self._lock:
            games = suggest_all(m, self.home(), self._log, self._begin())
            return {"ok": True, "manifest": m.src, "games": games, **self._net()}

    def one(self, source: Any, ident: Any) -> Dict[str, Any]:
        m = self._manifest()
        if m is None:
            return {"ok": False, "error": "no_manifest"}
        if source not in ("steam", "lutris") or not isinstance(ident, (int, str)):
            return {"ok": False, "error": "bad_args"}
        with self._lock:
            r = suggest_one(m, self.home(), source, ident, self._log, self._begin())
            return {"ok": True, "manifest": m.src, "game": r, **self._net()} if r else {"ok": False, "error": "no_match"}


def main(argv: List[str]) -> int:
    """`python3 checkpoint_savesuggest.py <save_manifest.json> [steam|lutris <appid|slug>]`: imprime el JSON (solo lectura)."""
    if not argv:
        print(main.__doc__, file=sys.stderr)
        return 2
    store = SaveSuggester(os.path.dirname(os.path.abspath(argv[0])))
    store.store.set_path(argv[0])
    out = store.one(argv[1], int(argv[2]) if argv[2].isdigit() else argv[2]) if len(argv) == 3 else store.all()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
