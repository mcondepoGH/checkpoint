"""Regenera assets/checkpoint.ico (16, 24, 32, 48, 64, 128 y 256 px) desde el logo de la app, frontend/public/icon-512.png.

Uso (desde cualquier carpeta; solo necesita Pillow, que ya está en requirements.txt):
    python packaging/windows/make_icon.py
El .ico resultante se versiona: el build de Windows (build.ps1 / release.yml) NO lo regenera, solo lo consume."""

import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "frontend" / "public" / "icon-512.png"
TARGET = HERE / "assets" / "checkpoint.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def build(source: Path = SOURCE, target: Path = TARGET) -> Path:
    img = Image.open(source).convert("RGBA")
    if min(img.size) < max(SIZES):
        sys.exit(f"make_icon: {source} es demasiado pequeño ({img.size})")
    target.parent.mkdir(parents=True, exist_ok=True)
    img.save(target, format="ICO", sizes=[(s, s) for s in SIZES])
    return target


if __name__ == "__main__":
    print(build())
