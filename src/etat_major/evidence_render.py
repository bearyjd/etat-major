"""Render the local progress report for the CLI."""

from dataclasses import asdict

from etat_major.evidence import ProgressReport, Rung
from etat_major.text_safety import safe


def progress_data(report: ProgressReport) -> dict[str, object]:
    rows = {item.key: {"state": item.state, **asdict(item.evidence)} for item in report.tasks}
    feature_rows = {
        item.key: {
            "state": item.state,
            "tasks": item.tasks,
            "architecture": dict(item.architecture),
            "accepted": item.acceptance,
        }
        for item in report.features
    }
    return {
        "version": report.version,
        "tasks": rows,
        "features": feature_rows,
        "disconnected_commits": report.disconnected_commits,
        "disconnected_prs": report.disconnected_prs,
        "stale_milestones": report.stale_milestones,
        "stale_links": report.stale_links,
        "unimplemented_requirements": report.unimplemented_requirements,
    } | ({"meute": asdict(report.meute)} if report.meute else {})


def render_text(report: ProgressReport) -> str:
    lines = []
    for task in report.tasks:
        lines.append(safe(f"task:{task.key}  {task.state}"))
        for label, refs in asdict(task.evidence).items():
            lines.append(safe(f"  {label}  {_format_rung(refs)}"))
    for feature in report.features:
        lines.append(safe(f"feature:{feature.key}  {feature.state}"))
        lines.append(safe(f"  accepted  {_format_rung(feature.acceptance)}"))
        lines.extend(safe(f"  {ref}  {state}") for ref, state in feature.architecture)
    lines.extend(safe(f"disconnected  commit:{oid}") for oid in report.disconnected_commits)
    lines.extend(safe(f"disconnected  pr:{number}") for number in report.disconnected_prs)
    lines.extend(safe(f"stale  {ref}") for ref in report.stale_milestones)
    lines.extend(safe(f"stale link  {owner}  {ref}") for owner, ref in report.stale_links)
    lines.extend(
        safe(f"unimplemented requirement  {owner}  {ref}")
        for owner, ref in report.unimplemented_requirements
    )
    if snapshot := report.meute:
        lines.append(safe(f"Meute snapshot  {snapshot.project}  exported {snapshot.exported_at}"))
        for row in snapshot.reports:
            link = f"linked to {row.task}" if row.linked else "unlinked"
            lines.append(safe(f"  {row.ref}  recorded {row.recorded_at}  {row.outcome}  {link}"))
    return "\n".join(lines) + ("\n" if lines else "")


def _format_rung(rung: Rung) -> str:
    return rung if isinstance(rung, str) else ", ".join(rung)
