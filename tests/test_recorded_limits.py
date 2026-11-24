import json
from pathlib import Path
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


def test_oversize_recording_names_file_and_field(tmp_path, monkeypatch):
    monkeypatch.setattr("etat_major.floorplan._LIMIT_MIB", 1)
    path = tmp_path / "huge-graph.json"
    path.write_text(" " * (1024 * 1024 + 1))
    with pytest.raises(TaskFileError, match=r"huge-graph\.json.*1 MiB"):
        load_graph(path)


def test_oversize_error_escapes_control_characters_in_the_file_name(tmp_path):
    from etat_major.localfiles import read_text_kib

    path = tmp_path / "bad\x1b[31mname.json"
    path.write_text("x" * 2048)
    with pytest.raises(ValueError) as caught:
        read_text_kib(path, 1)
    assert "\x1b" not in str(caught.value)
    assert "\\u001b" in str(caught.value)


def test_write_new_text_oversize_names_the_file(tmp_path):
    from etat_major.localfiles import write_new_text

    with pytest.raises(ValueError, match=r"out\.md.*file exceeds the 1 MiB limit"):
        write_new_text(tmp_path / "out.md", "x" * (1024 * 1024 + 1))


def test_write_new_text_limit_bytes_raises_the_cap_and_names_nothing_else(tmp_path):
    from etat_major.localfiles import write_new_text

    big = "x" * (2 * 1024 * 1024)
    write_new_text(tmp_path / "big.json", big, limit_bytes=4 * 1024 * 1024)
    assert (tmp_path / "big.json").read_text() == big
    with pytest.raises(ValueError, match=r"too\.json.*file exceeds the 1 MiB limit"):
        write_new_text(tmp_path / "too.json", big)
    assert not (tmp_path / "too.json").exists()


def test_write_new_text_limit_bytes_rejects_over_the_given_cap(tmp_path):
    from etat_major.localfiles import write_new_text

    with pytest.raises(ValueError, match=r"cap\.json.*file exceeds the 2 MiB limit"):
        write_new_text(tmp_path / "cap.json", "x" * (2 * 1024 * 1024 + 1), limit_bytes=2 << 20)
    assert not (tmp_path / "cap.json").exists()


def test_smoke_doc_labels_size_and_latency_measurements_not_run() -> None:
    doc = (Path(__file__).resolve().parents[1] / "docs" / "REAL-DATA-SMOKE.md").read_text(
        encoding="utf-8"
    )
    assert "## Data-size and latency observations" in doc
    section = doc.split("## Data-size and latency observations", 1)[1]
    assert "Not run" in section
    assert "deferred" in section.lower()
