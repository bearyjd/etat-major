import json
import shutil
from pathlib import Path

import pytest

from etat_major.floorplan import FloorplanError, load_graph
from etat_major.refs import parse_ref

FIXTURE = Path(__file__).parent / "fixtures" / "floorplan" / "graph.json"


def graph_with(tmp_path: Path, **changes) -> Path:
    data = json.loads(FIXTURE.read_text())
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(data))
    return path


def test_good_graph_index():
    idx = load_graph(FIXTURE)
    assert idx.has_node("ui.hostdetail") and not idx.has_node("nope")
    assert idx.has_file("app/src/net/Scanner.kt") and not idx.has_file("app/src/net/Latency.kt")


def test_resolve_fp_refs():
    idx = load_graph(FIXTURE)
    assert idx.resolve(parse_ref("fp:n:ui.hostdetail"))
    assert not idx.resolve(parse_ref("fp:n:ui.gone"))
    assert idx.resolve(parse_ref("fp:f:app/src/ui/HostDetail.kt"))
    assert not idx.resolve(parse_ref("fp:f:app/Latency.kt"))


def test_resolve_rejects_non_floorplan_refs():
    with pytest.raises(ValueError, match="fp:"):
        load_graph(FIXTURE).resolve(parse_ref("trail:a.py#s"))


@pytest.mark.parametrize("schema", ["floorplan/graph@2", "floorplan/plan@1", "", 1])
def test_wrong_schema_names_value(tmp_path, schema):
    with pytest.raises(FloorplanError) as exc:
        load_graph(graph_with(tmp_path, schema=schema))
    assert repr(schema) in str(exc.value) and "floorplan/graph@1" in str(exc.value)


def test_missing_schema(tmp_path):
    with pytest.raises(FloorplanError, match="missing"):
        load_graph(graph_with(tmp_path, schema=None))


def test_root_and_remote_not_retained(tmp_path):
    meta = {"root": "/abs/root/secret-repo", "repos": [{"remote": "git@host.example:x/y.git"}]}
    idx = load_graph(graph_with(tmp_path, meta=meta))
    blob = repr(idx) + repr(vars(idx) if hasattr(idx, "__dict__") else "")
    assert "secret-repo" not in blob and "host.example" not in blob
    assert not any("secret" in n or "example" in n for n in idx.node_ids | idx.file_paths)


def test_index_is_immutable():
    idx = load_graph(FIXTURE)
    with pytest.raises(AttributeError):
        idx.node_ids = frozenset()  # type: ignore[misc]


@pytest.mark.parametrize(
    "changes",
    [{"nodes": "x"}, {"files": [{"n": "a"}]}, {"nodes": [{"label": "no id"}]}, {"files": None}],
)
def test_malformed_structure(tmp_path, changes):
    with pytest.raises(FloorplanError):
        load_graph(graph_with(tmp_path, **changes))


def test_not_json_and_not_object(tmp_path):
    bad = tmp_path / "g.json"
    bad.write_text("{nope")
    with pytest.raises(FloorplanError, match="JSON"):
        load_graph(bad)
    bad.write_text("[]")
    with pytest.raises(FloorplanError, match="object"):
        load_graph(bad)
    with pytest.raises(FloorplanError, match="cannot read"):
        load_graph(tmp_path / "absent.json")


def test_fixture_copy_untouched(tmp_path):
    shutil.copy(FIXTURE, tmp_path / "g.json")
    assert load_graph(tmp_path / "g.json").has_node("net.scan")
