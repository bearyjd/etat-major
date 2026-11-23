from test_planning_web import client_for as client_for
from test_planning_web import planning_workspace as planning_workspace


def test_planning_reports_shared_input_diagnostics_without_disclosing_records(
    planning_workspace, client_for
):
    decisions = planning_workspace / "decisions"
    linked = decisions / "0012-add-latency-graph.md"
    linked.write_text("---\nid: [\n---\n")
    private = decisions / "0099-unrelated-private-draft.md"
    private.write_text("---\nid: [\n---\n")
    other = decisions / "0013-add-cloud-sync.md"
    other.write_text(
        other.read_text().replace(
            "evidence: [research:0007#f2]",
            "evidence: [research:0007#f2]\nfeatures: [feature:other/9123]",
        )
    )
    research = planning_workspace / "research" / "0007-android-network-tools.md"
    research.write_text("---\nid: [\n---\n")

    with client_for(planning_workspace) as client:
        response = client.get("/project.json")
        data = response.json()
        page = client.get("/").text.split('<section id="sources">', 1)[1]

    for rendered in (response.text, page):
        assert "4 diagnostics in shared decisions" in rendered
        assert "1 diagnostic in shared research" in rendered
        assert "feature:netlens/0031" in rendered
        assert all(
            value not in rendered
            for value in (linked.name, private.name, research.name, "feature:other/9123")
        )
    assert any(issue["path"] == "decisions" for issue in data["issues"])
    assert any(issue["path"] == "research" for issue in data["issues"])
    assert any(
        issue["path"] == "feature:netlens/0031" and issue["field"] == "decisions"
        for issue in data["issues"]
    )
