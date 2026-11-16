"""Rutas y utilidades comunes: el plugin se prueba sin Decky (con un `decky` falso) y contra un hub falso por HTTP."""

import json
import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))


class FakeHub:
    """Hub falso. `script`: lista de (estado, cuerpo, cabeceras) que se sirve en orden a `GET /requests/{id}`;
    la última respuesta se repite. Guarda cada petición recibida (método, ruta con consulta, cabeceras, cuerpo)."""

    def __init__(self):
        self.requests = []
        self.create = (201, {"id": "rid1", "code": "123456", "secret": "SECRET-xyz", "expires_in": 600}, {})
        self.script = []
        self.ping = (200, {"ok": True, "user": "admin", "device": "steam-deck-ab12"}, {})
        self.redirect_to = None
        # Plugin publicado por el hub: `deck_zip` (bytes) e `deck_info` (dict, o None = lo calcula del zip).
        # `deck_cut`: el zip se corta a mitad (la conexión se cierra tras enviar esos bytes).
        self.deck_zip = None
        self.deck_info = None
        self.deck_cut = None
        self._i = 0
        hub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body, headers):
                raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else b"")
                self.send_response(status)
                self.send_header("Content-Type", "application/zip" if isinstance(body, bytes) else "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def _record(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n).decode() if n else ""
                hub.requests.append((self.command, self.path, dict(self.headers), body))

            def _deck(self):
                import hashlib

                z = hub.deck_zip
                if z is None:
                    if self.path == "/api/deck/plugin/info":
                        return self._send(200, {"available": False}, {})
                    return self._send(404, {"detail": {"code": "err.deck.plugin_missing", "params": {}}}, {})
                sha = hashlib.sha256(z).hexdigest()
                if self.path == "/api/deck/plugin/info":
                    info = hub.deck_info or {
                        "available": True, "version": None, "protocol": None, "sha256": sha, "size": len(z),
                        "filename": "Checkpoint.zip",
                    }
                    return self._send(200, info, {})
                if self.path == "/api/deck/plugin.sha256":
                    raw = f"{sha}  Checkpoint.zip\n".encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if hub.deck_cut is not None:  # promete todo el zip y corta: Content-Length > bytes enviados
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(z)))
                    self.end_headers()
                    self.wfile.write(z[: hub.deck_cut])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self._send(200, z, {"X-Checkpoint-Plugin-Sha256": sha})

            def do_POST(self):
                self._record()
                if hub.redirect_to:
                    return self._send(307, None, {"Location": hub.redirect_to})
                self._send(*hub.create)

            def do_GET(self):
                self._record()
                if self.path.startswith("/api/hook/ping"):
                    return self._send(*hub.ping)
                if self.path.startswith("/api/deck/plugin"):
                    return self._deck()
                i = min(hub._i, len(hub.script) - 1)
                hub._i += 1
                self._send(*hub.script[i])

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fakehub():
    h = FakeHub()
    yield h
    h.stop()


@pytest.fixture
def settings_dir(tmp_path):
    return str(tmp_path / "settings")


@pytest.fixture
def fake_decky(tmp_path, monkeypatch):
    """Módulo `decky` falso con el logger real (para capturar logs con caplog)."""
    m = ModuleType("decky")
    m.logger = logging.getLogger("decky-fake")
    m.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path / "settings")
    # Plugin «instalado» de verdad en una carpeta temporal (versión 0.1.0), como `~/homebrew/plugins/Checkpoint`
    plug = tmp_path / "plugins" / "Checkpoint"
    (plug / "py_modules").mkdir(parents=True)
    (plug / "package.json").write_text(json.dumps({"name": "checkpoint-deck", "version": "0.1.0", "checkpointProtocol": 1}))
    (plug / "main.py").write_text("# main viejo\n")
    (plug / "plugin.json").write_text('{"name": "Checkpoint"}')
    (tmp_path / "runtime").mkdir()
    m.DECKY_PLUGIN_DIR = str(plug)
    m.DECKY_PLUGIN_RUNTIME_DIR = str(tmp_path / "runtime")
    monkeypatch.setitem(sys.modules, "decky", m)
    monkeypatch.delitem(sys.modules, "main", raising=False)
    monkeypatch.syspath_prepend(str(ROOT))
    return m


class ScriptHub:
    """Hub falso genérico. `handler(req) -> (estado, cuerpo, cabeceras)`; `cuerpo` puede ser bytes (se envía tal cual) u
    objeto JSON. `req` tiene method, path (con consulta), headers (minúsculas), body (bytes). Todo se guarda en
    `requests`. Si el handler lanza `Drop(n)`, se corta la conexión tras enviar n bytes del cuerpo prometido."""

    class Drop(Exception):
        def __init__(self, partial: bytes = b""):
            self.partial = partial

    class Req:
        def __init__(self, method, path, headers, body):
            self.method, self.path, self.headers, self.body = method, path, headers, body

    def __init__(self, handler):
        self.handler, self.requests = handler, []
        hub = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _go(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                req = ScriptHub.Req(self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body)
                hub.requests.append(req)
                try:
                    status, out, headers = hub.handler(req)
                except ScriptHub.Drop as d:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(d.partial) + 100))
                    self.end_headers()
                    self.wfile.write(d.partial)
                    self.wfile.flush()
                    self.close_connection = True
                    return
                raw = out if isinstance(out, bytes) else (json.dumps(out).encode() if out is not None else b"")
                self.send_response(status)
                if not isinstance(out, bytes):
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_PUT = _go

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def scripthub():
    made = []

    def make(handler):
        h = ScriptHub(handler)
        made.append(h)
        return h

    yield make
    for h in made:
        h.stop()


@pytest.fixture(autouse=True)
def _sqlite_sin_fsync(monkeypatch):
    """Las bases de Lutris que crean los tests no necesitan durabilidad: sin fsync por commit (en el disco del NAS cada
    commit costaba ~0,1 s). Solo las conexiones normales; las de solo lectura por URI que abre el código real no se tocan."""
    import sqlite3

    real = sqlite3.connect

    def connect(*a, **kw):
        con = real(*a, **kw)
        if not kw.get("uri"):
            con.execute("PRAGMA synchronous=OFF")
        return con

    monkeypatch.setattr(sqlite3, "connect", connect)


@pytest.fixture(autouse=True)
def _sin_fsync(monkeypatch):
    """Los tests no necesitan durabilidad: sin fsync en las escrituras atómicas (el hub real y el plugin; en el disco del
    NAS cada una costaba del orden de 0,1 s). El temporal + rename, que es lo que se comprueba, se conserva."""
    import os

    monkeypatch.setattr(os, "fsync", lambda fd: None)
