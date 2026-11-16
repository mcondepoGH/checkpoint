"""Backend de Checkpoint para Decky Loader (Python del cargador; solo biblioteca estándar).

Decky carga este fichero con `api_version` 1: `Plugin` se instancia y la interfaz llama a sus métodos con argumentos
posicionales (`callable` de `@decky/api`). La lógica vive en `py_modules/checkpoint_hub.py` (el cargador añade esa
carpeta al `sys.path`), para probarla sin Decky.
"""

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import decky  # lo inyecta el cargador

import checkpoint_browse
import checkpoint_steam
import checkpoint_update
from checkpoint_hub import (
    DeviceNameError,
    HubNetworkError,
    HubUrlError,
    Pairing,
    check_connection,
    load_settings,
    redact,
    save_settings,
)
from checkpoint_auto import AutoRunner, AutoSync, Notices
from checkpoint_client import refresh_library as hub_refresh_library
from checkpoint_games import GameTools, lutris_shortcut_appid, suggest_path, suggest_shortcut, verify_applied
from checkpoint_jobs import Jobs
from checkpoint_lutris_api import LutrisSteamLookup
from checkpoint_savesuggest import SaveSuggester
from checkpoint_sync import SyncEngine, protected_dirs
from checkpoint_version import plugin_dir, read_version


BUNDLED_MANIFEST_DIR = "data"  # <plugin>/data/save_manifest.json: lo mete scripts/package.sh; el de ajustes tiene prioridad
PREFS_FILE = "prefs.json"  # preferencias de la interfaz, aparte de settings.json (que lleva la clave `ckd_`)
PREF_DEFAULTS: Dict[str, bool] = {
    "show_unconfigured": True,  # mostrar «Sin configurar en el hub»
    "lutris_lookup": True,  # preguntar a lutris.net el appid de Steam de los juegos de Lutris nuevos (solo el slug, una vez, con caché)
}
DIAG_MAX_LEN = 64  # largo máximo de cada campo del evento crudo en el log de diagnóstico
DIAG_WINDOW = 60.0  # segundos de la ventana que limita el log de eventos crudos
DIAG_MAX_PER_WINDOW = 20  # líneas de eventos crudos distintos permitidas por ventana


class Plugin:
    pairing: Pairing
    _compat: Optional[str] = None  # última compatibilidad vista en un ping: `plugin_outdated` bloquea la sincronización

    def _log(self, msg: str) -> None:
        # Última barrera: aunque algún mensaje llevara la clave, no llega al log
        decky.logger.info(redact(msg, self.pairing.key()))

    async def _main(self) -> None:
        self.pairing = Pairing(decky.DECKY_PLUGIN_SETTINGS_DIR, log=self._log)
        self._installed: List[Any] = []  # (appid, nombre) de la última búsqueda en Steam (juegos y atajos)
        self._offered: Dict[int, Set[str]] = {}  # appid -> carpetas que `suggest_game` ofreció (existían al ofrecerlas)
        self._shortcut_ids: Set[int] = set()  # cuáles de esos appids son atajos de Steam
        self.saves = SaveSuggester(  # manifiesto propio de rutas de guardado
            decky.DECKY_PLUGIN_SETTINGS_DIR,
            log=self._log,
            lookup=LutrisSteamLookup(decky.DECKY_PLUGIN_SETTINGS_DIR, log=self._log),
            lookup_enabled=lambda: self._prefs()["lutris_lookup"],
            bundled_dir=plugin_dir(decky) / BUNDLED_MANIFEST_DIR,  # manifiesto empaquetado en el zip (solo lectura)
        )
        self.jobs = Jobs(
            self._make_engine,
            self._scan_and_send,
            log=self._log,
            library=lambda: self._installed,
            shortcuts=lambda: self._shortcut_ids,
        )
        # Avisos automáticos de abrir y cerrar: su motor NO rechaza el juego abierto (es justo el que sincroniza)
        self.notices = Notices()
        self.auto = AutoSync(
            lambda: self._make_engine(check_running=False),
            decky.DECKY_PLUGIN_SETTINGS_DIR,
            self.notices,
            log=self._log,
        )
        self.auto_runner = AutoRunner(self.auto, log=self._log)
        self.auto_runner.start()
        decky.logger.info("Checkpoint: plugin iniciado")

    async def _unload(self) -> None:
        # Cancela la vinculación en curso: sin tareas colgadas tras descargar el plugin
        await self.auto_runner.close()
        await self.jobs.close()
        await self.pairing.close()
        decky.logger.info("Checkpoint: plugin descargado")

    async def get_state(self) -> Dict[str, Any]:
        return self.pairing.state()

    async def set_hub_url(self, url: str) -> Dict[str, Any]:
        try:
            self.pairing.set_hub_url(url)
        except HubUrlError as e:
            return {"ok": False, "url_error": e.code}
        return {"ok": True, **self.pairing.state()}

    async def set_device_name(self, name: str) -> Dict[str, Any]:
        try:
            self.pairing.set_device_name(name)
        except DeviceNameError as e:
            return {"ok": False, "name_error": e.code}
        return {"ok": True, **self.pairing.state()}

    async def start_pairing(self) -> Dict[str, Any]:
        try:
            self.pairing.start()
        except HubUrlError as e:
            return {"ok": False, "url_error": e.code}
        return {"ok": True, **self.pairing.state()}

    async def cancel_pairing(self) -> Dict[str, Any]:
        self.pairing.cancel()
        return self.pairing.state()

    async def unlink(self) -> Dict[str, Any]:
        self.jobs.cancel()  # sin clave no hay sincronización en curso
        self.pairing.unlink()
        return self.pairing.state()

    async def test_connection(self) -> Dict[str, Any]:
        proto = read_version(plugin_dir(decky))["protocol"]
        result, data = await asyncio.to_thread(
            check_connection, self.pairing.hub_url, self.pairing.key(), proto
        )
        if result == "ok":
            self._compat = data.get("compat")
        return {"result": result, **data}

    # ---- versión y actualizaciones del plugin
    async def get_version(self) -> Dict[str, Any]:
        """Versión (semver) y protocolo del plugin, leídos del package.json instalado."""
        return read_version(plugin_dir(decky))

    def _outdated(self) -> bool:
        return self._compat == "plugin_outdated"

    def _blocked_state(self) -> Dict[str, Any]:
        return {**self.jobs.snapshot(), "error": "plugin_outdated", "error_params": {}}

    async def _update_context(self):
        """Evaluación de la versión o un dict de error `{state: error...}`. Solo lectura: no baja el zip."""
        hub, key = self.pairing.hub_url, self.pairing.key()
        if not hub or not key:
            return {"state": "not_linked"}
        cur = read_version(plugin_dir(decky))
        result, ping = await asyncio.to_thread(check_connection, hub, key, cur["protocol"])
        if result != "ok":
            return {"state": "error", "error": result, **ping}
        self._compat = ping.get("compat")
        try:
            info = await asyncio.to_thread(checkpoint_update.fetch_info, hub)
        except HubNetworkError:
            return {"state": "error", "error": "connection"}
        ev = checkpoint_update.evaluate(info, cur["version"], cur["protocol"], ping.get("protocol"))
        ev["compat"] = ping.get("compat")
        if ev["state"] == "available":
            ev.update(hub_url=hub)  # para que la interfaz muestre la URL de Decky
        return ev

    async def check_update(self) -> Dict[str, Any]:
        """Aviso de versión nueva (solo lectura): compara con la que anuncia el hub; no descarga ni instala (se actualiza con «Instalar plugin desde URL» de Decky)."""
        return await self._update_context()

    # ---- juegos y sincronización: tareas de fondo, la interfaz consulta `get_sync_state`
    def _make_engine(self, check_running: bool = True) -> Optional[SyncEngine]:
        key = self.pairing.key()
        if not key or not self.pairing.hub_url:
            return None
        return SyncEngine(
            self.pairing.hub_url,
            key,
            home=Path.home(),
            protected=protected_dirs(decky),
            log=self._log,
            is_running=self.auto.is_running if check_running else None,
        )

    def _scan(self):
        self._installed, self._shortcut_ids = checkpoint_steam.scan_games(log=self._log)
        return self._installed

    def _scan_and_send(self):
        return hub_refresh_library(self.pairing.hub_url, self.pairing.key(), self._scan, log=self._log)

    def _tools(self) -> Optional[GameTools]:
        key = self.pairing.key()
        if not key or not self.pairing.hub_url:
            return None
        return GameTools(self.pairing.hub_url, key, home=Path.home(), protected=protected_dirs(decky), log=self._log)

    @staticmethod
    def _failure(error: str) -> Dict[str, Any]:
        return {"ok": False, "error": error, "error_params": {}, "error_detail": None}

    async def game_event(self, appid: int, running: bool) -> Dict[str, Any]:
        """Steam avisa de que un juego se abrió (`running` verdadero) o se cerró. Se encola y la interfaz no espera:
        sincroniza, avisa al hub y deja toasts en `take_notices`. Un appid que no es de un juego del hub no hace nada."""
        if isinstance(appid, int) and not isinstance(appid, bool) and appid > 0:
            if self._outdated():
                self._log(f"auto: evento appid {appid} descartado: plugin_outdated (actualiza el plugin)")
            else:
                self.auto_runner.submit(appid, bool(running))
        return {"ok": True}

    async def take_notices(self) -> List[Dict[str, Any]]:
        """Avisos pendientes de mostrar como toast en la Deck (se vacían al entregarlos)."""
        out = self.notices.take()
        for n in out:
            self._log(f"auto: aviso entregado {n.get('code')}")  # solo el código: sin rutas ni claves
        return out

    async def diag_game_event(self, appid: Any, kind: Any, running: Any) -> Dict[str, Any]:
        """Diagnóstico: evento crudo de `SteamClient.GameSessions` (antes del filtro de la interfaz), solo `unAppID`,
        su tipo y `bRunning` como texto saneado y recortado. No depende de la vinculación ni del hub y nunca lanza.
        Un evento igual al anterior no se repite y hay un tope de líneas por minuto, para no inundar el log."""
        try:
            fields = ["".join(c if c.isprintable() else "?" for c in str(v))[:DIAG_MAX_LEN] for v in (appid, kind, running)]
            if tuple(fields) == getattr(self, "_diag_last", None):
                return {"ok": True}
            self._diag_last = tuple(fields)
            now = time.monotonic()
            if now - getattr(self, "_diag_start", -DIAG_WINDOW) >= DIAG_WINDOW:
                self._diag_start, self._diag_count = now, 0
            if self._diag_count >= DIAG_MAX_PER_WINDOW:
                return {"ok": True}
            self._diag_count += 1
            a, t, r = fields
            self._log(f"auto: evento crudo unAppID={a} tipo={t} bRunning={r}")
        except Exception:  # el diagnóstico nunca debe romper nada
            pass
        return {"ok": True}

    @staticmethod
    def _prefs() -> Dict[str, bool]:
        saved = load_settings(decky.DECKY_PLUGIN_SETTINGS_DIR, PREFS_FILE)
        return {k: saved[k] if isinstance(saved.get(k), bool) else d for k, d in PREF_DEFAULTS.items()}

    async def get_prefs(self) -> Dict[str, Any]:
        return {"ok": True, **self._prefs()}

    async def set_pref(self, key: str, value: Any) -> Dict[str, Any]:
        """Guarda una preferencia booleana de la interfaz. Solo claves conocidas; nunca toca `settings.json`."""
        if not isinstance(key, str) or key not in PREF_DEFAULTS:
            return {"ok": False, "error": "unknown_pref"}
        if not isinstance(value, bool):
            return {"ok": False, "error": "bad_value"}
        prefs = {**self._prefs(), key: value}
        save_settings(decky.DECKY_PLUGIN_SETTINGS_DIR, prefs, PREFS_FILE)
        return {"ok": True, **prefs}

    async def report_error(self, message: str) -> Dict[str, Any]:
        """Fallo capturado en la interfaz (error global, promesa rechazada o llamada que falló): al log de Decky,
        saneado y recortado, para poder verlo sin consola."""
        text = redact(str(message), self.pairing.key())[:1000]
        decky.logger.error("Checkpoint (interfaz): " + text)
        return {"ok": True}

    async def get_sync_state(self) -> Dict[str, Any]:
        return self.jobs.snapshot()

    async def refresh_library(self) -> Dict[str, Any]:
        """Busca los juegos instalados en la Deck (solo appid y nombre) y los envía al hub."""
        if self._outdated():
            return self._blocked_state()
        return self.jobs.start("refresh")

    async def list_games(self) -> Dict[str, Any]:
        """Juegos de esta Deck en el hub con su estado (al día, sube, baja, conflicto...)."""
        if self._outdated():
            return self._blocked_state()
        return self.jobs.start("check")

    def _unconfigured_name(self, appid: Any) -> Optional[str]:
        """Nombre de un juego instalado que aún no está en el hub (de la última búsqueda), o None."""
        if not isinstance(appid, int) or isinstance(appid, bool):
            return None
        return next((u["name"] for u in self.jobs.snapshot()["unconfigured"] if u["appid"] == appid), None)

    def _is_shortcut(self, appid: int) -> bool:
        return any(u["appid"] == appid and u.get("source") == "shortcut" for u in self.jobs.snapshot()["unconfigured"])

    async def suggest_game(self, appid: int) -> Dict[str, Any]:
        """Datos para configurar un juego que no está en el hub: nombre de Steam y ruta de saves detectada en la Deck
        (carpetas que existen; vacía si no hay nada; para un atajo de Lutris, `source` = "lutris", `candidates` encontrados en su prefijo y `browse_start`, dónde abre «Examinar…»; el prefijo entero no se sugiere; todo se verifica al sugerir con `verified_dir`; sin candidatos de Steam, `browse_start` = el ancestro existente de la ruta natural) y el home de la Deck, donde abre el selector de carpetas. Solo lectura."""
        name = self._unconfigured_name(appid)
        if name is None:
            return self._failure("unknown_game")
        home = Path.home()
        if self._is_shortcut(appid):  # atajo: solo hay sugerencia si lanza un juego de Lutris
            found = await asyncio.to_thread(suggest_shortcut, home, appid, protected_dirs(decky), self._log, name)
        else:
            found = await asyncio.to_thread(suggest_path, home, appid, name, protected_dirs(decky))
        self._offered[appid] = {p for p in [found.get("path", ""), *found.get("candidates", [])] if p}  # lo que se ofreció como existente
        return {"ok": True, "appid": appid, "name": name, "home": str(home), **found}

    async def suggest_saves(self) -> Dict[str, Any]:
        """Carpetas de guardado exactas (del manifiesto propio `save_manifest.json`: el de la carpeta de ajustes si existe; si no, el empaquetado en `<plugin>/data`) de TODOS los
        juegos de Steam y Lutris instalados que casan: `{ok, manifest, games: [...]}` (ver `checkpoint_savesuggest`). Solo
        lectura; nada se configura sin confirmación. Añade `network_lookups` y `lookups_pending` (consultas a lutris.net). Sin manifiesto: `{ok: False, error: "no_manifest"}`."""
        return await asyncio.to_thread(self.saves.all)

    async def suggest_saves_for(self, source: str, ident: Any) -> Dict[str, Any]:
        """Lo mismo para un juego: `source` = "steam" con su appid (entero) o "lutris" con su slug (texto) o id de fila (entero)."""
        return await asyncio.to_thread(self.saves.one, source, ident)

    def _apply_target(self, source: str, ident: Any, path: Any) -> Dict[str, Any]:
        """Bloqueante (corre en un hilo). Comprueba que `path` sea una de las rutas que EXISTEN de la sugerencia de ese juego y
        que `verified_dir` la siga admitiendo; luego busca el juego sin configurar al que corresponde (Steam: su appid; Lutris:
        el atajo con `lutris:rungameid/<id>`). No configura nada."""
        r = self.saves.one(source, ident)
        if not r.get("ok"):
            return self._failure(str(r.get("error", "no_match")))
        game = r["game"]
        if not isinstance(path, str) or path not in [p["path"] for p in game["paths"] if p["exists"]]:
            return self._failure("not_suggested")
        home = Path.home()
        good = verify_applied(path, home, protected_dirs(decky))
        if not good:
            return self._failure("path_missing")
        if source == "steam":
            appid = game["id"] if self._unconfigured_name(game["id"]) is not None else None
        else:
            shortcuts = [u["appid"] for u in self.jobs.snapshot()["unconfigured"] if u.get("source") == "shortcut"]
            appid = lutris_shortcut_appid(home, game["id"], shortcuts)
        if appid is None:
            return self._failure("not_unconfigured")
        self._offered.setdefault(appid, set()).add(good)  # si desaparece antes de guardar, mensaje de «carpeta sugerida»
        return {"ok": True, "appid": appid, "name": self._unconfigured_name(appid) or game["name"], "path": good}

    async def apply_save_suggestion(self, source: str, ident: Any, path: str) -> Dict[str, Any]:
        """Aplica la carpeta que el usuario CONFIRMÓ en la interfaz: no crea nada en el hub. Devuelve `{ok, appid, name, path}`
        del juego de «Sin configurar en el hub» cuyo formulario «Configurar» debe abrirse con esa carpeta; el guardado en el hub
        sigue el flujo de siempre (`configure_game`: `validate_game_path` y carpeta existente). Errores: `no_manifest`, `no_match`,
        `bad_args`, `not_suggested` (la ruta no es una de las sugeridas que existen), `path_missing` (ya no vale) y
        `not_unconfigured` (el juego ya está en el hub o no está en «Sin configurar»)."""
        if self._outdated():
            return self._failure("plugin_outdated")
        return await asyncio.to_thread(self._apply_target, source, ident, path)

    async def picker_start(self, path: str = "") -> Dict[str, Any]:
        """Ruta segura con la que abrir el selector de carpetas de Decky: `path` si existe, es carpeta y se puede leer; si no, el
        home de la Deck; si tampoco, `/`. Decky falla (y revienta su propio frontend) con una ruta que no puede listar."""
        return {"ok": True, "path": await asyncio.to_thread(checkpoint_browse.usable_start, path, Path.home())}

    async def configure_game(self, appid: int, name: str, path: str) -> Dict[str, Any]:
        """Crea en el hub el juego (con este dispositivo, `appid`, nombre y ruta confirmados), o, si el hub ya tiene uno con
        ese nombre y hueco, une este dispositivo a él (`game.joined` = True; la ruta sigue siendo la confirmada aquí). Solo
        para un juego instalado y sin configurar de la última búsqueda."""
        if self._outdated():
            return self._failure("plugin_outdated")
        tools = self._tools()
        if tools is None:
            return self._failure("not_linked")
        if self._unconfigured_name(appid) is None:
            return self._failure("unknown_game")
        out = await asyncio.to_thread(tools.create, appid, str(name), str(path))
        if not out["ok"] and out["error"] == "path_missing" and str(path) in self._offered.get(appid, ()):
            out["error"] = "path_vanished"  # la carpeta que se ofreció como existente ya no está: mensaje propio
        if out["ok"]:
            g = out["game"]
            self.jobs.add_game(g)
            out = {"ok": True, "game": {"id": g["id"], "name": g["name"], "appid": g["appid"]}}
            if g.get("joined") is True:  # el hub ya tenía el juego: este dispositivo se ha unido a él
                out["game"]["joined"] = True
        return out

    async def set_game_enabled(self, game: str, enabled: bool) -> Dict[str, Any]:
        """Activa o desactiva el juego en el hub (vale para todo el hub). Desactivado no se sincroniza ni al abrir ni al
        cerrar."""
        if self._outdated():
            return self._failure("plugin_outdated")
        tools = self._tools()
        if tools is None:
            return self._failure("not_linked")
        out = await asyncio.to_thread(tools.set_enabled, str(game), bool(enabled))
        if out["ok"]:
            self.jobs.set_enabled_row(out["game"], out["enabled"])
        return out

    async def check_game(self, game: str) -> Dict[str, Any]:
        if self._outdated():
            return self._blocked_state()
        return self.jobs.start("check_one", game)

    async def sync_game(self, game: str) -> Dict[str, Any]:
        if self._outdated():
            return self._blocked_state()
        return self.jobs.start("sync_game", game)

    async def resolve_conflict(self, game: str, winner: str) -> Dict[str, Any]:
        """Resuelve el conflicto de datos de un juego: `winner` = `hub` (esta Deck baja los datos del hub; su carpeta
        actual queda en `<carpeta>.checkpoint-backup`) o `device` (el hub guarda los de esta Deck y antes una versión de
        los suyos). Deja la resolución en el hub y sincroniza al momento (no con el juego abierto). Tarea de fondo."""
        if winner not in ("hub", "device"):
            return {**self.jobs.snapshot(), "error": "bad_winner", "error_params": {}}
        if self._outdated():
            return self._blocked_state()
        return self.jobs.start("resolve", str(game), winner)

    async def sync_all(self) -> Dict[str, Any]:
        if self._outdated():
            return self._blocked_state()
        return self.jobs.start("sync_all")

    async def cancel_sync(self) -> Dict[str, Any]:
        self.jobs.cancel()
        return self.jobs.snapshot()
