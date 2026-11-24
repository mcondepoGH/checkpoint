"""Regla estática (la misma que `backend/tests/test_text_encoding.py`): toda E/S de texto indica `encoding`.

En Windows el valor por defecto es cp1252, no UTF-8. Cubre `read_text`, `write_text`, `open` (builtin y `Path.open`) en
modo texto y `subprocess` con `text=True` o `universal_newlines=True`, en `src` y en `tests`.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOTS = [ROOT / "src", ROOT / "tests"]
SELF = Path(__file__).resolve()
SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}


def _kw(call: ast.Call, name: str):
    return next((k for k in call.keywords if k.arg == name), None)


def _is_text_mode(call: ast.Call, mode_pos: int) -> bool:
    mode = call.args[mode_pos] if len(call.args) > mode_pos else getattr(_kw(call, "mode"), "value", None)
    if mode is None:
        return True
    if isinstance(mode, ast.IfExp):  # open(d, "r+b" if x else "wb"): es texto si alguna rama lo es
        return any(_is_text_mode(ast.Call(func=call.func, args=[b], keywords=[]), 0) for b in (mode.body, mode.orelse))
    return not (isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value)


def violations(src: str):
    """Líneas de llamadas de E/S de texto sin `encoding`."""
    out = []
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n, ast.Call) or _kw(n, "encoding") or any(k.arg is None for k in n.keywords):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in {"read_text", "write_text"}:
            out.append(n.lineno)
        elif isinstance(f, ast.Name) and f.id == "open" and _is_text_mode(n, 1):
            out.append(n.lineno)
        elif isinstance(f, ast.Attribute) and f.attr == "open" and not isinstance(f.value, ast.Call):
            # Path.open(mode=...): solo si el modo es una cadena literal de texto (evita urllib/opener.open).
            if len(n.args) >= 1 and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                if _is_text_mode(n, 0):
                    out.append(n.lineno)
        elif isinstance(f, ast.Attribute) and f.attr in SUBPROCESS_FUNCS:
            for k in ("text", "universal_newlines"):
                kw = _kw(n, k)
                if kw is not None and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    out.append(n.lineno)
    return out


def test_no_text_io_without_encoding():
    bad = []
    for root in ROOTS:
        for p in sorted(root.rglob("*.py")):
            if p.resolve() == SELF:
                continue
            bad += [f"{p.relative_to(ROOT)}:{ln}" for ln in violations(p.read_text(encoding="utf-8"))]
    assert not bad, 'E/S de texto sin encoding="utf-8":\n' + "\n".join(bad)


def test_checker_flags_missing_encoding():
    src = "p.read_text()\np.write_text('x')\nopen('f')\nopen('f', 'w')\nsubprocess.run(['a'], text=True)\np.open('r')\n"
    assert violations(src) == [1, 2, 3, 4, 5, 6]


def test_checker_accepts_explicit_encoding_and_binary():
    src = (
        "p.read_text(encoding='utf-8')\np.write_text('x', encoding='utf-8')\nopen('f', 'rb')\n"
        "open('f', 'ab')\nopen('f', encoding='utf-8')\nsubprocess.run(['a'], capture_output=True)\n"
    )
    assert violations(src) == []


def test_checker_handles_conditional_binary_mode():
    assert violations("open(d, 'r+b' if s else 'wb')\n") == []
    assert violations("open(d, 'r' if s else 'wb')\n") == [1]
