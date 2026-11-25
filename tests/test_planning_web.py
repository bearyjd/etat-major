import json
import shutil
from contextlib import nullcontext
from html.parser import HTMLParser
from pathlib import Path

import pytest

from etat_major.cli import main
from test_progress import History

FIXTURES = Path(__file__).parent / "fixtures"
GRAPH = FIXTURES / "floorplan" / "graph-real.json"
COMPONENTS = FIXTURES / "planning" / "netlens.yaml"
PRS = FIXTURES / "progress" / "prs.json"
PROJECT = "netlens"


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = []
        self.hrefs = []
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if "href" in attrs:
            self.hrefs.append(attrs["href"])


@pytest.fixture
def planning_workspace(workspace_dir):
    folder = workspace_dir / "components"
    folder.mkdir()
    shutil.copy(COMPONENTS, folder / COMPONENTS.name)
    feature = next((workspace_dir / "features" / PROJECT).glob("*.md"))
    original = feature.read_text()
    feature.write_text(
        original.replace("architecture:\n", "tasks: [task:netlens/0042]\narchitecture:\n")
        .replace("fp:n:ui.hostdetail", "component:netlens/core.network")
        .replace("fp:f:app/src/net/Latency.kt", "component:netlens/gone")
    )
    return workspace_dir


@pytest.fixture
def client_for(monkeypatch, capsys):
    from fastapi.testclient import TestClient

    def client(workspace, *flags, project=PROJECT, port="8116"):
        import uvicorn

        calls = []
        monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
        args = ["serve", "--workspace", str(workspace), "--project", project, "--port", port]
        assert main([*args, *map(str, flags)]) == 0, capsys.readouterr().err
        [(app, options)] = calls
        assert options["host"] == "127.0.0.1"
        assert options["port"] == int(port)
        return TestClient(app, base_url=f"http://127.0.0.1:{port}")

    return client


@pytest.mark.parametrize(
    ("project", "options", "field"),
    [
        ("../private", [], "project"),
        ("unknown", [], "project"),
        (PROJECT, ["--port", "65536"], "port"),
        (PROJECT, ["--host", "0.0.0.0"], "arguments"),  # noqa: S104
    ],
)
def test_serve_rejects_invalid_startup(workspace_dir, capsys, project, options, field):
    args = ["serve", "--workspace", str(workspace_dir), "--project", project, *options]
    with pytest.raises(SystemExit) if field == "arguments" else nullcontext():
        assert main(args) == 2
    error = capsys.readouterr().err
    assert field in error
    assert "Traceback" not in error
    assert str(workspace_dir) not in error


def test_serve_rejects_symlink_workspace(tmp_path, workspace_dir, capsys):
    symlink = tmp_path / "linked"
    symlink.symlink_to(workspace_dir, target_is_directory=True)
    assert main(["serve", "--workspace", str(symlink), "--project", PROJECT]) == 2
    error = capsys.readouterr().err
    assert "linked: field 'workspace'" in error
    assert str(tmp_path) not in error


def test_project_view_embeds_in_opaque_sandbox(planning_workspace, client_for):
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from fastapi.testclient import TestClient

    parent = FastAPI()
    prefix = "/webview/recorded"
    parent.mount(prefix, client_for(planning_workspace, "--graph", GRAPH, "--prs", PRS).app)
    parent.get("/")(
        lambda: HTMLResponse(f'<iframe title="Planning" sandbox src="{prefix}/"></iframe>')
    )
    with TestClient(parent, base_url="http://localhost") as client:
        assert 'sandbox src="/webview/recorded/"' in client.get("/").text
        response = client.get(prefix + "/")
        page = Page(response.text)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "set-cookie" not in response.headers
        assert "x-frame-options" not in response.headers
        assert "style" in page.tags
        assert {"script", "link", "form", "base"}.isdisjoint(page.tags)
        assert len(page.ids) == len(set(page.ids))
        assert all(
            href.startswith(("./refresh?token=", "./understand?component="))
            or href in ("./understand", "./discover")
            or (href.startswith("#") and href[1:] in page.ids)
            for href in page.hrefs
        )
        assert {"#component-netlens-core.network", "#task-netlens-0042"} <= set(page.hrefs)
        assert "core/network" in response.text and "core</a>" in response.text
        assert "proposed" in response.text


@pytest.mark.parametrize("route", ["/", "/project.json"])
def test_project_routes_reject_external_host(planning_workspace, client_for, route):
    with client_for(planning_workspace) as client:
        response = client.get(route, headers={"Host": "external.invalid"})
        assert response.status_code == 400


def test_project_routes_are_read_only(planning_workspace, client_for):
    with client_for(planning_workspace, "--prs", PRS) as client:
        for route in ("/", "/project.json"):
            for method in ("POST", "PATCH", "PUT", "DELETE"):
                assert client.request(method, route).status_code == 405
        for route in ("/docs", "/redoc", "/openapi.json", "/project.json/other"):
            assert client.get(route).status_code == 404
        assert (
            client.get("/project.json?workspace=/private&project=other").json()
            == client.get("/project.json").json()
        )


@pytest.fixture
def recorded_history(tmp_path):
    root = tmp_path / "history"
    root.mkdir()
    return History(root)


def _evidence_flags(history, prs):
    return ("--repo", history.repo, "--prs", prs, "--releases", history.releases)


def _cli_data(capsys, command, workspace, *flags, exit_code=0):
    args = [*command, "--workspace", str(workspace), "--format", "json", *map(str, flags)]
    assert main(args) == exit_code
    return json.loads(capsys.readouterr().out)["data"]


def test_project_view_reuses_progress_and_trace(
    planning_workspace, client_for, recorded_history, capsys
):
    evidence = _evidence_flags(recorded_history, PRS)
    progress = _cli_data(capsys, ("progress",), planning_workspace, *evidence)
    trace = _cli_data(
        capsys,
        ("trace", "feature:netlens/0031"),
        planning_workspace,
        "--components",
        COMPONENTS,
        "--graph",
        GRAPH,
        exit_code=1,
    )
    with client_for(planning_workspace, *evidence, "--graph", GRAPH) as client:
        data = client.get("/project.json").json()
        feature = data["features"][0]
        task = next(row for row in data["tasks"] if row["id"] == "netlens/0042")
        assert feature["state"] == progress["features"]["netlens/0031"]["state"]
        assert feature["tasks"] == ["netlens/0042"]
        assert (
            next(c for c in data["components"] if c["id"].endswith("core.network"))["provenance"]
            == "proposed"
        )
        expected = progress["tasks"]["netlens/0042"]
        assert task["state"] == expected.pop("state") == "review"
        assert task["evidence"] == expected
        assert [(a["ref"], a["state"]) for a in feature["architecture"]] == [
            (a["ref"], a["state"]) for a in trace["architecture"]
        ]
        assert feature["architecture"][0]["state"] == "existing"
        assert feature["architecture"][1]["state"] == "stale"
        assert "pr:7" in client.get("/").text


def test_missing_and_invalid_inputs_leave_planning_usable(planning_workspace, tmp_path, client_for):
    (planning_workspace / "components" / "netlens.yaml").unlink()
    invalid = tmp_path / "invalid-prs.json"
    invalid.write_text('["https://private.invalid/repo"]')
    linked = tmp_path / "graph.json"
    linked.symlink_to(GRAPH)
    with client_for(planning_workspace, "--graph", linked, "--prs", invalid) as client:
        data = client.get("/project.json").json()
        assert data["components"] == []
        assert all(a["state"] == "unverified" for a in data["features"][0]["architecture"])
        assert {i["path"] for i in data["issues"]} >= {invalid.name, linked.name}
        page = client.get("/").text
        assert "Live latency graph" in page and "unverified" in page
        assert ".invalid/repo" not in page
        assert str(tmp_path) not in page


def test_project_isolation_and_output_safety(planning_workspace, client_for):
    root = planning_workspace
    original = next((root / "features" / PROJECT).glob("*.md"))
    for kind in ("features", "tasks"):
        (root / kind / "other").mkdir()
        for file in (root / kind / PROJECT).glob("*.md"):
            (root / kind / "other" / file.name).write_text(
                file.read_text()
                .replace("project: netlens", "project: other")
                .replace("title:", "title: PrivateNeighbor")
            )
    original.write_text(
        original.read_text()
        .replace(
            "title: Live latency graph",
            """title: '<img src=x> /private/location git@example.invalid:private/repo
            host.example:private/repo.git gitserver:private/repo.git [::1]:private/repo.git
                host.example:repo [::1]:repo'""",
        )
        .replace("tasks: [task:netlens/0042]", "tasks: [task:netlens/0042, task:other/0042]")
        .replace("component:netlens/gone", "component:other/gone")
    )
    with client_for(root) as client:
        html = client.get("/").text
        raw = client.get("/project.json").text
        for content in (html, raw):
            assert "PrivateNeighbor" not in content
            assert "other/" not in content
            assert "/private/location" not in content
            assert "git@example.invalid" not in content
            assert "host.example:private/repo.git" not in content
            assert "host.example:repo" not in content
            assert "[::1]:repo" not in content
            assert "gitserver:private/repo.git" not in content
            assert "[::1]:private/repo.git" not in content
        assert "<img src=x>" not in html
        assert "&lt;img src=x&gt;" in html
        assert "<img src=x>" in client.get("/project.json").json()["features"][0]["title"]


def test_core_invocation_does_not_import_web_packages(workspace_dir, monkeypatch, capsys):
    import builtins

    real_import = builtins.__import__

    def core_only(name, *args, **kwargs):
        if name.partition(".")[0] in {"fastapi", "uvicorn", "httpx"}:
            raise ModuleNotFoundError(f"blocked {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", core_only)
    assert main(["workspace", "validate", "--workspace", str(workspace_dir)]) == 0
    assert main(["serve", "--workspace", str(workspace_dir), "--project", PROJECT]) == 2
    error = capsys.readouterr().err
    assert "serve: field 'web'" in error and "etat-major[web]" in error


def test_missing_task_has_no_link_and_is_marked_unverified(planning_workspace, client_for):
    for task in (planning_workspace / "tasks" / PROJECT).glob("0042-*.md"):
        task.unlink()
    with client_for(planning_workspace) as client:
        page = client.get("/").text
        assert "#task-netlens-0042" not in Page(page).hrefs
        assert "netlens/0042</code> · <span" in page
        assert 'data-state="unverified">unverified' in page.split("netlens/0042</code>", 1)[1]


def test_component_and_feature_can_be_followed_both_ways(planning_workspace, client_for):
    with client_for(planning_workspace) as client:
        response = client.get("/")
        page = Page(response.text)
        assert "#feature-netlens-0031" in page.hrefs
        assert (
            page.ids.index("feature-netlens-0031")
            < page.ids.index("component-netlens-core.network")
            < page.ids.index("task-netlens-0042")
        )


def test_scoped_view_does_not_promote_partly_verified_feature(
    planning_workspace, client_for, recorded_history, capsys
):
    feature = next((planning_workspace / "features" / PROJECT).glob("*.md"))
    feature.write_text(
        feature.read_text().replace(
            "tasks: [task:netlens/0042]",
            "tasks: [task:netlens/0042, task:other/0042]\n"
            "accepted_by: maintainer\naccepted_on: 2026-11-21",
        )
    )
    task = next((planning_workspace / "tasks" / PROJECT).glob("0042-*.md"))
    task.write_text(
        task.read_text().replace(
            "status: ready", "status: done\naccepted_by: maintainer\naccepted_on: 2026-11-21"
        )
    )
    history = recorded_history
    merge = history.commit("Merge latency")
    history.set_prs(
        history.pr(
            mergeCommit={"oid": merge},
            statusCheckRollup=[
                {
                    "__typename": "CheckRun",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "commitOid": merge,
                }
            ],
        )
    )
    evidence = _evidence_flags(history, history.prs)
    progress = _cli_data(capsys, ("progress",), planning_workspace, *evidence)
    with client_for(planning_workspace, *evidence) as client:
        row = client.get("/project.json").json()["features"][0]
        assert row["state"] == progress["features"]["netlens/0031"]["state"] == "implementing"
        assert row["tasks"] == ["netlens/0042"]


def test_other_project_errors_do_not_displace_local_diagnostics(planning_workspace, client_for):
    features = planning_workspace / "features"
    other = features / "aaa"
    other.mkdir()
    for index in range(205):
        (other / f"{index}.md").write_text("---\nid: [\n---\n")
    research = planning_workspace / "research"
    for index in range(205):
        (research / f"{index:04d}-private-draft.md").write_text("---\nid: [\n---\n")
    (features / PROJECT / "broken.md").write_text("---\nid: [\n---\n")
    with client_for(planning_workspace) as client:
        issues = client.get("/project.json").json()["issues"]
        assert any(issue["path"] == "features/netlens/broken.md" for issue in issues)
        assert all("aaa" not in issue["path"] for issue in issues)
        assert any(
            issue["path"] == "research" and issue["message"] == "205 diagnostics in shared research"
            for issue in issues
        )
        assert all("private-draft" not in issue["path"] for issue in issues)


def test_planning_preserves_valid_component_path_punctuation(planning_workspace, client_for):
    model = planning_workspace / "components" / "netlens.yaml"
    path = "core/[ab]/**"
    model.write_text(model.read_text().replace("core/network", path))
    with client_for(planning_workspace) as client:
        data = client.get("/project.json").json()
        component = next(row for row in data["components"] if row["id"] == "netlens/core.network")
        assert path in component["paths"]
        assert f"<code>{path}</code>" in client.get("/").text


def test_planning_redacts_remote_shaped_issue_paths(planning_workspace, client_for, tmp_path):
    directory = planning_workspace / "features" / PROJECT
    feature = next(directory.glob("*.md"))
    feature.write_text(feature.read_text().replace("decision:0012", "decision:8123"))
    for name in ("private.invalid:repository.md", "bad-[scope]#2.md"):
        (directory / name).write_text("---\nid: [\n---\n")
    recording = tmp_path / "another.invalid:recorded.json"
    recording.write_text("invalid JSON")
    with client_for(planning_workspace, "--prs", recording) as client:
        data = client.get("/project.json")
        page = client.get("/").text
    for rendered in (data.text, page):
        assert "private.invalid" not in rendered
        assert "another.invalid" not in rendered
        assert "feature:netlens/0031" in rendered
        assert "features/netlens/bad-[scope]#2.md" in rendered
    assert data.status_code == 200
