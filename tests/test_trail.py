import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pydantic import ValidationError

from etat_major.trail import TrailError, load_wiring

FIXTURE = Path(__file__).parent / "fixtures/trail/wiring.json"
FILE = "src/etat_major/taskfile.py"
SYMBOL = f"{FILE}#_with_line"
PRIVATE_PATH = "/" + "private/project"


def graph(**overrides):
    return {"meta": {"version": 1}, "nodes": [], "edges": [], **overrides}


def write_graph(tmp_path, **overrides):
    path = tmp_path / "wiring.json"
    path.write_text(json.dumps(graph(**overrides)), encoding="utf-8")
    return path


def test_recorded_graph_preserves_fields_and_counts():
    index = load_wiring(FIXTURE)
    assert len(index.symbols) == 66
    assert len(index.edges) == 167
    assert index.coverage.languages == ("python",)
    assert index.coverage.node_kinds == {"file": 5, "class": 8, "function": 48, "method": 5}
    assert index.coverage.relations == {"calls": 82, "contains": 61, "imports": 17, "extends": 7}
    file = index.symbols_in(FILE)[0]
    assert (file.id, file.kind, file.path, file.start_line, file.end_line) == (
        FILE, "file", FILE, 1, 245,
    )  # fmt: skip
    assert not hasattr(file, "body_hash")
    assert index.has_symbol(SYMBOL)
    assert not index.has_symbol(f"{FILE}#missing")
    assert index.symbols_in("missing.py") == ()


def test_call_queries_return_direct_edges_in_graph_order():
    index = load_wiring(FIXTURE)
    callers = index.callers(SYMBOL)
    assert callers and all(edge.target == SYMBOL and edge.relation == "calls" for edge in callers)
    assert FILE in {edge.source for edge in callers}
    callees = index.callees(FILE)
    assert callees and all(edge.source == FILE and edge.relation == "calls" for edge in callees)
    assert callees == tuple(
        edge for edge in index.edges if edge.source == FILE and edge.relation == "calls"
    )
    assert index.callers("missing") == index.callees("missing") == ()


def test_coverage_counts_file_only_nodes_and_ignores_unused_metadata(tmp_path):
    path = write_graph(
        tmp_path,
        meta={"version": 1, "nodeCount": 99, "root": PRIVATE_PATH},
        nodes=[{"id": "empty.py", "path": "empty.py", "kind": "file", "span": "L1-L1"}],
    )
    index = load_wiring(path)
    assert index.coverage.languages == ()
    assert index.coverage.node_kinds == {"file": 1}
    assert index.coverage.files_without_symbols == frozenset({"empty.py"})
    assert PRIVATE_PATH not in repr(index)
    with pytest.raises((FrozenInstanceError, ValidationError)):
        index.symbols[0].path = "changed.py"
    with pytest.raises((FrozenInstanceError, ValidationError)):
        index.symbols = ()
    with pytest.raises(TypeError):
        index.coverage.node_kinds["file"] = 2


@pytest.mark.parametrize(
    ("relation", "confidence", "provenance", "flags"),
    [
        ("calls", "extracted", "verified", (False, False)),
        ("contains", "lsp_resolved", "verified", (False, False)),
        ("imports", "lsp_dispatch", "inferred", (False, False)),
        ("extends", "inferred", "inferred", (False, False)),
        ("references", "extracted", "verified", (False, False)),
        ("implements", "extracted", "verified", (False, False)),
        ("future-edge", "extracted", "verified", (True, False)),
        ("calls", "Future Confidence", "inferred", (False, True)),
    ],
)
def test_edge_confidences_and_unknown_labels(tmp_path, relation, confidence, provenance, flags):
    path = write_graph(
        tmp_path,
        edges=[
            {"source": SYMBOL, "target": "external", "relation": relation, "confidence": confidence}
        ],  # fmt: skip
    )
    index = load_wiring(path)
    (edge,) = index.edges
    assert (edge.source, edge.target) == (SYMBOL, "external")
    assert (edge.relation, edge.confidence, edge.provenance) == (relation, confidence, provenance)
    assert (edge.unknown_relation, edge.unknown_confidence) == flags
    assert index.coverage.relations == {relation: 1}


def test_freshness_uses_only_caller_supplied_revisions():
    index = load_wiring(FIXTURE, indexed_revision="a" * 40)
    assert index.freshness("a" * 40) == "fresh"
    assert index.freshness("b" * 40) == "stale"
    assert index.freshness(None) == "unknown"
    assert load_wiring(FIXTURE).freshness("a" * 40) == "unknown"


@pytest.mark.parametrize(
    "meta", [{}, {"version": 2}, {"version": True}, {"version": 1.0}, {"version": "1"}]
)
def test_requires_integer_version_one(tmp_path, meta):
    with pytest.raises(TrailError, match=r"wiring\.json.*meta\.version.*1"):
        load_wiring(write_graph(tmp_path, meta=meta))


@pytest.mark.parametrize(
    ("contents", "field"),
    [(b'{"meta":', "JSON"), (b"[]", "JSON"), (b"\xff", "JSON"), (b"[" * 5000, "JSON")],
)
def test_read_errors_name_file_and_field(tmp_path, contents, field):
    path = tmp_path / "wiring.json"
    path.write_bytes(contents)
    with pytest.raises(TrailError, match=rf"wiring\.json.*{field}"):
        load_wiring(path)


@pytest.mark.parametrize("span", ["L0-L3", "L9-L3", "3-9", "L3-L", "L" + "9" * 5000 + "-L1"])
def test_invalid_span_names_node_field(tmp_path, span):
    nodes = [{"id": SYMBOL, "path": FILE, "kind": "function", "span": span}]
    with pytest.raises(TrailError, match=r"wiring\.json.*nodes\.0\.span"):
        load_wiring(write_graph(tmp_path, nodes=nodes))


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"nodes": "bad"}, "nodes"),
        ({"edges": [None]}, r"edges\.0"),
        ({"edges": [{"source": None}]}, r"edges\.0\.source"),
        ({"meta": {"version": 1, "languages": [42]}}, r"meta\.languages\.0"),
        (
            {"nodes": [{"id": "x", "path": PRIVATE_PATH, "kind": "file", "span": "L1-L1"}]},
            r"nodes\.0\.path",
        ),
        (
            {"nodes": [{"id": "other.py#x", "path": FILE, "kind": "function", "span": "L1-L1"}]},
            r"nodes\.0\.id",
        ),
    ],
)
def test_invalid_graph_shape_names_field_without_echoing_values(tmp_path, overrides, field):
    with pytest.raises(TrailError, match=rf"wiring\.json.*{field}") as raised:
        load_wiring(write_graph(tmp_path, **overrides))
    assert PRIVATE_PATH not in str(raised.value)


def test_huge_graph_is_rejected_before_parsing(tmp_path):
    path = tmp_path / "wiring.json"
    with path.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)
    with pytest.raises(TrailError, match=r"wiring\.json.*JSON.*limit"):
        load_wiring(path)


def test_symlink_file_and_parent_are_rejected(tmp_path):
    path = write_graph(tmp_path)
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    parent = tmp_path / "linked-directory"
    parent.symlink_to(tmp_path, target_is_directory=True)
    for artifact in (link, parent / path.name):
        with pytest.raises(TrailError, match=rf"{artifact.name}.*JSON") as raised:
            load_wiring(artifact)
        assert str(tmp_path) not in str(raised.value)


def test_validation_error_preserves_field_after_escaping_filename(tmp_path):
    path = tmp_path / ("wire\x1b" + "\x1b" * 90 + ".json")
    path.write_text(json.dumps(graph(nodes=None)), encoding="utf-8")
    with pytest.raises(TrailError, match=r"wire\\u001b.*nodes") as raised:
        load_wiring(path)
    assert "\x1b" not in str(raised.value)
