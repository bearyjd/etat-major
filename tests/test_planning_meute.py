import json

import pytest

from test_planning_web import Page
from test_planning_web import client_for as client_for
from test_planning_web import planning_workspace as planning_workspace

CAPTURED = "2026-11-22T12:00:00Z"
RECORDED = "2026-11-21T12:00:00Z"
LINKED = "reports/example/scan-2026-11-21.md"
UNMATCHED = "reports/example/scan-2026-11-20.md"


def _snapshot(path, project="netlens", ref=LINKED):
    linked = {"ref": ref, "recorded_at": RECORDED, "outcome": "ok", "task": "netlens/0042"}
    unmatched = dict(linked, ref=UNMATCHED, task="netlens/9999")
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "project": project,
                "exported_at": CAPTURED,
                "reports": [linked, linked, unmatched],
            }
        )
    )
    return path


def test_planning_shows_meute_evidence_in_sandbox(planning_workspace, client_for, tmp_path):
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from fastapi.testclient import TestClient

    parent = FastAPI()
    prefix = "/webview/recorded"
    snapshot = _snapshot(tmp_path / "meute.yaml")
    parent.mount(prefix, client_for(planning_workspace, "--meute", snapshot).app)
    parent.get("/")(
        lambda: HTMLResponse(f'<iframe title="Planning" sandbox src="{prefix}/"></iframe>')
    )
    with TestClient(parent, base_url="http://localhost") as client:
        assert f'sandbox src="{prefix}/"' in client.get("/").text
        response = client.get(prefix + "/")
        data = client.get(prefix + "/project.json").json()
        assert client.get(prefix + "/", headers={"Host": "outside.invalid"}).status_code == 400
    assert response.status_code == 200
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert 'name="viewport"' in response.text
    assert 'grid-template-areas: "features" "components" "tasks"' in response.text
    assert all(
        href.startswith("./refresh?token=") or href.startswith("#")
        for href in Page(response.text).hrefs
    )
    assert {"label": "Meute reports", "status": "recorded"} in data["sources"]
    assert data["meute"]["exported_at"] == CAPTURED
    assert {r["ref"]: r["linked"] for r in data["meute"]["reports"]} == {
        LINKED: True,
        UNMATCHED: False,
    }
    assert len(data["meute"]["reports"]) == 2
    task = next(row for row in data["tasks"] if row["id"] == "netlens/0042")
    assert task["evidence"]["generated"] == [f"artifact:{LINKED}"]
    assert task["evidence"]["accepted"] == "unverified"
    assert task["state"] == "ready"
    card = response.text.split('id="task-netlens-0042"', 1)[1].split("</article>", 1)[0]
    assert all(value in card for value in ("Generated", LINKED, RECORDED, "ok"))
    assert UNMATCHED not in card
    assert response.text.count(LINKED) == response.text.count(UNMATCHED) == 1
    sources = response.text.split('id="sources"', 1)[1]
    assert CAPTURED in sources and UNMATCHED in sources


@pytest.mark.parametrize(
    ("kind", "field"), [("missing", "file"), ("other", "project"), ("malformed", "snapshot")]
)
def test_invalid_meute_does_not_hide_planning(
    planning_workspace, client_for, tmp_path, kind, field
):
    snapshot = tmp_path / "meute.yaml"
    if kind == "other":
        _snapshot(snapshot, project="other")
    if kind == "malformed":
        snapshot.write_text("project: [/private/location")
    with client_for(planning_workspace, "--meute", snapshot) as client:
        page = client.get("/")
        data = client.get("/project.json").json()
    assert page.status_code == 200
    assert "Live latency graph" in page.text
    assert "meute" not in data
    assert {"label": "Meute reports", "status": "invalid"} in data["sources"]
    assert (snapshot.name, field) in {(issue["path"], issue["field"]) for issue in data["issues"]}
    assert all(task["evidence"]["generated"] == "unverified" for task in data["tasks"])
    assert LINKED not in page.text and str(tmp_path) not in page.text
    assert "/private/location" not in page.text


def test_meute_is_absent_from_unconfigured_planning(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        assert "Meute reports" not in client.get("/").text
        assert "meute" not in client.get("/project.json").json()


@pytest.mark.parametrize("ref", ["reports/example/" + "a" * 493 + ".md", "reports/job-/scan.md"])
def test_planning_generated_proof_retains_exact_ref(planning_workspace, client_for, tmp_path, ref):
    snapshot = _snapshot(tmp_path / "meute.yaml", ref=ref)
    with client_for(planning_workspace, "--meute", snapshot) as client:
        data = client.get("/project.json").json()
    task = next(row for row in data["tasks"] if row["id"] == "netlens/0042")
    assert task["evidence"]["generated"] == [f"artifact:{ref}"]


def test_planning_preserves_shared_diagnostics_and_withholds_foreign_task_keys(
    planning_workspace, client_for, tmp_path
):
    decision = planning_workspace / "decisions" / "0012-add-latency-graph.md"
    decision.write_text("---\nid: [\n---\n")
    snapshot = _snapshot(tmp_path / "meute.yaml")
    raw = json.loads(snapshot.read_text())
    raw["reports"][-1]["task"] = "other/0042"
    snapshot.write_text(json.dumps(raw))

    with client_for(planning_workspace, "--meute", snapshot) as client:
        response = client.get("/project.json")
        page = client.get("/").text
    data = response.json()
    for rendered in (response.text, page):
        assert "1 diagnostic in shared decisions" in rendered
        assert decision.name not in rendered and "other/0042" not in rendered
        assert UNMATCHED in rendered
    assert data["meute"]["reports"][-1]["task"] is None
    assert data["meute"]["reports"][-1]["linked"] is False
    task = next(row for row in data["tasks"] if row["id"] == "netlens/0042")
    assert task["evidence"]["generated"] == [f"artifact:{LINKED}"]
