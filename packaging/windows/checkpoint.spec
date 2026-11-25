# -*- mode: python ; coding: utf-8 -*-
# Spec de PyInstaller (onedir) del hub para Windows. Se ejecuta DESDE la raíz del repositorio:
#   pyinstaller --noconfirm --distpath packaging/windows/dist --workpath packaging/windows/build packaging/windows/checkpoint.spec
# Requisitos previos (los hace el job `windows` de release.yml): frontend/dist (npm ci && npm run build) y
# checkpoint-deck/out/Checkpoint.zip (pnpm run zip). Si falta alguno, el build falla (no se empaqueta a medias).
# Resultado: packaging/windows/dist/checkpoint/checkpoint.exe (+ _internal/), que empaqueta installer.iss.
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(SPECPATH + "/../..")
STATIC = os.path.join(ROOT, "frontend", "dist")
DECK_ZIP = os.path.join(ROOT, "checkpoint-deck", "out", "Checkpoint.zip")
VERSION = os.path.join(ROOT, "VERSION")
# Icono de Checkpoint (regenerable con make_icon.py): es el del .exe y el que la bandeja carga del bundle (assets/).
ICON = os.path.join(SPECPATH, "assets", "checkpoint.ico")
for required in (os.path.join(STATIC, "index.html"), DECK_ZIP, VERSION, ICON):
    if not os.path.isfile(required):
        sys.exit(f"checkpoint.spec: falta {required}")

# Paquete `app` (backend/app): se recorre el árbol de ficheros y no la función de hooks de PyInstaller para submódulos, porque esa función se
# evalúa aquí, antes de que `pathex` (backend/) esté en sys.path, y devolvía [] (el bundle salía sin `app`).
APP_DIR = os.path.join(ROOT, "backend", "app")
app_modules = []
for dirpath, _dirs, files in os.walk(APP_DIR):
    rel = os.path.relpath(dirpath, os.path.dirname(APP_DIR)).replace(os.sep, ".")
    if "__pycache__" in rel:
        continue
    for f in files:
        if f.endswith(".py"):
            app_modules.append(rel if f == "__init__.py" else f"{rel}.{f[:-3]}")
if "app.main" not in app_modules or "app.cli" not in app_modules:
    sys.exit(f"checkpoint.spec: no se encontró el paquete app en {APP_DIR}")

# app.cli importa app.main de forma estática; aun así se listan todos los módulos (routers y servicios cargados por
# nombre) y los paquetes con carga dinámica (uvicorn: loops, protocolos, lifespan; fastapi/starlette; anyio).
hidden = (
    app_modules
    + collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
    + collect_submodules("anyio")
    + ["bcrypt", "cryptography", "yaml", "ruamel.yaml", "tray", "pystray", "pystray._win32", "PIL"]
)

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[os.path.join(ROOT, "backend"), SPECPATH],
    binaries=[],
    # Mismo diseño que /app en Docker: static/ y VERSION junto a app/, y el zip del plugin en deck/.
    datas=[(STATIC, "static"), (DECK_ZIP, "deck"), (VERSION, "."), (ICON, "assets")],
    hiddenimports=hidden,
    excludes=["pytest", "tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="checkpoint",
    console=False,  # sin ventana de consola; el log va a %APPDATA%\checkpoint\logs (launcher.py)
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name="checkpoint")
