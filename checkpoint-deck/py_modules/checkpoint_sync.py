"""Motor de sincronización manual de saves entre la Deck y el hub de Checkpoint (solo biblioteca estándar).

Protocolo del hub (`/api/hook/*`): `fingerprint` decide (`none` | `upload` | `download` | `conflict`); con `upload` se
suben TODOS los ficheros y se hace `commit`; con `download` se baja todo `hub_manifest` a un directorio temporal
hermano, se verifica y se reemplaza la carpeta. Con `conflict` no se toca nada (política skip).

Seguridad (la ruta y el manifiesto que da el hub son DATOS NO CONFIABLES):
- `validate_game_path`: absoluta, sin `..`, sin NUL, nunca el directorio personal ni un padre suyo, carpetas del sistema,
  del plugin ni de Decky, ni la raíz de Steam; la carpeta del juego no puede ser un enlace simbólico.
- `validate_rel`: cada ruta del `hub_manifest` se valida ANTES de escribir nada.
- Descarga a `<carpeta>.checkpoint-new` (hermana), verificación de sha256, tamaño y conjunto, y solo entonces se
  reemplaza: el original pasa a `<carpeta>.checkpoint-backup` (UNA copia; la anterior se sustituye en cada descarga
  correcta). Si algo falla, el original queda intacto y se limpia el temporal.

Un juego abierto se detecta fuera (`checkpoint_auto`): si se pasa `is_running`, sincronizar a mano con el juego en
marcha se rechaza con `game_running` (los ficheros pueden estar a medio escribir). Comprobar el estado no lo necesita.
"""

import hashlib
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import checkpoint_client as hc
import checkpoint_manifest as lm
import checkpoint_steam
from checkpoint_hub import HubNetworkError

NEW_SUFFIX = ".checkpoint-new"
BACKUP_SUFFIX = ".checkpoint-backup"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_REL = 1024
MAX_COMPONENT = 255
MIN_FREE_MARGIN = 8 * 1024 * 1024

SYSTEM_EXACT = {
    "/", "/home", "/run", "/usr", "/etc", "/var", "/tmp", "/opt", "/boot", "/dev", "/proc", "/sys", "/bin", "/sbin",
    "/lib", "/lib64", "/root", "/mnt", "/media", "/srv", "/run/media",
}  # fmt: skip
SYSTEM_TREES = ("/usr", "/etc", "/boot", "/dev", "/proc", "/sys", "/bin", "/sbin", "/lib", "/lib64")
HOME_KEEP = (  # carpetas del usuario que nunca pueden ser (ni contener) la carpeta de un juego
    ".local", ".local/share", ".config", ".var", ".var/app", ".steam", ".cache", "homebrew",
)  # fmt: skip

Progress = Callable[[str, int, int], None]


class PathNotAllowed(ValueError):
    """La ruta del hub no es aceptable («ruta no permitida»)."""


class BadManifest(ValueError):
    """El manifiesto del hub no es válido o no es seguro."""


class _Cancelled(Exception):
    pass


class _Fail(Exception):
    def __init__(self, code: str, **params: Any):
        super().__init__(code)
        self.code, self.params = code, params


# ---------------------------------------------------------------- rutas
def _under(p: str, base: str) -> bool:
    return p == base or p.startswith(base.rstrip("/") + "/")


def _clean(raw: Any) -> str:
    if not isinstance(raw, str) or not raw or "\0" in raw or not raw.startswith("/"):
        raise PathNotAllowed("no absoluta")
    parts = raw.split("/")
    if ".." in parts:
        raise PathNotAllowed("con `..`")
    return "/" + "/".join(p for p in parts if p not in ("", "."))


def _forbidden(p: str, homes: Set[str], keep_inside: List[str], keep_around: List[str]) -> bool:
    """`keep_inside`: ni ellas, ni padres, ni lo de dentro. `keep_around`: ni ellas ni sus padres."""
    if p in SYSTEM_EXACT or any(_under(p, t) for t in SYSTEM_TREES):
        return True
    if os.path.dirname(p) == "/home":  # el directorio personal de cualquier usuario
        return True
    for item in homes | set(keep_around):
        if _under(item, p):
            return True
    for item in keep_inside:
        if _under(item, p) or _under(p, item):
            return True
    return False


def validate_game_path(raw: Any, home: Path, protected: Sequence[Path] = ()) -> Path:
    """Ruta real (resuelta) de la carpeta del juego, o PathNotAllowed. No crea nada."""
    p = _clean(raw)
    homes = {str(home), os.path.realpath(home)}
    keep_around = [f"{h}/{k}" for h in homes for k in HOME_KEEP]
    try:
        for h in homes:
            for root in checkpoint_steam.find_steam_roots(Path(h)):
                keep_around.append(str(root))
                keep_around.extend(str(d) for d in checkpoint_steam.library_dirs(root))
    except OSError:
        pass
    keep_inside = [str(x) for x in protected] + [os.path.realpath(x) for x in protected]
    if _forbidden(p, homes, keep_inside, keep_around):
        raise PathNotAllowed("carpeta protegida")
    if os.path.islink(p):
        raise PathNotAllowed("enlace simbólico")
    real = os.path.realpath(p)
    if real != p and _forbidden(real, homes, keep_inside, keep_around):
        raise PathNotAllowed("la ruta real es una carpeta protegida")
    return Path(real)


def validate_rel(rel: Any) -> str:
    """Ruta relativa segura de un fichero del manifiesto del hub (`\\` -> `/`), o BadManifest."""
    if not isinstance(rel, str) or not rel or "\0" in rel or len(rel) > MAX_REL:
        raise BadManifest("ruta inválida")
    r = rel.replace("\\", "/")
    parts = r.split("/")
    if r.startswith("/") or any(x in ("", ".", "..") for x in parts) or any(len(x.encode()) > MAX_COMPONENT for x in parts):
        raise BadManifest("ruta inválida")
    return r


def parse_hub_manifest(raw: Any, max_files: int, max_file_bytes: int) -> List[Dict[str, Any]]:
    """Entradas normalizadas {path, sha256, size, mtime} o BadManifest. Sin duplicados ni choques fichero/carpeta."""
    if not isinstance(raw, list) or not raw:
        raise BadManifest("vacío")
    if len(raw) > max_files:
        raise BadManifest("demasiados ficheros")
    out, seen, dirs = [], set(), set()
    for e in raw:
        if not isinstance(e, dict):
            raise BadManifest("entrada")
        rel = validate_rel(e.get("path"))
        sha, size, mtime = e.get("sha256"), e.get("size"), e.get("mtime")
        sha = sha.lower() if isinstance(sha, str) else ""
        if not SHA_RE.match(sha):
            raise BadManifest("sha256")
        if not (isinstance(size, int) and not isinstance(size, bool) and 0 <= size <= max_file_bytes):
            raise BadManifest("tamaño")
        if not (isinstance(mtime, (int, float)) and not isinstance(mtime, bool) and 0 <= mtime < 2**40):
            raise BadManifest("mtime")
        if rel in seen:
            raise BadManifest("repetida")
        seen.add(rel)
        parts = rel.split("/")
        dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
        out.append({"path": rel, "sha256": sha, "size": size, "mtime": int(mtime)})
    if seen & dirs:
        raise BadManifest("fichero y carpeta con el mismo nombre")
    return out


def _remove(path: str) -> None:
    """Borra un fichero, enlace o carpeta (sin seguir enlaces)."""
    if os.path.islink(path) or not os.path.isdir(path):
        os.unlink(path)
    else:
        shutil.rmtree(path)


def _sha_size(path: str) -> Tuple[str, int]:
    h, n = hashlib.sha256(), 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(lm.BLOCK), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


# ---------------------------------------------------------------- exclusión mutua
_LOCKS_GUARD = threading.Lock()
_GAME_LOCKS: Dict[str, threading.Lock] = {}
_ALL_LOCK = threading.Lock()  # una sola `sync_all` a la vez


def _game_lock(game: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _GAME_LOCKS.setdefault(game, threading.Lock())


# ---------------------------------------------------------------- motor
class SyncEngine:
    def __init__(
        self,
        hub: str,
        key: str,
        *,
        home: Optional[Path] = None,
        protected: Sequence[Path] = (),
        sleep: Callable[[float], None] = __import__("time").sleep,
        max_files: int = lm.MAX_FILES,
        max_file_bytes: int = lm.MAX_FILE_BYTES,
        log: Callable[[str], None] = lambda _m: None,
        is_running: Optional[Callable[[int], bool]] = None,
    ):
        self.is_running = is_running  # appid -> ¿está el juego abierto? Con juego abierto no se sincroniza a mano
        self.client = hc.HubClient(hub, key, sleep=sleep)
        self.home = Path(home) if home else Path.home()
        self.protected = list(protected)
        self.max_files, self.max_file_bytes, self._log = max_files, max_file_bytes, log
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise _Cancelled()

    # ---- API pública
    def notify_closed(self, game: str, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Avisa al hub de que el juego se cerró (limpia su «jugando» y deja constancia en su historial)."""
        return self.client.closed(game, result)

    def notify_opened(self, game: str, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Avisa al hub de que el juego se abrió, con el resultado de la sync local (no crítico, un solo intento)."""
        return self.client.opened(game, result)

    def list_games(self) -> List[Dict[str, Any]]:
        return self.client.get_games()

    def check_game(self, game: str, games: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Estado sin tocar nada: up_to_date | upload | download | conflict | no_path | missing_dir | disabled | error."""
        return self._run(game, games, apply=False, progress=None)

    def sync_game(
        self, game: str, games: Optional[List[Dict[str, Any]]] = None, progress: Optional[Progress] = None
    ) -> Dict[str, Any]:
        """Sincroniza un juego. state: up_to_date | uploaded | downloaded | conflict | no_path | missing_dir | disabled |
        error (con `code`)."""
        self._cancel.clear()
        return self._run(game, games, apply=True, progress=progress)

    def resolve_conflict(
        self, game: str, winner: Any, games: Optional[List[Dict[str, Any]]] = None, progress: Optional[Progress] = None
    ) -> Dict[str, Any]:
        """Resuelve el conflicto de datos de un juego a favor de `hub` o `device` (este equipo) y sincroniza al momento.
        Compara de nuevo (las huellas de AHORA), deja la resolución pendiente en el hub (`PUT .../resolution`, con
        esas huellas) y llama a `sync_game`: el hub la aplica solo si siguen siendo las mismas. Con `hub`, la descarga
        deja antes la carpeta actual en `<carpeta>.checkpoint-backup`; con `device`, el hub guarda su versión previa.
        Si ya no hay conflicto, es una sync normal. Juego abierto: error `game_running` sin registrar nada.
        Estados extra: error `bad_winner`, `resolution_unsupported` (hub antiguo), `resolution_stale`, `side_empty`."""
        if winner not in ("hub", "device"):
            return {"game": game, "state": "error", "code": "bad_winner"}
        self._cancel.clear()
        lock = _game_lock(game)
        if not lock.acquire(blocking=False):
            return {"game": game, "state": "error", "code": "busy"}
        try:
            res = self._register_resolution(game, winner, games)
        except _Cancelled:
            res = {"state": "error", "code": "cancelled"}
        except (hc.HubApiError, HubNetworkError, lm.LocalManifestError) as e:
            res = self._resolution_error(e)
        except OSError as e:
            self._log(f"resolver {game}: error de disco ({type(e).__name__})")
            res = {"state": "error", "code": "io_error"}
        finally:
            lock.release()
        if res is not None:
            return {"game": game, **res}
        return self.sync_game(game, games, progress)

    def _register_resolution(self, game: str, winner: str, games) -> Optional[Dict[str, Any]]:
        """Paso del hub de `resolve_conflict` (con el lock del juego): None = resolución registrada (o ya no hay
        conflicto) y toca sincronizar; un dict = resultado final (error)."""
        target = self._target(game, games, apply=True)
        if isinstance(target, dict):
            return target
        path, exists = target
        self._check_cancel()
        manifest = (
            lm.build_manifest(path, max_files=self.max_files, max_file_bytes=self.max_file_bytes) if exists else []
        )
        fp = self.client.fingerprint(game, manifest)
        if fp["action"] != "conflict":
            return None  # el conflicto se deshizo solo: sync normal
        if winner == "device" and not manifest:
            return {"state": "error", "code": "empty_dir"}  # un lado vacío nunca gana
        hub, dev = fp.get("hub"), fp.get("device_state")
        expect = {
            "hub": hub.get("hash") if isinstance(hub, dict) else None,
            "device": dev.get("hash") if isinstance(dev, dict) else None,
        }
        self.client.set_resolution(game, winner, expect)
        return None

    def _resolution_error(self, e: Exception) -> Dict[str, Any]:
        if isinstance(e, lm.LocalManifestError):
            return {"state": "error", "code": e.code, **({"params": {"path": e.path}} if e.path else {})}
        if isinstance(e, hc.HubApiError):
            if e.code is None and e.status in (404, 405) or e.code == "bad_response":
                return {"state": "error", "code": "resolution_unsupported"}  # el hub no tiene esta función
            known = {
                "err.resolution.stale": "resolution_stale",
                "err.resolution.no_conflict": "resolution_stale",
                "err.resolution.side_empty": "side_empty",
                "err.resolution.invalid": "hub_error",
            }
            if e.code in known:
                return {"state": "error", "code": known[e.code]}
        return self._error(e)

    def sync_all(self, progress: Optional[Progress] = None) -> List[Dict[str, Any]]:
        """Sincroniza todos los juegos con ruta, uno tras otro. Un conflicto o un error de un juego no frena al resto."""
        if not _ALL_LOCK.acquire(blocking=False):
            return [{"game": "*", "state": "error", "code": "busy"}]
        try:
            self._cancel.clear()
            try:
                games = self.client.get_games()
            except (hc.HubApiError, HubNetworkError) as e:
                return [{"game": "*", **self._error(e)}]
            out = []
            for g in games:
                if self._cancel.is_set():
                    break
                out.append(self._run(g["id"], games, apply=True, progress=progress))
            return out
        finally:
            _ALL_LOCK.release()

    # ---- interno
    @staticmethod
    def _error(e: Exception) -> Dict[str, Any]:
        """Resultado de error a partir de una excepción del cliente (sin URL ni clave)."""
        if isinstance(e, HubNetworkError):
            return {"state": "error", "code": "connection"}
        if isinstance(e, hc.FileTooLarge):
            return {"state": "error", "code": "file_too_large", "params": {"path": str(e)}}
        assert isinstance(e, hc.HubApiError)
        known = {
            "err.hook.hub_changed": "hub_changed",
            "err.hook.commit_rejected": "commit_rejected",
            "err.hook.upload_incomplete": "upload_incomplete",
            "err.hook.set_mismatch": "set_mismatch",
            "err.hook.sha_mismatch": "file_changed",
            "err.hook.file_too_large": "file_too_large",
            "err.hook.staging_full": "staging_full",
            "err.main.run_in_progress": "hub_busy",
            "err.hook.upload_busy": "hub_busy",
        }
        if e.status == 401:
            return {"state": "error", "code": "unauthorized"}
        if e.status == 429:
            return {"state": "error", "code": "rate_limited", "params": {"wait_s": e.wait_s}}
        if e.code in known:
            return {"state": "error", "code": known[e.code]}
        return {"state": "error", "code": "hub_error", "params": {"code": e.code or str(e.status)}}

    def _run(self, game: str, games, apply: bool, progress: Optional[Progress]) -> Dict[str, Any]:
        lock = _game_lock(game)
        if not lock.acquire(blocking=False):
            return {"game": game, "state": "error", "code": "busy"}
        try:
            res = self._locked(game, games, apply, progress)
        except _Cancelled:
            res = {"state": "error", "code": "cancelled"}
        except _Fail as f:
            res = {"state": "error", "code": f.code, **({"params": f.params} if f.params else {})}
        except (hc.HubApiError, HubNetworkError, hc.FileTooLarge) as e:
            res = self._error(e)
        except lm.LocalManifestError as e:
            res = {"state": "error", "code": e.code, **({"params": {"path": e.path}} if e.path else {})}
        except OSError as e:
            self._log(f"sincronización de {game}: error de disco ({type(e).__name__})")
            res = {"state": "error", "code": "io_error"}
        finally:
            lock.release()
        return {"game": game, **res}

    def _target(self, game: str, games, apply: bool):
        """Qué carpeta toca la sync de `game`: `(ruta real, existe)` o un resultado ya decidido (dict) si no se
        puede seguir (juego desconocido o desactivado, sin ruta, abierto, ruta no permitida)."""
        if games is None:
            games = self.client.get_games()
        g = next((x for x in games if x["id"] == game), None)
        if g is None:
            return {"state": "error", "code": "unknown_game"}
        if not g.get("enabled", True):
            return {"state": "disabled"}
        if g["path"] is None:
            return {"state": "no_path"}
        appid = g.get("steam_appid")
        if apply and self.is_running and isinstance(appid, int) and self.is_running(appid):
            return {"state": "error", "code": "game_running"}
        try:
            path = validate_game_path(g["path"], self.home, self.protected)
        except PathNotAllowed:
            return {"state": "error", "code": "path_forbidden"}
        spath = str(path)
        exists = os.path.isdir(spath)
        if os.path.lexists(spath) and not exists:
            return {"state": "error", "code": "path_forbidden"}  # hay algo que no es una carpeta
        return path, exists

    def _locked(self, game: str, games, apply: bool, progress: Optional[Progress]) -> Dict[str, Any]:
        target = self._target(game, games, apply)
        if isinstance(target, dict):
            return target
        path, exists = target
        spath = str(path)
        self._check_cancel()
        if exists:
            if progress:
                progress("scan", 0, 0)
            manifest = lm.build_manifest(
                path, max_files=self.max_files, max_file_bytes=self.max_file_bytes
            )
        else:
            manifest = []
        fp = self.client.fingerprint(game, manifest, with_manifest=apply)
        action = fp["action"]
        hub_hash = fp.get("hub", {}).get("hash") if isinstance(fp.get("hub"), dict) else None
        if action == "none":
            return {"state": "up_to_date" if exists else "missing_dir"}
        if action == "conflict":
            # `resolution_stale`: había una resolución pendiente y los datos cambiaron: el hub la descartó
            return {"state": "conflict", **({"code": "resolution_stale"} if fp.get("reason") == "resolution_stale" else {})}
        if action == "upload":
            if not exists:
                return {"state": "missing_dir"}
            if not apply:
                return {"state": "upload"}
            if not manifest:
                return {"state": "error", "code": "empty_dir"}
            return self._upload(game, path, manifest, hub_hash, progress)
        if action == "download":
            if not apply:
                return {"state": "download"}
            return self._download(game, path, exists, fp.get("hub_manifest"), progress)
        return {"state": "error", "code": "bad_response"}

    def _upload(self, game, path: Path, manifest, expect, progress) -> Dict[str, Any]:
        total = len(manifest)
        for i, e in enumerate(manifest):
            self._check_cancel()
            if progress:
                progress("upload", i, total)
            self.client.upload_file(game, e["path"], path / e["path"], e["size"], e["sha256"])
        if progress:
            progress("upload", total, total)
        self._check_cancel()
        out = self.client.commit(game, expect if isinstance(expect, str) else None, manifest)
        if out.get("outcome") not in ("ok", "unchanged"):
            return {"state": "error", "code": "hub_error", "params": {"code": str(out.get("outcome"))}}
        return {"state": "uploaded", "files": total}

    def _download(self, game, path: Path, exists: bool, raw_manifest, progress) -> Dict[str, Any]:
        try:
            entries = parse_hub_manifest(raw_manifest, self.max_files, self.max_file_bytes)
        except BadManifest:
            if isinstance(raw_manifest, list) and not raw_manifest:
                return {"state": "error", "code": "hub_empty"}
            return {"state": "error", "code": "bad_manifest"}
        spath = str(path)
        parent = os.path.dirname(spath)
        home_real = os.path.realpath(self.home)
        if not os.path.isdir(parent):
            if not _under(spath, home_real):
                return {"state": "missing_dir"}  # fuera del directorio personal no se crean carpetas padre
            os.makedirs(parent, exist_ok=True)
        total_bytes = sum(e["size"] for e in entries)
        if shutil.disk_usage(parent).free < total_bytes + MIN_FREE_MARGIN:
            return {"state": "error", "code": "no_space"}
        new, backup = spath + NEW_SUFFIX, spath + BACKUP_SUFFIX
        if os.path.lexists(new):
            _remove(new)  # resto de un intento anterior: nuestro propio temporal
        os.mkdir(new)
        try:
            self._fetch(game, new, entries, progress)
            self._check_cancel()
            if exists:
                if os.path.lexists(backup):
                    _remove(backup)  # UNA copia: la anterior se sustituye
                os.rename(spath, backup)
                try:
                    os.rename(new, spath)
                except OSError:
                    os.rename(backup, spath)
                    raise
            else:
                os.rename(new, spath)
        except BaseException:
            if os.path.lexists(new):
                _remove(new)
            raise
        after = [{k: e[k] for k in ("path", "sha256", "size", "mtime")} for e in entries]
        fp2 = self.client.fingerprint(game, after, with_manifest=False)  # `none/same`: el hub fija la línea base
        if fp2.get("action") != "none":
            return {"state": "error", "code": "inconsistent"}
        return {"state": "downloaded", "files": len(entries)}

    def _fetch(self, game: str, new: str, entries: List[Dict[str, Any]], progress) -> None:
        """Descarga y verifica cada fichero dentro del temporal `new` (recién creado, sin enlaces)."""
        real_new = os.path.realpath(new)
        total = len(entries)
        for i, e in enumerate(entries):
            self._check_cancel()
            if progress:
                progress("download", i, total)
            dest = os.path.join(new, *e["path"].split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.commonpath([os.path.realpath(os.path.dirname(dest)), real_new]) != real_new or os.path.islink(
                dest
            ):
                raise _Fail("bad_manifest")
            self.client.download_file(game, e["path"], Path(dest))
            sha, size = _sha_size(dest)
            if sha != e["sha256"] or size != e["size"]:
                raise _Fail("verify_failed", path=e["path"])
            os.utime(dest, (e["mtime"], e["mtime"]))
        if progress:
            progress("download", total, total)
        found = {
            os.path.relpath(os.path.join(d, f), new).replace(os.sep, "/")
            for d, _dirs, files in os.walk(new, followlinks=False)
            for f in files
            if not os.path.islink(os.path.join(d, f))
        }
        links = any(os.path.islink(os.path.join(d, n)) for d, dirs, files in os.walk(new) for n in dirs + files)
        if links or found != {e["path"] for e in entries}:
            raise _Fail("verify_failed")


def protected_dirs(decky_module: Any) -> List[Path]:
    """Carpetas de Decky y del plugin que ningún juego puede ocupar (a partir del módulo `decky`)."""
    names = (
        "DECKY_PLUGIN_DIR", "DECKY_PLUGIN_SETTINGS_DIR", "DECKY_PLUGIN_RUNTIME_DIR", "DECKY_PLUGIN_LOG_DIR", "DECKY_HOME",
    )  # fmt: skip
    return [Path(v) for n in names if isinstance(v := getattr(decky_module, n, None), str) and v]


__all__: Iterable[str] = ("SyncEngine", "validate_game_path", "validate_rel", "PathNotAllowed", "BadManifest")
