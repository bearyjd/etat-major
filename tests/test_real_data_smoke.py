import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/real_data_smoke.py"


def smoke(*args):
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_recorded_kotlin_counts_and_provenance(tmp_path):
    pin = tmp_path / "expect.json"
    checks = {"index": {"status": 0, "data.symbols.nodes.#": 160}}
    pin.write_text(json.dumps(checks))
    args = [
        pin,
        "--graph",
        "tests/fixtures/floorplan/graph-real.json",
        "--trail",
        "tests/fixtures/trail/wiring-kotlin.json",
    ]
    assert smoke(*args).returncode == 2
    result = smoke(*args, "--partial")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS index" in result.stdout and "SKIP trace" in result.stdout
    checks["index"]["data.symbols.nodes.#"] = 1
    pin.write_text(json.dumps(checks))
    result = smoke(*args, "--partial")
    assert result.returncode == 1 and "data.symbols.nodes.#" in result.stdout


def test_untrusted_manifest_cannot_choose_commands_or_authorize_wrappers(tmp_path):
    pin = tmp_path / "expect.json"
    for name in ("run-me", "floorplan scan"):
        pin.write_text(json.dumps({name: {"status": 0}}))
        result = smoke(pin, "--partial")
        assert result.returncode == 2 and "Traceback" not in result.stderr


def test_full_baseline_tracks_public_cli_leaves():
    import argparse

    from etat_major.cli import _parser

    def leaves(parser, parts=()):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                return {
                    leaf
                    for name, child in action.choices.items()
                    for leaf in leaves(child, (*parts, name))
                }
            if action.dest == "action" and action.choices:
                return {" ".join((*parts, name)) for name in action.choices}
        return {" ".join(parts)}

    pins = ROOT / "docs/examples/netlens-real-data-smoke.json"
    assert json.loads(pins.read_text()).keys() == leaves(_parser())


def test_duplicate_pins_are_configuration_errors(tmp_path):
    pin = tmp_path / "expect.json"
    pin.write_text('{"index":{"status":1,"status":0}}')
    result = smoke(pin, "--partial")
    assert result.returncode == 2 and "expectations.file" in result.stdout


def test_status_only_and_nonstandard_constants_fail_configuration(tmp_path):
    pin = tmp_path / "expect.json"
    for raw in ['{"index":{"status":0}}', '{"index":{"status":0,"data.version":NaN}}']:
        pin.write_text(raw)
        result = smoke(pin, "--partial", "--graph", "unused", "--trail", "unused")
        assert result.returncode == 2


def test_positional_answer_cannot_request_help(tmp_path):
    pin = tmp_path / "expect.json"
    pin.write_text(json.dumps({"research import": {"status": 0, "data.status": "unreviewed"}}))
    result = smoke(pin, "--partial", "--answer=--help")
    assert result.returncode == 2 and "research import.answer" in result.stdout


def test_nested_json_numbers_and_booleans_differ():
    from runpy import run_path

    matches = run_path(str(SCRIPT))["matches"]
    assert not matches({"data": [{"items": [1]}]}, "data", [{"items": [True]}])
