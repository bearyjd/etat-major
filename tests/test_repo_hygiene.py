import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "__pycache__/",
    "*.egg-info/",
    ".pytest_cache/",
    ".coverage",
    ".ruff_cache/",
    "build/",
    "dist/",
]


def test_gitignore_covers_build_artifacts():
    lines = (ROOT / ".gitignore").read_text().splitlines()
    for entry in REQUIRED:
        assert entry in lines


def test_gitignore_keeps_existing_entries():
    lines = (ROOT / ".gitignore").read_text().splitlines()
    for entry in ["/graft/", ".omc/", ".trail/", ".env", "*.env"]:
        assert entry in lines


def test_no_artifacts_tracked():
    out = subprocess.run(  # noqa: S603
        ["git", "ls-files"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    bad = [f for f in out if "__pycache__" in f or ".egg-info" in f or f.endswith(".pyc")]
    assert bad == []
