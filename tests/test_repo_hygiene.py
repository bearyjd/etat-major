import os
import re
import subprocess
from pathlib import Path

import pytest

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
# A personal machine name must not appear in this public repository (CLAUDE.md
# constraint 8). It is built from pieces so this guard does not contain it.
HOST_NAME = "al" + "to"
HOST_NAME_RE = re.compile(rf"(?<![a-z]){HOST_NAME}(?![a-z])", re.IGNORECASE)


def tracked_files():
    out = subprocess.run(  # noqa: S603
        ["git", "ls-files", "-z"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [name for name in out.split("\0") if name]


def tracked_text(name):
    path = ROOT / name
    if path.is_symlink():
        return os.readlink(path)
    if not path.is_file():
        return ""
    data = path.read_bytes()
    return "" if b"\0" in data else data.decode("utf-8", errors="replace")


def test_gitignore_covers_build_artifacts():
    lines = (ROOT / ".gitignore").read_text().splitlines()
    for entry in REQUIRED:
        assert entry in lines


def test_gitignore_keeps_existing_entries():
    lines = (ROOT / ".gitignore").read_text().splitlines()
    for entry in ["/graft/", ".omc/", ".trail/", ".env", "*.env"]:
        assert entry in lines


def test_no_artifacts_tracked():
    out = tracked_files()
    bad = [f for f in out if "__pycache__" in f or ".egg-info" in f or f.endswith(".pyc")]
    assert bad == []


@pytest.mark.parametrize(
    ("template", "found"),
    [
        ("on {} today", True),
        ("{}.", True),
        ("docs/{}-RUNBOOK.md", True),
        ("run-{}.XXXXXX", True),
        ("{}_host", True),
        ("{}gether", False),
        ("contr{}", False),
    ],
)
def test_host_name_pattern(template, found):
    for name in (HOST_NAME, HOST_NAME.title(), HOST_NAME.upper()):
        assert bool(HOST_NAME_RE.search(template.format(name))) is found


def test_no_personal_host_name_tracked():
    bad = []
    for name in tracked_files():
        if HOST_NAME_RE.search(name):
            bad.append(f"{name}: file name")
        for number, line in enumerate(tracked_text(name).split("\n"), start=1):
            if HOST_NAME_RE.search(line):
                bad.append(f"{name}:{number}")
    assert bad == [], "personal host name found; use neutral wording"
