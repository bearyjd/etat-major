import json
import os
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from etat_major.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMAS = Path(__file__).resolve().parents[1] / "docs/contracts/schemas"
COMMANDS = ("trace", "decisions-list", "index", "progress", "workspace-validate")


@pytest.fixture
def cli_args(workspace_dir, graph_file, tmp_path):
    def args(command):
        workspace = ["--workspace", str(workspace_dir)]
        graph = ["--graph", str(graph_file)]
        trail = ["--trail", str(FIXTURES / "cli-json/demo-wiring.json")]
        if command == "trace":
            return ["trace", "feature:netlens/0031", *workspace, *graph]
        if command == "decisions-list":
            return ["decisions", "list", *workspace]
        if command == "index":
            return ["index", *graph, *trail]
        if command == "workspace-validate":
            return ["workspace", "validate", *workspace]
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(  # noqa: S603
            ["git", "init", "-b", "main"],  # noqa: S607
            cwd=repo,
            env={"PATH": os.defpath, "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1"},
            check=True,
            capture_output=True,
        )
        recorded = tmp_path / "recorded.json"
        recorded.write_text("[]", encoding="utf-8")
        return [
            "progress",
            *workspace,
            "--repo",
            str(repo),
            "--prs",
            str(recorded),
            "--releases",
            str(recorded),
            *graph,
        ]

    return args


def read_envelope(capsys, command, status):
    output = capsys.readouterr()
    assert not output.err
    value = json.loads(output.out)
    assert value["schema"] == f"etat-major/{command}@1"
    assert value["ok"] is (status == 0)
    assert output.out == json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    schema = json.loads((SCHEMAS / f"{command}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    return output.out, value


@pytest.mark.parametrize("command", COMMANDS)
def test_demo_json_matches_golden_and_is_deterministic(capsys, cli_args, command, tmp_path):
    args = [*cli_args(command), "--format", "json"]
    expected_status = 1 if command == "trace" else 0
    runs = []
    for _ in range(2):
        assert main(args) == expected_status
        output, value = read_envelope(capsys, command, expected_status)
        assert value["data"] is not None and str(tmp_path) not in output
        runs.append(output)
    assert runs[0] == runs[1]
    golden = (FIXTURES / "cli-json" / f"{command}.json").read_text(encoding="utf-8")
    assert json.loads(golden) == value


@pytest.mark.parametrize("command", COMMANDS)
def test_argument_errors_have_envelopes(capsys, command):
    args = [*command.split("-"), "--format=json"]
    assert main(args) == 2
    _, error = read_envelope(capsys, command, 2)
    assert error["data"] is None
    assert error["issues"][0]["field"] == "arguments"


@pytest.mark.parametrize(
    ("command", "flag", "field"),
    [
        ("trace", "--workspace", "workspace"),
        ("trace", "--graph", "JSON"),
        ("trace", "--trail", "JSON"),
        ("decisions-list", "--workspace", "workspace"),
        ("index", "--graph", "JSON"),
        ("index", "--trail", "JSON"),
        ("index", "--revision", "revision"),
        ("index", "--indexed-at", "indexed_at"),
        ("progress", "--workspace", "workspace"),
        ("progress", "--graph", "JSON"),
        ("progress", "--trail", "JSON"),
        ("progress", "--repo", "metadata"),
        ("progress", "--prs", "file"),
        ("progress", "--releases", "file"),
        ("workspace-validate", "--workspace", "workspace"),
    ],
)
def test_unavailable_inputs_have_file_and_field(capsys, cli_args, tmp_path, command, flag, field):
    missing = tmp_path / "missing\x1b"
    args = [*cli_args(command), flag, str(missing), "--format", "json"]
    assert main(args) == 2
    output, error = read_envelope(capsys, command, 2)
    assert error["data"] is None
    assert error["issues"][0]["field"] == field
    assert error["issues"][0]["path"]
    assert str(tmp_path) not in output and "\x1b" not in output


@pytest.mark.parametrize("ref", ["invalid", "decision:0012", "feature:netlens/0999"])
def test_bad_trace_ref_has_error_envelope(capsys, cli_args, ref):
    args = cli_args("trace")
    args[1] = ref
    assert main([*args, "--format", "json"]) == 2
    _, error = read_envelope(capsys, "trace", 2)
    assert error["issues"][0]["field"] == "ref"


@pytest.mark.parametrize("command", ["trace", "decisions-list", "progress", "workspace-validate"])
def test_workspace_errors_keep_partial_results(capsys, cli_args, workspace_dir, command):
    (workspace_dir / "decisions/0098-bad.md").write_text("bad", encoding="utf-8")
    (workspace_dir / "decisions/0099-link.md").symlink_to("0098-bad.md")
    args = [*cli_args(command), "--format", "json"]
    assert main(args) == 1
    _, result = read_envelope(capsys, command, 1)
    assert result["data"] is not None
    issues = {issue["path"]: issue for issue in result["issues"]}
    assert issues["decisions/0098-bad.md"]["field"] == "frontmatter"
    assert issues["decisions/0099-link.md"]["field"] == "file"


def test_workspace_validate_lists_every_detected_issue(capsys, tmp_path):
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    for index in range(201):
        (decisions / f"{index:04}-bad.md").touch()
    assert main(["workspace", "validate", "--workspace", str(tmp_path)]) == 1
    result = capsys.readouterr()
    assert result.err.count("invalid: decisions/") == 201
    assert "field 'frontmatter'" in result.err
    assert not result.out


def test_workspace_validate_checks_vision(capsys, workspace_dir):
    (workspace_dir / "visions/netlens.md").write_text("bad", encoding="utf-8")
    assert main(["workspace", "validate", "--workspace", str(workspace_dir)]) == 1
    assert "visions/netlens.md: field 'frontmatter'" in capsys.readouterr().err


def test_json_escapes_untrusted_data_and_redacts_local_paths(capsys, cli_args, workspace_dir):
    record = workspace_dir / "decisions/0099-local.md"
    question = f"Read {workspace_dir} then show \x1b\u202e\nnext line"
    record.write_text(
        f"---\nid: '0099'\nstatus: proposed\nquestion: {json.dumps(question)}\n---\n",
        encoding="utf-8",
    )
    assert main([*cli_args("decisions-list"), "--format=json"]) == 0
    output, result = read_envelope(capsys, "decisions-list", 0)
    assert str(workspace_dir) not in output
    assert "\\u001b\\u202e\\nnext line" in output
    assert result["data"]["decisions"][-1]["question"].endswith("\x1b\u202e\nnext line")


def test_invalid_graph_schema_does_not_echo_private_metadata(capsys, cli_args, graph_file):
    graph_file.write_text(json.dumps({"schema": str(graph_file.parent)}), encoding="utf-8")
    assert main([*cli_args("trace"), "--format=json"]) == 2
    output, result = read_envelope(capsys, "trace", 2)
    assert result["issues"][0]["field"] == "schema"
    assert str(graph_file.parent) not in output


def test_progress_uses_explicit_date_for_overdue_milestones(capsys, cli_args):
    args = [*cli_args("progress"), "--format=json"]
    assert main([*args, "--as-of", "2027-03-02"]) == 0
    _, result = read_envelope(capsys, "progress", 0)
    assert result["data"]["as_of"] == "2027-03-02"
    assert result["data"]["stale_milestones"] == ["milestone:netlens/m3"]
    assert main([*args, "--as-of", "invalid"]) == 2
    _, result = read_envelope(capsys, "progress", 2)
    assert result["issues"][0]["field"] == "as-of"


def test_trace_text_redacts_local_paths_and_remotes(capsys, cli_args, workspace_dir):
    feature = workspace_dir / "features/netlens/0031-latency-graph.md"
    remote = "ssh:" + "//private/repository"
    body = feature.read_text(encoding="utf-8")
    feature.write_text(
        body.replace("title: Live latency graph", f"title: Copy {workspace_dir} from {remote}"),
        encoding="utf-8",
    )
    assert main(cli_args("trace")) == 1
    captured = capsys.readouterr()
    assert str(workspace_dir) not in captured.out and remote not in captured.out
    assert "[redacted location]" in captured.out


def test_workspace_validation_does_not_resolve_even_its_root(capsys, workspace_dir, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("the workspace walker must use its opened directory descriptor")

    monkeypatch.setattr(Path, "resolve", forbidden)
    assert main(["workspace", "validate", "--workspace", str(workspace_dir)]) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("command", "flag", "field"),
    [
        ("trace", "--graph", "JSON"),
        ("trace", "--trail", "JSON"),
        ("index", "--graph", "JSON"),
        ("index", "--trail", "JSON"),
        ("progress", "--prs", "json"),
        ("progress", "--releases", "json"),
    ],
)
def test_malformed_inputs_have_error_envelopes(capsys, cli_args, tmp_path, command, flag, field):
    malformed = tmp_path / "broken.json"
    malformed.write_text("{", encoding="utf-8")
    assert main([*cli_args(command), flag, str(malformed), "--format=json"]) == 2
    _, error = read_envelope(capsys, command, 2)
    assert error["data"] is None
    assert error["issues"][0]["field"] == field
    assert error["issues"][0]["path"] == "broken.json"


def test_workspace_link_warnings_do_not_change_exit_status(capsys, cli_args, workspace_dir):
    decision = workspace_dir / "decisions/0012-add-latency-graph.md"
    content = decision.read_text(encoding="utf-8")
    decision.write_text(content.replace("features: [feature:netlens/0031]\n", ""), encoding="utf-8")
    assert main([*cli_args("workspace-validate"), "--format=json"]) == 0
    _, result = read_envelope(capsys, "workspace-validate", 0)
    assert [(issue["field"], issue["severity"]) for issue in result["issues"]] == [
        ("features", "warning")
    ]


def test_error_path_cannot_echo_drive_rooted_input(capsys, cli_args):
    drive_path = "C:" + "\\private\\graph.json"
    assert main([*cli_args("trace"), "--graph", drive_path, "--format=json"]) == 2
    output, error = read_envelope(capsys, "trace", 2)
    assert "private" not in output
    assert error["issues"][0]["path"] == "graph.json"


@pytest.mark.parametrize("output_format", ["text", "json"])
def test_trace_strips_source_url_credentials_query_and_fragment(
    workspace_dir, cli_args, capsys, output_format
):
    path = next((workspace_dir / "research").glob("*.md"))
    original = "https://" + ".".join(("example", "org")) + "/thread/123"
    credentialed = original.replace("://", "://reader:marker@", 1) + "?query-marker#fragment-marker"
    path.write_text(path.read_text().replace(original, credentialed))
    assert main([*cli_args("trace"), "--format", output_format]) == 1
    out = capsys.readouterr().out
    assert original in out
    for value in ("reader", "query-marker", "fragment-marker"):
        assert value not in out
