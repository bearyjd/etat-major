from urllib.parse import urljoin, urlsplit

import pytest

from etat_major.planning_view import PlanningInputs, load_planning_view
from etat_major.web import create_app
from test_planning_execution_links import _record, _row
from test_planning_meute import LINKED, _snapshot
from test_planning_web import Page
from test_planning_web import client_for as client_for
from test_planning_web import planning_workspace as planning_workspace


def _refresh_href(html, section):
    path = "./refresh" if section == "planning" else "./fleet-refresh"
    return next(href for href in Page(html).hrefs if href.startswith(path + "?token="))


def _retitle(workspace, title):
    feature = next((workspace / "features" / "netlens").glob("*.md"))
    feature.write_text(feature.read_text().replace("Live latency graph", title))
    return feature


def test_planning_updates_only_on_request(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        initial = client.get("/")
        refresh = _refresh_href(initial.text, "planning")[1:]
        assert ">Update Planning</a>" in initial.text
        _retitle(planning_workspace, "Updated latency graph")
        assert client.get("/refresh").status_code == 403
        assert client.get("/refresh?token=wrong").status_code == 403
        assert client.get("/refresh?token=%E2%98%83").status_code == 403
        assert "Updated latency graph" not in client.get("/planning").text
        assert "Updated latency graph" not in client.get("/project.json").text
        response = client.get(refresh + "&workspace=/private&project=other")
        assert response.status_code == 200
        assert "Updated latency graph" in response.text
        assert "Snapshot updated" in response.text
        assert "Updated latency graph" in client.get("/project.json").text
        assert "<time>" in response.text
        assert response.headers["referrer-policy"] == "no-referrer"
        assert urlsplit(refresh).query.split("=", 1)[1] not in client.get("/project.json").text
        assert client.post("/refresh").status_code == 405
        assert client.get("/refresh", headers={"Host": "outside.invalid"}).status_code == 400


@pytest.mark.parametrize("failure", ["recording", "workspace-record", "workspace-missing"])
def test_refresh_failure_preserves_last_good_snapshot(
    planning_workspace, client_for, tmp_path, failure
):
    meute = _snapshot(tmp_path / "reports.yaml")
    with client_for(planning_workspace, "--meute", meute) as client:
        _retitle(planning_workspace, "Latest latency graph")
        refresh = _refresh_href(client.get("/").text, "planning")[1:]
        updated = client.get(refresh)
        assert "Latest latency graph" in updated.text
        timestamp = updated.text.split("<time>", 1)[1].split("</time>", 1)[0]
        payload = client.get("/project.json").json()
        if failure == "recording":
            meute.write_text("reports: [/private/location")
        elif failure == "workspace-record":
            feature = _retitle(planning_workspace, "Unused")
            feature.write_text("---\ntitle: [/private/location\n---")
        else:
            planning_workspace.rename(tmp_path / "removed-workspace")
        failed = client.get(refresh)
        assert failed.status_code == 200
        assert "Update unavailable. Showing the previous snapshot." in failed.text
        assert "Latest latency graph" in failed.text and LINKED in failed.text
        assert timestamp in failed.text
        assert "/private/location" not in failed.text and str(tmp_path) not in failed.text
        assert client.get("/project.json").json() == payload
        assert LINKED in client.get("/fleet").text


@pytest.mark.parametrize("section", ["planning", "fleet"])
def test_web_tab_root_resolves_relative_update_and_return_link(
    planning_workspace, client_for, tmp_path, section
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    meute = _snapshot(tmp_path / "reports.yaml")
    links = _record(tmp_path / "execution.yaml", [_row()])
    app = client_for(
        planning_workspace, "--meute", meute, "--execution-links", links, port="8123"
    ).app
    prefix = "/webview/recorded"
    browser_root = f"{prefix}/"
    path = f"{prefix}/{section}"

    async def codeman_proxy(scope, receive, send):
        if scope["type"] == "http" and scope["path"] == browser_root:
            scope = dict(scope, path=path, raw_path=path.encode())
        await app(scope, receive, send)

    parent = FastAPI()
    parent.mount(prefix, codeman_proxy)
    with TestClient(parent, base_url="http://localhost") as client:
        initial = client.get(browser_root)
        refresh = _refresh_href(initial.text, section)
        assert f">Update {section.title()}</a>" in initial.text
        refresh_target = urlsplit(urljoin(browser_root, refresh))
        assert refresh_target.path == f"{prefix}/{urlsplit(refresh).path[2:]}"
        assert client.get(refresh_target.path).status_code == 403
        old_link = LINKED
        new_link = "reports/example/scan-2026-11-22.md"
        assert old_link in initial.text
        _snapshot(meute, ref=new_link)
        response = client.get(urljoin(browser_root, refresh))
        assert response.status_code == 200
        assert "Snapshot updated" in response.text and new_link in response.text
        assert old_link not in response.text
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert not {"script", "form"}.intersection(Page(response.text).tags)
        assert _refresh_href(response.text, section) == refresh

        planning = client.get(f"{prefix}/planning")
        return_url = "http://127.0.0.1:8123/planning#task-netlens-0042"
        assert f"<code>{return_url}</code>" in planning.text
        assert return_url not in Page(planning.text).hrefs
        assert urlsplit(return_url).fragment in Page(planning.text).ids


def test_static_create_app_preserves_snapshot_api(planning_workspace):
    from fastapi.testclient import TestClient

    view = load_planning_view(PlanningInputs(planning_workspace, "netlens"))
    with TestClient(create_app(view), base_url="http://localhost") as client:
        assert ">Update Planning</a>" not in client.get("/").text
        assert ">Update Fleet</a>" not in client.get("/fleet").text
        assert client.get("/refresh").status_code == 404
        assert client.get("/fleet-refresh").status_code == 404


def test_refresh_keeps_startup_paths_after_directory_change(
    planning_workspace, client_for, monkeypatch, tmp_path
):
    monkeypatch.chdir(planning_workspace.parent)
    with client_for(planning_workspace.name) as client:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        _retitle(planning_workspace, "Startup path remembered")
        refresh = _refresh_href(client.get("/").text, "planning")[1:]
        assert "Startup path remembered" in client.get(refresh).text


def test_refresh_keeps_diagnostics_project_scoped(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        refresh = _refresh_href(client.get("/").text, "planning")[1:]
        foreign = planning_workspace / "features" / "other"
        foreign.mkdir()
        (foreign / "private-draft.md").write_text("---\ntitle: [/private/location\n---\n")
        _retitle(planning_workspace, "First refresh title")
        updated = client.get(refresh)
        assert "Snapshot updated" in updated.text and "First refresh title" in updated.text
        payload = client.get("/project.json")
        assert "private-draft" not in updated.text and "private-draft" not in payload.text

        decision = planning_workspace / "decisions" / "0099-private-decision.md"
        decision.write_text("---\nid: [/private/location\n---\n")
        feature = next((planning_workspace / "features" / "netlens").glob("*.md"))
        feature.write_text(feature.read_text().replace("First refresh title", "Rejected title"))
        failed = client.get(refresh)
        assert "Showing the previous snapshot" in failed.text
        assert "First refresh title" in failed.text and "Rejected title" not in failed.text
        assert "private-decision" not in failed.text and "/private/location" not in failed.text
        assert client.get("/project.json").json() == payload.json()
