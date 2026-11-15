"""Asociación automática de juegos de Steam (sin FastAPI).

La Deck envía su lista de juegos instalados `[{appid, name}]`; el hub la compara con los juegos de ESE dispositivo y:

- ASOCIA solo con certeza (escribe `steam_appid` del juego, por `ConfigStore.save`): el juego está activo, tiene ese
  dispositivo, aún no tiene appid, su nombre normalizado es igual al de UNA sola entrada de Steam, ningún otro juego del
  hub tiene ese mismo nombre normalizado y el appid no lo usa otro juego.
- SUGIERE (memoria; el usuario decide en la web) los casos dudosos: nombre parecido pero no igual (`SIMILARITY`), nombre
  igual pero ambiguo (dos juegos del hub o dos entradas de Steam con el mismo nombre).
- NUNCA pisa un appid existente (si es el mismo no hace nada; si es otro, ni lo toca ni lo sugiere).

Los descartes (par appid + juego) se recuerdan en `data/state/_steam/dismissed.json` (sin secretos) y no se vuelven a
proponer hasta que el usuario los olvida. Nada de aquí escribe claves ni cuerpos de petición en logs."""

import json
import logging
import re
import secrets
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Tuple

from ..config.models import atomic_write, valid_appid, validate_config
from ..config.store import Conflict, ConfigStore, InvalidConfig
from ..core import settings
from ..core.errors import ApiError

api_log = logging.getLogger("checkpoint.api")  # DEBUG: solo recuentos, nunca nombres ni claves

MAX_GAMES = 5000  # entradas por petición
MAX_NAME = 200  # caracteres del nombre de Steam
MAX_BODY = 1_048_576  # 1 MiB: 5000 entradas de 200 caracteres caben de sobra
MAX_GAME_BODY = 8192  # crear un juego: appid, nombre (200) y ruta (1024) caben de sobra
MAX_PATH = 1024
MAX_SUGGESTIONS = 50  # sugerencias pendientes en todo el hub
MAX_PER_DEVICE = 25  # ... y por dispositivo (un dispositivo no agota el cupo de los demás)
TTL_S = 86400  # caducidad en memoria: la Deck reenvía su lista al abrir
MAX_DISMISSED = 1000  # descartes recordados (al pasarse, se olvidan los más antiguos)
SAVE_TRIES = 3  # reintentos si config.yaml cambia mientras se escribe
SIMILARITY = 0.85  # `difflib.SequenceMatcher.ratio()` mínimo entre nombres normalizados para SUGERIR (nunca asocia)

_STRIP = {"™", "®", "©", "℠"}


def normalize(name: str) -> str:
    """Nombre comparable: NFKD (ancho completo, ligaduras), sin tildes, minúsculas, sin ™ ® © y con cualquier signo o
    espacio repetido reducido a un espacio. `&` cuenta como `and`. Puede devolver "" (nada comparable)."""
    s = unicodedata.normalize("NFKD", "".join(c for c in name if c not in _STRIP))  # antes: NFKD vuelve ™ en "TM"
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    s = s.replace("&", " and ")
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())


def similar(steam_name: str, game_name: str) -> bool:
    """¿Parecidos? Recibe nombres YA normalizados. `SequenceMatcher.ratio() >= SIMILARITY`, determinista."""
    a, b = steam_name, game_name
    if not a or not b or 2 * min(len(a), len(b)) / (len(a) + len(b)) < SIMILARITY:
        return False  # la longitud sola ya lo descarta (y evita el coste en listas grandes)
    m = SequenceMatcher(None, a, b, autojunk=False)
    return m.quick_ratio() >= SIMILARITY and m.ratio() >= SIMILARITY


def parse_library(body: dict) -> List[Tuple[int, str]]:
    """Valida el cuerpo `{"games": [{"appid": int > 0, "name": str}]}` y devuelve [(appid, name)] sin appids repetidos
    (gana el primero). 413 si hay demasiadas entradas, 422 si el cuerpo o una entrada no cumplen la forma."""
    if set(body) != {"games"} or not isinstance(body["games"], list):
        raise ApiError(422, "err.steam.body_invalid")
    games = body["games"]
    if len(games) > MAX_GAMES:
        raise ApiError(413, "err.steam.too_many_games", max=MAX_GAMES)
    seen, out = set(), []
    for i, e in enumerate(games):
        name = e.get("name") if isinstance(e, dict) else None
        if (
            not isinstance(e, dict)
            or set(e) != {"appid", "name"}
            or not valid_appid(e["appid"])
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > MAX_NAME
        ):
            raise ApiError(422, "err.steam.entry_invalid", index=i)
        if e["appid"] not in seen:
            seen.add(e["appid"])
            out.append((e["appid"], name.strip()))
    return out


def parse_game(body: dict) -> Tuple[int, str, str]:
    """Valida `{"appid": int > 0, "name": str, "path": str}` (exactamente esas claves) y devuelve (appid, nombre, ruta).
    422 `game_body_invalid` si no cumple la forma; el valor de cada campo lo valida después la config."""
    name, path = body.get("name"), body.get("path")
    if (
        set(body) != {"appid", "name", "path"}
        or not valid_appid(body["appid"])
        or not isinstance(name, str)
        or not name.strip()
        or len(name) > MAX_NAME
        or not isinstance(path, str)
        or not path.strip()
        or len(path) > MAX_PATH
    ):
        raise ApiError(422, "err.steam.game_body_invalid")
    return body["appid"], name.strip(), path.strip()


def parse_enabled(body: dict) -> bool:
    """Valida `{"enabled": bool}` (exactamente esa clave y un booleano de verdad)."""
    if set(body) != {"enabled"} or not isinstance(body["enabled"], bool):
        raise ApiError(422, "err.steam.game_body_invalid")
    return body["enabled"]


def slug(name: str) -> str:
    """Id de juego a partir del nombre: minúsculas ASCII, dígitos y guiones (sin tildes). Puede devolver "" (nombre sin
    nada aprovechable, p. ej. solo ideogramas)."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:48].strip("-")


def new_game_id(name: str, appid: int, taken) -> str:
    """Id libre (sin distinguir mayúsculas): el slug del nombre; si ya existe, con el appid detrás; sin slug,
    `steam-<appid>`. Nunca devuelve uno de `taken`."""
    low = {t.casefold() for t in taken}
    base = slug(name)
    for cand in ([base, f"{base}-{appid}"] if base else []) + [f"steam-{appid}"]:
        if cand.casefold() not in low:
            return cand
    n = 2
    while f"steam-{appid}-{n}" in low:
        n += 1
    return f"steam-{appid}-{n}"


def game_error(errors: Dict[str, dict], gid: str) -> dict:
    """{field, reason} del primer error de validación que cae en el juego nuevo. Solo el campo y el código: nunca
    parámetros (llevarían nombres de otros juegos). Sin error propio (la config ya fallaba en otro sitio), `game`."""
    prefix = f"games.{gid}."
    for path, err in errors.items():
        if path.startswith(prefix):
            tail = path[len(prefix) :]
            field = {"name": "name", "steam_appid": "appid"}.get(tail, "path" if tail.startswith("paths") else "game")
            return {"field": field, "reason": err.get("code", "err.config.invalid")}
    return {"field": "game", "reason": "err.config.invalid"}


class Plan:
    def __init__(self):
        self.associate: Dict[int, str] = {}  # appid -> id del juego
        self.unchanged: set = set()  # appids que ya estaban asociados a su juego
        self.suggest: List[Tuple[int, str]] = []  # (appid, id del juego)


def plan_matches(entries: List[Tuple[int, str]], games: dict, device: str) -> Plan:
    """Decisión pura: qué asociar, qué ya estaba y qué sugerir, mirando solo los juegos activos de `device`."""
    plan = Plan()
    used = {g.steam_appid: gid for gid, g in games.items() if g.steam_appid is not None}
    gnames = {gid: normalize(g.name) for gid, g in games.items()}
    name_count = Counter(n for n in gnames.values() if n)  # TODOS los juegos: cualquier duplicado es ambiguo
    ents = [(appid, normalize(name)) for appid, name in entries]
    by_name = defaultdict(list)
    for appid, n in ents:
        if n:
            by_name[n].append(appid)
    scope = [gid for gid, g in games.items() if g.enabled and device in g.devices and gnames[gid]]
    sugg = []
    for gid in scope:
        g, gn = games[gid], gnames[gid]
        exact = by_name.get(gn, [])
        if g.steam_appid is not None:
            if g.steam_appid in exact:
                plan.unchanged.add(g.steam_appid)
            continue  # con appid: nunca se pisa ni se sugiere
        if exact:
            if len(exact) == 1 and name_count[gn] == 1 and exact[0] not in used:
                plan.associate[exact[0]] = gid
                used[exact[0]] = gid
            else:
                sugg += [(a, gid) for a in exact]
        else:
            sugg += [(a, gid) for a, n in ents if n and n not in name_count and similar(n, gn)]
    plan.suggest = [(a, gid) for a, gid in sugg if a not in used]
    return plan


class _Sug:
    __slots__ = ("id", "appid", "steam_name", "game", "device", "expires")

    def __init__(self, appid, steam_name, game, device, expires):
        self.id = secrets.token_urlsafe(9)
        self.appid, self.steam_name, self.game, self.device, self.expires = appid, steam_name, game, device, expires


class SteamService:
    def __init__(self, store: ConfigStore, clock: Callable[[], float] = time.time):
        self._store, self._clock = store, clock
        self._lock = threading.Lock()  # sugerencias en memoria
        self._dlock = threading.Lock()  # fichero de descartes
        self._sugg: Dict[str, _Sug] = {}

    # ---- config ----
    def _snap(self):
        snap = self._store.snapshot()
        if snap.error:
            raise ApiError(500, "err.main.config_file_invalid", cause=snap.error)
        return snap

    def _write_appids(self, snap, assign: Dict[str, int]):
        """Guarda `steam_appid` de cada juego de `assign` con la versión base de `snap` (mismas validaciones que
        `PUT /api/config`). Lanza `Conflict` si el fichero cambió, `InvalidConfig` si el resultado no vale."""
        data = snap.cfg.model_dump(exclude_none=True)
        for gid, appid in assign.items():
            data["games"][gid]["steam_appid"] = appid
        cfg, errors = validate_config(data)
        if errors:
            raise InvalidConfig(errors)
        self._store.save(snap.version, cfg)

    def create_game(self, device: str, appid: int, name: str, path: str) -> dict:
        """Crea un juego con SOLO ese dispositivo, la ruta dada y el appid (activo), o, si el hub ya tiene un juego con ese
        nombre normalizado (`normalize`, la misma comparación que `plan_matches`), lo UNE a él (`_join`). Misma validación
        que `PUT /api/config` (nombre, ruta, appid único): un fallo es `422 game_invalid` con campo y código."""
        for _ in range(SAVE_TRIES):
            snap = self._snap()
            twins = self._twins(snap.cfg.games, name)
            if twins:
                out = self._join(snap, twins, device, appid, path)
                if out is None:
                    continue
                return out
            gid = new_game_id(name, appid, snap.cfg.games)
            data = snap.cfg.model_dump(exclude_none=True)
            data["games"][gid] = {"name": name, "devices": [device], "paths": {device: path}, "steam_appid": appid}
            cfg, errors = validate_config(data)
            if errors:
                raise ApiError(422, "err.steam.game_invalid", **game_error(errors, gid))
            try:
                self._store.save(snap.version, cfg)
            except Conflict:
                continue
            api_log.debug("steam: juego creado desde dispositivo=%s juego=%s", device, gid)
            return {"id": gid, "name": name, "appid": appid, "path": cfg.games[gid].paths[device]}
        raise ApiError(409, "err.main.config_changed")

    @staticmethod
    def _twins(games: dict, name: str) -> List[str]:
        """Ids de los juegos del hub cuyo nombre normalizado es el de `name` (vacío si el nombre no es comparable)."""
        key = normalize(name)
        return [gid for gid, g in games.items() if key and normalize(g.name) == key]

    def _join(self, snap, twins: List[str], device: str, appid: int, path: str):
        """Añade `device` (con `path`) al juego existente. Devuelve la respuesta, o None si `config.yaml` cambió (el
        llamador relee y repite). Solo une con UN juego de ese nombre, hueco libre (<2 dispositivos), el dispositivo fuera,
        appid igual al del juego o juego sin appid, y appid no usado por otro juego. Un juego desactivado se une igual y
        sigue desactivado. Dispositivo ya dentro con el mismo appid: no cambia nada (`joined: false`). Cualquier otro
        caso es `422 game_invalid` (campo `name`) con motivo; nunca nombres ni dispositivos de otros juegos."""
        dup = {"field": "name", "reason": "err.config.name_duplicate"}
        if len(twins) != 1:
            raise ApiError(422, "err.steam.game_invalid", **dup)
        gid = twins[0]
        g = snap.cfg.games[gid]
        reply = {"id": gid, "name": g.name, "appid": g.steam_appid, "enabled": g.enabled}
        if device in g.devices:
            if g.steam_appid == appid:
                return {**reply, "path": g.paths[device], "devices": list(g.devices), "joined": False}
            raise ApiError(422, "err.steam.game_invalid", **dup)
        if len(g.devices) >= 2:
            raise ApiError(422, "err.steam.game_invalid", field="name", reason="err.steam.no_free_slot")
        if g.steam_appid is not None and g.steam_appid != appid:
            raise ApiError(422, "err.steam.game_invalid", field="name", reason="err.steam.appid_mismatch")
        if any(o != gid and og.steam_appid == appid for o, og in snap.cfg.games.items()):
            raise ApiError(422, "err.steam.game_invalid", field="name", reason="err.steam.appid_in_use")
        data = snap.cfg.model_dump(exclude_none=True)
        data["games"][gid]["devices"] = [*g.devices, device]
        data["games"][gid]["paths"] = {**g.paths, device: path}
        data["games"][gid]["steam_appid"] = appid
        cfg, errors = validate_config(data)
        if errors:
            raise ApiError(422, "err.steam.game_invalid", **game_error(errors, gid))
        try:
            self._store.save(snap.version, cfg)
        except Conflict:
            return None
        api_log.debug("steam: dispositivo=%s unido al juego=%s", device, gid)
        j = cfg.games[gid]
        return {**reply, "appid": appid, "path": j.paths[device], "devices": list(j.devices), "joined": True}

    def set_enabled(self, device: str, game: str, enabled: bool) -> dict:
        """Activa o desactiva uno de LOS JUEGOS de ese dispositivo (campo `enabled` del juego: vale para todos sus
        dispositivos y para el hub). Inexistente o de otro dispositivo: el mismo 404."""
        for _ in range(SAVE_TRIES):
            snap = self._snap()
            g = snap.cfg.games.get(game)
            if g is None or device not in g.devices:
                raise ApiError(404, "err.steam.game_unknown")
            if g.enabled == enabled:
                return {"game": game, "enabled": enabled}
            data = snap.cfg.model_dump(exclude_none=True)
            data["games"][game]["enabled"] = enabled
            cfg, errors = validate_config(data)
            if errors:
                raise ApiError(409, "err.steam.config_invalid")
            try:
                self._store.save(snap.version, cfg)
            except Conflict:
                continue
            api_log.debug("steam: juego=%s enabled=%s dispositivo=%s", game, enabled, device)
            return {"game": game, "enabled": enabled}
        raise ApiError(409, "err.main.config_changed")

    # ---- descartes (disco) ----
    @staticmethod
    def _dpath():
        return settings.DATA_DIR / "state" / "_steam" / "dismissed.json"

    def _dload(self) -> List[dict]:
        try:
            items = json.loads(self._dpath().read_text(encoding="utf-8")).get("items", [])
        except (OSError, ValueError, AttributeError):
            return []
        keys = ("id", "appid", "steam_name", "game")
        return (
            [d for d in items if isinstance(d, dict) and all(k in d for k in keys)] if isinstance(items, list) else []
        )

    def _dsave(self, items: List[dict]):
        atomic_write(self._dpath(), json.dumps({"version": 1, "items": items}, ensure_ascii=False), mode=0o600)

    def dismissed(self) -> List[dict]:
        try:
            games = self._snap().cfg.games
        except ApiError:
            games = {}
        with self._dlock:
            items = self._dload()
        return [
            {
                "id": d["id"],
                "appid": d["appid"],
                "steam_name": d["steam_name"],
                "game": d["game"],
                "game_name": games[d["game"]].name if d["game"] in games else None,
            }
            for d in items
        ]

    def forget(self, did: str) -> dict:
        with self._dlock:
            items = self._dload()
            rest = [d for d in items if d["id"] != did]
            if len(rest) == len(items):
                raise ApiError(404, "err.steam.dismissed_unknown")
            self._dsave(rest)
        api_log.debug("steam: descarte olvidado")
        return {"id": did, "forgotten": True}

    def _is_dismissed(self, items: List[dict], appid: int, game: str) -> bool:
        return any(d["appid"] == appid and d["game"] == game for d in items)

    # ---- mantenimiento ----
    def purge(self):
        """Quita sugerencias caducadas y descartes de juegos que ya no existen. Lo llama el scheduler."""
        with self._lock:
            self._purge()
        try:
            games = self._snap().cfg.games
        except ApiError:
            return  # config inválida: no se toca nada
        with self._dlock:
            items = self._dload()
            rest = [d for d in items if d["game"] in games]
            if len(rest) != len(items):
                self._dsave(rest)

    def _purge(self):
        now = self._clock()
        for k in [k for k, s in self._sugg.items() if s.expires <= now]:
            del self._sugg[k]

    # ---- Deck ----
    def library(self, device: str, entries: List[Tuple[int, str]]) -> dict:
        for _ in range(SAVE_TRIES):
            snap = self._snap()
            plan = plan_matches(entries, snap.cfg.games, device)
            if plan.associate:
                try:
                    self._write_appids(snap, {gid: a for a, gid in plan.associate.items()})
                except Conflict:
                    continue
                except InvalidConfig:
                    raise ApiError(409, "err.steam.config_invalid") from None  # sin detalle de la config a la Deck
            break
        else:
            raise ApiError(409, "err.main.config_changed")
        names = dict(entries)
        with self._dlock:
            dismissed = self._dload()
        suggested = set()
        with self._lock:
            self._purge()
            now = self._clock()
            for appid, gid in plan.suggest:
                if self._is_dismissed(dismissed, appid, gid):
                    continue
                cur = next((s for s in self._sugg.values() if s.appid == appid and s.game == gid), None)
                if cur is None:
                    mine = sum(1 for s in self._sugg.values() if s.device == device)
                    if len(self._sugg) >= MAX_SUGGESTIONS or mine >= MAX_PER_DEVICE:
                        continue
                    cur = _Sug(appid, names[appid], gid, device, now + TTL_S)
                    self._sugg[cur.id] = cur
                else:
                    cur.steam_name, cur.expires = names[appid], now + TTL_S
                suggested.add(appid)
        done = set(plan.associate) | plan.unchanged
        api_log.debug(
            "steam: dispositivo=%s entradas=%d asociadas=%d sugeridas=%d",
            device,
            len(entries),
            len(plan.associate),
            len(suggested),
        )
        return {
            "associated": [{"appid": a, "game": gid} for a, gid in plan.associate.items()],
            "suggested": len(suggested - done),
            "unchanged": len(plan.unchanged - set(plan.associate)),
            "ignored": len(entries) - len(done | suggested),
        }

    # ---- usuario (sesión) ----
    def suggestions(self) -> List[dict]:
        try:
            cfg = self._snap().cfg
        except ApiError:
            return []
        used = {g.steam_appid for g in cfg.games.values() if g.steam_appid is not None}
        with self._lock:
            self._purge()
            for k, s in list(self._sugg.items()):  # ya no aplicable: el juego se fue, tiene appid o el appid se usa
                g = cfg.games.get(s.game)
                if g is None or g.steam_appid is not None or s.appid in used:
                    del self._sugg[k]
            return [
                {
                    "id": s.id,
                    "appid": s.appid,
                    "steam_name": s.steam_name,
                    "game": s.game,
                    "game_name": cfg.games[s.game].name,
                    "device": s.device,
                    "device_name": cfg.devices[s.device].name if s.device in cfg.devices else None,
                }
                for s in sorted(self._sugg.values(), key=lambda s: (s.expires, s.id))
            ]

    def _take(self, sid: str) -> _Sug:
        with self._lock:
            self._purge()
            s = self._sugg.get(sid)
        if s is None:
            raise ApiError(404, "err.steam.suggestion_unknown")
        return s

    def _drop(self, s: _Sug, rivals: bool = False):
        with self._lock:
            for k, o in list(self._sugg.items()):
                if o is s or (rivals and (o.appid == s.appid or o.game == s.game)):
                    del self._sugg[k]

    def accept(self, sid: str) -> dict:
        s = self._take(sid)
        for _ in range(SAVE_TRIES):
            snap = self._snap()
            games = snap.cfg.games
            g = games.get(s.game)
            if g is None:
                self._drop(s)
                raise ApiError(404, "err.steam.game_unknown")
            if g.steam_appid is not None:
                self._drop(s)
                raise ApiError(409, "err.steam.game_has_appid", game=g.name)
            if any(o.steam_appid == s.appid for o in games.values()):
                self._drop(s)
                raise ApiError(409, "err.steam.appid_in_use", appid=s.appid)
            try:
                self._write_appids(snap, {s.game: s.appid})
            except Conflict:
                continue
            self._drop(s, rivals=True)
            api_log.debug("steam: sugerencia aceptada juego=%s", s.game)
            return {"id": sid, "appid": s.appid, "game": s.game, "name": g.name}
        raise ApiError(409, "err.main.config_changed")

    def dismiss(self, sid: str) -> dict:
        s = self._take(sid)
        with self._dlock:
            items = self._dload()
            if not self._is_dismissed(items, s.appid, s.game):
                items.append(
                    {
                        "id": secrets.token_urlsafe(6),
                        "appid": s.appid,
                        "steam_name": s.steam_name,
                        "game": s.game,
                        "at": int(self._clock()),
                    }
                )
                self._dsave(items[-MAX_DISMISSED:])
        self._drop(s)
        api_log.debug("steam: sugerencia descartada juego=%s", s.game)
        return {"id": sid, "appid": s.appid, "game": s.game}
