from pathlib import Path

import pytest

from etat_major.workspace import WorkspaceError, load_workspace


def write_task(
    root: Path,
    task_id: str,
    *,
    project: str = "example",
    depends_on: tuple[str, ...] = (),
    slug: str = "task",
    location: str | None = None,
) -> Path:
    folder = root / (location if location is not None else f"tasks/{project}")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{task_id}-{slug}.md"
    path.write_text(
        f"---\nid: '{task_id}'\ntitle: Example Task\ninitiative: demo\n"
        f"project: {project}\nowner: alice\nstatus: draft\n"
        f"depends_on: {list(depends_on)!r}\n---\n"
    )
    return path


def test_dependencies_resolve_only_within_the_project(tmp_path):
    write_task(tmp_path, "0001", depends_on=("0002", "0003", "0004"))
    write_task(tmp_path, "0002")
    write_task(tmp_path, "0001", project="other")
    write_task(tmp_path, "0003", project="other")

    ws = load_workspace(tmp_path)

    assert [(task.project, task.id) for task in ws.tasks] == [
        ("example", "0001"),
        ("example", "0002"),
        ("other", "0001"),
        ("other", "0003"),
    ]
    assert [(issue.path, issue.field) for issue in ws.issues] == [
        ("tasks/example/0001-task.md", "depends_on"),
        ("tasks/example/0001-task.md", "depends_on"),
    ]
    assert "0003" in ws.issues[0].message
    assert "0004" in ws.issues[1].message


def test_collects_cycles_and_unresolved_dependencies(tmp_path):
    write_task(tmp_path, "002", depends_on=("003",))
    write_task(tmp_path, "003", depends_on=("002",))
    write_task(tmp_path, "001", depends_on=("001", "999"))
    write_task(tmp_path, "004", depends_on=("002", "005"))
    write_task(tmp_path, "005", depends_on=("004",))

    issues = load_workspace(tmp_path).issues

    assert len(issues) == 4
    assert all(issue.field == "depends_on" for issue in issues)
    assert any("999" in issue.message for issue in issues)
    cycles = [issue for issue in issues if "cycle" in issue.message]
    assert [issue.path for issue in cycles] == [
        "tasks/example/001-task.md",
        "tasks/example/002-task.md",
        "tasks/example/004-task.md",
    ]
    for issue, members in zip(cycles, [("001",), ("002", "003"), ("004", "005")], strict=True):
        assert all(member in issue.message for member in members)
    assert load_workspace(tmp_path).issues == issues


def test_reports_invalid_task_locations_and_duplicate_ids(tmp_path):
    write_task(tmp_path, "001")
    write_task(tmp_path, "001", slug="another")
    write_task(tmp_path, "002", location="tasks")
    write_task(tmp_path, "003", location="tasks/different")

    issues = load_workspace(tmp_path).issues

    assert any(
        issue.path in {"tasks/example/001-task.md", "tasks/example/001-another.md"}
        and issue.field == "id"
        and "duplicate" in issue.message
        for issue in issues
    )
    assert any(issue.path == "tasks/002-task.md" for issue in issues)
    assert any(
        issue.path == "tasks/different/003-task.md" and issue.field == "project" for issue in issues
    )


def test_workspace_reports_task_symlinks(tmp_path):
    target = write_task(tmp_path, "001", location="outside")
    project = tmp_path / "tasks" / "example"
    project.mkdir(parents=True)
    (project / target.name).symlink_to(target)
    (project.parent / "other").symlink_to(target.parent)

    ws = load_workspace(tmp_path)

    assert ws.tasks == ()
    assert [issue.path for issue in ws.issues] == [
        "tasks/example/001-task.md",
        "tasks/other",
    ]
    assert all("symlink" in issue.message for issue in ws.issues)


def test_workspace_rejects_a_symlinked_parent(tmp_path):
    write_task(tmp_path / "outside" / "workspace", "001")
    link = tmp_path / "linked"
    link.symlink_to(tmp_path / "outside")

    with pytest.raises(WorkspaceError):
        load_workspace(link / "workspace")


def test_task_project_mismatch_does_not_echo_an_untrusted_absolute_path(tmp_path):
    path = write_task(tmp_path, "001", location="tasks/other")
    path.write_text(path.read_text().replace("project: example", "project: /private/project"))
    (issue,) = load_workspace(tmp_path).issues
    assert issue.field == "project"
    assert "/private/" not in str(issue)


def test_dependency_issue_escapes_untrusted_filename(tmp_path):
    write_task(tmp_path, "001", slug="task\x1b", depends_on=("002",))
    (issue,) = load_workspace(tmp_path).issues
    assert r"001-task\u001b.md" in str(issue)


@pytest.mark.parametrize("cycle", [False, True])
def test_long_dependency_chain_and_cycle(tmp_path, cycle):
    for n in range(1100):
        following = (f"{n + 1:04}",) if n < 1099 else (("0000",) if cycle else ())
        write_task(tmp_path, f"{n:04}", depends_on=following)

    ws = load_workspace(tmp_path)

    assert len(ws.tasks) == 1100
    assert len(ws.issues) == int(cycle)
    if cycle:
        assert "cycle" in ws.issues[0].message
