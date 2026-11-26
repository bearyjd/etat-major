"""`export understand --json` against the trimmed real recordings."""

import json
import os
import subprocess
import sys

import pytest

from etat_major import trail
from etat_major.cli import main
from understand_export_support import (
    COMPONENTS,
    GRAPH,
    ROOT,
    SHA_A,
    SHA_B,
    TRAIL,
    argv,
    errors,
    export,
    failure,
    recorded_flags,
    schema,
)

MARKER = "etat-major/understand@1"
TOP_KEYS = {
    "schema",
    "version",
    "project",
    "artifacts",
    "coverage",
    "components",
    "symbols",
    "issues",
    "omitted_issues",
}


def _payload(capsys, workspace, *flags):
    return json.loads(export(capsys, workspace, *recorded_flags(), *flags))


def test_schema_file_is_closed_draft_2020_12_and_names_the_marker():
    document = schema()
    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert document["properties"]["schema"] == {"const": MARKER}
    assert document["additionalProperties"] is False

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for child in node.values():
                yield from objects(child)
        elif isinstance(node, list):
            for child in node:
                yield from objects(child)

    for node in objects(document):
        closed = node.get("additionalProperties")
        assert closed is False or "propertyNames" in node, node


def test_schema_count_keys_match_the_trail_reader():
    defs = schema()["$defs"]
    confidences = defs["confidenceCounts"]["properties"]
    assert set(defs["kindCounts"]["properties"]) == trail._NODE_KINDS | {"unknown"}
    assert set(confidences) == trail._CONFIDENCES | {"unknown"}
    assert set(defs["edgeCounts"]["properties"]) == trail._RELATIONS | {"unknown"}
    assert set(defs["relationCounts"]["properties"]) == trail._RELATIONS | {"unknown"}


@pytest.mark.parametrize("include", [(), ("--include-files",)])
def test_recorded_export_validates_and_has_content(workspace_dir, capsys, include):
    payload = _payload(capsys, workspace_dir, *include)
    assert errors(payload) == []
    assert (payload["schema"], payload["version"], payload["project"]) == (MARKER, 1, "netlens")
    optional = {"files", "ties", "files_truncated"} if include else set()
    assert set(payload) == TOP_KEYS | optional
    assert any(row["files"] > 0 and row["symbols"] > 0 for row in payload["components"])


def test_schema_rejects_unknown_keys_and_missing_marker(workspace_dir, capsys):
    payload = _payload(capsys, workspace_dir)
    assert errors({**payload, "lookup": {}})
    assert errors({**payload, "version": 2})
    assert errors({k: v for k, v in payload.items() if k != "schema"})
    row = {**payload["components"][0], "reviewed_by": "x"}
    assert errors({**payload, "components": [row]})


def test_artifacts_and_coverage_counts(workspace_dir, capsys):
    payload = _payload(capsys, workspace_dir)
    assert [a["label"] for a in payload["artifacts"]] == ["Floorplan", "Trail"]
    for artifact in payload["artifacts"]:
        assert artifact["status"] == "present" and len(artifact["digest"]) == 64
        assert artifact["revision"] is None and artifact["freshness"] == "unknown"
    coverage = payload["coverage"]
    assert coverage["inventory"] == "available"
    assert coverage["owned"] + coverage["unowned"] + coverage["tied"] == coverage["total"] > 0
    assert coverage["unmatchable_paths"] <= coverage["unowned"]
    assert [a["label"] for a in coverage["artifacts"]] == ["Floorplan", "Trail"]
    assert coverage["notes"] == [
        "Trail's cross-module Kotlin calls were weak on the measured sample.",
        "Trail imports are unresolved for Kotlin.",
    ]


def test_components_are_sorted_and_match_planning(workspace_dir, capsys):
    payload = _payload(capsys, workspace_dir)
    base = ["--json", "--workspace", str(workspace_dir), "--project", "netlens"]
    assert main(["export", "planning", *base, "--components", str(COMPONENTS)]) == 0
    planning = {row["id"]: row for row in json.loads(capsys.readouterr().out)["components"]}
    ids = [row["id"] for row in payload["components"]]
    assert ids == sorted(planning)
    for row in payload["components"]:
        shared = {k: v for k, v in row.items() if k not in ("files", "symbols")}
        assert shared == planning[row["id"]]


def test_symbol_summary_attributes_every_symbol_and_edge_once(workspace_dir, capsys):
    symbols = _payload(capsys, workspace_dir)["symbols"]
    wiring = json.loads(TRAIL.read_text())
    total, groups = symbols["total"], symbols["by_component"]
    assert total["count"] == len({node["id"] for node in wiring["nodes"]})
    assert sum(total["kinds"].values()) == total["count"]
    assert sum(group["count"] for group in groups.values()) == total["count"]

    def edges(bucket):
        return sum(n for row in bucket["edges"].values() for n in row.values())

    assert edges(total) == len(wiring["edges"])
    assert sum(map(edges, groups.values())) + symbols["unresolved_source"] == edges(total)
    assert symbols["languages"] == ["bash", "kotlin", "python"]
    assert "" in symbols["module_scopes"]
    assert {"[Unowned files]", "[Tied ownership]"} <= set(groups)


def test_files_are_opt_in_and_cover_the_inventory(workspace_dir, capsys):
    plain = _payload(capsys, workspace_dir)
    assert "files" not in plain and "files_without_symbols_paths" not in plain["symbols"]
    full = _payload(capsys, workspace_dir, "--include-files")
    listed = [path for paths in full["files"].values() for path in paths]
    coverage = full["coverage"]
    assert len(listed) == coverage["total"] - coverage["unmatchable_paths"]
    assert all(paths == sorted(paths) for paths in full["files"].values())
    assert full["files_truncated"] is False
    for row in full["components"]:
        assert row["files"] == len(full["files"][row["id"]])
    symbols = full["symbols"]
    assert len(symbols["files_without_symbols_paths"]) == symbols["files_without_symbols"]


def test_output_is_deterministic_sorted_json_across_hash_seeds(workspace_dir, capsys):
    flags = (*recorded_flags(), "--include-files")
    first = export(capsys, workspace_dir, *flags)
    assert first == json.dumps(json.loads(first), sort_keys=True, indent=2) + "\n"
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": seed}
        command = [sys.executable, "-m", "etat_major.cli", *argv(workspace_dir, *flags)]
        result = subprocess.run(command, capture_output=True, env=env)  # noqa: S603
        assert result.returncode == 0, result.stderr
        assert result.stdout == first.encode()


def test_runs_without_web_packages_or_subprocesses(workspace_dir):
    command = argv(workspace_dir, *recorded_flags(), "--include-files")
    code = (
        "import subprocess, sys\n"
        "for name in ('fastapi', 'starlette', 'uvicorn', 'httpx'):\n"
        "    sys.modules[name] = None\n"
        "def refuse(*a, **k): raise AssertionError('subprocess used')\n"
        "subprocess.Popen = refuse\n"
        f"sys.path.insert(0, {str(ROOT / 'src')!r})\n"
        "from etat_major.cli import main\n"
        f"status = main({command!r})\n"
        "assert 'etat_major.understand_html' not in sys.modules\n"
        "sys.exit(status)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)  # noqa: S603
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["schema"] == MARKER


@pytest.mark.parametrize(
    ("source", "freshness"), [(SHA_A, "fresh"), (SHA_B, "stale"), (None, "unknown")]
)
def test_freshness_trusts_the_flags_and_warns_when_stale(workspace_dir, capsys, source, freshness):
    flags = ["--floorplan-revision", SHA_A, "--trail-revision", SHA_A]
    if source:
        flags += ["--source-revision", source]
    payload = _payload(capsys, workspace_dir, *flags)
    assert errors(payload) == []
    assert [a["freshness"] for a in payload["artifacts"]] == [freshness] * 2
    assert [a["revision"] for a in payload["artifacts"]] == [SHA_A] * 2
    stale = [i for i in payload["issues"] if i["field"] == "revision"]
    assert [i["path"] for i in stale] == (["graph", "trail"] if freshness == "stale" else [])
    assert all(i["severity"] == "warning" and i["blocking"] is False for i in stale)


def test_missing_artifacts_exit_zero_with_issues(workspace_dir, capsys):
    payload = json.loads(export(capsys, workspace_dir, "--components", COMPONENTS))
    assert errors(payload) == []
    assert payload["coverage"]["inventory"] == "unavailable"
    assert payload["coverage"]["total"] == 0 and payload["components"]
    assert [a["status"] for a in payload["artifacts"]] == ["missing"] * 2
    missing = [i["path"] for i in payload["issues"] if i["field"] == "file"]
    assert {"graph", "trail"} <= set(missing)


def test_configured_but_absent_artifact_reports_one_issue(workspace_dir, tmp_path, capsys):
    flags = ("--components", COMPONENTS, "--graph", tmp_path / "gone.json", "--trail", TRAIL)
    payload = json.loads(export(capsys, workspace_dir, *flags))
    assert payload["artifacts"][0]["status"] == "missing"
    paths = [i["path"] for i in payload["issues"]]
    assert paths.count("gone.json") == 1 and "graph" not in paths


def test_invalid_artifact_exits_zero_even_without_a_model(workspace_dir, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    payload = json.loads(export(capsys, workspace_dir, "--graph", bad))
    assert errors(payload) == []
    assert payload["artifacts"][0]["status"] == "invalid"
    assert payload["components"] == [] and payload["coverage"]["inventory"] == "unavailable"
    assert any(i["path"] == "bad.json" and i["severity"] == "error" for i in payload["issues"])


def test_no_model_with_records_and_an_artifact_exports(workspace_dir, capsys):
    payload = json.loads(export(capsys, workspace_dir, "--graph", GRAPH))
    assert errors(payload) == []
    assert payload["components"] == []
    assert payload["coverage"]["unowned"] == payload["coverage"]["total"] > 0


def test_no_model_and_no_artifact_exits_two(workspace_dir, capsys):
    error = failure(capsys, workspace_dir)
    assert "export understand: field 'components'" in error


@pytest.mark.parametrize("project", ["nope", "../private", "a" * 129])
def test_project_errors_name_export_understand(workspace_dir, capsys, project):
    error = failure(capsys, workspace_dir, "--graph", GRAPH, project=project)
    assert "export understand: field 'project'" in error
    assert "serve" not in error


def test_bad_revision_names_export_understand(workspace_dir, capsys):
    error = failure(capsys, workspace_dir, *recorded_flags(), "--source-revision", "main")
    assert "export understand: field 'source_revision'" in error
    assert "serve" not in error


def test_unreadable_workspace_names_export_understand(tmp_path, capsys):
    error = failure(capsys, tmp_path / "absent", "--graph", GRAPH)
    assert "export understand: field 'workspace'" in error
    assert "absent" in error and str(tmp_path) not in error


@pytest.mark.parametrize(
    "flag",
    [
        "--repo",
        "--prs",
        "--releases",
        "--meute",
        "--manual-review",
        "--execution-links",
        "--codeman-origin",
        "--immutable-source",
    ],
)
def test_evidence_flags_are_rejected(workspace_dir, capsys, flag):
    with pytest.raises(SystemExit) as raised:
        main(argv(workspace_dir, flag, "x"))
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert captured.out == "" and flag in captured.err


def test_json_flag_is_required(workspace_dir, capsys):
    args = ["export", "understand", "--workspace", str(workspace_dir), "--project", "netlens"]
    with pytest.raises(SystemExit) as raised:
        main(args)
    assert raised.value.code == 2
    assert "--json" in capsys.readouterr().err
