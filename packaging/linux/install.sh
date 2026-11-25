#!/usr/bin/env bash
# Instalador de Checkpoint para Linux (hub nativo, sin Docker). Instala, actualiza (--upgrade) y desinstala (--uninstall)
# desde la carpeta extraída del tarball checkpoint-<versión>-linux.tar.gz. Todo es POR USUARIO: no pide root ni toca el sistema.
#
# DISEÑO (dónde va cada cosa; el código se separa de los datos para poder actualizar y volver atrás sin tocar nada del usuario):
#   código  $XDG_DATA_HOME/checkpoint-app/<versión>/   (por defecto ~/.local/share/checkpoint-app/<versión>/)
#             backend/, VERSION, checkpoint-deck/, install.sh y venv/ (un venv POR versión, con el Python del sistema)
#           $XDG_DATA_HOME/checkpoint-app/current      enlace a la versión activa: la unidad apunta SIEMPRE a él, así
#                                                      actualizar es cambiar el enlace (atómico) y volver atrás es devolverlo.
#                                                      Se conservan la versión activa y la anterior.
#   entorno $XDG_CONFIG_HOME/checkpoint/checkpoint.env (0600; ~/.config/checkpoint/checkpoint.env): usuario y contraseña
#           (+ host y puerto si se pasan). Vive FUERA del código para que actualizar o desinstalar no lo toque.
#   unidad  $XDG_CONFIG_HOME/systemd/user/checkpoint.service
#   datos   $XDG_DATA_HOME/checkpoint (native_home() del hub: config, keys, datos). Este script NO los crea y NUNCA los borra
#           salvo con --uninstall --purge (que pide confirmación escrita).
# Variables para pruebas o instalaciones a medida: CHECKPOINT_INSTALL_PREFIX (carpeta del código en vez de checkpoint-app),
# SYSTEMCTL, LOGINCTL, PYTHON (intérprete a usar), CHECKPOINT_MIN_PYTHON (3.12 por defecto), CHECKPOINT_INSTALL_WAIT
# (segundos esperando a que el hub responda tras arrancar; 20 por defecto, 0 no espera), además de HOME y XDG_*.
# La unidad fija Environment=CHECKPOINT_RUNTIME=native: en contenedores /.dockerenv haría creer al hub que corre en Docker.
set -euo pipefail
umask 077

usage() {
  cat <<'USAGE'
Uso: install.sh [opciones]          (instala; con una instalación previa, usa --upgrade)
     install.sh --upgrade           actualiza a la versión de este tarball (conserva el .env, no pide credenciales)
     install.sh --uninstall [--purge]

Instala Checkpoint (hub nativo, sin Docker) como servicio de usuario de systemd. No necesita root.

Credenciales (el hub las exige salvo en 127.0.0.1):
  (sin opciones)         con terminal, pregunta usuario y contraseña (mínimo 8 caracteres, máximo 72 bytes);
                         con Intro vacío en la contraseña genera una segura y la muestra UNA vez
  --no-login             sin usuario ni contraseña: el hub solo acepta 127.0.0.1 (como en Windows)
  --user USUARIO --password-file FICHERO
                         sin terminal: la contraseña es la primera línea del fichero (nunca va en la línea de comandos)
  CHECKPOINT_USER y CHECKPOINT_PASSWORD
                         alternativa por variables de entorno
Opciones:
  --host HOST            dirección de escucha (por defecto 127.0.0.1; otra exige credenciales)
  --port PUERTO          puerto (por defecto 8088)
  --no-start             instala los ficheros y la unidad, pero no la habilita ni la arranca
  --enable-linger        ejecuta loginctl enable-linger para arrancar sin iniciar sesión (si no, solo avisa)
  --dry-run              muestra lo que haría sin cambiar nada
  --purge                con --uninstall: borra TAMBIÉN datos, claves y credenciales (pide escribir BORRAR)
  -h, --help             esta ayuda
USAGE
}

say() { printf '%s\n' "$*"; }
warn() { printf 'AVISO: %s\n' "$*" >&2; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
bad_usage() { printf 'install.sh: %s\nPrueba install.sh --help\n' "$*" >&2; exit 2; }
plan() { printf '[dry-run] %s\n' "$*"; }

MODE=install UPGRADE=0 NO_LOGIN=0 NO_START=0 DRY=0 PURGE=0 ENABLE_LINGER=0
OPT_USER="" OPT_PWFILE="" OPT_HOST="" OPT_PORT="" HAVE_HOST=0 HAVE_PORT=0
CREATED_NEW="" TMPFILES=()

# shellcheck disable=SC2329  # la invoca el trap
cleanup() {
  local f
  for f in "${TMPFILES[@]+"${TMPFILES[@]}"}"; do rm -rf "$f"; done
  if [ -n "$CREATED_NEW" ]; then
    rm -rf "$CREATED_NEW"
    rmdir "$(dirname "$CREATED_NEW")" 2>/dev/null || true
  fi
}
trap cleanup EXIT

need_value() { [ "$1" -ge 2 ] || bad_usage "$2 necesita un valor."; }
parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      -h|--help) usage; exit 0 ;;
      --upgrade) UPGRADE=1; shift ;;
      --uninstall) MODE=uninstall; shift ;;
      --purge) PURGE=1; shift ;;
      --no-login) NO_LOGIN=1; shift ;;
      --no-start) NO_START=1; shift ;;
      --enable-linger) ENABLE_LINGER=1; shift ;;
      --dry-run) DRY=1; shift ;;
      --user) need_value $# "$1"; OPT_USER="$2"; shift 2 ;;
      --password-file) need_value $# "$1"; OPT_PWFILE="$2"; shift 2 ;;
      --host) need_value $# "$1"; OPT_HOST="$2"; HAVE_HOST=1; shift 2 ;;
      --port) need_value $# "$1"; OPT_PORT="$2"; HAVE_PORT=1; shift 2 ;;
      --password|--password=*) bad_usage "la contraseña nunca va en la línea de comandos: usa --password-file, CHECKPOINT_PASSWORD o el terminal." ;;
      *) bad_usage "opción desconocida: $1" ;;
    esac
  done
  if [ "$PURGE" = 1 ] && [ "$MODE" != uninstall ]; then bad_usage "--purge solo se usa junto con --uninstall."; fi
  if [ "$MODE" = uninstall ] && [ "$UPGRADE" = 1 ]; then bad_usage "--upgrade y --uninstall no se combinan."; fi
}

# ---------------------------------------------------------------- rutas

init_paths() {
  [ -n "${HOME:-}" ] || die "HOME no está definido."
  USER_NAME="${USER:-$(id -un)}"
  local data_base="${XDG_DATA_HOME:-$HOME/.local/share}" conf_base="${XDG_CONFIG_HOME:-$HOME/.config}"
  APP_BASE="${CHECKPOINT_INSTALL_PREFIX:-$data_base/checkpoint-app}"
  CURRENT="$APP_BASE/current"
  CONF_DIR="$conf_base/checkpoint"
  ENV_FILE="$CONF_DIR/checkpoint.env"
  UNIT_DIR="$conf_base/systemd/user"
  UNIT_FILE="$UNIT_DIR/checkpoint.service"
  DATA_HOME="$data_base/checkpoint"
  SYSTEMCTL="${SYSTEMCTL:-systemctl}"
  LOGINCTL="${LOGINCTL:-loginctl}"
  local p
  for p in "$APP_BASE" "$CONF_DIR" "$UNIT_DIR" "$DATA_HOME"; do
    case "$p" in /*) ;; *) die "la ruta $p no es absoluta (revisa HOME, XDG_* y CHECKPOINT_INSTALL_PREFIX)." ;; esac
    case "$p" in
      *'"'*|*\\*|*$'\n'*) die "la ruta $p lleva comillas, barras invertidas o saltos de línea: usa otra, no se pueden escribir en la unidad de systemd." ;;
    esac
  done
}

sc() { "$SYSTEMCTL" --user "$@"; }
detect_systemd() { if sc show-environment >/dev/null 2>&1; then HAVE_SYSTEMD=1; else HAVE_SYSTEMD=0; fi; }

# Escapes: en la unidad, % y $ se duplican (especificadores y variables); en el .env, \ y " (comillas dobles de systemd).
unit_escape() { local s="${1//%/%%}"; printf '%s' "${s//\$/\$\$}"; }
env_quote() { local v="${1//\\/\\\\}"; v="${v//\"/\\\"}"; printf '"%s"' "$v"; }
env_get() { [ -f "$ENV_FILE" ] || return 0; sed -n "s/^$1=\"\\(.*\\)\"\$/\\1/p" "$ENV_FILE" | head -n1; }

write_atomic() { # $1 = destino, $2 = modo; contenido por stdin
  local tmp
  tmp="$(mktemp "$(dirname "$1")/.checkpoint.XXXXXX")"
  TMPFILES+=("$tmp")
  cat > "$tmp"
  chmod "$2" "$tmp"
  mv -f "$tmp" "$1"
}

# ---------------------------------------------------------------- Python

find_python() {
  MIN_PY="${CHECKPOINT_MIN_PYTHON:-3.12}"
  case "$MIN_PY" in [0-9]*.[0-9]*) ;; *) die "CHECKPOINT_MIN_PYTHON debe ser del estilo 3.12." ;; esac
  local maj="${MIN_PY%%.*}" min="${MIN_PY#*.}" c path tried=""
  py_ok() { "$1" -c "import sys; sys.exit(0 if sys.version_info >= ($maj, $min) else 1)" >/dev/null 2>&1; }
  PY=""
  if [ -n "${PYTHON:-}" ]; then
    py_ok "$PYTHON" || die "$PYTHON no es Python $MIN_PY o superior (o no existe). Checkpoint necesita Python $MIN_PY o superior; no instalo nada."
    PY="$PYTHON"
  else
    for c in python3 python3.14 python3.13 python3.12; do
      path="$(command -v "$c" 2>/dev/null || true)"
      [ -n "$path" ] || continue
      tried="$tried $c"
      if py_ok "$path"; then PY="$path"; break; fi
    done
    [ -n "$PY" ] || die "Checkpoint necesita Python $MIN_PY o superior y no lo encuentro${tried:+ (probé:$tried)}. Instálalo con el gestor de paquetes de tu distribución y vuelve a ejecutar este script; no instalo nada."
  fi
  "$PY" -c "import venv, ensurepip" >/dev/null 2>&1 \
    || die "A $PY le falta el módulo venv (o ensurepip, que trae pip). En Debian o Ubuntu: sudo apt install python3-venv. No instalo nada."
}

# ---------------------------------------------------------------- credenciales

# Valida el usuario ("user") o la contraseña ("pw") que llega por stdin. 0 = bien; 1 corta, 2 larga, 3 control, 4 vacía.
CHECK_CODE='
import sys
b = sys.stdin.buffer.read()
try:
    s = b.decode("utf-8")
except UnicodeDecodeError:
    sys.exit(3)
if not s:
    sys.exit(4)
if any(ord(c) < 32 or ord(c) == 127 for c in s):
    sys.exit(3)
if sys.argv[1] == "pw":
    if len(s) < 8:
        sys.exit(1)
    if len(b) > 72:
        sys.exit(2)
elif len(b) > 64:
    sys.exit(2)
'
cred_check() { # $1 = user|pw, $2 = valor. Imprime el motivo en stderr y devuelve 1 si no vale.
  local rc=0
  printf '%s' "$2" | "$PY" -I -c "$CHECK_CODE" "$1" || rc=$?
  case "$rc" in
    0) return 0 ;;
    1) warn "La contraseña debe tener al menos 8 caracteres." ;;
    2) if [ "$1" = pw ]; then warn "La contraseña no puede pasar de 72 bytes (límite de bcrypt; una letra con tilde ocupa 2)."; else warn "El usuario no puede pasar de 64 bytes."; fi ;;
    3) warn "No admito caracteres de control (tabuladores, saltos de línea...) ni texto que no sea UTF-8 en el usuario ni en la contraseña." ;;
    *) if [ "$1" = pw ]; then warn "La contraseña no puede estar vacía."; else warn "El usuario no puede estar vacío."; fi ;;
  esac
  return 1
}

CRED_USER="" CRED_PW="" GENERATED=0
ask_credentials() { # con terminal; pregunta solo lo que falta
  local p2
  if [ -z "$CRED_USER" ]; then
    for _ in 1 2 3 4 5; do
      printf 'Usuario de Checkpoint: ' >&2
      IFS= read -r CRED_USER || die "no pude leer el usuario."
      if cred_check user "$CRED_USER"; then break; fi
      CRED_USER=""
    done
    [ -n "$CRED_USER" ] || die "demasiados intentos con el usuario."
  fi
  if [ -z "$CRED_PW" ]; then
    for _ in 1 2 3 4 5; do
      printf 'Contraseña (mínimo 8 caracteres; Intro vacío para generar una segura): ' >&2
      IFS= read -rs CRED_PW || die "no pude leer la contraseña."
      printf '\n' >&2
      if [ -z "$CRED_PW" ]; then
        CRED_PW="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(18))')"
        GENERATED=1
        break
      fi
      if cred_check pw "$CRED_PW"; then
        printf 'Repite la contraseña: ' >&2
        IFS= read -rs p2 || die "no pude leer la contraseña."
        printf '\n' >&2
        if [ "$p2" = "$CRED_PW" ]; then break; fi
        warn "Las contraseñas no coinciden."
      fi
      CRED_PW=""
    done
    [ -n "$CRED_PW" ] || die "demasiados intentos con la contraseña."
  fi
}

resolve_credentials() {
  # Un .env existente manda (instalación previa o tras --uninstall): no se pregunta nada ni se pisa.
  KEEP_ENV=0
  if [ -f "$ENV_FILE" ]; then
    KEEP_ENV=1
    unset CHECKPOINT_USER CHECKPOINT_PASSWORD
    if [ -n "$OPT_USER$OPT_PWFILE$OPT_HOST$OPT_PORT" ] || [ "$NO_LOGIN" = 1 ]; then
      warn "Ya existe $ENV_FILE: lo conservo tal cual e ignoro --user, --password-file, --no-login, --host y --port. Edítalo a mano para cambiarlos."
    fi
    return 0
  fi
  if [ "$NO_LOGIN" = 1 ]; then
    if [ "$HAVE_HOST" = 1 ] && ! is_local_host "$OPT_HOST"; then
      die "--no-login solo vale con 127.0.0.1 (o ::1 o localhost): con --host $OPT_HOST hacen falta usuario y contraseña."
    fi
    return 0
  fi
  CRED_USER="${OPT_USER:-${CHECKPOINT_USER:-}}"
  if [ -n "$OPT_PWFILE" ]; then
    [ -r "$OPT_PWFILE" ] && [ -f "$OPT_PWFILE" ] || die "no puedo leer el fichero de contraseña $OPT_PWFILE."
    IFS= read -r CRED_PW < "$OPT_PWFILE" || true
    CRED_PW="${CRED_PW%$'\r'}"
  else
    CRED_PW="${CHECKPOINT_PASSWORD:-}"
  fi
  unset CHECKPOINT_USER CHECKPOINT_PASSWORD  # que no se hereden en pip ni en ningún subproceso
  if [ -z "$CRED_USER" ] || [ -z "$CRED_PW" ]; then
    if [ -t 0 ]; then
      if [ "$DRY" = 1 ]; then return 0; fi
      ask_credentials
      return 0
    fi
    die "faltan el usuario o la contraseña y no hay terminal para preguntarlos. Usa las variables CHECKPOINT_USER y CHECKPOINT_PASSWORD, o --user USUARIO --password-file FICHERO, o --no-login (hub solo en 127.0.0.1)."
  fi
  cred_check user "$CRED_USER" || exit 1
  cred_check pw "$CRED_PW" || exit 1
}

is_local_host() {
  local h="${1,,}"
  case "$h" in \[*\]) h="${h:1:${#h}-2}" ;; esac
  case "$h" in 127.0.0.1|::1|localhost) return 0 ;; *) return 1 ;; esac
}

validate_net() {
  if [ "$HAVE_PORT" = 1 ]; then
    case "$OPT_PORT" in
      ''|*[!0-9]*) die "puerto no válido: «$OPT_PORT» (un número de 1 a 65535)." ;;
    esac
    [ "$OPT_PORT" -ge 1 ] && [ "$OPT_PORT" -le 65535 ] || die "puerto no válido: «$OPT_PORT» (un número de 1 a 65535)."
  fi
  if [ "$HAVE_HOST" = 1 ]; then
    case "$OPT_HOST" in
      ''|*[[:space:]\"\\\$\`]*) die "host no válido: «$OPT_HOST»." ;;
    esac
  fi
  if [ "$NO_LOGIN" = 1 ] && [ "$HAVE_HOST" = 1 ] && ! is_local_host "$OPT_HOST"; then
    die "--no-login solo vale con 127.0.0.1 (o ::1 o localhost): con --host $OPT_HOST hacen falta usuario y contraseña."
  fi
}

# ---------------------------------------------------------------- unidad y entorno

unit_text() {
  cat <<UNIT
[Unit]
Description=Checkpoint (hub de sincronización de partidas guardadas)

[Service]
Type=simple
WorkingDirectory=$(unit_escape_noquote "$CURRENT")/backend
EnvironmentFile=$(unit_escape_noquote "$ENV_FILE")
Environment=CHECKPOINT_RUNTIME=native
ExecStart="$(unit_escape "$CURRENT")/venv/bin/python" -m app.cli serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
}
unit_escape_noquote() { printf '%s' "${1//%/%%}"; }  # fuera de ExecStart $ no se interpreta; solo los especificadores %

env_text() {
  printf '%s\n' "# Entorno del servicio de Checkpoint (lo lee systemd con EnvironmentFile). Permisos 0600."
  printf '%s\n' "# Tras editarlo: systemctl --user restart checkpoint"
  if [ "$NO_LOGIN" = 1 ]; then
    printf '%s\n' "# Sin usuario ni contraseña (--no-login): el hub solo acepta 127.0.0.1."
  else
    printf 'CHECKPOINT_USER=%s\n' "$(env_quote "$CRED_USER")"
    printf 'CHECKPOINT_PASSWORD=%s\n' "$(env_quote "$CRED_PW")"
  fi
  if [ "$HAVE_HOST" = 1 ]; then printf 'CHECKPOINT_HOST=%s\n' "$(env_quote "$OPT_HOST")"; fi
  if [ "$HAVE_PORT" = 1 ]; then printf 'CHECKPOINT_PORT=%s\n' "$(env_quote "$OPT_PORT")"; fi
}

# ---------------------------------------------------------------- instalar / actualizar

hub_url() {
  local h p
  h="$(env_get CHECKPOINT_HOST)"; p="$(env_get CHECKPOINT_PORT)"
  [ "$HAVE_HOST" = 1 ] && [ "$KEEP_ENV" = 0 ] && h="$OPT_HOST"
  [ -n "$h" ] || h=127.0.0.1
  [ -n "$p" ] || p=8088
  case "$h" in 0.0.0.0) h=127.0.0.1 ;; ::) h=::1 ;; esac
  case "$h" in *:*) case "$h" in \[*) ;; *) h="[$h]" ;; esac ;; esac
  printf 'http://%s:%s' "$h" "$p"
}

copy_version() { # crea $NEW con el código y el venv; si ya está completo lo reutiliza
  if [ -f "$NEW/.instalado" ]; then
    say "La versión $VER ya está en $NEW: la reutilizo."
    return 0
  fi
  rm -rf "$NEW"
  mkdir -p "$APP_BASE"
  CREATED_NEW="$NEW"
  mkdir "$NEW"
  mkdir "$NEW/backend"
  cp -R "$SRC/backend/app" "$NEW/backend/app"
  find "$NEW" \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} +
  cp "$SRC/backend/requirements.txt" "$NEW/backend/requirements.txt"
  [ ! -d "$SRC/backend/static" ] || cp -R "$SRC/backend/static" "$NEW/backend/static"
  cp "$SRC/VERSION" "$NEW/VERSION"
  cp "$SRC/install.sh" "$NEW/install.sh"
  chmod 755 "$NEW/install.sh"
  if [ -f "$SRC/checkpoint-deck/out/Checkpoint.zip" ]; then
    mkdir -p "$NEW/checkpoint-deck/out"
    cp "$SRC/checkpoint-deck/out/Checkpoint.zip" "$NEW/checkpoint-deck/out/Checkpoint.zip"
  fi
  say "Creando el entorno de Python (venv) e instalando las dependencias; puede tardar un minuto..."
  "$PY" -m venv "$NEW/venv" || die "no pude crear el venv en $NEW/venv."
  "$NEW/venv/bin/python" -m pip install --quiet --disable-pip-version-check -r "$NEW/backend/requirements.txt" \
    || die "no se pudieron instalar las dependencias (pip). ¿Hay red? No he cambiado nada de tu instalación anterior."
  : > "$NEW/.instalado"
  CREATED_NEW=""
}

point_current() { # $1 = versión; cambio atómico del enlace
  ln -sfn "$1" "$APP_BASE/.current.tmp"
  mv -T "$APP_BASE/.current.tmp" "$CURRENT"
}

restore_unit() { # $1 = copia de la unidad anterior ("" si no había)
  if [ -n "$1" ]; then cp -p "$1" "$UNIT_FILE"; else rm -f "$UNIT_FILE"; fi
  if [ "$HAVE_SYSTEMD" = 1 ]; then sc daemon-reload >/dev/null 2>&1 || true; fi
}

prune_versions() {
  local d name keep1 keep2
  keep1="$(basename "$(readlink "$CURRENT")")"; keep2="${PREV:-}"
  for d in "$APP_BASE"/*/; do
    d="${d%/}"; name="$(basename "$d")"
    [ ! -L "$d" ] && [ -f "$d/.instalado" ] || continue  # current es un enlace a una carpeta: no se toca
    [ "$name" != "$keep1" ] && [ "$name" != "$keep2" ] || continue
    rm -rf "$d"
  done
}

wait_hub() {
  local n="${CHECKPOINT_INSTALL_WAIT:-20}" url i
  [ "$n" -gt 0 ] 2>/dev/null || return 1
  url="$(hub_url)/api/session"
  for ((i = 0; i < n; i++)); do
    if "$PY" -I -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=1)' "$url" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

linger_check() {
  [ "$HAVE_SYSTEMD" = 1 ] || return 0
  local state
  state="$("$LOGINCTL" show-user "$USER_NAME" -p Linger 2>/dev/null || true)"
  [ "$state" = "Linger=no" ] || return 0
  if [ "$ENABLE_LINGER" = 1 ]; then
    if "$LOGINCTL" enable-linger "$USER_NAME"; then say "Activado loginctl enable-linger: Checkpoint arrancará con el equipo, sin iniciar sesión."; return 0; fi
    warn "No pude activar enable-linger. Hazlo tú con: loginctl enable-linger $USER_NAME"
    return 0
  fi
  warn "Sin sesión iniciada systemd detiene los servicios de usuario: Checkpoint no arrancará al encender el equipo hasta que entres. Para que arranque solo: loginctl enable-linger $USER_NAME (o vuelve a ejecutar con --enable-linger)."
}

do_install() {
  find_python
  SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  [ -d "$SRC/backend/app" ] && [ -f "$SRC/backend/requirements.txt" ] && [ -f "$SRC/VERSION" ] \
    || die "ejecuta install.sh desde la carpeta extraída del tarball (junto a backend/ y VERSION)."
  VER="$(tr -d '[:space:]' < "$SRC/VERSION")"
  case "$VER" in ''|*[!0-9A-Za-z._-]*|.*) die "VERSION no válida: «$VER»." ;; esac
  NEW="$APP_BASE/$VER"
  PREV=""
  if [ -L "$CURRENT" ]; then PREV="$(basename "$(readlink "$CURRENT")")"; fi
  EXISTING=0
  if [ -L "$CURRENT" ] || [ -e "$UNIT_FILE" ]; then EXISTING=1; fi
  if [ "$EXISTING" = 1 ] && [ "$UPGRADE" = 0 ]; then
    die "ya hay una instalación de Checkpoint${PREV:+ (versión $PREV)}. Para actualizar usa install.sh --upgrade; para quitarla, install.sh --uninstall."
  fi
  detect_systemd
  resolve_credentials

  if [ "$DRY" = 1 ]; then
    plan "Python: $PY"
    plan "Instalaría Checkpoint $VER en $NEW (código, venv y dependencias)."
    plan "Apuntaría $CURRENT a $VER${PREV:+ (ahora apunta a $PREV)}."
    if [ "$KEEP_ENV" = 1 ]; then plan "Conservaría $ENV_FILE tal cual."
    elif [ "$NO_LOGIN" = 1 ]; then plan "Escribiría $ENV_FILE (0600) sin usuario ni contraseña (--no-login)."
    elif [ -n "$CRED_USER" ]; then plan "Escribiría $ENV_FILE (0600) con el usuario $CRED_USER y la contraseña indicada (no se muestra)."
    else plan "Pediría usuario y contraseña por el terminal y escribiría $ENV_FILE (0600)."; fi
    plan "Escribiría la unidad $UNIT_FILE."
    if [ "$HAVE_SYSTEMD" = 0 ]; then plan "No hay systemd de usuario: no arrancaría nada."
    elif [ "$NO_START" = 1 ]; then plan "systemctl --user daemon-reload (sin habilitar ni arrancar: --no-start)."
    elif [ "$EXISTING" = 1 ]; then plan "systemctl --user daemon-reload y restart checkpoint."
    else plan "systemctl --user daemon-reload y enable --now checkpoint."; fi
    return 0
  fi

  copy_version
  if [ "$KEEP_ENV" = 0 ]; then
    mkdir -p "$CONF_DIR"
    chmod 700 "$CONF_DIR"
    env_text | write_atomic "$ENV_FILE" 600
  else
    say "Conservo las credenciales y la configuración de $ENV_FILE."
  fi
  point_current "$VER"
  say "Instalada la versión $VER en $NEW (enlace $CURRENT)."

  mkdir -p "$UNIT_DIR"
  UNIT_BACKUP=""
  if [ -e "$UNIT_FILE" ]; then
    UNIT_BACKUP="$(mktemp)"
    TMPFILES+=("$UNIT_BACKUP")
    cp -p "$UNIT_FILE" "$UNIT_BACKUP"
  fi
  unit_text | write_atomic "$UNIT_FILE" 644

  if [ "$HAVE_SYSTEMD" = 0 ]; then
    warn "No hay systemd de usuario en esta sesión (systemctl --user no responde): dejo los ficheros instalados pero no arranco nada. Para arrancarlo a mano:"
    say "  cd \"$CURRENT/backend\" && set -a && . \"$ENV_FILE\" && set +a && CHECKPOINT_RUNTIME=native \"$CURRENT/venv/bin/python\" -m app.cli serve"
    finish_credentials_note
    return 0
  fi

  if [ "$NO_START" = 1 ]; then
    sc daemon-reload || warn "No pude ejecutar systemctl --user daemon-reload."
    if [ "$EXISTING" = 1 ]; then say "Para aplicar la actualización: systemctl --user restart checkpoint"
    else say "No lo he arrancado (--no-start). Para habilitarlo y arrancarlo: systemctl --user enable --now checkpoint"; fi
    finish_credentials_note
    linger_check
    return 0
  fi

  if [ "$EXISTING" = 1 ]; then
    if sc daemon-reload && sc restart checkpoint; then :; else
      if [ -n "$PREV" ] && [ "$PREV" != "$VER" ]; then
        point_current "$PREV"
        restore_unit "$UNIT_BACKUP"
        sc restart checkpoint >/dev/null 2>&1 || true
        die "no pude reiniciar Checkpoint con la versión $VER: he vuelto a la $PREV. Mira el motivo con: journalctl --user -u checkpoint -n 50"
      fi
      restore_unit "$UNIT_BACKUP"
      die "no pude reiniciar Checkpoint. Mira el motivo con: journalctl --user -u checkpoint -n 50"
    fi
  else
    if sc daemon-reload && sc enable --now checkpoint; then :; else
      restore_unit "$UNIT_BACKUP"
      die "no pude habilitar y arrancar la unidad de Checkpoint (los ficheros quedan instalados en $APP_BASE). Mira el motivo con: journalctl --user -u checkpoint -n 50"
    fi
  fi
  prune_versions

  if wait_hub; then
    say "Checkpoint $VER está en marcha: $(hub_url)"
  elif [ "${CHECKPOINT_INSTALL_WAIT:-20}" -gt 0 ] 2>/dev/null; then
    warn "El hub aún no respondió en $(hub_url) tras esperar ${CHECKPOINT_INSTALL_WAIT:-20} s: no respondió. Mira el motivo con: journalctl --user -u checkpoint -n 50"
  else
    say "Checkpoint $VER arrancado: $(hub_url)"
  fi
  finish_credentials_note
  linger_check
  say "Para actualizar más adelante: extrae el tarball nuevo y ejecuta ./install.sh --upgrade. Para quitarlo: $CURRENT/install.sh --uninstall"
}

finish_credentials_note() {
  if [ "$KEEP_ENV" = 1 ]; then return 0; fi
  if [ "$NO_LOGIN" = 1 ]; then
    say "Sin usuario ni contraseña: el hub solo se abre desde este equipo (127.0.0.1)."
  else
    say "Entra con el usuario «$CRED_USER». Las credenciales están en $ENV_FILE (solo lectura para ti, 0600)."
    if [ "$GENERATED" = 1 ]; then
      say "Contraseña generada (se muestra solo ahora; guárdala): $CRED_PW"
    fi
  fi
}

# ---------------------------------------------------------------- desinstalar

safe_rm_dir() { # $1 = carpeta a borrar entera (solo con --purge)
  case "$1" in ''|/|"$HOME") die "me niego a borrar «$1»." ;; esac
  rm -rf "$1"
}

do_uninstall() {
  local custom_home purge_dirs=() d found=0
  custom_home="$(env_get CHECKPOINT_HOME_DIR)"
  detect_systemd
  [ ! -L "$CURRENT" ] && [ ! -e "$UNIT_FILE" ] || found=1
  if [ "$found" = 0 ] && [ -d "$APP_BASE" ]; then
    for d in "$APP_BASE"/*/; do if [ -f "${d}.instalado" ]; then found=1; fi; done
  fi
  if [ "$found" = 0 ]; then say "No hay ninguna instalación de Checkpoint en $APP_BASE ni la unidad $UNIT_FILE."; fi
  if [ "$PURGE" = 1 ]; then
    purge_dirs=("${custom_home:-$DATA_HOME}" "$CONF_DIR")
    if [ "$DRY" = 1 ]; then
      plan "Pediría escribir BORRAR y borraría también: ${purge_dirs[*]}"
    else
      [ -t 0 ] || die "--purge borra datos, claves y credenciales y necesita un terminal para pedir confirmación. No he borrado nada."
      warn "--purge borrará TAMBIÉN, sin vuelta atrás: ${purge_dirs[*]} (configuración, claves SSH, datos y credenciales)."
      printf 'Escribe BORRAR para confirmar: ' >&2
      IFS= read -r ans || ans=""
      [ "$ans" = BORRAR ] || die "cancelado: no he borrado nada."
    fi
  fi
  if [ "$DRY" = 1 ]; then
    plan "systemctl --user disable --now checkpoint y quitaría la unidad $UNIT_FILE."
    plan "Quitaría el código de $APP_BASE (versiones y enlace current) y dejaría datos y credenciales."
    return 0
  fi
  if [ "$HAVE_SYSTEMD" = 1 ]; then
    sc disable --now checkpoint >/dev/null 2>&1 || warn "No pude parar o deshabilitar la unidad (¿no estaba instalada?)."
  elif [ -e "$UNIT_FILE" ]; then
    warn "No hay systemd de usuario en esta sesión: borro la unidad pero no puedo parar un servicio que siga en marcha."
  fi
  rm -f "$UNIT_FILE"
  if [ "$HAVE_SYSTEMD" = 1 ]; then sc daemon-reload >/dev/null 2>&1 || true; fi
  rm -f "$CURRENT" "$APP_BASE/.current.tmp"
  if [ -d "$APP_BASE" ]; then
    for d in "$APP_BASE"/*/; do
      d="${d%/}"
      if [ ! -L "$d" ] && [ -f "$d/.instalado" ]; then rm -rf "$d"; fi
    done
    rmdir "$APP_BASE" 2>/dev/null || true
  fi
  if [ "$PURGE" = 1 ]; then
    for d in "${purge_dirs[@]}"; do safe_rm_dir "$d"; done
    say "Checkpoint desinstalado y borrados también datos, claves y credenciales."
  else
    say "Checkpoint desinstalado. Conservo tus datos ($DATA_HOME) y las credenciales ($ENV_FILE). Para borrarlo todo: install.sh --uninstall --purge"
  fi
}

main() {
  parse_args "$@"
  init_paths
  if [ "$MODE" = uninstall ]; then do_uninstall; return 0; fi
  validate_net
  do_install
}

main "$@"
exit 0
