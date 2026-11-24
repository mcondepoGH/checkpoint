import tomllib
from pathlib import Path

import checkpoint_client

ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_pyproject():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert checkpoint_client.__version__ == meta["version"]
    assert meta["name"] == "checkpoint-client"
    assert meta["scripts"] == {"checkpoint-client": "checkpoint_client.cli:main"}
    assert meta["requires-python"] == ">=3.12"


def test_changelog_has_current_version():
    assert f"## {checkpoint_client.__version__}" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_no_readme_en_yet():
    assert not (ROOT / "README.en.md").exists()
