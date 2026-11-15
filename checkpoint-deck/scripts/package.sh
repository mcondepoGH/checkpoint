#!/usr/bin/env bash
# Empaqueta el plugin en un zip instalable con Decky Loader (Ajustes de Decky > Desarrollador > Instalar plugin desde ZIP).
# Uso: bash scripts/package.sh [directorio-de-salida]   (por defecto ./out). El zip NO se commitea (.gitignore).
# Estructura del zip: una carpeta «Checkpoint/» en la raíz con dist/index.js (sin sourcemap), main.py, plugin.json, package.json,
# py_modules/, LICENSE y README.md (el cargador extrae el zip tal cual en ~/homebrew/plugins).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-out}"
NAME="Checkpoint"
# Un solo paso (compila y empaqueta): «pnpm run zip» o «npm run zip».
[ -f dist/index.js ] || { echo "Falta dist/index.js: ejecuta antes «pnpm i && pnpm run build» (o «npm i && npm run build»), o todo junto con «pnpm run zip»." >&2; exit 1; }
[ -d py_modules ] || { echo "Falta la carpeta py_modules/: el plugin no puede empaquetarse sin sus módulos de Python." >&2; exit 1; }
compgen -G "py_modules/checkpoint_*.py" >/dev/null || { echo "py_modules/ no contiene ningún checkpoint_*.py." >&2; exit 1; }
for f in main.py plugin.json package.json LICENSE README.md; do
  [ -f "$f" ] || { echo "Falta $f." >&2; exit 1; }
done
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME" "$OUT"
mkdir "$STAGE/$NAME/dist" "$STAGE/$NAME/py_modules"
cp dist/index.js "$STAGE/$NAME/dist/"   # solo el bundle: sin sourcemap (*.map) ni otros ficheros
cp py_modules/*.py "$STAGE/$NAME/py_modules/"   # sin __pycache__; tests/, node_modules/ y out/ nunca entran
rm -f "$STAGE/$NAME/dist/"*.map  # sin sourcemap: pesa 1,4 MB y en la Deck no se depura con él
find "$STAGE/$NAME" -name __pycache__ -type d -prune -exec rm -rf {} +
cp main.py plugin.json package.json LICENSE README.md "$STAGE/$NAME/"
ZIP="$(cd "$OUT" && pwd)/$NAME.zip"
rm -f "$ZIP"
(cd "$STAGE" && python3 -c "
import os, sys, zipfile
with zipfile.ZipFile(sys.argv[1], 'w', zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(sys.argv[2]):
        for f in sorted(files):
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, '.'))
" "$ZIP" "$NAME")
echo "Creado $ZIP"
