"""Los agentes de proyecto de `.claude/agents/` (líder + Haiku lee + Sonnet escribe) existen y se pueden commitear.

Son de desarrollo: no van en la imagen Docker ni en los paquetes del producto.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".claude" / "agents"


def _agent(name: str):
    text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
    head, body = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S).groups()
    meta = dict(line.split(":", 1) for line in head.splitlines() if ":" in line)
    return {k: v.strip() for k, v in meta.items()}, body


def test_explore_is_haiku_and_read_only():
    meta, body = _agent("Explore")
    assert meta["name"] == "Explore"
    assert meta["model"] == "haiku"
    assert {t.strip() for t in meta["tools"].split(",")} == {"Read", "Grep", "Glob"}
    assert "No edites nada" in body


def test_implementer_is_sonnet_and_does_not_delegate():
    meta, body = _agent("implementer")
    assert meta["name"] == "implementer"
    assert meta["model"] == "sonnet"
    tools = {t.strip() for t in meta["tools"].split(",")}
    assert "Agent" not in tools
    assert {"Edit", "Write", "Bash"} <= tools
    for rule in ("TDD", "en español", "push", "tag", "versión", "REPO_WARDEN_CONFIRMED", "ruff", "pytest", "npm ci"):
        assert rule in body, rule


def test_agents_are_not_git_ignored():
    for name in ("Explore", "implementer"):
        r = subprocess.run(["git", "check-ignore", "-q", f".claude/agents/{name}.md"], cwd=ROOT, capture_output=True)
        assert r.returncode == 1, f"{name}.md está ignorado por git"


def test_agents_stay_out_of_docker_context():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".claude" in lines
