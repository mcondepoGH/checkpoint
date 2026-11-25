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
for required in (os.path.join(STATIC, "index.html"), DECK_ZIP, VERSION):
    if not os.path.isfile(required):
        sys.exit(f"checkpoint.spec: falta {required}")

# `uvicorn.run("app.main:app_factory", factory=True)` importa por cadena: PyInstaller no lo ve.
hidden = collect_submodules("app") + collect_submodules("uvicorn") + ["bcrypt", "cryptography", "yaml", "ruamel.yaml", "tray", "pystray", "pystray._win32", "PIL"]

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[os.path.join(ROOT, "backend"), SPECPATH],
    binaries=[],
    # Mismo diseño que /app en Docker: static/ y VERSION junto a app/, y el zip del plugin en deck/.
    datas=[(STATIC, "static"), (DECK_ZIP, "deck"), (VERSION, ".")],
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
    icon=os.path.join(SPECPATH, "checkpoint.ico") if os.path.isfile(os.path.join(SPECPATH, "checkpoint.ico")) else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="checkpoint")
