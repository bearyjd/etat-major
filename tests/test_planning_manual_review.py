import pytest
import yaml

from test_planning_meute import LINKED, _snapshot
from test_planning_web import client_for as client_for
from test_planning_web import planning_workspace as planning_workspace

LABEL = "Manual Anthropic API review"
REF = "reports/manual/review.md"
RECORDED = "2026-11-22T14:00:00Z"


def _record(path, **changes):
    data = {
        "version": 1,
        "source": "manual-anthropic-api-review",
        "task": "netlens/0042",
        "ref": REF,
        "recorded_at": RECORDED,
        "outcome": "completed <locally>",
        "commit": "c" * 40,
        "report_sha256": "a" * 64,
    }
    path.write_text(yaml.safe_dump(data | changes))
    return path


def test_manual_review_and_meute_both_appear_under_generated(
    planning_workspace, client_for, tmp_path
):
    review = _record(tmp_path / "manual.yaml")
    meute = _snapshot(tmp_path / "meute.yaml")
    with client_for(planning_workspace, "--manual-review", review, "--meute", meute) as client:
        page = client.get("/").text
        data = client.get("/project.json").json()
    card = page.split('id="task-netlens-0042"', 1)[1].split("</article>", 1)[0]
    generated = card.split("<dt>Generated</dt>", 1)[1].split("</dd>", 1)[0]
    assert all(value in generated for value in (LABEL, REF, RECORDED, "completed &lt;locally&gt;"))
    assert LINKED in generated
    assert data["manual_review"]["ref"] == REF
    assert data["manual_review"]["report_sha256"] == "a" * 64
    assert {"label": LABEL, "status": "recorded"} in data["sources"]
    task = next(row for row in data["tasks"] if row["id"] == "netlens/0042")
    assert set(task["evidence"]["generated"]) == {f"artifact:{REF}", f"artifact:{LINKED}"}
    assert task["evidence"]["accepted"] == "unverified"
    assert task["state"] == "ready"


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"version": True}, "version"),
        ({"source": "meute"}, "source"),
        ({"task": "other/0042"}, "task"),
        ({"task": "netlens/0999"}, "task"),
        ({"ref": "../private.md"}, "ref"),
        ({"recorded_at": "2026-11-22T14:00:00"}, "recorded_at"),
        ({"recorded_at": "2026-13-22T14:00:00Z"}, "recorded_at"),
        ({"commit": "1234"}, "commit"),
        ({"report_sha256": "invalid"}, "report_sha256"),
        ({"symlink": True}, "file"),
    ],
)
def test_invalid_manual_review_does_not_hide_planning(
    planning_workspace, client_for, tmp_path, changes, field
):
    review = tmp_path / "manual.yaml"
    if field == "file":
        review.symlink_to(_record(tmp_path / "private.yaml"))
    else:
        _record(review, **changes)
    with client_for(planning_workspace, "--manual-review", review) as client:
        response = client.get("/")
        data = client.get("/project.json").json()
    assert response.status_code == 200
    assert "Live latency graph" in response.text
    assert "manual_review" not in data
    assert {"label": LABEL, "status": "invalid"} in data["sources"]
    assert (review.name, field) in {(issue["path"], issue["field"]) for issue in data["issues"]}
    assert all(task["evidence"]["generated"] == "unverified" for task in data["tasks"])
    assert REF not in response.text


def test_unconfigured_manual_review_preserves_planning_output(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        assert LABEL not in client.get("/").text
        assert "manual_review" not in client.get("/project.json").json()


def test_manual_review_preserves_source_and_shared_diagnostic_privacy(
    planning_workspace, client_for, tmp_path
):
    decision = planning_workspace / "decisions" / "0012-add-latency-graph.md"
    decision.write_text("---\nid: [\n---\n")
    review = _record(tmp_path / "host.invalid:review.yaml", task="other/0042")
    meute = _snapshot(tmp_path / "meute.yaml")
    with client_for(planning_workspace, "--manual-review", review, "--meute", meute) as client:
        page = client.get("/").text
        response = client.get("/project.json")

    for rendered in (page, response.text):
        assert "1 diagnostic in shared decisions" in rendered
        assert all(value not in rendered for value in (review.name, decision.name, "other/0042"))
        assert LINKED in rendered
    data = response.json()
    assert "manual_review" not in data
    assert {"label": LABEL, "status": "invalid"} in data["sources"]
    assert any(
        issue["path"] == "[redacted location]" and issue["field"] == "task"
        for issue in data["issues"]
    )
