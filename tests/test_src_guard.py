"""Guard: product code under src/ makes no network call, runs no unlisted process and never
reaches the capture script. See the capture-script exception in AGENTS.md."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "etat_major"
SUBPROCESS_ALLOWED = frozenset({"evidence_git", "floorplan_runner", "renames", "trail_runner"})
BANNED_MODULES = (
    "socket",
    "urllib.request",
    "http",
    "requests",
    "httpx",
    "pty",
    "asyncio.subprocess",
)
BANNED_CALLS = ("os.system", "os.popen", "__import__", "importlib.import_module")
BANNED_CALL_PREFIXES = ("os.exec", "os.spawn", "os.posix_spawn", "asyncio.create_subprocess")


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _under(name: str, root: str) -> bool:
    return name == root or name.startswith(root + ".")


def _imported_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    base = node.module or ""
    return [base, *(f"{base}.{alias.name}" for alias in node.names)]


def _import_violations(node: ast.Import | ast.ImportFrom, module: str) -> list[str]:
    found = []
    for name in _imported_names(node):
        if _under(name, "subprocess") and module not in SUBPROCESS_ALLOWED:
            found.append(f"{module}: import of subprocess")
        found.extend(f"{module}: import of {root}" for root in BANNED_MODULES if _under(name, root))
    return sorted(set(found))


def _call_violations(node: ast.Call, module: str) -> list[str]:
    name = _dotted(node.func)
    banned = name in BANNED_CALLS or name.startswith(BANNED_CALL_PREFIXES)
    return [f"{module}: call to {name}"] if banned else []


def _constant_violations(node: ast.Constant, module: str) -> list[str]:
    value = node.value
    if not isinstance(value, str):
        return []
    found = []
    if value == "gh":
        found.append(f"{module}: string constant 'gh'")
    if "scripts/" in value:
        found.append(f"{module}: reference to scripts/")
    return found


def check_source(source: str, module: str) -> list[str]:
    """Return one message per violation in the source of a src/ module."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [f"{module}: source does not parse"]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            found.extend(_import_violations(node, module))
        elif isinstance(node, ast.Call):
            found.extend(_call_violations(node, module))
        elif isinstance(node, ast.Constant):
            found.extend(_constant_violations(node, module))
    return found


@pytest.mark.parametrize("path", sorted(SRC.rglob("*.py")), ids=lambda p: p.name)
def test_current_src_has_no_violations(path):
    assert check_source(path.read_text(encoding="utf-8"), path.stem) == []


def test_src_is_not_empty():
    assert len(list(SRC.rglob("*.py"))) > 40


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ("import subprocess", "subprocess"),
        ("import subprocess as sp", "subprocess"),
        ("from subprocess import run", "subprocess"),
        ("import socket", "socket"),
        ("import urllib.request", "urllib.request"),
        ("from urllib.request import urlopen", "urllib.request"),
        ("from urllib import request", "urllib.request"),
        ("import http.client", "http"),
        ("from http import client", "http"),
        ("import requests", "requests"),
        ("import httpx", "httpx"),
        ("import pty", "pty"),
        ("from asyncio import subprocess", "asyncio.subprocess"),
        ("import os\nos.system('x')", "os.system"),
        ("import os\nos.popen('x')", "os.popen"),
        ("import os\nos.execv('x', [])", "os.exec"),
        ("import os\nos.spawnl(0, 'x')", "os.spawn"),
        ("import asyncio\nasyncio.create_subprocess_exec('x')", "asyncio.create_subprocess"),
        ("__import__('subprocess')", "__import__"),
        ("import importlib\nimportlib.import_module('x')", "importlib.import_module"),
        ("ARGV = ['gh', 'pr', 'list']\nTOOL = 'gh'", "gh"),
        ("PATH = 'scripts/record_github.py'", "scripts/"),
    ],
)
def test_violation_is_reported(source, rule):
    messages = check_source(source, "evidence_records")
    assert messages, f"expected a violation for {rule}"
    assert any(rule in message for message in messages)


@pytest.mark.parametrize("module", sorted(SUBPROCESS_ALLOWED))
def test_allow_listed_module_may_import_subprocess(module):
    assert check_source("import subprocess\nfrom subprocess import run", module) == []


def test_allow_list_does_not_cover_other_banned_modules():
    assert check_source("import socket", "renames")
    assert check_source("import os\nos.system('x')", "trail_runner")


def test_a_fifth_subprocess_importer_fails():
    assert check_source("import subprocess", "planning_view")


@pytest.mark.parametrize(
    "source",
    [
        "from urllib.parse import urlsplit",
        "from urllib import parse",
        "import json, os, re",
        "TEXT = 'ghost github.com/gh-pages'",
        "DOC = 'see docs/contracts/ and scripts'",
        "import asyncio\nasyncio.sleep(0)",
        "import os\nos.path.join('a', 'b')",
    ],
)
def test_harmless_code_passes(source):
    assert check_source(source, "evidence_records") == []


def test_unparseable_source_is_reported():
    assert check_source("def broken(:", "evidence_records")


def test_subprocess_allow_list_names_real_modules():
    existing = {path.stem for path in SRC.rglob("*.py")}
    assert SUBPROCESS_ALLOWED <= existing
