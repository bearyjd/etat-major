"""Shared inputs for the `export understand` tests."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from etat_major.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
GRAPH = FIXTURES / "floorplan" / "graph-real.json"
TRAIL = FIXTURES / "trail" / "wiring-kotlin.json"
COMPONENTS = FIXTURES / "planning" / "netlens.yaml"
ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/contracts/schemas/understand.schema.json"
SHA_A = "a" * 40
SHA_B = "b" * 40


def argv(workspace, *flags, project="netlens"):
    base = ["export", "understand", "--json", "--workspace", str(workspace)]
    return [*base, "--project", project, *map(str, flags)]


def recorded_flags():
    return ("--components", COMPONENTS, "--graph", GRAPH, "--trail", TRAIL)


def export(capsys, workspace, *flags, project="netlens"):
    status = main(argv(workspace, *flags, project=project))
    captured = capsys.readouterr()
    assert status == 0, captured.err
    assert captured.err == ""
    return captured.out


def failure(capsys, workspace, *flags, project="netlens"):
    assert main(argv(workspace, *flags, project=project)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    return captured.err


def schema():
    return json.loads(SCHEMA_PATH.read_text())


def errors(payload):
    document = schema()
    Draft202012Validator.check_schema(document)
    return [
        f"{list(e.absolute_path)}: {e.message}"
        for e in Draft202012Validator(document).iter_errors(payload)
    ]
