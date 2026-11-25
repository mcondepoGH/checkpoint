#!/usr/bin/env bash
# Empaqueta el plugin en un zip instalable con Decky Loader (Ajustes de Decky > Desarrollador > Instalar plugin desde ZIP).
# Uso: bash scripts/package.sh [--save-manifest <save_manifest.json>] [directorio-de-salida]   (salida por defecto ./out).
# El zip NO se commitea (.gitignore). El manifiesto de rutas de guardado (~2 MB) tampoco se commitea: se pasa con
# --save-manifest o con la variable SAVE_MANIFEST y entra al zip como Checkpoint/data/save_manifest.json (el plugin lo lee de ahí,
# solo lectura; uno en la carpeta de ajustes de Decky tiene prioridad). Sin él el empaquetado FALLA: un zip sin manifiesto instala
# bien pero «Sugerir carpeta» solo diría «sin manifiesto». Se genera con scripts/gen_save_manifest.py (ver README, «Manifiesto»).
# Excepción explícita: --no-save-manifest (o SAVE_MANIFEST=none) empaqueta SIN él y lo avisa (la imagen Docker del hub no tiene el JSON).
# Estructura del zip: una carpeta «Checkpoint/» en la raíz con dist/index.js (sin sourcemap), main.py, plugin.json, package.json,
# py_modules/ (con py_modules/checkpoint_core/), data/save_manifest.json, LICENSE y README.md (el cargador extrae el zip tal cual en
# ~/homebrew/plugins).
# El código puro común al plugin y al cliente de Linux vive SOLO en ../checkpoint-core/src/checkpoint_core (fuente única): el
# plugin no guarda copia y este script la mete en el zip como py_modules/checkpoint_core/ (Decky pone py_modules/ en sys.path).
# Otra ruta: CHECKPOINT_CORE_SRC=<carpeta checkpoint_core>. En Docker, la etapa `deck` copia checkpoint-core/src a /checkpoint-core/src.
set -euo pipefail
START="$PWD"   # las rutas relativas del manifiesto cuentan desde donde se ejecuta el script
cd "$(dirname "$0")/.."
MANIFEST="${SAVE_MANIFEST:-}"
OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --save-manifest) [ $# -ge 2 ] || { echo "--save-manifest necesita la ruta del save_manifest.json." >&2; exit 1; }; MANIFEST="$2"; shift 2 ;;
    --save-manifest=*) MANIFEST="${1#*=}"; shift ;;
    --no-save-manifest) MANIFEST="none"; shift ;;
    -*) echo "Opción desconocida: $1" >&2; exit 1 ;;
    *) [ -z "$OUT" ] || { echo "Solo se admite un directorio de salida." >&2; exit 1; }; OUT="$1"; shift ;;
  esac
done
OUT="${OUT:-out}"
case "$MANIFEST" in ""|none|/*|[A-Za-z]:[\\/]*) ;; *) MANIFEST="$START/$MANIFEST" ;; esac
NAME="Checkpoint"
# En Windows (Git Bash) no hay python3: setup-python solo deja python.exe.
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python
CORE="${CHECKPOINT_CORE_SRC:-../checkpoint-core/src/checkpoint_core}"
# Un solo paso (compila y empaqueta): «pnpm run zip» o «npm run zip».
[ -f dist/index.js ] || { echo "Falta dist/index.js: ejecuta antes «pnpm i && pnpm run build» (o «npm i && npm run build»), o todo junto con «pnpm run zip»." >&2; exit 1; }
[ -d py_modules ] || { echo "Falta la carpeta py_modules/: el plugin no puede empaquetarse sin sus módulos de Python." >&2; exit 1; }
compgen -G "py_modules/checkpoint_*.py" >/dev/null || { echo "py_modules/ no contiene ningún checkpoint_*.py." >&2; exit 1; }
[ -f "$CORE/__init__.py" ] || { echo "Falta checkpoint-core ($CORE): el plugin necesita el paquete checkpoint_core de ../checkpoint-core/src (o CHECKPOINT_CORE_SRC)." >&2; exit 1; }
for f in main.py plugin.json package.json LICENSE README.md; do
  [ -f "$f" ] || { echo "Falta $f." >&2; exit 1; }
done
if [ "$MANIFEST" = "none" ]; then
  echo "AVISO: se empaqueta SIN el manifiesto de rutas de guardado: «Sugerir carpeta» dirá que no hay manifiesto." >&2
else
[ -n "$MANIFEST" ] || { echo "Falta el manifiesto de rutas de guardado: pasa --save-manifest <save_manifest.json> o define SAVE_MANIFEST (se genera con scripts/gen_save_manifest.py; no se commitea)." >&2; exit 1; }
[ -f "$MANIFEST" ] || { echo "No existe el manifiesto $MANIFEST." >&2; exit 1; }
# Comprobación mínima: JSON v=1 con juegos y con «src» «ludusavi-manifest@<commit>» (el commit de Ludusavi con el que se generó)
"$PY" - "$MANIFEST" <<'PY' || { echo "El manifiesto $MANIFEST no es válido (se espera el JSON de gen_save_manifest.py: v=1, games y src con el commit de Ludusavi)." >&2; exit 1; }
import json, re, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d.get("v") == 1 and isinstance(d.get("games"), list) and d["games"]
assert re.fullmatch(r"ludusavi-manifest@[0-9a-f]{7,40}", d.get("src", ""))
PY
fi
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME" "$OUT"
mkdir "$STAGE/$NAME/dist" "$STAGE/$NAME/py_modules" "$STAGE/$NAME/data"
if [ "$MANIFEST" != "none" ]; then cp "$MANIFEST" "$STAGE/$NAME/data/save_manifest.json"; else rmdir "$STAGE/$NAME/data"; fi
cp dist/index.js "$STAGE/$NAME/dist/"   # solo el bundle: sin sourcemap (*.map) ni otros ficheros
cp py_modules/*.py "$STAGE/$NAME/py_modules/"   # sin __pycache__; tests/, node_modules/ y out/ nunca entran
mkdir "$STAGE/$NAME/py_modules/checkpoint_core"
cp "$CORE"/*.py "$STAGE/$NAME/py_modules/checkpoint_core/"   # solo los .py del core: ni tests ni __pycache__
rm -f "$STAGE/$NAME/dist/"*.map  # sin sourcemap: pesa 1,4 MB y en la Deck no se depura con él
find "$STAGE/$NAME" -name __pycache__ -type d -prune -exec rm -rf {} +
cp main.py plugin.json package.json LICENSE README.md "$STAGE/$NAME/"
ZIP="$(cd "$OUT" && pwd)/$NAME.zip"
rm -f "$ZIP"
(cd "$STAGE" && "$PY" -c "
import os, sys, zipfile
with zipfile.ZipFile(sys.argv[1], 'w', zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(sys.argv[2]):
        for f in sorted(files):
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, '.'))
" "$ZIP" "$NAME")
echo "Creado $ZIP"
