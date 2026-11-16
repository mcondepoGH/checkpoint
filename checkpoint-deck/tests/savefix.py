"""Ayudantes SINTÉTICOS para las pruebas de rutas de guardado: HOME de tmp_path con Steam (interna y SD), prefijos y Lutris."""

import json
import os
import sqlite3
from pathlib import Path


def write(path: Path, text: str = "x", mtime=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def steam_home(home: Path, sd: Path = None) -> Path:
    """`<home>/.local/share/Steam` con `libraryfolders.vdf` (interna y, si se da, SD); devuelve la raíz."""
    root = home / ".local/share/Steam"
    (root / "steamapps").mkdir(parents=True, exist_ok=True)
    libs = [f'"0" {{ "path" "{root}" }}']
    if sd is not None:
        (sd / "steamapps").mkdir(parents=True, exist_ok=True)
        libs.append(f'"1" {{ "path" "{sd}" }}')
    (root / "steamapps/libraryfolders.vdf").write_text('"libraryfolders" {\n' + "\n".join(libs) + "\n}\n")
    return root


def steam_game(lib: Path, appid: int, name: str, installdir: str = None, pfx: bool = True, user: str = "steamuser") -> Path:
    """appmanifest en `lib/steamapps`, carpeta de instalación y (opcional) compatdata en la MISMA biblioteca."""
    apps = lib / "steamapps"
    installdir = installdir or name.replace(" ", "")
    (apps / f"appmanifest_{appid}.acf").write_text(
        f'"AppState" {{ "appid" "{appid}" "name" "{name}" "installdir" "{installdir}" }}\n'
    )
    (apps / "common" / installdir).mkdir(parents=True, exist_ok=True)
    prefix = apps / f"compatdata/{appid}/pfx"
    if pfx:
        (prefix / "drive_c/users" / user).mkdir(parents=True, exist_ok=True)
        (prefix / "drive_c/users/Public").mkdir(parents=True, exist_ok=True)
    return prefix


def lutris_db(data: Path, rows) -> None:
    """rows: dicts con id, name, slug, runner, service, service_id, installed, directory, configpath."""
    data.mkdir(parents=True, exist_ok=True)
    (data / "pga.db").unlink(missing_ok=True)
    con = sqlite3.connect(data / "pga.db")
    con.execute(
        "CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT, slug TEXT, runner TEXT, service TEXT, service_id TEXT, "
        "installed INTEGER, directory TEXT, configpath TEXT)"
    )
    for r in rows:
        con.execute(
            "INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?)",
            (r["id"], r["name"], r.get("slug"), r.get("runner", "wine"), r.get("service"), r.get("service_id"),
             r.get("installed", 1), r.get("directory"), r.get("configpath")),
        )  # fmt: skip
    con.commit()
    con.close()


def lutris_yml(gamesdir: Path, configpath: str, prefix=None, exe=None, slug="x", name="X") -> None:
    gamesdir.mkdir(parents=True, exist_ok=True)
    lines = ["game:"]
    if exe is not None:
        lines.append(f"  exe: {exe}")
    if prefix is not None:
        lines.append(f"  prefix: {prefix}")
    lines += [f"game_slug: {slug}", f"name: {name}"]
    (gamesdir / f"{configpath}.yml").write_text("\n".join(lines) + "\n")


def manifest(*games, src="test@0") -> bytes:
    return json.dumps({"v": 1, "src": src, "games": list(games)}).encode()


def mgame(n, steam=None, lutris=None, paths=(), slug=None):
    g = {"n": n, "steam": steam, "lutris": lutris, "paths": list(paths)}
    if slug:
        g["slug"] = slug
    return g


def rule(r, p, os_="win", x=None, d_=False):
    d = {"r": r, "p": p, "os": os_}
    if d_:
        d["d"] = True
    if x:
        d["x"] = x
    return d
