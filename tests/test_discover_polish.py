from datetime import date
from types import SimpleNamespace

import pytest

from etat_major.discover_html import render
from etat_major.discover_view import (
    CiteRow,
    DecisionRow,
    DiscoverView,
    FindingRow,
    ResearchRow,
    build_discover,
)
from etat_major.workspace import Issue


def _decision(record_id="0001", cite_state="ok"):
    cite = CiteRow("research:0001#f1", cite_state, "reviewed", "ai-generated")
    return DecisionRow(
        record_id, "Question?", "approved", date(2026, 11, 21), "A", "Why", (), 0, (cite,), 0, ()
    )


def _research(record_id="0001"):
    finding = FindingRow("f1", "Claim", "https://example.org/t", date(2026, 9, 14), False)
    return ResearchRow(record_id, "Title", "reviewed", "ai-generated", None, (finding,), 0, ())


def test_sections_sit_inside_one_main_landmark():
    html = render(DiscoverView((_research(),), (_decision(),)))
    assert html.count("<main>") == 1 and html.count("</main>") == 1
    assert html.index("<main>") < html.index("<section>")
    assert html.rindex("</section>") < html.index("</main>")


def test_the_header_stays_outside_main():
    html = render(DiscoverView((), (_decision(),)))
    assert html.index("</header>") < html.index("<main>")


def test_a_resolving_citation_is_labelled_resolves():
    html = render(DiscoverView((), (_decision(cite_state="ok"),)))
    assert ">resolves<" in html
    assert ">ok<" not in html


@pytest.mark.parametrize("state", ["unsourced", "missing"])
def test_other_citation_states_keep_their_labels(state):
    assert f">{state}<" in render(DiscoverView((), (_decision(cite_state=state),)))


def test_record_ids_are_escaped_in_both_sections():
    html = render(DiscoverView((_research("<i>9</i>"),), (_decision("<b>1</b>"),)))
    assert "<b>1</b>" not in html and "&lt;b&gt;1&lt;/b&gt;" in html
    assert "<i>9</i>" not in html and "&lt;i&gt;9&lt;/i&gt;" in html


def test_the_banner_counts_diagnostics_not_failed_records():
    html = render(DiscoverView((), (_decision(),), issue_count=2))
    assert "2 diagnostics in decision or research records" in html
    assert "failed to load" not in html


def test_a_single_diagnostic_is_singular():
    html = render(DiscoverView((), (_decision(),), issue_count=1))
    assert "1 diagnostic in decision or research records" in html


def test_warnings_count_the_same_as_errors():
    issues = (
        Issue("decisions/0001.md", "title", "odd", severity="warning"),
        Issue("research/0002.md", "body", "bad", severity="error"),
        Issue("features/netlens/0001.md", "title", "unrelated", severity="error"),
    )
    view = build_discover(SimpleNamespace(issues=issues, research=(), decisions=()))
    assert view.issue_count == 2
