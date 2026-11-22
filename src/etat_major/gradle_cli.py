"""CLI entry points for the recorded Gradle comparison."""

import argparse
from dataclasses import asdict

from etat_major.cli_json import json_result
from etat_major.floorplan import load_architecture
from etat_major.gradle import INPUT_LIMIT_KIB, load_dependencies
from etat_major.gradle_drift import compare_dependencies
from etat_major.text_safety import public_text, safe
from etat_major.trail import load_wiring
from etat_major.workspace import Issue


def run_gradle(args: argparse.Namespace) -> int:
    dependencies = load_dependencies(args.root)
    issues = dependencies.issues
    if args.action == "deps":
        data = {
            "modules": [asdict(module) for module in dependencies.modules],
            "edges": [asdict(edge) for edge in dependencies.edges],
        }
    else:
        graph = load_architecture(args.graph, limit_kib=INPUT_LIMIT_KIB)
        trail = load_wiring(args.trail, limit_kib=INPUT_LIMIT_KIB) if args.trail else None
        report = compare_dependencies(dependencies, graph, trail)
        data = asdict(report)
        if report.has_differences:
            issues += (
                Issue("gradle-drift", "drift", "candidate dependency or module differences"),
            )
    if args.format == "json":
        escaped = tuple(
            Issue(safe(i.path), safe(i.field or "file"), safe(i.message)) for i in issues
        )
        return json_result(f"gradle-{args.action}", int(bool(issues)), data, issues=escaped)
    _render(data)
    for issue in issues:
        print(safe(public_text(str(issue))))
    return int(bool(issues))


def _render(data: dict) -> None:
    for field, rows in data.items():
        print(field.replace("_", " ") + ":")
        for row in rows:
            if isinstance(row, str):
                print(safe(row))
            elif "directory" in row:
                print(safe(f"{row['id']}  {row['directory'] or '.'}"))
            elif "configuration" in row:
                _print_declaration(row)
            else:
                print(safe(f"{row['source']} -> {row['target']}  evidence={row['evidence_count']}"))
                for declaration in row["declarations"]:
                    _print_declaration(declaration, indent="  ")
                for item in row["evidence"]:
                    confidence = f"/{item['confidence']}" if item["confidence"] else ""
                    print(
                        safe(
                            f"  {item['layer']} {item['relation']} "
                            f"{item['provenance']}{confidence}  count={item['count']}"
                        )
                    )


def _print_declaration(edge: dict, *, indent: str = "") -> None:
    test = "  test-only" if edge["test_only"] else ""
    print(
        safe(
            f"{indent}{edge['source']} -> {edge['target']}  {edge['configuration']}{test}"
            f"  {edge['file']}:{edge['line']}"
        )
    )
