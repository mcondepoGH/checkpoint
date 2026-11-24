"""checkpoint-core se prueba desde su propio árbol fuente, sin instalarlo."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
