import json
from urllib.parse import urljoin, urlsplit

import pytest

from test_planning_meute import CAPTURED, LINKED, RECORDED, UNMATCHED, _snapshot
from test_planning_web import Page
from test_planning_web import client_for as client_for
from test_planning_web import planning_workspace as planning_workspace


def test_fleet_renders_recorded_meute_inside_sandbox(planning_workspace, client_for, tmp_path):
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from fastapi.testclient import TestClient

    snapshot = _snapshot(tmp_path / "meute.yaml")
    app = client_for(planning_workspace, "--meute", snapshot).app
    parent = FastAPI()
    prefix = "/webview/recorded"
    fleet = f"{prefix}/"

    async def codeman_proxy(scope, receive, send):
        if scope["type"] == "http" and scope["path"] == fleet:
            scope = dict(scope, path=f"{prefix}/fleet", raw_path=f"{prefix}/fleet".encode())
        await app(scope, receive, send)

    parent.mount(prefix, codeman_proxy)
    parent.get("/")(lambda: HTMLResponse(f'<iframe title="Fleet" sandbox src="{fleet}"></iframe>'))
    with TestClient(parent, base_url="http://localhost") as client:
        assert f'sandbox src="{fleet}"' in client.get("/").text
        response = client.get(fleet)
        assert response.status_code == 200
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-store"
        assert "x-frame-options" not in response.headers
        assert client.get(fleet, headers={"Host": "outside.invalid"}).status_code == 400
        assert client.post(fleet).status_code == 405
        assert client.get(f"{fleet}/").status_code == 404
        assert all(
            value in response.text for value in ("netlens", CAPTURED, RECORDED, LINKED, "ok")
        )
        assert UNMATCHED in response.text and "No matching task" in response.text
        assert "netlens/9999" not in response.text
        page = Page(response.text)
        assert {"script", "form", "base", "link"}.isdisjoint(page.tags)
        assert len(page.hrefs) == 2
        assert page.hrefs[0].startswith("./fleet-refresh?token=")
        assert page.hrefs[1] == "./planning#task-netlens-0042"
        target = urlsplit(urljoin(fleet, page.hrefs[1]))
        assert target.path == prefix + "/planning"
        planning = client.get(target.path)
        assert planning.status_code == 200
        assert (
            planning.headers["content-security-policy"]
            == response.headers["content-security-policy"]
        )
        assert client.get(target.path, headers={"Host": "outside.invalid"}).status_code == 400
        assert target.fragment in Page(planning.text).ids


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("missing", "No Meute snapshot configured."),
        ("invalid", "The configured Meute snapshot is invalid."),
        ("empty", "No reports in this snapshot."),
    ],
)
def test_fleet_distinguishes_snapshot_states(
    planning_workspace, client_for, tmp_path, kind, message
):
    flags = ()
    if kind != "missing":
        snapshot = tmp_path / "meute.yaml"
        flags = ("--meute", snapshot)
        if kind == "empty":
            snapshot.write_text(
                json.dumps(
                    {"version": 1, "project": "netlens", "exported_at": CAPTURED, "reports": []}
                )
            )
        else:
            snapshot.write_text("project: [/private/location")
    with client_for(planning_workspace, *flags) as client:
        response = client.get("/fleet")
        assert response.status_code == 200
        assert message in response.text
        assert "/private/location" not in response.text
        assert (CAPTURED in response.text) == (kind == "empty")
        assert client.get("/").status_code == 200
        data = client.get("/project.json").json()
        assert "fleet" not in data
        assert ("meute" in data) == (kind == "empty")
