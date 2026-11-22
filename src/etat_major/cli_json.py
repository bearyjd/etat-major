"""Serialization for the versioned CLI contracts."""

import json
import sys
from dataclasses import fields, is_dataclass

from etat_major.records import Decision
from etat_major.refs import Ref
from etat_major.taskfile import TaskFileError
from etat_major.text_safety import public_source_url, public_text
from etat_major.trace import ARCHITECTURE_PROBLEM_STATES, Trace
from etat_major.workspace import Issue, feature_ref

COMMAND_NAMES = {
    "trace": "trace",
    "decisions": "decisions-list",
    "index": "index",
    "progress": "progress",
    "workspace": "workspace-validate",
}


def json_format_requested(argv: list[str]) -> bool:
    formats = []
    for index, arg in enumerate(argv):
        if arg == "--":
            break
        if arg.startswith("--format="):
            formats.append(arg.partition("=")[2])
        elif arg == "--format" and index + 1 < len(argv):
            formats.append(argv[index + 1])
    return bool(formats and formats[-1] == "json")


def issue_data(issue: Issue, severity: str = "error") -> dict[str, str]:
    return {
        "path": public_text(issue.path),
        "field": public_text(issue.field or "file"),
        "message": public_text(issue.message),
        "severity": severity,
    }


def json_result(
    command: str,
    status: int,
    data: dict[str, object] | None = None,
    *,
    issues: tuple[Issue, ...] = (),
    warnings: tuple[Issue, ...] = (),
) -> int:
    envelope = {
        "schema": f"etat-major/{COMMAND_NAMES[command]}@1",
        "ok": status == 0,
        "data": data,
        "issues": [issue_data(issue) for issue in issues]
        + [issue_data(warning, "warning") for warning in warnings],
    }
    sys.stdout.write(json.dumps(envelope, sort_keys=True, ensure_ascii=True, indent=2) + "\n")
    return status


def json_error(command: str, error: TaskFileError) -> int:
    issue = Issue(error.filename, error.field_name, error.message)
    return json_result(command, 2, issues=(issue,))


def _trace_value(value: object) -> object:
    if isinstance(value, Ref):
        return public_text(str(value))
    if isinstance(value, tuple):
        return [_trace_value(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: (
                public_source_url(getattr(value, item.name))
                if item.name == "source"
                else _trace_value(getattr(value, item.name))
            )
            for item in fields(value)
        }
    return public_text(value) if isinstance(value, str) else value


def trace_data(trace: Trace, omitted_issues: int) -> dict[str, object]:
    feature = trace.feature
    return {
        "feature": {
            "ref": str(feature_ref(feature)),
            "title": public_text(feature.title),
            "status": feature.status,
            "outcome": None if feature.outcome is None else public_text(feature.outcome),
            "provenance": "human",
        },
        "research": _trace_value(trace.research),
        "decisions": _trace_value(trace.decisions),
        "architecture": _trace_value(trace.architecture),
        "acceptance": _trace_value(trace.acceptance),
        "links": _trace_value(trace.links),
        "omitted_issues": omitted_issues,
    }


def trace_issues(trace: Trace) -> tuple[Issue, ...]:
    return tuple(
        Issue(str(feature_ref(trace.feature)), "architecture", f"{row.state}: {row.ref}")
        for row in trace.architecture
        if row.state in ARCHITECTURE_PROBLEM_STATES
    )


def decisions_data(decisions: list[Decision], omitted_issues: int) -> dict[str, object]:
    return {
        "decisions": [
            {
                "ref": f"decision:{decision.id}",
                "status": decision.status,
                "decided_by": decision.decided_by,
                "question": public_text(decision.question),
            }
            for decision in decisions
        ],
        "omitted_issues": omitted_issues,
    }
