import pytest

from etat_major.cli import main
from etat_major.refs import Ref, RefError, parse_ref
from test_cli_json import read_envelope

FEATURE = "features/netlens/0031-latency-graph.md"
COMPONENT_REF = "component:netlens/ui.host.detail"


def test_component_ref_is_project_scoped():
    assert parse_ref(COMPONENT_REF) == Ref("component", "ui.host.detail", project="netlens")
    assert str(parse_ref(COMPONENT_REF)) == COMPONENT_REF


@pytest.mark.parametrize(
    "ref",
    [
        "component:ui.host-detail",
        "component:NetLens/ui.host.detail",
        "component:netlens/ui.Host.detail",
        "component:netlens/ui..detail",
        "component:netlens/ui.detail#f1",
        "component:netlens/ui/detail",
    ],
)
def test_component_ref_rejects_wrong_scope_and_id(ref):
    with pytest.raises(RefError, match="component refs use"):
        parse_ref(ref)


@pytest.fixture
def trace_inputs(workspace_dir, tmp_path):
    feature = workspace_dir / FEATURE
    feature.write_text(
        feature.read_text().replace(
            "ref: fp:n:ui.hostdetail\n    relation: modifies",
            f"ref: {COMPONENT_REF}\n    relation: new",
        )
    )
    directory = tmp_path / "components"
    directory.mkdir()
    model = directory / "netlens.yaml"
    model.write_text(
        "version: 1\nproject: netlens\ncomponents:\n"
        "  - {id: ui, label: UI, kind: group, paths: []}\n"
        "  - {id: ui.host, label: Host, parent: ui, kind: group, paths: []}\n"
        "  - id: ui.host.detail\n"
        "    label: Detail\n"
        "    parent: ui.host\n"
        "    kind: screen\n"
        "    paths: [app/src/ui, 'feature/host/**']\n"
    )
    return ["trace", "feature:netlens/0031", "--workspace", str(workspace_dir)], model


@pytest.mark.parametrize("use_dir", [False, True])
def test_trace_lists_component_paths_and_ancestors(trace_inputs, capsys, use_dir):
    args, model = trace_inputs
    source = model.parent if use_dir else model
    assert main([*args, "--components", str(source), "--format", "json"]) == 0
    _, result = read_envelope(capsys, "trace", 0)
    assert result["data"]["architecture"][0] == {
        "ref": COMPONENT_REF,
        "relation": "new",
        "state": "existing",
        "provenance": "human",
        "paths": ["app/src/ui", "feature/host/**"],
        "ancestors": ["ui.host", "ui"],
    }


def test_trace_prints_component_details(trace_inputs, capsys):
    args, model = trace_inputs
    assert main([*args, "--components", str(model)]) == 0
    output = capsys.readouterr().out
    assert f"{COMPONENT_REF}  new  existing  human" in output
    assert "    path: app/src/ui" in output
    assert "    ancestors: ui.host -> ui" in output


@pytest.mark.parametrize("format_name", ["text", "json"])
def test_trace_preserves_valid_component_globs(trace_inputs, capsys, format_name):
    args, model = trace_inputs
    model.write_text(model.read_text().replace("feature/host/**", "app/**/src"))
    assert main([*args, "--components", str(model), "--format", format_name]) == 0
    if format_name == "json":
        _, result = read_envelope(capsys, "trace", 0)
        assert result["data"]["architecture"][0]["paths"] == ["app/src/ui", "app/**/src"]
    else:
        assert "    path: app/**/src" in capsys.readouterr().out


def test_trace_without_components_leaves_link_unverified(trace_inputs, capsys, graph_file):
    args, _ = trace_inputs
    assert main([*args, "--graph", str(graph_file), "--format", "json"]) == 1
    _, result = read_envelope(capsys, "trace", 1)
    assert result["data"]["architecture"][0]["state"] == "unverified"
    assert result["data"]["architecture"][1]["state"] == "gap"


@pytest.mark.parametrize("other_project", [False, True])
def test_trace_missing_component_is_stale(trace_inputs, capsys, other_project):
    args, model = trace_inputs
    content = model.read_text()
    content = (
        content.replace("project: netlens", "project: another")
        if other_project
        else content.replace("id: ui.host.detail", "id: ui.host.other")
    )
    model.write_text(content)
    assert main([*args, "--components", str(model), "--format", "json"]) == 1
    _, result = read_envelope(capsys, "trace", 1)
    assert result["data"]["architecture"][0]["state"] == "stale"
    assert result["issues"][0]["message"] == f"stale: {COMPONENT_REF}"


def test_trace_refuses_component_source_symlinks(trace_inputs, capsys):
    args, model = trace_inputs
    link = model.parent / "shortcut.yaml"
    link.symlink_to(model)
    assert main([*args, "--components", str(link), "--format", "json"]) == 2
    output, result = read_envelope(capsys, "trace", 2)
    assert result["data"] is None
    assert result["issues"][0]["path"] == "shortcut.yaml"
    assert "symlink" in result["issues"][0]["message"]
    assert str(model.parent) not in output


def test_trace_rejects_invalid_component_model_with_field_details(trace_inputs, capsys):
    args, model = trace_inputs
    model.write_text(model.read_text().replace("parent: ui.host", "parent: absent"))
    assert main([*args, "--components", str(model), "--format", "json"]) == 2
    _, result = read_envelope(capsys, "trace", 2)
    assert result["data"] is None
    assert any(
        issue["path"] == "netlens.yaml" and "parent" in issue["field"] for issue in result["issues"]
    )


def test_trace_escapes_component_issue_path(trace_inputs, capsys):
    args, model = trace_inputs
    bad = model.with_name("invalid\x1b.yaml")
    bad.write_text("[\n")
    assert main([*args, "--components", str(bad), "--format", "json"]) == 2
    _, result = read_envelope(capsys, "trace", 2)
    (issue,) = result["issues"]
    assert issue["path"] == r"invalid\u001b.yaml"
    assert issue["field"] == "components"


def test_trace_requires_all_supplied_component_directory_models_to_be_valid(trace_inputs, capsys):
    args, valid = trace_inputs
    unrelated = valid.with_name("unrelated.yaml")
    unrelated.write_text("components: [")
    assert main([*args, "--components", str(valid.parent), "--format", "json"]) == 2
    _, result = read_envelope(capsys, "trace", 2)
    assert result["data"] is None
    assert [(issue["path"], issue["field"]) for issue in result["issues"]] == [
        ("unrelated.yaml", "components")
    ]
