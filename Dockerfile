# --- 1) build del frontend (React + SCSS con sass) ---
FROM node:25-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2) zip del plugin de Steam Deck (Decky Loader): el hub lo sirve en /api/deck/plugin ---
FROM node:25-alpine AS deck
# package.sh necesita bash y python3 (zipfile); el build usa pnpm 9 (el de la plantilla de Decky y su pnpm-lock.yaml).
RUN apk add --no-cache bash python3 && npm install -g pnpm@9 --no-audit --no-fund
WORKDIR /deck
COPY checkpoint-deck/package.json checkpoint-deck/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY checkpoint-deck/ ./
RUN pnpm run zip

# --- 3) runtime ---
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
