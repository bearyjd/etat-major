import json
from dataclasses import replace
from pathlib import Path

import pytest

from etat_major.floorplan import load_graph
from etat_major.refs import parse_ref
from etat_major.render import render_trace
from etat_major.trace import TraceError, trace_feature
from etat_major.workspace import load_workspace

REF = parse_ref("feature:netlens/0031")
FEATURE = "features/netlens/0031-latency-graph.md"


def run(workspace_dir, graph_path=None, ref=REF):
    graph = load_graph(graph_path) if graph_path else None
    return trace_feature(load_workspace(workspace_dir), graph, ref)


def states(trace):
    return {str(a.ref): (a.relation, a.state) for a in trace.architecture}


def edit(root: Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def edit_graph(path: Path, fn) -> None:
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


def test_full_chain(workspace_dir, graph_file):
    t = run(workspace_dir, graph_file)
    assert t.feature.title == "Live latency graph"
    (r,) = t.research
    assert (str(r.ref), r.status, r.provenance, r.found) == (
        "research:0007",
        "reviewed",
        "ai-generated",
        True,
    )
    assert [(f.id, f.unsourced) for f in r.findings] == [("f1", False), ("f2", True)]
    assert all(f.provenance == "ai-generated" for f in r.findings)
    assert [(str(d.ref), d.relation, d.status, d.provenance) for d in t.decisions] == [
        ("decision:0012", "linked", "approved", "human"),
        ("decision:0013", "related", "rejected", "human"),
    ]
    assert [(a.id, a.state, a.provenance) for a in t.acceptance] == [
        ("a1", "open", "human"),
        ("a2", "open", "human"),
    ]


def test_gap_and_existing(workspace_dir, graph_file):
    t = run(workspace_dir, graph_file)
    assert states(t) == {
        "fp:n:ui.hostdetail": ("modifies", "existing"),
        "fp:f:app/src/net/Latency.kt": ("new", "gap"),
    }
    assert t.has_problems


def test_new_ref_present_is_built(workspace_dir, graph_file):
    edit_graph(
        graph_file, lambda d: d["files"].append({"p": "app/src/net/Latency.kt", "n": "net.scan"})
    )
    t = run(workspace_dir, graph_file)
    assert states(t)["fp:f:app/src/net/Latency.kt"] == ("new", "built")
    assert not t.has_problems


def test_stale_after_removing_node(workspace_dir, graph_file):
    edit_graph(
        graph_file, lambda d: d.update(nodes=[n for n in d["nodes"] if n["id"] != "ui.hostdetail"])
    )
    t = run(workspace_dir, graph_file)
    assert states(t)["fp:n:ui.hostdetail"] == ("modifies", "stale")
    assert t.has_problems


def test_uses_absent_is_stale_present_is_existing(workspace_dir, graph_file):
    edit(workspace_dir, FEATURE, "relation: modifies", "relation: uses")
    assert states(run(workspace_dir, graph_file))["fp:n:ui.hostdetail"] == ("uses", "existing")
    edit_graph(graph_file, lambda d: d.update(nodes=[]))
    assert states(run(workspace_dir, graph_file))["fp:n:ui.hostdetail"] == ("uses", "stale")


def test_no_graph_everything_unverified(workspace_dir):
    t = run(workspace_dir)
    assert {s for _, s in states(t).values()} == {"unverified"}
    assert not t.has_problems


def test_trail_ref_is_always_unverified(workspace_dir, graph_file):
    edit(
        workspace_dir,
        FEATURE,
        "ref: fp:n:ui.hostdetail",
        "ref: trail:app/src/ui/HostDetail.kt#show",
    )
    assert states(run(workspace_dir, graph_file))["trail:app/src/ui/HostDetail.kt#show"] == (
        "modifies",
        "unverified",
    )


def test_rejected_and_postponed_decisions_never_hidden(workspace_dir, graph_file):
    edit(workspace_dir, "decisions/0013-add-cloud-sync.md", "status: rejected", "status: postponed")
    statuses = {str(d.ref): d.status for d in run(workspace_dir, graph_file).decisions}
    assert statuses == {"decision:0012": "approved", "decision:0013": "postponed"}


def test_related_decision_flagged(workspace_dir):
    related = [d for d in run(workspace_dir).decisions if d.relation == "related"]
    assert [str(d.ref) for d in related] == ["decision:0013"]
    assert [(str(c.ref), c.state) for c in related[0].cites] == [("research:0007#f2", "unsourced")]


def test_decision_linking_feature_from_its_side_is_linked(workspace_dir):
    edit(
        workspace_dir,
        "decisions/0013-add-cloud-sync.md",
        "evidence:",
        "features: [feature:netlens/0031]\nevidence:",
    )
    rel = {str(d.ref): d.relation for d in run(workspace_dir).decisions}
    assert rel["decision:0013"] == "linked"


def test_warning_approved_decision_citing_unreviewed_research(workspace_dir):
    edit(
        workspace_dir,
        "research/0007-android-network-tools.md",
        "status: reviewed",
        "status: unreviewed",
    )
    t = run(workspace_dir)
    assert any("decision:0012" in w and "unreviewed" in w for w in t.warnings)
    assert not any("decision:0013" in w for w in t.warnings)  # rejected: no warning
    assert "WARNINGS\n  decision:0012 is approved but cites unreviewed research:0007\n" in (
        render_trace(t)
    )


def test_warning_approved_decision_citing_unsourced_finding(workspace_dir):
    edit(workspace_dir, "decisions/0012-add-latency-graph.md", "#f1", "#f2")
    assert any("unsourced" in w and "research:0007#f2" in w for w in run(workspace_dir).warnings)


def test_clean_demo_has_no_warnings(workspace_dir):
    assert run(workspace_dir).warnings == ()


@pytest.mark.parametrize("status", ["gap", "stale", "missing"])
def test_found_records_do_not_use_architecture_problem_states(workspace_dir, status):
    trace = run(workspace_dir)
    (research,) = trace.research
    decision = trace.decisions[0]
    assert not replace(trace, research=(replace(research, status=status),)).has_problems
    assert not replace(trace, decisions=(replace(decision, status=status),)).has_problems


def test_problem_states_are_specific_to_architecture_and_citations(workspace_dir):
    trace = run(workspace_dir)
    assert not replace(
        trace, architecture=(replace(trace.architecture[0], state="missing"),)
    ).has_problems
    decision = trace.decisions[0]
    (cite,) = decision.cites
    for state in ("gap", "stale"):
        assert not replace(
            trace, decisions=(replace(decision, cites=(replace(cite, state=state),)),)
        ).has_problems


def test_missing_links_marked_missing(workspace_dir):
    edit(
        workspace_dir,
        FEATURE,
        "research: [research:0007]",
        "research: [research:0099, research:0007]",
    )
    t = run(workspace_dir)
    missing = [r for r in t.research if not r.found]
    assert [(str(r.ref), r.status) for r in missing] == [("research:0099", "missing")]
    assert t.has_problems


@pytest.mark.parametrize("ref", ["research:0099", "research:0007#f99"])
def test_missing_decision_citation_is_a_problem(workspace_dir, ref):
    edit(workspace_dir, "decisions/0012-add-latency-graph.md", "research:0007#f1", ref)
    t = run(workspace_dir)
    decision = next(d for d in t.decisions if str(d.ref) == "decision:0012")
    assert [(str(c.ref), c.state) for c in decision.cites] == [(ref, "missing")]
    assert t.has_problems


def test_missing_feature_listed_decision_is_a_problem(workspace_dir):
    edit(
        workspace_dir,
        FEATURE,
        "decisions: [decision:0012]",
        "decisions: [decision:0012, decision:0099]",
    )
    t = run(workspace_dir)
    missing = [d for d in t.decisions if not d.found]
    assert [(str(d.ref), d.relation, d.status) for d in missing] == [
        ("decision:0099", "linked", "missing"),
    ]
    assert t.has_problems


def test_tasks_and_milestones_unverified(workspace_dir):
    edit(
        workspace_dir,
        FEATURE,
        "status: planned",
        "status: planned\ntasks: [task:netlens/0042]\nmilestones: [milestone:netlens/m3]",
    )
    t = run(workspace_dir)
    assert [(str(x.ref), x.state) for x in t.links] == [
        ("task:netlens/0042", "unverified"),
        ("milestone:netlens/m3", "unverified"),
    ]
    assert (
        "TASKS AND MILESTONES\n"
        "  task:netlens/0042  unverified\n"
        "  milestone:netlens/m3  unverified\n" in render_trace(t)
    )


def test_trace_errors(workspace_dir):
    with pytest.raises(TraceError, match="not found"):
        run(workspace_dir, ref=parse_ref("feature:netlens/0999"))
    with pytest.raises(TraceError, match="feature"):
        run(workspace_dir, ref=parse_ref("research:0007"))


def test_trace_is_immutable(workspace_dir):
    t = run(workspace_dir)
    with pytest.raises(AttributeError):
        t.warnings = ()  # type: ignore[misc]


def test_render_full_chain(workspace_dir, graph_file):
    out = render_trace(run(workspace_dir, graph_file))
    for needle in [
        "feature:netlens/0031",
        "Live latency graph",
        "research:0007  reviewed  ai-generated",
        "f1  sourced",
        "f2  unsourced",
        "decision:0012  approved  linked  human",
        "decision:0013  rejected  related  human",
        "fp:n:ui.hostdetail  modifies  existing  human",
        "fp:f:app/src/net/Latency.kt  new  gap  human",
        "a1  open  human",
        "a2  open  human",
    ]:
        assert needle in out, needle


def test_render_no_graph_and_deterministic(workspace_dir):
    out = render_trace(run(workspace_dir))
    assert "modifies  unverified" in out and "new  unverified" in out
    assert out == render_trace(run(workspace_dir))
    assert str(workspace_dir) not in out


def test_render_empty_architecture_as_unverified(workspace_dir):
    trace = replace(run(workspace_dir), architecture=())
    assert "ARCHITECTURE\n  (none)  unverified\nACCEPTANCE\n" in render_trace(trace)
