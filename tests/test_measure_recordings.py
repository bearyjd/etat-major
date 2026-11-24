import json
import os
import re
import subprocess
import sys
from pathlib import Path
from runpy import run_path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/measure_recordings.py"
GRAPH = ROOT / "tests/fixtures/floorplan/graph-real.json"
TRAIL = ROOT / "tests/fixtures/trail/wiring-kotlin.json"
LIMITS = ROOT / "docs/LIMITS.md"
HOST = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|lan|local|internal)\b", re.I)


@pytest.fixture(scope="module")
def module():
    return run_path(str(SCRIPT))


def run(*args):
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_report_has_bytes_counts_and_seconds(module):
    report = module["measure"]([GRAPH, TRAIL], 2)
    graph, trail = report["recordings"]
    assert graph["bytes"] == GRAPH.stat().st_size
    assert trail["bytes"] == TRAIL.stat().st_size
    assert graph["kind"] == "floorplan" and trail["kind"] == "trail"
    assert graph["nodes"] > 0 and graph["edges"] >= 0 and graph["files"] > 0
    assert trail["nodes"] > 0 and trail["symbols"] > 0 and trail["edges"] >= 0
    for row in (graph["load_seconds"], trail["load_seconds"], report["index_build_seconds"]):
        assert row["runs"] == 2
        assert 0.0 <= row["min"] <= row["median"]
        assert isinstance(row["min"], float) and isinstance(row["median"], float)


def test_single_recording_has_no_index_build(module):
    assert module["measure"]([GRAPH], 1)["index_build_seconds"] is None


def test_no_absolute_path_or_hostname_in_output():
    result = run(GRAPH, TRAIL)
    assert result.returncode == 0, result.stderr
    text = result.stdout + result.stderr
    assert str(ROOT) not in text and "/home" not in text and "/var" not in text
    assert not HOST.search(text.replace("graph-real.json", "").replace("wiring-kotlin.json", ""))
    json.loads(run(GRAPH, "--json").stdout)


def test_default_is_five_runs(module):
    assert module["measure"]([GRAPH])["runs"] == 5


def test_missing_file_is_a_clear_error(tmp_path):
    result = run(tmp_path / "nope.json")
    assert result.returncode == 2
    assert "nope.json" in result.stderr and "Traceback" not in result.stderr
    assert str(tmp_path) not in result.stderr


def test_invalid_recording_is_a_clear_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    result = run(bad)
    assert result.returncode == 2 and "bad.json" in result.stderr
    assert "Traceback" not in result.stderr


def test_runs_must_be_positive():
    assert run(GRAPH, "--runs", "0").returncode == 2


def test_limits_doc_has_no_absolute_path_and_matches_rerun(module):
    text = LIMITS.read_text()
    assert not re.search(r"(?<![\w.])/(?:home|var|usr|tmp|Users)/", text)
    graph, trail = module["measure"]([GRAPH, TRAIL], 1)["recordings"]
    for value in (
        graph["bytes"],
        graph["nodes"],
        graph["edges"],
        graph["files"],
        trail["bytes"],
        trail["nodes"],
        trail["edges"],
        trail["symbols"],
    ):
        assert f"{value:,}" in text or str(value) in text
