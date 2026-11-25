#!/usr/bin/env bash
# Construye el paquete nativo de Linux: dist/checkpoint-<versión>-linux.tar.gz y su .sha256 («<hash>  <nombre>»,
# igual que el .exe.sha256 de Windows). Lo usan el job `linux-package` de ci.yml (y, más adelante, release.yml).
# Uso, desde cualquier carpeta:
#   bash packaging/linux/build.sh [--tag vX.Y.Z] [--out-dir DIR] [--no-deck] [--deck-zip FICHERO] [--frontend-dir DIR]
#     --tag           comprueba que VERSION coincide con el tag.
#     --out-dir       carpeta de salida (por defecto <repo>/dist).
#     --no-deck       no incluye el plugin de Steam Deck (pruebas locales: la descarga /api/deck/plugin dará 404).
#     --deck-zip      usa un Checkpoint.zip ya construido en vez de construirlo (necesita Node y red).
#     --frontend-dir  usa un frontend ya compilado en vez de `npm ci && npm run build` (pruebas).
# Requisitos del build completo: bash, Python 3 con venv, Node (npm) y red (manifiesto de Ludusavi y pnpm 9).
# Contenido del tarball (carpeta raíz checkpoint-<versión>/):
#   install.sh, VERSION, backend/{app,requirements.txt,static}, checkpoint-deck/out/Checkpoint.zip
# El zip va en checkpoint-deck/out/ porque es donde el hub nativo lo busca (settings.DECK_ZIP): así no hace falta tocar el código.
# El tarball es reproducible (orden, propietario y fecha fijos): el mismo commit da los mismos bytes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TAG="" OUT="$ROOT/dist" NO_DECK=0 DECK_ZIP="" FRONTEND_DIR=""
die() { echo "build.sh: $*" >&2; exit 1; }
need() { [ $# -ge 2 ] || die "$1 necesita un valor."; }
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) need "$@"; TAG="$2"; shift 2 ;;
    --out-dir) need "$@"; OUT="$2"; shift 2 ;;
    --no-deck) NO_DECK=1; shift ;;
    --deck-zip) need "$@"; DECK_ZIP="$2"; shift 2 ;;
    --frontend-dir) need "$@"; FRONTEND_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "opción desconocida: $1" ;;
  esac
done
[ "$NO_DECK" = 0 ] || [ -z "$DECK_ZIP" ] || die "--no-deck y --deck-zip son incompatibles."

VERSION="$(tr -d '[:space:]' < VERSION)"
[ -n "$VERSION" ] || die "VERSION vacío."
if [ -n "$TAG" ] && [ "$TAG" != "v$VERSION" ]; then die "VERSION ($VERSION) no coincide con el tag $TAG"; fi
echo "== Checkpoint $VERSION (linux) =="

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== 1/4 frontend =="
if [ -z "$FRONTEND_DIR" ]; then
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
  FRONTEND_DIR="$ROOT/frontend/dist"
else
  echo "usando $FRONTEND_DIR"
fi
[ -f "$FRONTEND_DIR/index.html" ] || die "el frontend no tiene index.html ($FRONTEND_DIR)."

echo "== 2/4 plugin de Steam Deck =="
if [ "$NO_DECK" = 1 ]; then
  echo "AVISO: --no-deck: el paquete saldrá SIN el plugin de Deck." >&2
elif [ -n "$DECK_ZIP" ]; then
  [ -s "$DECK_ZIP" ] || die "no existe o está vacío: $DECK_ZIP"
else
  # Igual que el Dockerfile (etapas savemanifest y deck) y packaging/windows/build.ps1.
  COMMIT="$(sed -n 's/^ARG LUDUSAVI_MANIFEST_COMMIT=\([0-9a-f]\{40\}\)$/\1/p' Dockerfile | head -n1)"
  [ -n "$COMMIT" ] || die "no se encontró LUDUSAVI_MANIFEST_COMMIT en el Dockerfile."
  python3 -m venv "$WORK/venv"
  "$WORK/venv/bin/pip" install --quiet --disable-pip-version-check "$(grep -i '^PyYAML==' backend/requirements.txt)"
  "$WORK/venv/bin/python" -I -c "import sys, urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/' + sys.argv[1] + '/data/manifest.yaml', sys.argv[2])" \
    "$COMMIT" "$WORK/manifest.yaml" || die "no se pudo descargar el manifiesto de Ludusavi (commit $COMMIT)."
  "$WORK/venv/bin/python" -I checkpoint-deck/scripts/gen_save_manifest.py "$WORK/manifest.yaml" "$WORK/save_manifest.json" --commit "$COMMIT"
  [ -s "$WORK/save_manifest.json" ] || die "save_manifest.json vacío."
  if command -v pnpm >/dev/null 2>&1 && [ "$(pnpm --version | cut -d. -f1)" = 9 ]; then PNPM=(pnpm); else PNPM=(npx --yes pnpm@9); fi
  (cd checkpoint-deck && "${PNPM[@]}" install --frozen-lockfile && SAVE_MANIFEST="$WORK/save_manifest.json" "${PNPM[@]}" run zip)
  DECK_ZIP="$ROOT/checkpoint-deck/out/Checkpoint.zip"
  [ -s "$DECK_ZIP" ] || die "no se generó checkpoint-deck/out/Checkpoint.zip"
fi

echo "== 3/4 tarball =="
NAME="checkpoint-$VERSION"
STAGE="$WORK/stage/$NAME"
mkdir -p "$STAGE/backend" "$OUT"
cp -R backend/app "$STAGE/backend/app"
find "$STAGE" \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} +
cp backend/requirements.txt "$STAGE/backend/requirements.txt"
cp -R "$FRONTEND_DIR" "$STAGE/backend/static"
cp VERSION "$STAGE/VERSION"
cp packaging/linux/install.sh "$STAGE/install.sh"
chmod 755 "$STAGE/install.sh"
if [ "$NO_DECK" = 0 ]; then
  mkdir -p "$STAGE/checkpoint-deck/out"
  cp "$DECK_ZIP" "$STAGE/checkpoint-deck/out/Checkpoint.zip"
fi
EPOCH="${SOURCE_DATE_EPOCH:-$(git log -1 --format=%ct 2>/dev/null || echo 1700000000)}"
TGZ="$OUT/$NAME-linux.tar.gz"
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$EPOCH" --mode='u+rwX,go+rX,go-w' \
  -C "$WORK/stage" -cf - "$NAME" | gzip -n -9 > "$TGZ"

echo "== 4/4 hash =="
FILE="$(basename "$TGZ")"
HASH="$(cd "$OUT" && sha256sum "$FILE" | cut -d' ' -f1)"
printf '%s  %s\n' "$HASH" "$FILE" > "$TGZ.sha256"
echo "$FILE  sha256=$HASH"
