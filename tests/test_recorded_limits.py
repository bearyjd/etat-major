import json
from time import monotonic

import pytest

from etat_major.evidence_records import branch_task, load_prs, load_releases
from etat_major.floorplan import SUPPORTED_SCHEMA, load_architecture, load_graph, load_plan
from etat_major.taskfile import TaskFileError
from etat_major.trail import load_wiring


@pytest.mark.parametrize(
    ("load", "document", "field"),
    [
        (load_prs, None, "json"),
        (load_releases, None, "json"),
        (load_wiring, {"meta": {"version": 1}, "nodes": [], "edges": []}, "nodes"),
        (load_wiring, {"meta": {"version": 1}, "nodes": [], "edges": []}, "edges"),
        (load_graph, {"schema": SUPPORTED_SCHEMA, "nodes": []}, "nodes"),
        (load_architecture, {"schema": SUPPORTED_SCHEMA, "nodes": []}, "files"),
        (load_plan, {}, "files"),
    ],
)
def test_recorded_array_is_capped_before_row_validation(tmp_path, load, document, field):
    path = tmp_path / "recording.json"
    rows = [{}] * 50_001
    data = rows if document is None else document | {field: rows}
    path.write_text(json.dumps(data))
    with pytest.raises(TaskFileError, match=rf"recording.json.*{field}.*50000"):
        load(path)


def test_branch_task_bounds_lengths_and_repetitive_input():
    known = frozenset({"a/1"})
    assert branch_task("task/a-1-" + "x" * 247, known) is None
    branch = "task/a" + "-1-a" * 80_000
    start = monotonic()
    assert branch_task(branch, known) is None
    assert monotonic() - start < 1
    assert branch_task("task/a-1-a-1-end", known) == "a/1"


def test_oversize_error_names_file_and_limit(tmp_path):
    from etat_major.localfiles import read_text_kib

    path = tmp_path / "wiring.json"
    path.write_text("x" * 2048)
    with pytest.raises(ValueError, match=r"wiring\.json.*file exceeds the 1 KiB limit"):
        read_text_kib(path, 1)


def test_oversize_recording_names_file_and_field(tmp_path):
    path = tmp_path / "huge-graph.json"
    path.write_text(" " * (64 * 1024 * 1024 + 1))
    with pytest.raises(TaskFileError, match=r"huge-graph\.json.*64 MiB"):
        load_graph(path)
