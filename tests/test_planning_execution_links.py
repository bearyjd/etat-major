import json

import pytest
import yaml

from etat_major.cli import main
from test_planning_web import Page
from test_planning_web import client_for as client_for
from test_planning_web import planning_workspace as planning_workspace

SESSION = "5a1ac876-cf2d-456b-b2ab-48620ca8156a"
SEEN_AT = "2026-11-22T14:00:00Z"
ORIGIN = "https://codeman.example.invalid:8443"
SOURCE = {"label": "Recorded execution links", "status": "recorded"}


def _row(kind="codeman-session", ref=SESSION, **changes):
    return {"task": "netlens/0042", "kind": kind, "ref": ref, "seen_at": SEEN_AT} | changes


def _record(path, links, project="netlens"):
    path.write_text(yaml.safe_dump({"version": 1, "project": project, "links": links}))
    return path


def test_planning_shows_recorded_handoff_as_text(planning_workspace, client_for, tmp_path):
    links = _record(
        tmp_path / "links.yaml", [_row(), _row(), _row("meute-job", "nightly/build-42")]
    )
    with client_for(
        planning_workspace, "--execution-links", links, "--codeman-origin", ORIGIN + "/"
    ) as client:
        page = client.get("/planning").text
        data = client.get("/project.json").json()
    card = page.split('id="task-netlens-0042"', 1)[1].split("</article>", 1)[0]
    url = f"{ORIGIN}/session/{SESSION}"
    assert all(text in card for text in ("Codeman session", "Meute job", "netlens/0042", SEEN_AT))
    assert f"<code>{url}</code>" in card
    assert "<code>nightly/build-42</code>" in card
    assert card.count("Codeman session") == 1
    assert all(
        href.startswith("./refresh?token=") or href.startswith("#") for href in Page(page).hrefs
    )
    assert {"script", "form"}.isdisjoint(Page(page).tags)
    assert SOURCE in data["sources"]
    assert [row["url"] for row in data["execution_links"]["links"]] == [url, None]
    task = next(row for row in data["tasks"] if row["id"] == "netlens/0042")
    assert task["state"] == "ready" and task["evidence"]["generated"] == "unverified"


def test_planning_keeps_reference_without_configured_origin(
    planning_workspace, client_for, tmp_path
):
    links = tmp_path / "links.json"
    links.write_text(json.dumps({"version": 1, "project": "netlens", "links": [_row()]}))
    with client_for(planning_workspace, "--execution-links", links) as client:
        assert f"<code>{SESSION}</code>" in client.get("/").text
        assert client.get("/project.json").json()["execution_links"]["links"][0]["url"] is None


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        ("missing", "file"),
        ("malformed", "snapshot"),
        ("symlink", "file"),
        ("project", "project"),
        ("cross-task", "links.0.task"),
        ("unknown-task", "links.0.task"),
        ("conflict", "links.1.ref"),
        ("unsafe-ref", "links.0.ref"),
        ("not-uuid", "links.0.ref"),
        ("url", "snapshot"),
        ("timestamp", "links.0.seen_at"),
    ],
)
def test_invalid_handoff_remains_visible_without_hiding_planning(
    planning_workspace, client_for, tmp_path, kind, field
):
    path = tmp_path / "links.yaml"
    rows = {
        "cross-task": [_row(task="other/0042")],
        "unknown-task": [_row(task="netlens/9999")],
        "conflict": [_row(), _row(seen_at="2026-11-22T15:00:00Z")],
        "unsafe-ref": [_row("meute-job", "<img/src=x>")],
        "not-uuid": [_row(ref="not-a-uuid")],
        "url": [_row(url="https://outside.invalid/private")],
        "timestamp": [_row(seen_at="2026-11-22T12:00:00")],
    }
    if kind == "malformed":
        path.write_text("links: [/private/location")
    elif kind == "symlink":
        path.symlink_to(_record(tmp_path / "private.yaml", [_row()]))
    elif kind != "missing":
        _record(path, rows.get(kind, [_row()]), project="other" if kind == "project" else "netlens")
    with client_for(planning_workspace, "--execution-links", path) as client:
        page = client.get("/planning")
        data = client.get("/project.json").json()
    assert page.status_code == 200 and "Live latency graph" in page.text
    assert "execution_links" not in data
    assert (SOURCE | {"status": "invalid"}) in data["sources"]
    assert (path.name, field) in {(issue["path"], issue["field"]) for issue in data["issues"]}
    assert "outside.invalid" not in page.text and "/private/location" not in page.text
    assert "<img" not in page.text


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.invalid",
        "https://name@host.invalid",
        "https://example.invalid/path",
        "https://example.invalid?",
        "https://example.invalid/#fragment",
        "https://example.invalid:",
        "https://example.invalid:65536",
        "https://example.invalid\\evil.invalid",
    ],
)
def test_invalid_codeman_origin_is_a_startup_error(workspace_dir, capsys, origin):
    args = [
        "serve",
        "--workspace",
        str(workspace_dir),
        "--project",
        "netlens",
        "--codeman-origin",
        origin,
    ]
    assert main(args) == 2
    error = capsys.readouterr().err
    assert "field 'codeman-origin'" in error
    assert origin not in error


def test_absent_handoff_does_not_change_planning_output(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        assert SOURCE["label"] not in client.get("/").text
        assert "execution_links" not in json.loads(client.get("/project.json").text)
