from pathlib import Path

import pytest

from etat_major.records import (
    load_decision,
    load_feature,
    load_research,
)
from etat_major.refs import Ref
from etat_major.taskfile import TaskFileError

RESEARCH = """---
id: 0007
title: What do network-tool users complain about?
status: reviewed
provenance: ai-generated
sources:
  - url: https://example.org/thread/123
    date: 2026-09-14
    kind: reddit
    evidence: firsthand
findings:
  - id: f1
    text: Users report slow scans.
    source: https://example.org/thread/123
    confidence: medium
  - id: f2
    text: Some say the UI is dated.
    evidence: unverified
---
Body text.
"""

DECISION = """---
id: 0012
question: Should NetLens add a live latency graph?
status: approved
decided_on: 2026-11-21
decided_by: human
chosen: Add a graph.
alternatives:
  - option: Export CSV only
    why_not: Does not show trends.
evidence: [research:0007#f1]
features: [feature:netlens/0031]
---
"""

FEATURE = """---
id: 0031
project: netlens
title: Live latency graph
status: planned
research: [research:0007]
decisions: [decision:0012]
acceptance:
  - id: a1
    text: Graph updates once per second.
architecture:
  - ref: fp:n:ui.hostdetail
    relation: modifies
  - ref: fp:f:app/Latency.kt
    relation: new
---
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def sub(text: str, old: str, new: str) -> str:
    assert old in text
    return text.replace(old, new, 1)


def fail(loader, path: Path, field: str | None, fragment: str) -> TaskFileError:
    with pytest.raises(TaskFileError) as exc:
        loader(path)
    assert exc.value.field == field, str(exc.value)
    assert fragment in str(exc.value), str(exc.value)
    assert path.name in str(exc.value)
    return exc.value


# ---- research ----


def test_research_loads(tmp_path):
    r = load_research(write(tmp_path, "0007-net.md", RESEARCH))
    assert r.id == "0007" and r.status == "reviewed" and r.provenance == "ai-generated"
    assert r.sources[0].url == "https://example.org/thread/123"
    assert [f.id for f in r.findings] == ["f1", "f2"]


def test_unsourced_flag_is_computed(tmp_path):
    r = load_research(write(tmp_path, "0007-net.md", RESEARCH))
    assert [r.is_unsourced(f) for f in r.findings] == [False, True]
    assert "unsourced" not in r.model_dump()["findings"][1]


def test_finding_source_not_in_sources_is_unsourced(tmp_path):
    text = sub(
        RESEARCH,
        "source: https://example.org/thread/123\n    confidence",
        "source: https://example.org/other\n    confidence",
    )
    r = load_research(write(tmp_path, "0007-net.md", text))
    assert r.is_unsourced(r.findings[0])


def test_research_is_frozen(tmp_path):
    r = load_research(write(tmp_path, "0007-net.md", RESEARCH))
    with pytest.raises(Exception, match="frozen"):
        r.status = "unreviewed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("old", "new", "field", "msg"),
    [
        ("status: reviewed", "status: approved", "status", "reviewed"),
        ("provenance: ai-generated", "provenance: robot", "provenance", "ai-generated"),
        ("id: 0007", "id: 0008", "id", "filename"),
        ("    date: 2026-09-14\n", "", "sources.0.date", "required"),
        ("  - id: f1", "  - idd: f1", "findings.0.id", "required"),
        ("    confidence: medium", "    confidence: certain", "findings.0.confidence", "medium"),
        ("kind: reddit", "kind: tweet", "sources.0.kind", "reddit"),
        ("status: reviewed\n", "status: reviewed\nunsourced: true\n", "unsourced", "not permitted"),
        (
            "    evidence: unverified",
            "    evidence: firsthand",
            "findings.1.evidence",
            "unverified",
        ),
    ],
)
def test_research_errors(tmp_path, old, new, field, msg):
    path = write(tmp_path, "0007-net.md", sub(RESEARCH, old, new))
    fail(load_research, path, field, msg)


def test_research_requires_a_source(tmp_path):
    text = sub(
        RESEARCH,
        RESEARCH[RESEARCH.index("sources:") : RESEARCH.index("findings:")],
        "sources: []\n",
    )
    fail(load_research, write(tmp_path, "0007-net.md", text), "sources", "at least 1")


def test_research_bad_frontmatter(tmp_path):
    fail(load_research, write(tmp_path, "0007-net.md", "no frontmatter"), None, "frontmatter")


# ---- decision ----


def test_decision_loads(tmp_path):
    d = load_decision(write(tmp_path, "0012-graph.md", DECISION))
    assert d.status == "approved" and d.decided_by == "human"
    assert d.evidence == (Ref("research", "0007", fragment="f1"),)
    assert d.features[0].project == "netlens"


@pytest.mark.parametrize("status", ["approved", "rejected", "postponed"])
def test_decided_status_requires_human(tmp_path, status):
    text = sub(sub(DECISION, "status: approved", f"status: {status}"), "decided_by: human\n", "")
    fail(load_decision, write(tmp_path, "0012-graph.md", text), "decided_by", "human")


def test_decided_by_must_be_human_not_agent(tmp_path):
    text = sub(DECISION, "decided_by: human", "decided_by: claude")
    fail(load_decision, write(tmp_path, "0012-graph.md", text), "decided_by", "human")


def test_proposed_decision_needs_no_decider(tmp_path):
    text = sub(sub(DECISION, "status: approved", "status: proposed"), "decided_by: human\n", "")
    assert load_decision(write(tmp_path, "0012-graph.md", text)).decided_by is None


@pytest.mark.parametrize(
    ("old", "new", "field", "msg"),
    [
        ("status: approved", "status: maybe", "status", "approved"),
        (
            "evidence: [research:0007#f1]",
            "evidence: [feature:netlens/0031]",
            "evidence.0",
            "research",
        ),
        (
            "evidence: [research:0007#f1]",
            "evidence: [research:abc]",
            "evidence.0",
            "invalid reference",
        ),
        ("features: [feature:netlens/0031]", "features: [research:0007]", "features.0", "feature"),
        ("question: Should NetLens add a live latency graph?\n", "", "question", "required"),
        ("option: Export CSV only", "opt: x", "alternatives.0.option", "required"),
    ],
)
def test_decision_errors(tmp_path, old, new, field, msg):
    fail(load_decision, write(tmp_path, "0012-graph.md", sub(DECISION, old, new)), field, msg)


# ---- feature ----


def test_feature_loads(tmp_path):
    f = load_feature(write(tmp_path, "0031-graph.md", FEATURE))
    assert f.id == "0031" and f.project == "netlens" and f.status == "planned"
    assert [str(a.ref) for a in f.architecture] == ["fp:n:ui.hostdetail", "fp:f:app/Latency.kt"]
    assert f.acceptance[0].id == "a1"


@pytest.mark.parametrize(
    "status",
    ["approved", "rejected", "postponed", "implementing", "verified", "released"],
)
def test_feature_rejects_derived_status(tmp_path, status):
    path = write(tmp_path, "0031-graph.md", sub(FEATURE, "status: planned", f"status: {status}"))
    err = fail(load_feature, path, "status", "derived")
    assert status in str(err)


@pytest.mark.parametrize("status", ["idea", "researching", "proposed", "planned"])
def test_feature_stored_statuses_ok(tmp_path, status):
    path = write(tmp_path, "0031-graph.md", sub(FEATURE, "status: planned", f"status: {status}"))
    assert load_feature(path).status == status


def test_feature_unknown_status(tmp_path):
    path = write(tmp_path, "0031-graph.md", sub(FEATURE, "status: planned", "status: wat"))
    fail(load_feature, path, "status", "idea")


@pytest.mark.parametrize(
    ("old", "new", "field", "msg"),
    [
        ("ref: fp:n:ui.hostdetail", "ref: feature:netlens/0031", "architecture.0.ref", "fp:"),
        ("ref: fp:n:ui.hostdetail", "ref: research:0007", "architecture.0.ref", "fp:"),
        ("ref: fp:n:ui.hostdetail", "ref: fp:f:../x", "architecture.0.ref", "path"),
        ("relation: modifies", "relation: deletes", "architecture.0.relation", "new"),
        ("research: [research:0007]", "research: [decision:0012]", "research.0", "research"),
        ("decisions: [decision:0012]", "decisions: [research:0007]", "decisions.0", "decision"),
        ("id: 0031", "id: 0099", "id", "filename"),
        ("title: Live latency graph\n", "", "title", "required"),
        ("status: planned\n", "status: planned\nverified: true\n", "verified", "not permitted"),
        ("  - id: a1", "  - idd: a1", "acceptance.0.id", "required"),
    ],
)
def test_feature_errors(tmp_path, old, new, field, msg):
    fail(load_feature, write(tmp_path, "0031-graph.md", sub(FEATURE, old, new)), field, msg)


def test_feature_trail_ref_and_optionals(tmp_path):
    text = sub(FEATURE, "ref: fp:n:ui.hostdetail", "ref: trail:app/x.py#Sym")
    text = sub(
        text,
        "status: planned\n",
        "status: planned\npriority: 2\nproblem: p\noutcome: o\n"
        "tasks: [task:netlens/0042]\nmilestones: [milestone:netlens/m3]\n",
    )
    f = load_feature(write(tmp_path, "0031-graph.md", text))
    assert f.architecture[0].ref.kind == "trail" and f.priority == 2
    assert f.tasks[0].kind == "task" and f.milestones[0].id == "m3"


def test_unreadable_file(tmp_path):
    fail(load_feature, tmp_path / "0031-x.md", None, "cannot read")
