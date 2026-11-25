import shutil

import pytest

from test_planning_refresh import _refresh_href
from test_planning_web import Page
from test_planning_web import client_for as client_for
from test_planning_web import planning_workspace as planning_workspace

BROKEN = "---\nid: [oops\n---\n"


def test_page_shows_rejected_decision_with_rationale(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        response = client.get("/discover")
    assert response.status_code == 200
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    text = response.text
    assert "Should NetLens sync scan history to a cloud service?" in text
    assert "rejected" in text and "Optional cloud sync" in text
    assert "Adds an account system and a privacy burden." in text
    assert "Not supported by the research" in text
    assert "research:0007#f2" in text and "unsourced" in text
    assert "netlens/0031" in text


def test_page_shows_actual_status_and_provenance_badges(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        text = client.get("/discover").text
    assert ">reviewed<" in text and ">ai-generated<" in text
    assert "unreviewed" not in text
    assert "Users report slow scans on large subnets." in text
    badge = '<span class="badge">{}</span>'
    assert badge.format("unsourced") + "Some users find competing UIs dated." in text
    assert badge.format("sourced") + "Users report slow scans" in text


def test_source_urls_are_plain_text_and_page_is_inert(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        text = client.get("/discover").text
    assert "https://example.org/thread/123" in text and "2026-09-14" in text
    page = Page(text)
    assert page.hrefs == ["./planning"]
    assert not {"form", "script", "input", "iframe"} & set(page.tags)


def test_markup_in_records_is_escaped(planning_workspace, client_for):
    decision = planning_workspace / "decisions" / "0012-add-latency-graph.md"
    decision.write_text(
        decision.read_text().replace("live latency graph?", "<img src=x onerror=alert(1)>?")
    )
    with client_for(planning_workspace) as client:
        text = client.get("/discover").text
    assert "<img" not in text and "&lt;img src=x onerror=alert(1)&gt;" in text


def test_query_filters_decisions(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        found = client.get("/discover", params={"q": "cloud SYNC"}).text
        missing = client.get("/discover", params={"q": "nothing like this"}).text
    assert "Should NetLens sync scan history" in found
    assert "Should NetLens add a live latency graph?" not in found
    assert "No prior decision found" in missing
    assert "Should NetLens sync scan history" not in missing


def test_query_is_escaped_and_bounded(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        shown = client.get("/discover", params={"q": "<script>x</script>"})
        assert shown.status_code == 200 and "<script>" not in shown.text
        assert "&lt;script&gt;" in shown.text
        assert client.get("/discover", params={"q": "x" * 128}).status_code == 200
        for query in ("?q=" + "x" * 129, "?q=%00", "?q=a%0Ab", "?q=%FF", "?q=a&q=b", "?z=1"):
            response = client.get("/discover" + query)
            assert response.status_code == 400, query
            assert "x" * 129 not in response.text


def test_failed_record_marker(planning_workspace, client_for):
    (planning_workspace / "decisions" / "0099-broken.md").write_text(BROKEN)
    with client_for(planning_workspace) as client:
        text = client.get("/discover").text
    assert "1 records failed to load" in text
    assert "0099-broken" not in text


def test_no_failure_marker_when_clean(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        assert "failed to load" not in client.get("/discover").text


def test_refresh_updates_then_rejected_refresh_says_previous_snapshot(
    planning_workspace, client_for
):
    with client_for(planning_workspace) as client:
        refresh = _refresh_href(client.get("/").text, "planning")[1:]
        assert "previous snapshot" not in client.get("/discover").text
        decision = planning_workspace / "decisions" / "0013-add-cloud-sync.md"
        decision.write_text(decision.read_text().replace("cloud service?", "hosted service?"))
        client.get(refresh)
        assert "hosted service?" in client.get("/discover").text
        (planning_workspace / "decisions" / "0099-broken.md").write_text(BROKEN)
        assert "Showing the previous snapshot" in client.get(refresh).text
        text = client.get("/discover").text
        assert "Showing the previous snapshot" in text
        assert "hosted service?" in text and "failed to load" not in text
        (planning_workspace / "decisions" / "0099-broken.md").unlink()
        client.get(refresh)
        assert "previous snapshot" not in client.get("/discover").text


def test_planning_nav_link_only_with_discover_data(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        assert "./discover" in Page(client.get("/planning").text).hrefs
    shutil.rmtree(planning_workspace / "decisions")
    shutil.rmtree(planning_workspace / "research")
    with client_for(planning_workspace) as client:
        assert "./discover" not in Page(client.get("/planning").text).hrefs


def test_oversized_page_is_replaced_by_a_notice(planning_workspace, client_for, monkeypatch):
    from etat_major import discover_html

    monkeypatch.setattr(discover_html, "LIMIT", 500)
    with client_for(planning_workspace) as client:
        text = client.get("/discover").text
    assert "Display truncated" in text and len(text.encode()) < 2000


@pytest.mark.parametrize("path", ["/discover"])
def test_host_is_checked(planning_workspace, client_for, path):
    with client_for(planning_workspace) as client:
        assert client.get(path, headers={"Host": "outside.invalid"}).status_code == 400
