from dataclasses import replace
from datetime import date

import pytest

from etat_major import discover_view
from etat_major.discover_view import build_discover, filter_decisions
from etat_major.planning_view import PlanningInputs, load_planning_view
from etat_major.records import Decision
from etat_major.refs import Ref
from etat_major.trace import cite
from etat_major.workspace import load_workspace


def _view(workspace_dir):
    return build_discover(load_workspace(workspace_dir))


def _decision(n, **kwargs):
    return Decision(id=f"{n:04d}", question=f"Question {n}?", status="proposed", **kwargs)


def test_trace_cite_is_public(workspace_dir):
    ws = load_workspace(workspace_dir)
    assert cite(ws, Ref("research", "0007", fragment="f2")).state == "unsourced"
    assert cite(ws, Ref("research", "0007", fragment="f1")).state == "ok"
    assert cite(ws, Ref("research", "9999")).state == "missing"


def test_demo_research_labels_each_finding(workspace_dir):
    view = _view(workspace_dir)
    [research] = view.research
    assert (research.id, research.status, research.provenance) == (
        "0007",
        "reviewed",
        "ai-generated",
    )
    findings = {f.id: f for f in research.findings}
    assert findings["f1"].unsourced is False
    assert findings["f1"].source == "https://example.org/thread/123"
    assert findings["f1"].source_date == date(2026, 9, 14)
    assert findings["f2"].unsourced is True
    assert findings["f2"].source is None
    assert research.project is None


def test_demo_decisions_include_rejected_with_alternatives_and_cites(workspace_dir):
    view = _view(workspace_dir)
    rows = {d.id: d for d in view.decisions}
    assert set(rows) == {"0012", "0013"}
    rejected = rows["0013"]
    assert rejected.status == "rejected"
    assert rejected.alternatives == (
        ("Optional cloud sync", "Adds an account system and a privacy burden."),
    )
    [cited] = rejected.cites
    assert (cited.ref, cited.state) == ("research:0007#f2", "unsourced")
    assert (cited.status, cited.provenance) == ("reviewed", "ai-generated")
    assert rows["0012"].cites[0].state == "ok"
    assert rows["0012"].features == ("netlens/0031",)


def test_research_lists_features_that_cite_it(workspace_dir):
    ws = load_workspace(workspace_dir)
    feature = ws.features[0].model_copy(update={"research": (Ref("research", "0007"),)})
    view = build_discover(replace(ws, features=(feature,)))
    assert view.research[0].features == (f"{feature.project}/{feature.id}",)


def test_issue_count_comes_from_workspace_issues(workspace_dir):
    (workspace_dir / "decisions" / "0099-broken.md").write_text("---\nid: [oops\n---\n")
    view = _view(workspace_dir)
    assert view.issue_count >= 1
    assert {d.id for d in view.decisions} == {"0012", "0013"}
    assert view.has_data


def test_empty_workspace_has_no_data():
    from etat_major.workspace import Workspace

    view = build_discover(Workspace((), (), (), ()))
    assert not view.has_data
    assert view.issue_count == 0


def test_caps_show_omitted_counts(monkeypatch):
    from etat_major.workspace import Workspace

    monkeypatch.setattr(discover_view, "MAX_DECISIONS", 3)
    ws = Workspace((), tuple(_decision(n) for n in range(1, 6)), (), ())
    view = build_discover(ws)
    assert len(view.decisions) == 3
    assert view.omitted_decisions == 2


def test_filter_matches_text_and_status(workspace_dir):
    view = _view(workspace_dir)
    assert [d.id for d in filter_decisions(view, "CLOUD sync").decisions] == ["0013"]
    assert [d.id for d in filter_decisions(view, "rejected").decisions] == ["0013"]
    assert [d.id for d in filter_decisions(view, "account system").decisions] == ["0013"]
    empty = filter_decisions(view, "no such thing")
    assert empty.decisions == () and empty.query == "no such thing"
    assert len(filter_decisions(view, "").decisions) == 2


@pytest.mark.parametrize("query", ["x" * 129, "a\x00b", "a\nb", "bad�"])
def test_filter_rejects_invalid_query(workspace_dir, query):
    with pytest.raises(ValueError, match="query"):
        filter_decisions(_view(workspace_dir), query)


def test_filter_accepts_limit_length(workspace_dir):
    assert filter_decisions(_view(workspace_dir), "x" * 128).decisions == ()


def test_planning_view_carries_private_discover_field(workspace_dir):
    view = load_planning_view(PlanningInputs(workspace_dir, "netlens"))
    assert {d.id for d in view._discover.decisions} == {"0012", "0013"}
    assert "_discover" not in repr(view)
    assert replace(view, _discover=None) == view
