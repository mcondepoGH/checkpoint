# --- 1) build del frontend (React + SCSS con sass) ---
FROM node:25-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2) manifiesto de rutas de guardado (Steam y Lutris, ~2 MB) del plugin de Steam Deck ---
# Se genera aquí (no se commitea): baja el manifiesto de Ludusavi de un commit FIJO y lo pasa por gen_save_manifest.py.
# Para actualizarlo, cambia LUDUSAVI_MANIFEST_COMMIT (o `--build-arg LUDUSAVI_MANIFEST_COMMIT=<hash>`).
# Si falla la descarga o el generador, el build FALLA (no se empaqueta sin manifiesto en silencio). Para saltarlo a
# propósito (sin red de build): `--build-arg SKIP_SAVE_MANIFEST=1`; el zip sale sin manifiesto y «Sugerir carpeta» lo avisa.
FROM python:3.12-slim AS savemanifest
ARG LUDUSAVI_MANIFEST_COMMIT=0b39b9129e1d7024b3d45b8c1b577ec494ee470d
ARG SKIP_SAVE_MANIFEST=0
WORKDIR /gen
# PyYAML con la misma versión fijada que el backend (backend/requirements.txt)
COPY backend/requirements.txt /gen/backend-requirements.txt
RUN [ "$SKIP_SAVE_MANIFEST" = "1" ] || pip install --no-cache-dir "$(grep -i '^PyYAML==' /gen/backend-requirements.txt)"
COPY checkpoint-deck/scripts/gen_save_manifest.py checkpoint-deck/scripts/save_overrides.json /gen/
RUN mkdir -p /out \
 && if [ "$SKIP_SAVE_MANIFEST" = "1" ]; then \
      echo "AVISO: SKIP_SAVE_MANIFEST=1: el zip del plugin saldra SIN manifiesto de rutas de guardado." >&2; \
    else \
      set -e; \
      case "$LUDUSAVI_MANIFEST_COMMIT" in *[!0-9a-f]*|"") echo "LUDUSAVI_MANIFEST_COMMIT no es un hash hexadecimal: $LUDUSAVI_MANIFEST_COMMIT" >&2; exit 1 ;; esac; \
      python -I -c "import sys, urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/' + sys.argv[1] + '/data/manifest.yaml', '/gen/manifest.yaml')" "$LUDUSAVI_MANIFEST_COMMIT" \
        || { echo "No se pudo descargar el manifiesto de Ludusavi (commit $LUDUSAVI_MANIFEST_COMMIT): revisa la red del build o usa --build-arg SKIP_SAVE_MANIFEST=1." >&2; exit 1; }; \
      python -I /gen/gen_save_manifest.py /gen/manifest.yaml /out/save_manifest.json --commit "$LUDUSAVI_MANIFEST_COMMIT" \
        || { echo "gen_save_manifest.py fallo: no se genera el manifiesto de rutas de guardado." >&2; exit 1; }; \
      [ -s /out/save_manifest.json ] || { echo "save_manifest.json vacio." >&2; exit 1; }; \
    fi

# --- 3) zip del plugin de Steam Deck (Decky Loader): el hub lo sirve en /api/deck/plugin ---
FROM node:25-alpine AS deck
ARG SKIP_SAVE_MANIFEST=0
# package.sh necesita bash y python3 (zipfile); el build usa pnpm 9 (el de la plantilla de Decky y su pnpm-lock.yaml).
RUN apk add --no-cache bash python3 && npm install -g pnpm@9 --no-audit --no-fund
WORKDIR /deck
COPY checkpoint-deck/package.json checkpoint-deck/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY checkpoint-deck/ ./
# El código común al plugin y al cliente (fuente única): package.sh lo busca en ../checkpoint-core/src/checkpoint_core y lo mete en el zip.
COPY checkpoint-core/src /checkpoint-core/src
# El manifiesto lo genera la etapa savemanifest y entra al zip como data/save_manifest.json; package.sh lo valida y falla si falta.
COPY --from=savemanifest /out /savemanifest
RUN if [ "$SKIP_SAVE_MANIFEST" = "1" ]; then export SAVE_MANIFEST=none; else export SAVE_MANIFEST=/savemanifest/save_manifest.json; fi \
 && pnpm run zip

# --- 4) runtime ---
FROM python:3.12-alpine
# `apk upgrade` trae los paquetes de la base con sus correcciones de seguridad (p. ej. krb5-libs, que entra
# por openssh-client); `setuptools` viene preinstalado en la imagen base y se sube a una versión corregida.
RUN apk add --no-cache openssh-client rsync tar tzdata su-exec \
 && apk upgrade --no-cache \
 && pip install --no-cache-dir --upgrade pip setuptools
ARG PUID=1000
ARG PGID=1000
RUN addgroup -g ${PGID} checkpoint && adduser -D -u ${PUID} -G checkpoint -h /home/checkpoint checkpoint \
 && mkdir -p /config /keys /data /app && chown checkpoint:checkpoint /config /keys /data
WORKDIR /app
COPY backend/requirements.txt ./
# bcrypt, pyyaml, cryptography y pydantic-core publican wheels musllinux (x86_64 y arm64)
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY VERSION ./VERSION
COPY --from=web /web/dist ./static
COPY --from=deck /deck/out/Checkpoint.zip ./deck/Checkpoint.zip
# La CLI baja a checkpoint si se invoca como root (docker exec), para no crear ficheros de root en /data.
RUN printf '#!/bin/sh\nif [ "$(id -u)" = "0" ]; then exec su-exec checkpoint python -m app.cli "$@"; fi\nexec python -m app.cli "$@"\n' > /usr/local/bin/checkpoint && chmod +x /usr/local/bin/checkpoint
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENV HOME=/home/checkpoint PYTHONUNBUFFERED=1 CHECKPOINT_RUNTIME=docker
# Sin USER: el entrypoint arranca como root, prepara carpetas y baja a checkpoint.
EXPOSE 8088
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8088", "--no-server-header"]
