"""Compare fixed CLI operations with a maintainer's recorded JSON expectations."""

import argparse
import io
import json
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from etat_major.cli import main as cli
from etat_major.evidence_git import _resolve_commit
from etat_major.localfiles import open_directory, read_text_kib
from etat_major.records import load_research
from etat_major.renames import _open_repository

# Each token names a trusted CLI flag, a positional input ($), or an optional flag (?).
OPERATIONS = {
    "trace": "$feature workspace graph trail",
    "index": "graph trail",
    "decisions list": "workspace",
    "research brief": "$feature workspace",
    "research import": "$answer",
    "gradle deps": "root",
    "gradle drift": "root graph trail",
    "components validate": "workspace",
    "components map": "workspace project path",
    "components coverage": "workspace project graph",
    "components seed": "root project trail",
    "progress": "workspace repo prs releases graph trail ?as-of ?meute",
    "workspace validate": "workspace",
    "serve": "workspace project graph trail repo prs releases ?meute",
    "floorplan scan": "copy source",
    "floorplan build": "copy source",
    "floorplan refresh": "copy source",
}
SELECTOR = re.compile(
    r"(?:[A-Za-z_][A-Za-z_0-9]*|[0-9]{1,8}|#)(?:\.(?:\w{1,64}|#)){0,15}", re.ASCII
)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("expectations", type=Path)
    p.add_argument("--partial", action="store_true", help="allow an explicitly incomplete baseline")
    p.add_argument("--understand", action="store_true", help="also check GET /understand")
    for key in sorted({k.lstrip("$?") for row in OPERATIONS.values() for k in row.split()}):
        p.add_argument("--" + key)
    return p


def unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate expectation")
    return result


def invalid_constant(_):
    raise ValueError("invalid JSON constant")


def baseline(args):
    try:
        with open_directory(args.expectations.parent) as fd:
            pins = json.loads(
                read_text_kib(args.expectations, 64, dir_fd=fd),
                parse_constant=invalid_constant,
                object_pairs_hook=unique_fields,
            )
    except (ValueError, OSError, RecursionError):
        raise ValueError("expectations.file: expected a bounded JSON file") from None
    if not isinstance(pins, dict) or not pins or pins.keys() - OPERATIONS.keys():
        raise ValueError("expectations.commands: expected known CLI operation names")
    if not args.partial and pins.keys() != OPERATIONS.keys():
        raise ValueError("expectations.commands: incomplete baseline requires --partial")
    for name, checks in pins.items():
        if not isinstance(checks, dict) or type(checks.get("status")) is not int:
            raise ValueError(f"{name}.status: expected a pinned exit code")
        if checks["status"] not in (0, 1):
            raise ValueError(f"{name}.status: expected success or a recorded diagnostic")
        if any(len(k) > 256 or not SELECTOR.fullmatch(k) for k in checks):
            raise ValueError(f"{name}.fields: expected bounded dotted selectors")
        if not any(k.startswith(("data.", "issues.")) or k == "data" for k in checks):
            raise ValueError(f"{name}.fields: expected a pinned result field")
        if name == "serve" and not any(k.startswith("data.project.") for k in checks):
            raise ValueError("serve.fields: expected a field from GET /project.json")
    return pins


def arguments(name, args, scratch):
    argv = name.split()
    for spec in OPERATIONS[name].split():
        field = spec.lstrip("$?")
        value = getattr(args, field.replace("-", "_"))
        if value is None:
            if spec.startswith("?"):
                continue
            raise ValueError(f"{name}.{field}: missing --{field}")
        if value.startswith("-"):
            raise ValueError(f"{name}.{field}: expected a value, not a CLI option")
        if not spec.startswith("$"):
            argv.append("--" + field)
        argv.append(value)
    if name == "research import":
        return [*argv, "--workspace", str(scratch), "--id", "0001"]
    if name == "research brief":
        return [*argv, "--out", str(scratch / "brief.md")]
    if name == "components seed":
        argv.extend(["--out", str(scratch / "seed.yaml")])
    if not name.startswith("floorplan ") and name != "serve":
        argv.extend(["--format", "json"])
    return argv


def guard_copy_inputs(args):
    fields = (
        "source",
        "root",
        "repo",
        "workspace",
        "graph",
        "trail",
        "prs",
        "releases",
        "meute",
        "answer",
        "expectations",
    )
    try:
        copy = Path(args.copy).resolve()
        for field in fields:
            value = getattr(args, field)
            if value is not None:
                source = Path(value).resolve()
                if copy.is_relative_to(source) or source.is_relative_to(copy):
                    raise ValueError(f"floorplan.copy: overlap with {field}")
    except (OSError, RuntimeError):
        raise ValueError("floorplan.copy: cannot resolve input paths") from None


def serve(argv, understand):
    from fastapi.testclient import TestClient

    result = {}

    def probe(app, **kwargs):
        with TestClient(app, base_url="http://127.0.0.1") as client:
            for route in [
                "planning",
                "fleet",
                "project.json",
                *(["understand"] if understand else []),
            ]:
                response = client.get("/" + route)
                response.raise_for_status()
                if route == "project.json":
                    result["project"] = response.json()
                else:
                    result[route] = response.status_code

    with patch("uvicorn.run", probe):
        status = cli(argv)
    return {"status": status, "data": result}


def observe(name, argv, scratch, understand):
    if name == "progress":
        repo = Path(argv[argv.index("--repo") + 1])
        with _open_repository(repo) as fd:
            revision = _resolve_commit(fd, "HEAD")
    with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()):
        if name == "serve":
            return serve(argv, understand)
        status = cli(argv)
    if status not in (0, 1):
        return {"status": status}
    if "--format" in argv:
        result = json.loads(stdout.getvalue())
        if name == "progress":
            with _open_repository(repo) as fd:
                if revision != _resolve_commit(fd, "HEAD"):
                    raise ValueError("progress.revision: HEAD changed during observation")
            result["revision"] = revision
    elif status == 0 and name == "research import":
        record = load_research(scratch / "research/0001-chatgpt-research.md")
        result = {"data": record.model_dump(mode="json")}
    elif status == 0 and name == "research brief":
        result = {"data": {"written": (scratch / "brief.md").stat().st_size > 0}}
    else:
        result = {"data": {"lines": stdout.getvalue().splitlines()}}
    return {**result, "status": status}


def matches(result, selector, expected):
    value = result
    try:
        for part in selector.split("."):
            if part == "#" and isinstance(value, list | dict):
                value = len(value)
            elif isinstance(value, list) and part.isdigit():
                value = value[int(part)]
            else:
                value = value[part]
    except (IndexError, KeyError, TypeError):
        return False
    return json.dumps(value, sort_keys=True) == json.dumps(expected, sort_keys=True)


def main():
    args = parser().parse_args()
    with TemporaryDirectory() as directory:
        scratch = Path(directory)
        try:
            pins = baseline(args)
            commands = {name: arguments(name, args, scratch) for name in pins}
            if any(name.startswith("floorplan ") for name in commands):
                guard_copy_inputs(args)
        except ValueError as exc:
            print(exc)
            return 2
        failed = False
        for name in OPERATIONS:
            if name not in pins:
                print("SKIP", name)
                continue
            try:
                result = observe(name, commands[name], scratch, args.understand)
                errors = [k for k, v in pins[name].items() if not matches(result, k, v)]
            except (Exception, SystemExit) as exc:
                # Diagnostics and artifact contents can contain private paths or terminal controls.
                errors = [type(exc).__name__]
            if errors:
                print("FAIL", name, ", ".join(errors))
                failed = True
            else:
                print("PASS", name)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
