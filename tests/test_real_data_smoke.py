import json
import os
import subprocess
import sys
from pathlib import Path
from runpy import run_path

import pytest

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
        pin.write_text(json.dumps({name: {"status": 0, "data.lines.#": 1}}))
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
    runner = run_path(str(SCRIPT))
    operations = runner["OPERATIONS"]
    assert json.loads(pins.read_text()).keys() == operations.keys() == leaves(_parser())
    flags = {field.lstrip("$?") for specs in operations.values() for field in specs.split()}
    args = runner["parser"]().parse_args(
        [str(pins), *(token for field in flags for token in ("--" + field, field))]
    )
    for name in operations:
        parsed = _parser().parse_args(runner["arguments"](name, args, ROOT))
        assert parsed.command == name.split()[0]
        if " " in name:
            assert parsed.action == name.split()[1]
        for spec in operations[name].split():
            field = spec.lstrip("$?")
            dest = {"feature": "ref", "answer": "file"}.get(field, field.replace("-", "_"))
            assert str(getattr(parsed, dest)) == field


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
    matches = run_path(str(SCRIPT))["matches"]
    assert not matches({"data": [{"items": [1]}]}, "data", [{"items": [True]}])


def test_checked_in_partial_baseline():
    result = smoke(
        "docs/examples/real-data-smoke.json",
        "--partial",
        "--root",
        "tests/fixtures/gradle-real",
        "--graph",
        "tests/fixtures/floorplan/graph-real.json",
        "--trail",
        "tests/fixtures/trail/wiring-kotlin.json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert [line for line in result.stdout.splitlines() if line.startswith("PASS")] == [
        "PASS index",
        "PASS gradle deps",
        "PASS gradle drift",
    ]


@pytest.mark.parametrize(
    "field",
    [
        "root",
        "repo",
        "workspace",
        "graph",
        "trail",
        "source",
        "prs",
        "releases",
        "meute",
        "answer",
        "expectations",
    ],
)
def test_wrapper_overlap_fails_before_any_operation(tmp_path, field):
    copy = tmp_path / "copy"
    copy.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(copy, target_is_directory=True)
    source = tmp_path / "tool"
    pin = (copy if field == "expectations" else tmp_path) / "expect.json"
    pin.write_text(json.dumps({"floorplan scan": {"status": 0, "data.lines.#": 1}}))
    flags = ["--copy", copy, "--source", tmp_path if field == "source" else source]
    if field not in ("source", "expectations"):
        flags.extend(["--" + field, alias / "evidence" if field != "repo" else alias])
    result = smoke(pin, "--partial", *flags)
    assert result.returncode == 2 and "overlap" in result.stdout
    assert "PASS" not in result.stdout and "SKIP" not in result.stdout
    assert str(tmp_path) not in result.stdout


def test_wrapper_requires_both_paths_and_delegates_disjoint_paths(tmp_path, monkeypatch):
    pin = tmp_path / "expect.json"
    pin.write_text(json.dumps({"floorplan scan": {"status": 0, "data.lines.#": 1}}))
    for given, missing in [("source", "copy"), ("copy", "source")]:
        result = smoke(pin, "--partial", "--" + given, tmp_path / given)
        assert result.returncode == 2 and f"missing --{missing}" in result.stdout
    args = ["--copy", str(tmp_path / "copy"), "--source", str(tmp_path / "tool")]
    expected = ["floorplan", "scan", *args]
    called = []

    def record(argv):
        called.append(argv)
        print("Recorded floorplan/.cache/scan.json")
        return 0

    main = run_path(str(SCRIPT))["main"]
    monkeypatch.setitem(main.__globals__, "cli", record)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(pin), "--partial", *args])
    assert main() == 0
    assert called == [expected]


def test_moving_head_cannot_certify_progress(monkeypatch, tmp_path):
    from contextlib import nullcontext

    observe = run_path(str(SCRIPT))["observe"]
    revisions = iter(["a" * 40, "b" * 40])
    monkeypatch.setitem(observe.__globals__, "_open_repository", lambda repo: nullcontext(0))
    monkeypatch.setitem(observe.__globals__, "_resolve_commit", lambda *args: next(revisions))

    def fake_cli(argv):
        print('{"data": {}}')
        return 0

    monkeypatch.setitem(observe.__globals__, "cli", fake_cli)
    with pytest.raises(ValueError, match="revision"):
        observe("progress", ["--repo", ".", "--format", "json"], tmp_path, False)


def test_non_json_cli_failure_preserves_exit_code(monkeypatch, tmp_path):
    observe = run_path(str(SCRIPT))["observe"]
    monkeypatch.setitem(observe.__globals__, "cli", lambda argv: 2)
    assert observe("index", ["--format", "json"], tmp_path, False)["status"] == 2
