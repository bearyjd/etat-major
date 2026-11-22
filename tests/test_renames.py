import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(  # noqa: S603 - local test repositories only
        ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        env={
            "PATH": os.defpath,
            "HOME": str(repo),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def history(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "--template=")
    for path, text in {
        "old name.py": "exact match\n",
        "edit.py": "".join(f"line {i} of original content\n" for i in range(50)),
        "delete.py": "this will be removed\n",
    }.items():
        (repo / path).write_text(text)
    commit(repo)
    (repo / "old name.py").rename(repo / "new\tname.py")
    old = repo / "edit.py"
    (repo / "edited.py").write_text(old.read_text().replace("line 5 ", "changed 5 "))
    old.unlink()
    (repo / "delete.py").unlink()
    (repo / "add.py").write_text("a new file with entirely different text\n")
    commit(repo)
    return repo


def commit(repo):
    git(repo, "add", "--all")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test", "commit", "-qm", "snapshot")


def test_git_reports_only_renames_including_edits(history):
    from etat_major.renames import load_renames

    result = load_renames(history, "HEAD~1", "HEAD")
    assert isinstance(result, Mapping)
    assert result == {"old name.py": "new\tname.py", "edit.py": "edited.py"}
    with pytest.raises(TypeError):
        result["delete.py"] = "add.py"


def test_git_no_renames_between_same_revision(history):
    from etat_major.renames import load_renames

    assert load_renames(history, "HEAD", "HEAD") == {}


@pytest.mark.parametrize(
    "revision", ["--output=outside", "missing", "HEAD...HEAD", "HEAD:edited.py"]
)
def test_git_rejects_invalid_commit_revision(history, revision):
    from etat_major.renames import RenameError, load_renames

    with pytest.raises(RenameError, match=r"repo.*old_revision"):
        load_renames(history, revision, "HEAD")
    assert not (history / "outside").exists()


@pytest.mark.parametrize("relative", ["config", "objects", "refs/heads"])
def test_git_rejects_symlinked_metadata(history, relative):
    from etat_major.renames import RenameError, load_renames

    path = history / ".git" / relative
    target = history / "moved"
    path.rename(target)
    path.symlink_to(target, target_is_directory=target.is_dir())
    with pytest.raises(RenameError, match=r"repo.*\.git.*symlink"):
        load_renames(history, "HEAD~1", "HEAD")


def test_git_rejects_symlinked_repository_ancestor(history):
    from etat_major.renames import RenameError, load_renames

    alias = history.parent / "alias"
    alias.symlink_to(history.parent, target_is_directory=True)
    with pytest.raises(RenameError, match=r"repo.*\.git"):
        load_renames(alias / history.name, "HEAD~1", "HEAD")


@pytest.mark.parametrize(
    ("relative", "data"),
    [
        ("config", '\n[includeIf "gitdir:**"]\npath = /private/remote\n'),
        ("objects/info/alternates", "/private/remote\n"),
        ("objects/info/http-alternates", "https://example.invalid/remote\n"),
        ("commondir", "/private/remote\n"),
    ],
)
def test_git_rejects_indirect_metadata_without_printing_target(history, relative, data):
    from etat_major.renames import RenameError, load_renames

    with (history / ".git" / relative).open("a") as stream:
        stream.write(data)
    with pytest.raises(RenameError, match=r"repo.*\.git") as exc:
        load_renames(history, "HEAD~1", "HEAD")
    assert "/private" not in str(exc.value)
    assert "example.invalid" not in str(exc.value)


def test_rename_metadata_does_not_walk_all_entries(history, monkeypatch):
    from etat_major.renames import load_renames

    monkeypatch.setattr(
        os, "fwalk", lambda *args, **kwargs: iter([(".", [], ["item"] * 100001, 0)])
    )
    assert load_renames(history, "HEAD~1", "HEAD")["edit.py"] == "edited.py"


def test_git_reads_renames_in_a_linked_worktree(history, tmp_path):
    from etat_major.renames import load_renames

    worktree = tmp_path / "linked worktree"
    git(history, "worktree", "add", "--detach", str(worktree))
    assert load_renames(worktree, "HEAD~1", "HEAD")["edit.py"] == "edited.py"


def test_git_reads_renames_in_a_relative_linked_worktree(history, tmp_path):
    from etat_major.renames import load_renames

    worktree = tmp_path / "relative"
    git(history, "worktree", "add", "--detach", str(worktree))
    pointer = worktree / ".git"
    gitdir = Path(pointer.read_text().strip().removeprefix("gitdir: "))
    pointer.write_text(f"gitdir: {os.path.relpath(gitdir, worktree)}\n")
    (gitdir / "gitdir").write_text(f"{os.path.relpath(pointer, gitdir)}\n")
    assert load_renames(worktree, "HEAD~1", "HEAD")["edit.py"] == "edited.py"


def test_git_rejects_symlinked_loose_object_bucket(history):
    from etat_major.renames import RenameError, load_renames

    oid = git(history, "rev-parse", "HEAD").decode().strip()
    bucket = history / ".git" / "objects" / oid[:2]
    target = history / "moved"
    bucket.rename(target)
    bucket.symlink_to(target, target_is_directory=True)
    with pytest.raises(RenameError, match=r"repo.*\.git.*symlink"):
        load_renames(history, "HEAD~1", "HEAD")
