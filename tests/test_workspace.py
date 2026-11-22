from pathlib import Path

import pytest

from etat_major.refs import parse_ref
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


def test_decision_side_link_counts(workspace_dir):
    edit(workspace_dir, FEATURE, "decisions: [decision:0012]\n", "")
    ws = load_workspace(workspace_dir)
    assert ws.issues == ()
    feature = ws.get_feature("netlens", "0031")
    assert [d.id for d in linked_decisions(ws, feature)] == ["0012"]


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
