#!/usr/bin/env python3
"""Genera el manifiesto propio y compacto de rutas de guardado (solo Steam y Lutris) a partir del de Ludusavi.

Uso:
    python gen_save_manifest.py <manifest.yaml> <salida.json> --commit <hash> [--overrides <fichero.json>]

Herramienta de desarrollo, NO forma parte del plugin ni se empaqueta en el zip. Necesita PyYAML (el del backend,
`backend/requirements.txt`). Esquema de salida (v=1; los campos `slug` y `x` son opcionales y aditivos, por eso
`v` sigue en 1: un lector de v=1 que ignora claves desconocidas no se rompe y uno que los conoce los trata como
ausentes si faltan; también `d`):

    {"v":1,"src":"ludusavi-manifest@<commit>","games":[{"n":nombre,"steam":int|null,"lutris":slug|null,
      "slug":"<nombre slugificado>" (solo si `lutris` es null),
      "paths":[{"r":<raíz>,"p":"<ruta relativa>","os":"linux|win","x":[<patrones a excluir>] (opcional),"d":true (opcional)}]}]}

`slug`: nombre del juego slugificado como Lutris (minúsculas, ASCII, alfanumérico y guiones; «Dragon Quest VII
Reimagined» -> `dragon-quest-vii-reimagined`). Es un casado SECUNDARIO y menos fiable (el slug local de Lutris puede
no coincidir con el nombre de Ludusavi): el resolvedor lo usa solo cuando `lutris` es null y tras `steam`/`lutris`.

`x`: patrones (fnmatch, sin distinguir mayúsculas, contra el nombre de cada fichero o carpeta) que el resolvedor debe
excluir al sugerir la carpeta de la ruta (o su carpeta padre si la ruta acaba en un glob de fichero), porque esa
carpeta arrastra logs, caché y configuración (Magicka 2: `ParadoxInteractive/Magicka2`). Sale de `EXCLUDED` (logs,
`*.log`, cache, `crash*`) más las extensiones de configuración (`*.config`, `*.cfg`, `*.ini`, `*.conf`) si el
manifiesto de Ludusavi etiqueta como `config` algún fichero con esa extensión en ese juego. No sale en rutas cuya
carpeta es de la lista blanca (Saves, SaveGames...), en `steamCloud` ni en rutas de override.

Rutas con glob de fichero (`*.sav`, `GameSaveData*.sav`) bajo una carpeta de la lista blanca: se emite TAMBIÉN la
ruta a esa carpeta (sin el glob), para no perder partidas en subcarpetas (DQ VII Reimagined: `SaveGames/Book/...`);
el glob se conserva por si el resolvedor lo prefiere, y la carpeta es la preferible.

`d`: ruta DUDOSA (`true`; ausente = no dudosa). Heurística LÖVE: si un juego no tiene NINGUNA ruta Linux aceptada y el
manifiesto trae una entrada Linux `<xdgData>/love/<X>/...` (con cualquier tag, normalmente `config`), se emite
`{"r":"xdgData","p":"love/<X>","os":"linux","d":true}` (la carpeta del juego, no el fichero de config), una sola por
juego. Solo para el prefijo `love/` bajo xdgData (los juegos hechos con el motor LÖVE guardan en `~/.local/share/love/<juego>`;
Move or Die: `love/Move Or Die`). El resolvedor la sugiere con `doubtful: true`.

Raíces `r`: home, xdgData, xdgConfig, pfxRoaming, pfxLocal, pfxLocalLow, pfxDocs, pfxSaved, pfxProgData, install,
steamCloud (solo subruta bajo `userdata/<usuario>/<appid>/`). `<storeUserId>` se escribe `*`. Las rutas de Windows
son relativas al prefijo de Proton/Wine. El informe de filtrado sale por stdout.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

DEFAULT_OVERRIDES = Path(__file__).with_name("save_overrides.json")

GENERIC = {"appdata", "local", "locallow", "roaming", "documents", "my games", "saved games"}
SAVE_DIRS = {"saves", "savegames", "gamesaves", "savedata", "profiles"}
SAVE_EXT = (".sav", ".save", ".dat", ".sl2", ".plr", ".wld", ".celeste", ".srm")
EXCLUDED = (
    "cache",
    "shader*",
    "logs",
    "crash*",
    "*.log",
    "*.tmp",
    "binaries",
    "*.exe",
    "*.dll",
    "*.so",
    "mods",
    "workshop",
)
X_BASE = ("logs", "*.log", "cache", "crash*")  # subconjunto de EXCLUDED que puede colgar de una carpeta de guardado
CONFIG_EXT = (".config", ".cfg", ".ini", ".conf")
MAX_DEPTH = 3
WIN_ROOTS = {
    "<winAppData>": "pfxRoaming",
    "<winLocalAppData>": "pfxLocal",
    "<winDocuments>": "pfxDocs",
    "<winProgramData>": "pfxProgData",
}
HOME_WIN = {
    "appdata/locallow": "pfxLocalLow",
    "appdata/local": "pfxLocal",
    "appdata/roaming": "pfxRoaming",
    "documents": "pfxDocs",
    "saved games": "pfxSaved",
}
HOME_LINUX_HINTS = (".config/", ".local/share/", ".steam/", ".var/")
STEAM_CLOUD = re.compile(r"^<root>/userdata/<storeUserId>/\d+(?:/(.*))?$")


def _segs(rel):
    return [s for s in rel.split("/") if s]


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _has_glob(seg):
    return "*" in seg or "?" in seg


def lutris_slug(name):
    """Slug estilo Lutris: ASCII, minúsculas, alfanumérico y guiones («Dragon Quest VII: Reimagined» -> `dragon-quest-vii-reimagined`)."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    text = text.replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _is_file_glob(seg):
    return _has_glob(seg) and seg not in ("*", "**")


def exclusions(root, segs, config_pats):
    """Patrones `x` de una ruta ya aceptada; [] si su carpeta es de la lista blanca o es steamCloud."""
    folder = segs[:-1] if segs and _is_file_glob(segs[-1]) else segs
    if root == "steamCloud" or (folder and folder[-1].lower() in SAVE_DIRS):
        return []
    return list(X_BASE) + sorted(config_pats)


def derive_os(path):
    """Sistema por la ruta cuando `when` no lo dice: xdg y rutas típicas de home de Linux -> linux; si no, windows."""
    if path.startswith(("<xdgData>", "<xdgConfig>")):
        return "linux"
    if path.startswith("<home>/") and path[len("<home>/") :].startswith(HOME_LINUX_HINTS):
        return "linux"
    return "win"


def when_oses(when, path):
    """Conjunto de os ({'linux','win'}) o un motivo de descarte ('otra_tienda'/'otro_os'). `when` es una lista de OR."""
    if not when:
        return {derive_os(path)}, None
    oses, reasons = set(), set()
    for c in when:
        store = c.get("store")
        if store not in (None, "steam"):
            reasons.add("otra_tienda")
            continue
        o = c.get("os")
        if o is None:
            oses.add(derive_os(path))
        elif o in ("linux", "windows"):
            oses.add("linux" if o == "linux" else "win")
        else:
            reasons.add("otro_os")
    if oses:
        return oses, None
    return set(), ("otra_tienda" if "otra_tienda" in reasons else "otro_os")


def map_root(path, os_):
    """(raíz, subruta) o (None, motivo). El mapeo depende del sistema de la variante."""
    m = STEAM_CLOUD.match(path)
    if m:
        sub = (m.group(1) or "").strip("/")
        return ("steamCloud", sub) if sub else (None, "steamcloud_sin_subruta")
    head, _, rest = path.partition("/")
    if os_ == "linux":
        if head == "<xdgData>":
            return "xdgData", rest
        if head == "<xdgConfig>":
            return "xdgConfig", rest
        if head == "<base>":
            return "install", rest
        if head == "<home>":
            if rest.startswith(".local/share/"):
                return "xdgData", rest[len(".local/share/") :]
            if rest.startswith(".config/"):
                return "xdgConfig", rest[len(".config/") :]
            return "home", rest
        return None, "raiz_incoherente" if head in WIN_ROOTS else "raiz_no_mapeable"
    if head == "<base>":
        return "install", rest
    if head in WIN_ROOTS:
        root = WIN_ROOTS[head]
        if head == "<winLocalAppData>" and rest.lower().startswith("../locallow"):
            return "pfxLocalLow", rest[len("../locallow") :].lstrip("/")
        return root, rest
    if head == "<home>":
        for prefix, root in HOME_WIN.items():
            if rest.lower() == prefix or rest.lower().startswith(prefix + "/"):
                return root, rest[len(prefix) :].lstrip("/")
        return None, "raiz_no_mapeable"
    return None, "raiz_incoherente" if head in ("<xdgData>", "<xdgConfig>") else "raiz_no_mapeable"


def _save_ext(segs):
    if not segs:
        return False
    last = segs[-1].lower()
    if last.endswith(SAVE_EXT):
        return True
    return last.endswith(".json") and any("save" in s.lower() or s.lower() in SAVE_DIRS for s in segs[:-1])


def _save_dir_index(segs):
    """Índice de la última carpeta de la lista blanca (ignorando una hoja o carpetas con comodín tras ella)."""
    idx = None
    for i, s in enumerate(segs):
        if not _has_glob(s) and s.lower() in SAVE_DIRS:
            idx = i
    return idx


def _name_match(seg, game):
    a, b = _norm(seg), _norm(game)
    return len(a) >= 4 and len(b) >= 4 and (a == b or a in b or b in a)


def filter_path(root, rel, game):
    """None si la ruta pasa; si no, el motivo de descarte."""
    segs = _segs(rel)
    if any(fnmatch.fnmatch(s.lower(), pat) for s in segs for pat in EXCLUDED):
        return "excluida"
    if root == "steamCloud":
        return None
    if root == "install":
        if not segs:
            return "base_sola"
        if all(_has_glob(s) for s in segs) and not _save_ext(segs):
            return "base_comodin"
    lead = 0
    if root != "install":
        while lead < len(segs) and segs[lead].lower() in GENERIC:
            lead += 1
    own = [s for s in segs[lead:] if not _has_glob(s)]
    if root != "install" and len(own) <= 1:
        if len(own) == 1 and _name_match(own[0], game):
            return None
        return "segmento_unico"
    sdir = _save_dir_index(segs)
    if not (_save_ext(segs) or len(own) >= 2 or sdir is not None):
        return "fuera_de_lista_blanca"
    cand = sdir if sdir is not None else lead
    if len(segs) - cand - 1 > MAX_DEPTH:
        return "demasiado_profundo"
    return None


def game_variants(game_name, data, stats):
    """Rutas (r, p, os) de un juego tras mapear y filtrar; cuenta cada descarte en `stats`."""
    out = []
    config_pats = {
        "*" + os.path.splitext(path.rstrip("/"))[1].lower()
        for path, entry in (data.get("files") or {}).items()
        if "config" in (entry.get("tags") or []) and path.rstrip("/").lower().endswith(CONFIG_EXT)
    }
    for path, entry in (data.get("files") or {}).items():
        stats["entradas_juegos_con_id"] += 1
        if "save" not in (entry.get("tags") or []):
            stats["descartes"]["sin_tag_save"] += 1
            continue
        stats["entradas_save"] += 1
        oses, why = when_oses(entry.get("when"), path)
        if why:
            stats["descartes"][why] += 1
            continue
        for os_ in sorted(oses):
            stats["variantes"] += 1
            root, rel = map_root(path, os_)
            if root is None:
                stats["descartes"][rel] += 1
                continue
            rel = rel.replace("<storeUserId>", "*")
            if "<" in rel:
                stats["descartes"]["placeholder_desconocido"] += 1
                continue
            why = filter_path(root, rel, game_name)
            if why:
                stats["descartes"][why] += 1
                continue
            rel = rel.strip("/")
            segs = _segs(rel)
            os_out = "linux" if root == "steamCloud" else os_
            item = {"r": root, "p": rel, "os": os_out}
            x = exclusions(root, segs, config_pats)
            if x:
                item["x"] = x
            out.append(item)
            if len(segs) >= 2 and _is_file_glob(segs[-1]) and segs[-2].lower() in SAVE_DIRS:
                # glob de fichero bajo SaveGames/Saves...: también la carpeta, por si el guardado va en subcarpetas
                out.append({"r": root, "p": "/".join(segs[:-1]), "os": os_out})
    if not any(i["os"] == "linux" for i in out):
        out += love_paths(data)
    return out


def love_paths(data):
    """Heurística LÖVE: `<xdgData>/love/<X>/...` en Linux (con cualquier tag) -> `love/<X>` con `d: true` (dudosa)."""
    found = []
    for path, entry in (data.get("files") or {}).items():
        oses, why = when_oses(entry.get("when"), path)
        if why or "linux" not in oses:
            continue
        root, rel = map_root(path, "linux")
        segs = _segs(rel) if root == "xdgData" else []
        if len(segs) >= 3 and segs[0] == "love" and segs[1] and "<" not in segs[1] and not _has_glob(segs[1]):
            item = {"r": "xdgData", "p": f"love/{segs[1]}", "os": "linux", "d": True}
            if item not in found:
                found.append(item)
    return found[:1]


def dedupe(paths, stats):
    seen, out = set(), []
    for p in paths:
        key = (p["r"], p["p"], p["os"])
        if key in seen:
            stats["descartes"]["duplicada"] += 1
            continue
        seen.add(key)
        out.append(p)
    return out


def load_overrides(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("overrides", [])


def apply_overrides(game, overrides, notes):
    for o in overrides:
        if (o.get("steam") and o["steam"] == game["steam"]) or (o.get("lutris") and o["lutris"] == game["lutris"]):
            if o.get("replace"):
                oses = {p["os"] for p in o["replace"]}
                game["paths"] = [p for p in game["paths"] if p["os"] not in oses] + [dict(p) for p in o["replace"]]
            if o.get("add"):
                game["paths"] += [dict(p) for p in o["add"]]
            if o.get("note"):
                notes.append(f"{game['n']}: {o['note']}")
            return True
    return False


def build(manifest, commit, overrides=()):
    """(documento, informe) a partir del manifiesto de Ludusavi ya cargado (dict)."""
    stats = {"entradas_juegos_con_id": 0, "entradas_save": 0, "variantes": 0, "descartes": Counter()}
    games, notes = [], []
    total = with_id = 0
    for name, data in manifest.items():
        total += 1
        steam = (data.get("steam") or {}).get("id")
        lutris = (data.get("id") or {}).get("lutris")
        if not steam and not lutris:
            continue
        with_id += 1
        game = {"n": name, "steam": steam or None, "lutris": lutris or None}
        if not lutris and lutris_slug(name):
            game["slug"] = lutris_slug(name)  # casado secundario (menos fiable) cuando `lutris` es null
        game["paths"] = []
        game["paths"] = dedupe(game_variants(name, data, stats), stats)
        overridden = apply_overrides(game, overrides, notes)
        if game["paths"] or overridden:
            games.append(game)
    games.sort(key=lambda g: g["n"].lower())
    doc = {"v": 1, "src": f"ludusavi-manifest@{commit}", "games": games}
    stats.update(
        juegos_total=total,
        juegos_con_id=with_id,
        juegos_salida=len(games),
        rutas_salida=sum(len(g["paths"]) for g in games),
        notas=notes,
    )
    return doc, stats


def dump(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def report(stats, size):
    d = stats["descartes"]
    lines = [
        f"juegos en el manifiesto: {stats['juegos_total']}; con steam.id o id.lutris: {stats['juegos_con_id']}; "
        f"en la salida: {stats['juegos_salida']}",
        f"entradas files (juegos con id): {stats['entradas_juegos_con_id']}; con tag save: {stats['entradas_save']}; "
        f"variantes por sistema: {stats['variantes']}; rutas en la salida: {stats['rutas_salida']}",
        "descartes por regla:",
    ]
    lines += [f"  {k}: {v}" for k, v in sorted(d.items(), key=lambda kv: -kv[1])]
    lines.append(f"tamaño del JSON: {size} bytes ({size / 1024:.0f} KiB)")
    lines += [f"nota: {n}" for n in stats["notas"]]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("manifest", help="manifest.yaml de Ludusavi")
    ap.add_argument("out", help="JSON de salida")
    ap.add_argument("--commit", required=True, help="commit del manifiesto de Ludusavi (va en `src`)")
    ap.add_argument("--overrides", default=str(DEFAULT_OVERRIDES), help="correcciones manuales (JSON)")
    args = ap.parse_args(argv)
    import yaml  # solo la herramienta lo necesita: el plugin no depende de PyYAML

    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with open(args.manifest, encoding="utf-8") as f:
        manifest = yaml.load(f, Loader=loader)  # noqa: S506 - SafeLoader
    doc, stats = build(manifest, args.commit, load_overrides(args.overrides))
    text = dump(doc)
    Path(args.out).write_text(text, encoding="utf-8")
    print(report(stats, len(text.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
