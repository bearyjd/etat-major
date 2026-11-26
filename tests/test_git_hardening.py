"""A hostile repository config must never run code through any Git call made by src/."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from etat_major import evidence_git, renames
from etat_major.git_hardening import GIT_CONFIG_ARGS, HARDENED_CONFIG, git_environment
from etat_major.taskfile import TaskFileError

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


def _git_out(repo: Path, *args: str, stdin: bytes | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - local test repository only
        ["/usr/bin/git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        env={**BASE_ENV, "GIT_CONFIG_GLOBAL": os.devnull},
        input=stdin,
        capture_output=True,
        check=True,
    )
    return result.stdout.decode().strip()


@pytest.fixture
def bare_attack(tmp_path):
    """A repository whose config runs a marker script through every bare-mode vector."""
    repo = tmp_path / "attack"
    repo.mkdir()
    _git_out(repo, "init", "-q", "--template=")
    (repo / "old.txt").write_text("".join(f"line {n}\n" for n in range(20)))
    (repo / ".gitattributes").write_text("*.txt diff=evil filter=evil\n")
    _git_out(repo, "add", "-A")
    _git_out(repo, "commit", "-qm", "one")
    (repo / "old.txt").rename(repo / "new.txt")
    _git_out(repo, "add", "-A")
    _git_out(repo, "commit", "-qm", "two")
    second = _git_out(repo, "cat-file", "commit", "HEAD")
    head, _, message = second.partition("\n\n")
    signature = "gpgsig -----BEGIN PGP SIGNATURE-----\n \n x\n -----END PGP SIGNATURE-----"
    signed = f"{head}\n{signature}\n\n{message}\n"
    oid = _git_out(repo, "hash-object", "-t", "commit", "-w", "--stdin", stdin=signed.encode())
    _git_out(repo, "update-ref", "refs/heads/master", oid)
    _git_out(repo, "update-ref", "refs/heads/main", oid)
    marker = tmp_path / "marker"
    script = _script(tmp_path / "evil.sh", marker)
    for key in ("log.showSignature",):
        _git_out(repo, "config", key, "true")
    for key in ("gpg.program", "gpg.ssh.program", "gpg.x509.program", "diff.external"):
        _git_out(repo, "config", key, str(script))
    _git_out(repo, "config", "diff.evil.textconv", str(script))
    _git_out(repo, "config", "filter.evil.clean", str(script))
    _git_out(repo, "config", "filter.evil.smudge", str(script))
    return repo, marker


def _bare_env(repo: Path) -> dict[str, str]:
    return {**BASE_ENV, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_DIR": str(repo / ".git")}


def test_bare_control_runs_hostile_config(bare_attack):
    repo, marker = bare_attack
    env = _bare_env(repo)
    subprocess.run(
        ["/usr/bin/git", "--bare", "log", "-1", "--format=%H"], cwd="/", env=env, check=False
    )  # noqa: S603
    assert marker.exists()
    marker.unlink()
    subprocess.run(
        ["/usr/bin/git", "--bare", "diff", "HEAD~1", "HEAD"], cwd="/", env=env, check=False
    )  # noqa: S603
    assert marker.exists()


@pytest.mark.parametrize(
    "args",
    [
        ("log", "-1", "--format=%H"),
        ("for-each-ref", "--format=%(signature)"),
        ("verify-commit", "HEAD"),
        ("diff", "HEAD~1", "HEAD"),
    ],
)
def test_module_alone_neutralises_bare_mode_vectors(bare_attack, args):
    repo, marker = bare_attack
    env = git_environment()
    env["GIT_DIR"] = str(repo / ".git")
    subprocess.run(  # noqa: S603 - local test repository only
        ["/usr/bin/git", *GIT_CONFIG_ARGS, "--bare", *args], cwd="/", env=env, check=False
    )
    assert not marker.exists()


def test_load_renames_runs_no_repository_program(bare_attack):
    repo, marker = bare_attack
    renames.load_renames(repo, "HEAD~1", "HEAD")
    assert not marker.exists()


def test_load_git_runs_no_repository_program(bare_attack):
    repo, marker = bare_attack
    evidence_git.load_git(repo, (), (), frozenset())
    assert not marker.exists()


@pytest.fixture
def promisor_attack(tmp_path):
    """A partial clone missing a tree, whose promisor remote is an ext:: marker command."""
    repo = tmp_path / "promisor"
    (repo / "sub").mkdir(parents=True)
    _git_out(repo, "init", "-q", "--template=")
    for message, content in (("one", "a\n"), ("two", "b\n")):
        (repo / "sub" / "a.txt").write_text(content)
        _git_out(repo, "add", "-A")
        _git_out(repo, "commit", "-qm", message)
    tree = _git_out(repo, "rev-parse", "HEAD:sub")
    marker = tmp_path / "marker"
    script = _script(tmp_path / "remote.sh", marker)
    for key, value in (
        ("core.repositoryformatversion", "1"),
        ("extensions.partialClone", "origin"),
        ("remote.origin.promisor", "true"),
        ("remote.origin.url", f"ext::{script}"),
        ("protocol.ext.allow", "always"),
    ):
        _git_out(repo, "config", key, value)
    (repo / ".git" / "objects" / tree[:2] / tree[2:]).unlink()
    return repo, marker


@pytest.mark.parametrize("args", [("ls-tree", "-r", "HEAD"), ("diff", "HEAD~1", "HEAD")])
def test_promisor_control_runs_remote_command(promisor_attack, args):
    repo, marker = promisor_attack
    subprocess.run(  # noqa: S603 - local test repository only
        ["/usr/bin/git", "--bare", *args], cwd="/", env=_bare_env(repo), check=False
    )
    assert marker.exists()


def _drive_renames(repo: Path) -> None:
    renames.load_renames(repo, "HEAD~1", "HEAD")


def _drive_evidence(repo: Path) -> None:
    evidence_git.load_git(repo, (), (), frozenset())


@pytest.mark.parametrize(
    ("loader", "error"),
    [(_drive_renames, renames.RenameError), (_drive_evidence, TaskFileError)],
)
def test_loaders_never_lazy_fetch_from_a_promisor(promisor_attack, loader, error):
    repo, marker = promisor_attack
    with pytest.raises(error):
        loader(repo)
    assert not marker.exists()
    assert dict(HARDENED_CONFIG)["protocol.allow"] == "never"
    assert git_environment()["GIT_ALLOW_PROTOCOL"] == ""
    assert git_environment()["GIT_NO_LAZY_FETCH"] == "1"
