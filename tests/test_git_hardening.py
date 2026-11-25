"""A hostile repository config must never run code through any Git call made by src/."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from etat_major import renames
from etat_major.git_hardening import GIT_CONFIG_ARGS, git_environment

BASE_ENV = {"PATH": os.defpath, "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1"}


def _run(repo: Path, *args: str, env: dict[str, str] | None = None, prefix=()):
    return subprocess.run(  # noqa: S603 - local test repository only
        ["/usr/bin/git", *prefix, *args],
        cwd=repo,
        env=env or {**BASE_ENV, "GIT_CONFIG_GLOBAL": os.devnull},
        capture_output=True,
        check=False,
    )


def _script(path: Path, marker: Path) -> Path:
    path.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def hostile(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q", "--template=")
    (repo / "a.txt").write_text("a\n")
    _run(repo, "add", "-A")
    _run(repo, "-c", "user.name=T", "-c", "user.email=t", "commit", "-qm", "one", prefix=())
    marker = tmp_path / "marker"
    monitor = _script(tmp_path / "monitor.sh", marker)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    _script(hooks / "reference-transaction", marker)
    _run(repo, "config", "core.fsmonitor", str(monitor))
    _run(repo, "config", "core.hooksPath", str(hooks))
    return repo, marker


def _tripwire(repo: Path, env=None, prefix=()):
    _run(repo, "status", env=env, prefix=prefix)
    _run(repo, "update-ref", "refs/heads/x", "HEAD", env=env, prefix=prefix)


def test_fixture_is_hostile_without_hardening(hostile):
    repo, marker = hostile
    _tripwire(repo)
    assert marker.exists()


def test_hardened_arguments_neutralise_hostile_config(hostile):
    repo, marker = hostile
    env = git_environment()
    env["GIT_DIR"] = str(repo / ".git")
    env["GIT_WORK_TREE"] = str(repo)
    _tripwire(repo, env=env, prefix=GIT_CONFIG_ARGS)
    assert not marker.exists()


def test_environment_is_an_allow_list():
    env = git_environment()
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    assert set(env) <= {
        "PATH",
        "LC_ALL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_GLOBAL",
        "GIT_TERMINAL_PROMPT",
        "GIT_OPTIONAL_LOCKS",
        "GIT_ALLOW_PROTOCOL",
        "GIT_NO_LAZY_FETCH",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_ATTR_NOSYSTEM",
    }


def test_renames_git_call_uses_hardened_command(hostile, monkeypatch):
    repo, marker = hostile
    seen = {}
    real = subprocess.Popen

    def spy(command, **kwargs):
        seen.setdefault("commands", []).append(command)
        seen.setdefault("envs", []).append(kwargs["env"])
        return real(command, **kwargs)

    monkeypatch.setattr(renames.subprocess, "Popen", spy)
    renames.load_renames(repo, "HEAD", "HEAD")
    assert seen["commands"]
    for command, env in zip(seen["commands"], seen["envs"], strict=True):
        assert command[0] == "git"
        assert all(arg in command for arg in GIT_CONFIG_ARGS if arg != "-c")
        assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert not marker.exists()


def test_tool_runners_pass_hardened_git_config(tmp_path):
    from etat_major import floorplan_runner, trail_runner

    envs = [
        floorplan_runner._environment(tmp_path, tmp_path),
        trail_runner._environment(str(tmp_path), os.defpath, tmp_path),
    ]
    for env in envs:
        pairs = {
            env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
            for i in range(int(env["GIT_CONFIG_COUNT"]))
        }
        assert pairs["core.fsmonitor"] == "false"
        assert pairs["core.hooksPath"] == os.devnull
        assert env["GIT_TERMINAL_PROMPT"] == "0"
