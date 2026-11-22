import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter

import pytest

from etat_major.refs import parse_ref
from etat_major.trace import trace_feature
from etat_major.workspace import linked_decisions, load_workspace

FEATURE = "features/netlens/0031-latency-graph.md"
DECISION = "decisions/0012-add-latency-graph.md"


def edit(root: Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def messages(ws) -> list[str]:
    return [str(i) for i in ws.issues]


def test_demo_loads_clean(workspace_dir):
    ws = load_workspace(workspace_dir)
    assert ws.issues == ()
    assert [r.id for r in ws.research] == ["0007"]
    assert [d.id for d in ws.decisions] == ["0012", "0013"]
    assert [(f.project, f.id) for f in ws.features] == [("netlens", "0031")]


def test_lookups(workspace_dir):
    ws = load_workspace(workspace_dir)
    assert ws.get_research("0007").title.startswith("What do")
    assert ws.get_decision("0013").status == "rejected"
    assert ws.get_feature("netlens", "0031").title == "Live latency graph"
    assert ws.get_research("9999") is None and ws.get_feature("x", "1") is None


def test_missing_directories_are_empty(tmp_path):
    ws = load_workspace(tmp_path)
    assert ws.issues == () and ws.features == ()


def test_collects_all_file_errors(workspace_dir):
    edit(workspace_dir, "research/0007-android-network-tools.md", "status: reviewed", "status: x")
    edit(workspace_dir, DECISION, "decided_by: human\n", "")
    edit(workspace_dir, FEATURE, "status: planned", "status: verified")
    ws = load_workspace(workspace_dir)
    text = "\n".join(messages(ws))
    assert "research/0007-android-network-tools.md" in text and "field 'status'" in text
    assert "decisions/0012-add-latency-graph.md" in text and "decided_by" in text
    assert "features/netlens/0031-latency-graph.md" in text and "derived" in text
    file_issues = [i for i in ws.issues if i.path.endswith(".md")]
    assert len(file_issues) == 3
    assert [d.id for d in ws.decisions] == ["0013"]  # the valid files still load


def test_planned_requires_approved_decision(workspace_dir):
    edit(workspace_dir, DECISION, "status: approved", "status: postponed")
    ws = load_workspace(workspace_dir)
    assert any("planned" in m and "approved" in m for m in messages(ws))


def test_planned_without_any_decision(workspace_dir):
    edit(workspace_dir, FEATURE, "decisions: [decision:0012]\n", "")
    edit(workspace_dir, DECISION, "features: [feature:netlens/0031]\n", "")
    ws = load_workspace(workspace_dir)
    assert any(i.path == "feature:netlens/0031" and "approved" in i.message for i in ws.issues)


def test_not_planned_needs_no_decision(workspace_dir):
    edit(workspace_dir, FEATURE, "status: planned", "status: proposed")
    edit(workspace_dir, DECISION, "status: approved", "status: rejected")
    assert load_workspace(workspace_dir).issues == ()


@pytest.mark.parametrize(
    ("rel", "line", "missing_field"),
    [
        (FEATURE, "decisions: [decision:0012]\n", "decisions"),
        (DECISION, "features: [feature:netlens/0031]\n", "features"),
    ],
)
def test_one_sided_links_count_and_warn(workspace_dir, rel, line, missing_field):
    edit(workspace_dir, rel, line, "")
    ws = load_workspace(workspace_dir)
    assert ws.issues == ()
    feature = ws.get_feature("netlens", "0031")
    assert [d.id for d in linked_decisions(ws, feature)] == ["0012"]
    (warning,) = ws.warnings
    assert warning.field == missing_field
    trace = trace_feature(ws, None, parse_ref("feature:netlens/0031"))
    (trace_warning,) = trace.warnings
    assert "one-sided" in trace_warning
    assert "feature:netlens/0031" in trace_warning and "decision:0012" in trace_warning
    assert not trace.has_problems


@pytest.mark.parametrize(
    ("rel", "old", "new", "ref"),
    [
        (FEATURE, "research: [research:0007]", "research: [research:0099]", "research:0099"),
        (FEATURE, "decisions: [decision:0012]", "decisions: [decision:0099]", "decision:0099"),
        (
            DECISION,
            "features: [feature:netlens/0031]",
            "features: [feature:netlens/0099]",
            "feature:netlens/0099",
        ),
        (DECISION, "[research:0007#f1]", "[research:0099#f1]", "research:0099"),
        (DECISION, "[research:0007#f1]", "[research:0007#f9]", "research:0007#f9"),
    ],
)
def test_unresolved_refs_reported_as_missing(workspace_dir, rel, old, new, ref):
    edit(workspace_dir, rel, old, new)
    ws = load_workspace(workspace_dir)
    assert any("missing" in i.message and ref in i.message for i in ws.issues), messages(ws)


def test_duplicate_ids(workspace_dir):
    src = workspace_dir / "decisions/0013-add-cloud-sync.md"
    (workspace_dir / "decisions/0013-other-slug.md").write_text(src.read_text())
    assert any("duplicate" in m for m in messages(load_workspace(workspace_dir)))


def test_feature_project_must_match_directory(workspace_dir):
    (workspace_dir / "features/other").mkdir()
    (workspace_dir / FEATURE).rename(workspace_dir / "features/other/0031-latency-graph.md")
    msgs = messages(load_workspace(workspace_dir))
    assert any("project" in m and "other" in m for m in msgs)


def test_non_markdown_files_ignored(workspace_dir):
    (workspace_dir / "research/notes.txt").write_text("hi")
    assert load_workspace(workspace_dir).issues == ()


def test_feature_ref_resolution_helper(workspace_dir):
    ws = load_workspace(workspace_dir)
    assert ws.get_feature_by_ref(parse_ref("feature:netlens/0031")) is not None
    assert ws.get_feature_by_ref(parse_ref("feature:netlens/0999")) is None


@pytest.mark.parametrize("location", ["research/0099-linked.md", "features/linked", "decisions"])
def test_workspace_reports_symlinks(workspace_dir, tmp_path, location):
    link = workspace_dir / location
    target = tmp_path / "external"
    if location == "decisions":
        link.rename(target)
    elif location.endswith(".md"):
        demo = workspace_dir / "research/0007-android-network-tools.md"
        target.write_text(demo.read_text().replace("id: 0007", "id: 0099"))
    else:
        target.mkdir()
        path = target / "0099-external.md"
        path.write_text("---\nid: 0099\nproject: linked\ntitle: External\nstatus: idea\n---\n")
    link.symlink_to(target)
    ws = load_workspace(workspace_dir)
    assert any(i.path == location and "symlink" in i.message for i in ws.issues)
    assert ws.get_research("0099") is None
    assert ws.get_feature("linked", "0099") is None
    if location == "decisions":
        assert ws.decisions == ()


def test_workspace_reports_fifo_without_waiting(workspace_dir):
    os.mkfifo(workspace_dir / "research/0099-pipe.md")
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "etat_major.cli",
            "decisions",
            "list",
            "--workspace",
            str(workspace_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=2,
    )
    assert proc.returncode == 1
    assert "0099-pipe.md" in proc.stderr and "regular file" in proc.stderr


@pytest.mark.parametrize(
    "bad",
    ["2024-13-45", "9" * 5000, '!!int ""', "!!bool perhaps", "!!timestamp invalid"],
    ids=["date", "integer", "empty-int", "invalid-bool", "invalid-timestamp"],
)
def test_workspace_collects_yaml_value_errors(workspace_dir, bad):
    research = workspace_dir / "research"
    (research / "0098-value.md").write_text(f"---\nvalue: {bad}\n---\n")
    (research / "0099-other.md").write_text("invalid")
    ws = load_workspace(workspace_dir)
    assert [i.path for i in ws.issues] == ["research/0098-value.md", "research/0099-other.md"]
    assert "invalid YAML" in ws.issues[0].message
    assert [d.id for d in ws.decisions] == ["0012", "0013"]


def test_workspace_reports_stray_feature_files(workspace_dir):
    stray = ("features/.md", "features/top.md")
    for rel in stray:
        path = workspace_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    ws = load_workspace(workspace_dir)
    assert {i.path for i in ws.issues} == set(stray)
    assert all("features/<project>/" in i.message for i in ws.issues)
    assert len(ws.features) == 1


@pytest.mark.parametrize("location", ["research", "decisions", "features/netlens"])
def test_workspace_reports_unexpected_directories(workspace_dir, location):
    nested = workspace_dir / location / "unexpected" / "hidden.md"
    nested.parent.mkdir()
    nested.touch()
    (issue,) = load_workspace(workspace_dir).issues
    assert issue.path == f"{location}/unexpected"
    assert "unexpected directory" in issue.message


def test_workspace_skips_a_2000_deep_tree(tmp_path):
    project = tmp_path / "features" / "project"
    project.mkdir(parents=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(project, flags)
    depth = 0
    try:
        for _ in range(2000):
            os.mkdir("d", dir_fd=fd)
            child = os.open("d", flags, dir_fd=fd)
            os.close(fd)
            fd = child
            depth += 1
        start = perf_counter()
        ws = load_workspace(tmp_path)
        assert perf_counter() - start < 5
        (issue,) = ws.issues
        assert issue.path == "features/project/d"
        assert "unexpected directory" in issue.message
    finally:
        for _ in range(depth):
            parent = os.open("..", flags, dir_fd=fd)
            os.close(fd)
            fd = parent
            os.rmdir("d", dir_fd=fd)
        os.close(fd)


def test_workspace_uses_directory_descriptor_without_resolving(workspace_dir, monkeypatch):
    original = Path.resolve
    resolved = []

    def track_resolve(path, *args, **kwargs):
        resolved.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", track_resolve)
    ws = load_workspace(workspace_dir)
    assert ws.issues == ()
    assert resolved == []


def test_workspace_limits_records_read_per_directory(tmp_path):
    for project, count in (("crowded", 2001), ("small", 1)):
        folder = tmp_path / "features" / project
        folder.mkdir(parents=True)
        for index in range(count):
            (folder / f"{index}.md").write_text(
                f"---\nid: '{index}'\nproject: {project}\ntitle: Example\nstatus: idea\n---\n"
            )
    ws = load_workspace(tmp_path)
    assert len(ws.features) == 2001
    assert ws.get_feature("small", "0") is not None
    (issue,) = ws.issues
    assert issue.path == "features/crowded"
    assert "2000" in issue.message


def test_record_size_limit_before_reading(workspace_dir):
    path = workspace_dir / "research/0099-large.md"
    with path.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    (issue,) = load_workspace(workspace_dir).issues
    assert issue.path == "research/0099-large.md" and "1 MiB" in issue.message


def test_record_error_bounds_echoed_id(workspace_dir):
    edit(workspace_dir, FEATURE, "id: 0031", "id: " + "8" * 1000)
    issue = next(i for i in load_workspace(workspace_dir).issues if i.field == "id")
    assert "8" * 81 not in issue.message
    assert "8" * 79 in issue.message


def test_feature_research_finding_must_resolve(workspace_dir):
    edit(workspace_dir, FEATURE, "research: [research:0007]", "research: [research:0007#f9]")
    (issue,) = load_workspace(workspace_dir).issues
    assert (issue.path, issue.field) == ("feature:netlens/0031", "research")
    assert "missing" in issue.message and "research:0007#f9" in issue.message
