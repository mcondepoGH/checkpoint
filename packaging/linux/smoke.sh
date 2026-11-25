#!/usr/bin/env bash
# Smoke test del paquete de Linux: extrae el tarball, ejecuta install.sh --no-login --no-start en un HOME temporal (venv y
# dependencias reales; SIN systemd: SYSTEMCTL=false, el runner puede no tenerlo), arranca el hub SIN login desde el venv
# instalado (127.0.0.1, puerto libre, CHECKPOINT_HOME_DIR temporal), comprueba /api/session, la web (/) y el plugin de Deck,
# y al final ejecuta install.sh --uninstall. La unidad de systemd solo se comprueba como texto.
# Uso, desde cualquier carpeta (tras build.sh):  bash packaging/linux/smoke.sh [tarball]
# Sin argumento usa dist/checkpoint-<versión>-linux.tar.gz. Necesita Python 3 con venv y red (pip).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
TGZ="${1:-$ROOT/dist/checkpoint-$VERSION-linux.tar.gz}"
[ -f "$TGZ" ] || { echo "smoke.sh: no existe $TGZ: ejecuta antes build.sh" >&2; exit 1; }

WORK="$(mktemp -d)"
PID=""
cleanup() {
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    kill -TERM "$PID" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
    kill -KILL "$PID" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT
fail() { echo "smoke.sh: $*" >&2; [ -f "$WORK/hub.log" ] && { echo "--- log del hub ---" >&2; tail -n 40 "$WORK/hub.log" >&2; }; exit 1; }

tar -xzf "$TGZ" -C "$WORK"
APP="$WORK/checkpoint-$VERSION"
[ -d "$APP/backend/app" ] || fail "el tarball no trae checkpoint-$VERSION/backend/app"
[ -f "$APP/VERSION" ] && [ "$(tr -d '[:space:]' < "$APP/VERSION")" = "$VERSION" ] || fail "VERSION del tarball distinta de $VERSION"
[ -x "$APP/install.sh" ] || fail "install.sh falta o no es ejecutable"
HAS_DECK=0; [ -f "$APP/checkpoint-deck/out/Checkpoint.zip" ] && HAS_DECK=1

echo "== install.sh --no-login --no-start =="
H="$WORK/home-install"
mkdir -p "$H"
# env -u: ni XDG_* ni credenciales del que llama; SYSTEMCTL=false => install.sh ve «sin systemd de usuario» y no arranca nada.
inst() { env -u XDG_DATA_HOME -u XDG_CONFIG_HOME -u CHECKPOINT_USER -u CHECKPOINT_PASSWORD HOME="$H" SYSTEMCTL=false LOGINCTL=false \
  CHECKPOINT_INSTALL_WAIT=0 bash "$APP/install.sh" "$@"; }
inst --no-login --no-start || fail "install.sh falló"
CUR="$H/.local/share/checkpoint-app/current"
[ -L "$CUR" ] && [ -x "$CUR/venv/bin/python" ] && [ -f "$CUR/backend/app/cli.py" ] || fail "install.sh no dejó current/ con venv y código"
ENVF="$H/.config/checkpoint/checkpoint.env"
[ "$(stat -c %a "$ENVF")" = 600 ] || fail "$ENVF no es 0600"
! grep -q '^CHECKPOINT_PASSWORD=' "$ENVF" || fail "--no-login no debe guardar contraseña"
UNIT="$H/.config/systemd/user/checkpoint.service"
grep -q "^ExecStart=\"$CUR/venv/bin/python\" -m app.cli serve\$" "$UNIT" || fail "ExecStart de la unidad inesperado"
grep -q '^Environment=CHECKPOINT_RUNTIME=native$' "$UNIT" || fail "la unidad no fija CHECKPOINT_RUNTIME=native"
inst --upgrade --dry-run > "$WORK/dry.txt" || fail "install.sh --upgrade --dry-run falló"
inst --upgrade --no-start || fail "install.sh --upgrade (misma versión) falló"
[ "$(readlink "$CUR")" = "$VERSION" ] || fail "current no apunta a $VERSION tras --upgrade"

PORT="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
URL="http://127.0.0.1:$PORT"
echo "== arrancar el hub en $URL =="
# env -u: el entorno del que llama no debe colar credenciales (si las hubiera, el hub exigiría login). CHECKPOINT_RUNTIME=native
# evita que /.dockerenv (CI en contenedor, Distrobox...) haga creer al hub que corre en Docker.
(cd "$CUR/backend" && exec env -u CHECKPOINT_USER -u CHECKPOINT_PASSWORD CHECKPOINT_RUNTIME=native CHECKPOINT_HOME_DIR="$WORK/home" \
  "$CUR/venv/bin/python" -m app.cli serve --host 127.0.0.1 --port "$PORT") > "$WORK/hub.log" 2>&1 &
PID=$!

SESSION=""
for _ in $(seq 1 60); do
  kill -0 "$PID" 2>/dev/null || fail "el hub terminó antes de responder"
  SESSION="$(curl -fsS --max-time 3 "$URL/api/session" 2>/dev/null)" && break
  SESSION=""; sleep 1
done
[ -n "$SESSION" ] || fail "el hub no responde en $URL tras 60 s"
case "$SESSION" in *'"noLogin":true'*|*'"noLogin": true'*) ;; *) fail "se esperaba noLogin=true: $SESSION" ;; esac

CODE="$(curl -s -o "$WORK/index.html" -w '%{http_code}' --max-time 5 "$URL/")"
[ "$CODE" = 200 ] || fail "GET / devolvió $CODE"
cmp -s "$WORK/index.html" "$CUR/backend/static/index.html" || fail "GET / no devuelve el index.html del paquete"

CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL/api/deck/plugin")"
if [ "$HAS_DECK" = 1 ]; then
  [ "$CODE" = 200 ] || fail "GET /api/deck/plugin devolvió $CODE (el tarball lleva el zip)"
else
  echo "AVISO: el tarball no lleva el plugin de Deck; /api/deck/plugin devolvió $CODE"
fi

kill -TERM "$PID"
for _ in $(seq 1 20); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
if kill -0 "$PID" 2>/dev/null; then fail "el hub no paró con SIGTERM en 10 s"; fi
wait "$PID" 2>/dev/null || true
PID=""

echo "== install.sh --uninstall =="
inst --uninstall || fail "install.sh --uninstall falló"
[ ! -e "$CUR" ] && [ ! -e "$UNIT" ] || fail "--uninstall no quitó el código o la unidad"
[ -f "$ENVF" ] || fail "--uninstall no debe borrar las credenciales"
echo "OK: paquete de Linux $VERSION arranca sin login y sirve la web."
