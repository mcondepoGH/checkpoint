"""Utilidades comunes: el cliente se prueba contra un hub falso por HTTP (sin red real, sin Linux de escritorio).

`FakeHub` es la copia del de `checkpoint-deck/tests/conftest.py` (vinculación y `ping`) ampliada con lo que necesita el
cliente: `GET /api/games` (con `path` y `process`, como el hub con key de dispositivo) y un `/api/hook/*` mínimo con
estado (fingerprint, subida y bajada de ficheros con `Range`, commit, resolución, opened/closed). No es el hub real: el
hub de verdad se prueba en `test_integration_hub.py`.
"""

import hashlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
# checkpoint_core: fuente única en ../checkpoint-core (en el wheel va dentro)
sys.path.insert(0, str(ROOT.parent / "checkpoint-core" / "src"))

KEY = "ckd_clave-de-prueba-9876"  # literal de prueba (allowlist exacta en .gitleaks.toml)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def set_hash(files: dict) -> str | None:
    """Huella de un conjunto de ficheros {ruta: bytes}; None si está vacío."""
    if not files:
        return None
    return sha("\n".join(f"{p}:{sha(files[p])}" for p in sorted(files)).encode())


def manifest_hash(manifest: list) -> str | None:
    if not manifest:
        return None
    return sha("\n".join(f"{e['path']}:{e['sha256']}" for e in sorted(manifest, key=lambda e: e["path"])).encode())


class FakeHub:
    """Hub falso. `script`: lista de (estado, cuerpo, cabeceras) que se sirve en orden a `GET /requests/{id}`;
    la última respuesta se repite. Guarda cada petición recibida (método, ruta con consulta, cabeceras, cuerpo).

    Juegos: `games` = lista de dicts como los que devuelve `GET /api/games` con key de dispositivo; `files[juego]` =
    {ruta: bytes} del hub; `base[juego]` = huella de la última sincronización acordada."""

    def __init__(self):
        self.requests = []
        self.create = (201, {"id": "rid1", "code": "123456", "secret": "SECRET-xyz", "expires_in": 600}, {})
        self.script = []
        self.ping = (200, {"ok": True, "device": "pc-ab12", "protocol": 1, "min_plugin_protocol": 1}, {})
        self.key = KEY
        self.redirect_to = None
        self.games = []
        self.files = {}
        self.base = {}
        self.staging = {}
        self.resolution = {}
        self.events = []  # ("opened"|"closed", juego, cuerpo)
        self.fail_commit = None  # (estado, cuerpo) para forzar un error en commit
        self._i = 0
        hub = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, status, body, headers=None):
                raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else b"")
                self.send_response(status)
                if not isinstance(body, bytes):
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def _read(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                hub.requests.append((self.command, self.path, dict(self.headers), raw))
                return raw

            def _authorized(self):
                return self.headers.get("Authorization") == f"Bearer {hub.key}"

            def _hook(self, raw):
                parts = urlsplit(self.path)
                segs = parts.path.split("/")  # ['', 'api', 'hook', juego, accion]
                if len(segs) != 5:
                    return self._send(404, {"detail": {"code": "err.not_found", "params": {}}})
                game, action = unquote(segs[3]), segs[4]
                q = {k: v[0] for k, v in parse_qs(parts.query).items()}
                files = hub.files.setdefault(game, {})
                if action == "fingerprint" and self.command == "POST":
                    return self._send(200, hub.fingerprint(game, json.loads(raw or b"[]"), q.get("manifest") == "1"))
                if action == "files" and self.command == "PUT":
                    return self._put_file(game, q, raw)
                if action == "files" and self.command == "GET":
                    data = files.get(q.get("path", ""))
                    if data is None:
                        return self._send(404, {"detail": {"code": "err.hook.file_missing", "params": {}}})
                    rng = self.headers.get("Range")
                    if rng and rng.startswith("bytes="):
                        start = int(rng[6:].split("-")[0])
                        if start >= len(data):
                            return self._send(416, {"detail": {"code": None, "params": {}}})
                        part = data[start:]
                        return self._send(206, part, {"Content-Range": f"bytes {start}-{len(data) - 1}/{len(data)}"})
                    return self._send(200, data)
                if action == "commit":
                    return self._commit(game, json.loads(raw))
                if action == "resolution" and self.command == "PUT":
                    hub.resolution[game] = json.loads(raw)
                    return self._send(200, {"ok": True})
                if action in ("opened", "closed"):
                    hub.events.append((action, game, json.loads(raw) if raw else None))
                    return self._send(200, {"ok": True})
                return self._send(404, {"detail": {"code": "err.not_found", "params": {}}})

            def _put_file(self, game, q, raw):
                path, size, want = q["path"], int(q["size"]), q["sha256"]
                offset = int(q.get("offset", 0))
                have = hub.staging.setdefault(game, {}).get(path, b"")
                if offset != len(have):
                    return self._send(
                        409, {"detail": {"code": "err.hook.upload_offset_mismatch", "params": {"received": len(have)}}}
                    )
                data = have + raw
                if len(data) == size and sha(data) != want:
                    return self._send(422, {"detail": {"code": "err.hook.sha_mismatch", "params": {}}})
                hub.staging[game][path] = data
                return self._send(200, {"path": path, "received": len(data)})

            def _commit(self, game, body):
                if hub.fail_commit:
                    return self._send(*hub.fail_commit)
                staged = hub.staging.get(game, {})
                manifest = body["manifest"]
                if {e["path"] for e in manifest} != set(staged):
                    return self._send(409, {"detail": {"code": "err.hook.upload_incomplete", "params": {}}})
                hub.files[game] = dict(staged)
                hub.staging[game] = {}
                hub.base[game] = set_hash(hub.files[game])
                return self._send(200, {"outcome": "ok"})

            def do_POST(self):
                raw = self._read()
                if self.path.startswith("/api/hook/"):
                    return self._hook(raw) if self._authorized() else self._send(401, {"detail": {"code": "err.auth"}})
                if hub.redirect_to:
                    return self._send(307, None, {"Location": hub.redirect_to})
                self._send(*hub.create)

            def do_PUT(self):
                raw = self._read()
                if not self._authorized():
                    return self._send(401, {"detail": {"code": "err.auth"}})
                self._hook(raw)

            def do_GET(self):
                raw = self._read()
                if self.path.startswith("/api/hook/ping"):
                    if not self._authorized():
                        return self._send(401, {"detail": {"code": "err.auth"}})
                    return self._send(*hub.ping)
                if self.path.startswith("/api/games"):
                    if not self._authorized():
                        return self._send(401, {"detail": {"code": "err.auth"}})
                    return self._send(200, hub.games)
                if self.path.startswith("/api/hook/"):
                    return self._hook(raw) if self._authorized() else self._send(401, {"detail": {"code": "err.auth"}})
                i = min(hub._i, len(hub.script) - 1)
                hub._i += 1
                self._send(*hub.script[i])

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def fingerprint(self, game, manifest, with_manifest):
        files = self.files.get(game, {})
        hub_h, dev_h = set_hash(files), manifest_hash(manifest)
        base = self.base.get(game)
        out = {"hub": {"hash": hub_h}, "device_state": {"hash": dev_h}}
        if hub_h == dev_h:
            self.base[game] = hub_h
            return {**out, "action": "none"}
        if hub_h is None:
            action = "upload"
        elif dev_h is None:
            action = "download"
        elif base == hub_h:
            action = "upload"
        elif base == dev_h:
            action = "download"
        else:
            res = self.resolution.pop(game, None)
            if res and res["expect"] == {"hub": hub_h, "device": dev_h}:
                action = "upload" if res["winner"] == "device" else "download"
            else:
                return {**out, "action": "conflict"}
        if action == "download" and with_manifest:
            out["hub_manifest"] = [
                {"path": p, "sha256": sha(d), "size": len(d), "mtime": 1_700_000_000} for p, d in sorted(files.items())
            ]
        return {**out, "action": action}

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class FakeGitHub:
    """API de Releases de GitHub falsa (`GET .../releases/latest`). `response` = (estado, cuerpo bytes|dict|list, cabeceras);
    `delay` = segundos de espera antes de responder (para el tiempo agotado). Guarda cada petición (ruta y cabeceras)."""

    def __init__(self):
        self.requests = []
        self.response = (200, release(), {})
        self.delay = 0.0
        gh = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                gh.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
                if gh.delay:
                    time.sleep(gh.delay)
                status, body, headers = gh.response
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/repos/x/y/releases/latest"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def release(tag="v1.4.0", wheels=("checkpoint_client-1.2.0-py3-none-any.whl",), prerelease=False):
    """Cuerpo de una Release de GitHub con sus assets (los del hub, sin wheel, si `wheels` está vacío)."""
    base = "https://github.com/mcondepoGH/checkpoint/releases/download/" + tag
    assets = [{"name": n, "browser_download_url": f"{base}/{n}"} for n in wheels]
    assets.append({"name": "Checkpoint.zip", "browser_download_url": f"{base}/Checkpoint.zip"})
    return {"tag_name": tag, "draft": False, "prerelease": prerelease, "assets": assets}


@pytest.fixture
def fakegithub(monkeypatch):
    g = FakeGitHub()
    monkeypatch.setenv("CHECKPOINT_CLIENT_RELEASES_URL", g.url)
    yield g
    g.stop()


@pytest.fixture(autouse=True)
def never_real_github(monkeypatch):
    """Ningún test llega a GitHub de verdad: por defecto la consulta apunta a un puerto cerrado."""
    monkeypatch.setenv("CHECKPOINT_CLIENT_RELEASES_URL", "http://127.0.0.1:1/releases/latest")


@pytest.fixture
def fakehub():
    h = FakeHub()
    yield h
    h.stop()


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Directorio personal falso (HOME) y config del cliente dentro de él, como en un Linux de escritorio."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("CHECKPOINT_CLIENT_CONFIG_DIR", raising=False)
    return h


@pytest.fixture
def settings_dir(tmp_path):
    return str(tmp_path / "settings")


def _memory_keyring_class():
    """Llavero en memoria. `fail_set`/`fail_get`/`fail_delete` lanzan KeyringError."""
    from keyring import backend, errors

    class Memory(backend.KeyringBackend):
        priority = 1

        def __init__(self):
            super().__init__()
            self.items = {}
            self.fail_set = self.fail_get = self.fail_delete = False
            self.lose_on_set = False  # acepta la escritura pero no la guarda (backend roto)

        def set_password(self, service, username, password):
            if self.fail_set:
                raise errors.KeyringError("cartera bloqueada")
            if not self.lose_on_set:
                self.items[(service, username)] = password

        def get_password(self, service, username):
            if self.fail_get:
                raise errors.KeyringError("cartera bloqueada")
            return self.items.get((service, username))

        def delete_password(self, service, username):
            if self.fail_delete:
                raise errors.KeyringError("cartera bloqueada")
            if (service, username) not in self.items:
                raise errors.PasswordDeleteError("no existe")
            del self.items[(service, username)]

    return Memory


@pytest.fixture(autouse=True)
def no_real_keyring():
    """Nunca se toca el llavero real: por defecto no hay llavero (backend `fail`); los tests que lo necesitan piden
    `memory_keyring`."""
    import keyring
    from keyring.backends import fail

    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture
def memory_keyring(no_real_keyring):
    import keyring

    kr = _memory_keyring_class()()
    keyring.set_keyring(kr)
    return kr


@pytest.fixture(autouse=True)
def migration_not_warned(monkeypatch):
    """El aviso de migración fallida es de una vez por ejecución: cada test parte de «aún no avisado»."""
    from checkpoint_client import keystore

    monkeypatch.setattr(keystore, "_migration_warned", False)
