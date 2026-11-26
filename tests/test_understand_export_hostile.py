"""Hostile recordings and the size caps of `export understand --json`."""

import json
import re

import pytest

from etat_major import components, understand_export
from understand_export_support import errors, export, failure, recorded_flags, schema

TOKEN = re.compile(r"u-[0-9a-f]{32}")
REDACTED = "[redacted location]"
COMPONENT_YAML = """version: 1
project: netlens
components:
- id: app
  label: Runs from /home/someone/secret and git@forge.example:org/repo.git
  kind: https://user:pw@forge.example/x?token=abc
  paths: ['src']
  owner: ~/private/owner
  summary:
    text: See scpbox.example:/srv/data and /home/someone/secret
    provenance: ai-generated
- id: checked
  label: Checked
  kind: library
  parent: app
  paths: ['src/checked']
  summary:
    text: LONG
    provenance: human
    reviewed_by: Reviewer Name
    reviewed_on: 2026-01-02
- id: tie-b
  label: Tie B
  kind: library
  paths: ['shared']
- id: tie-a
  label: Tie A
  kind: library
  paths: ['shared']
""".replace("LONG", "x" * 700)
UNMATCHABLE = ("src/bad#name.kt", "src/bad:name.kt")
FILES = ("src/a.kt", *UNMATCHABLE, "shared/t.kt", "docs/loose.md", "src/checked/c.kt")


def _node(path, ident, kind):
    return {"id": ident, "path": path, "kind": kind, "name": "n", "span": "L1-L2"}


def _edge(source, target, relation="calls", confidence="inferred"):
    return {"source": source, "target": target, "relation": relation, "confidence": confidence}


def _wiring():
    nodes = [
        _node("src/a.kt", "src/a.kt", "file"),
        _node("src/a.kt", "src/a.kt#run", "function"),
        _node("src/a.kt", "src/a.kt#run", "method"),
        _node("src/odd.bin", "src/odd.bin", "/home/someone/kind"),
        _node("src/empty.kt", "src/empty.kt", "file"),
        _node("shared/t.kt", "shared/t.kt#tied", "function"),
        _node("docs/loose.md", "docs/loose.md#loose", "function"),
    ]
    edges = [
        _edge("src/a.kt#run", "shared/t.kt#tied"),
        _edge("src/a.kt#run", "ghost.kt#gone", "git@forge.example:org/rel", "/home/someone/conf"),
        _edge("shared/t.kt#tied", "src/a.kt#run", "calls", "extracted"),
        _edge("docs/loose.md#loose", "elsewhere#x", "imports", "lsp_resolved"),
        _edge("ghost.kt#gone", "src/a.kt#run"),
    ]
    meta = {
        "version": 1,
        "languages": ["kotlin", "/home/someone/lang"],
        "scopes": [{"prefix": ""}, {"prefix": "src"}],
    }
    return {"meta": meta, "nodes": nodes, "edges": edges}


@pytest.fixture
def hostile(workspace_dir, tmp_path):
    folder = workspace_dir / "components"
    folder.mkdir()
    (folder / "netlens.yaml").write_text(COMPONENT_YAML)
    graph = tmp_path / "graph.json"
    files = [{"p": path} for path in FILES]
    graph.write_text(json.dumps({"schema": "floorplan/graph@1", "nodes": [], "files": files}))
    trail = tmp_path / "wiring.json"
    trail.write_text(json.dumps(_wiring()))
    return workspace_dir, ("--graph", graph, "--trail", trail, "--include-files")


def _export(capsys, hostile):
    workspace, flags = hostile
    return export(capsys, workspace, *flags)


def test_hostile_text_leaks_nothing(hostile, tmp_path, capsys):
    out = _export(capsys, hostile)
    assert errors(json.loads(out)) == []
    for needle in (
        str(tmp_path),
        "/home/",
        "~/",
        "://",
        "git@forge",
        "forge.example:",
        "scpbox.example",
        "someone",
        "token=abc",
        "Reviewer Name",
        "2026-01-02",
        "reviewed_by",
        "lookup",
        "symbol_pages",
    ):
        assert needle not in out, needle
    assert TOKEN.search(out) is None
    assert REDACTED in out


def test_provenance_review_flag_and_summary_cap(hostile, capsys):
    rows = {r["id"]: r for r in json.loads(_export(capsys, hostile))["components"]}
    assert list(rows) == sorted(rows)
    app, checked = rows["netlens/app"], rows["netlens/checked"]
    assert (app["summary_provenance"], app["reviewed"]) == ("ai-generated", False)
    assert (checked["summary_provenance"], checked["reviewed"]) == ("human", True)
    assert len(checked["summary"]) == 512 and checked["summary"].endswith("…")
    assert checked["parent"] == "netlens/app" and app["parent"] is None
    assert checked["owner"] is None and app["owner"] == REDACTED


def test_unmatchable_paths_are_counted_but_never_listed(hostile, capsys):
    payload = json.loads(_export(capsys, hostile))
    coverage = payload["coverage"]
    assert coverage["unmatchable_paths"] == len(UNMATCHABLE)
    assert coverage["owned"] + coverage["unowned"] + coverage["tied"] == coverage["total"] == 8
    assert (coverage["owned"], coverage["unowned"], coverage["tied"]) == (4, 3, 1)
    files = payload["files"]
    listed = [path for paths in files.values() for path in paths]
    listed += payload["symbols"]["files_without_symbols_paths"]
    assert REDACTED not in listed and not set(UNMATCHABLE) & set(listed)
    assert files["[Unowned files]"] == ["docs/loose.md"]
    assert files["[Tied ownership]"] == ["shared/t.kt"]
    assert files["netlens/tie-a"] == []
    assert payload["ties"] == [
        {"path": "shared/t.kt", "components": ["netlens/tie-a", "netlens/tie-b"]}
    ]


def test_symbol_summary_buckets_unknowns_and_duplicates(hostile, capsys):
    symbols = json.loads(_export(capsys, hostile))["symbols"]
    total, groups = symbols["total"], symbols["by_component"]
    assert total["count"] == 6
    assert total["kinds"] == {"file": 2, "function": 3, "unknown": 1}
    assert total["edges"]["unknown"] == {"unknown": 1}
    assert total["edges"]["calls"] == {"extracted": 1, "inferred": 2}
    assert symbols["unresolved_source"] == 1
    assert groups["netlens/app"]["edges"] == {
        "calls": {"inferred": 1},
        "unknown": {"unknown": 1},
    }
    assert groups["[Tied ownership]"]["edges"] == {"calls": {"extracted": 1}}
    assert groups["[Unowned files]"]["edges"] == {"imports": {"lsp_resolved": 1}}
    assert symbols["unresolved_relations"] == {"imports": 1, "unknown": 1}
    assert symbols["unknown_kinds"] == [REDACTED]
    assert symbols["unknown_relations"] == [REDACTED]
    assert symbols["unknown_confidences"] == [REDACTED]
    assert symbols["languages"] == sorted([REDACTED, "kotlin"])
    assert symbols["files_without_symbols"] == 1
    assert symbols["files_without_symbols_paths"] == ["src/empty.kt"]


def test_caps_are_pinned_and_mirrored_in_the_schema():
    assert (components.MAX_COMPONENTS, components.MAX_PATHS) == (500, 1000)
    assert understand_export.MAX_FILES == 20_000
    assert understand_export.MAX_ISSUES == 200
    assert understand_export.MAX_DOCUMENT_BYTES == 4 * 1024 * 1024
    document = schema()
    assert document["properties"]["components"]["maxItems"] == 500
    assert document["$defs"]["component"]["properties"]["paths"]["maxItems"] == 1000
    assert document["properties"]["issues"]["maxItems"] == 200
    assert document["$defs"]["pathList"]["maxItems"] == 20_000
    assert document["properties"]["ties"]["maxItems"] == 20_000


def test_file_lists_are_truncated_and_declared(hostile, capsys, monkeypatch):
    monkeypatch.setattr(understand_export, "MAX_FILES", 2)
    payload = json.loads(_export(capsys, hostile))
    assert errors(payload) == []
    assert payload["files_truncated"] is True
    assert sum(map(len, payload["files"].values())) == 2
    assert len(payload["symbols"]["files_without_symbols_paths"]) <= 2
    listed = {path for paths in payload["files"].values() for path in paths}
    assert all(tie["path"] in listed for tie in payload["ties"])
    assert [i for i in payload["issues"] if i["path"] == "files"] == [
        {
            "path": "files",
            "field": "files",
            "message": "file lists truncated at 2 paths",
            "severity": "warning",
            "blocking": False,
        }
    ]
    assert payload["coverage"]["total"] == 8


def test_issue_cap_keeps_export_warnings_and_counts_the_rest(workspace_dir, capsys, monkeypatch):
    for number in range(5):
        (workspace_dir / f"features/netlens/090{number}-bad.md").write_text("no frontmatter")
    folder = workspace_dir / "components"
    folder.mkdir()
    (folder / "netlens.yaml").write_text(COMPONENT_YAML)
    full = json.loads(export(capsys, workspace_dir))
    assert full["omitted_issues"] == 0 and len(full["issues"]) >= 7
    monkeypatch.setattr(understand_export, "MAX_ISSUES", 3)
    capped = json.loads(export(capsys, workspace_dir))
    assert errors(capped) == []
    assert len(capped["issues"]) == 3
    assert capped["omitted_issues"] == len(full["issues"]) - 3
    paths = [issue["path"] for issue in capped["issues"]]
    assert {"graph", "trail"} <= set(paths)
    assert any(issue["severity"] == "error" for issue in capped["issues"])
    assert paths == sorted(paths)


def test_document_cap_is_an_error_not_a_cut(hostile, capsys, monkeypatch):
    workspace, flags = hostile
    size = len(_export(capsys, hostile).encode())
    monkeypatch.setattr(understand_export, "MAX_DOCUMENT_BYTES", size)
    assert len(_export(capsys, hostile).encode()) == size
    monkeypatch.setattr(understand_export, "MAX_DOCUMENT_BYTES", size - 1)
    error = failure(capsys, workspace, *flags)
    assert "export understand: field 'document'" in error
    assert f"{size - 1} byte" in error


def test_listed_paths_are_escaped_and_cut(workspace_dir, tmp_path, capsys):
    odd, long = "src/odd.kt", "src/" + "n" * 300 + ".kt"
    graph = tmp_path / "graph.json"
    files = [{"p": odd}, {"p": long}]
    graph.write_text(json.dumps({"schema": "floorplan/graph@1", "nodes": [], "files": files}))
    out = export(capsys, workspace_dir, "--graph", graph, "--include-files")
    payload = json.loads(out)
    assert errors(payload) == []
    listed = payload["files"]["[Unowned files]"]
    assert "src/odd\\ue000.kt" in listed and odd not in listed
    assert sorted(map(len, listed))[-1] == 256 and long not in listed


def test_issue_rows_redact_remote_looking_file_names(workspace_dir, capsys):
    name = "scpbox.example:private.md"
    (workspace_dir / "features/netlens" / name).write_text("no frontmatter")
    folder = workspace_dir / "components"
    folder.mkdir()
    (folder / "netlens.yaml").write_text(COMPONENT_YAML)
    out = export(capsys, workspace_dir)
    assert "scpbox.example:private" not in out
    assert REDACTED in [issue["path"] for issue in json.loads(out)["issues"]]


def test_other_projects_diagnostics_are_not_exported(workspace_dir, capsys):
    other = workspace_dir / "features/other"
    other.mkdir(parents=True)
    (other / "0001-SECRETNAME.md").write_text("no frontmatter")
    out = export(capsys, workspace_dir, *recorded_flags(), "--include-files")
    assert "SECRETNAME" not in out
