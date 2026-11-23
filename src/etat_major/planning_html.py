"""Render the read-only planning projection as a self-contained page."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import fields
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from etat_major.planning_view import ArchRow, ComponentRow, FeatureRow, PlanningView, TaskRow

_STYLE = """
* { box-sizing: border-box; }
html { color-scheme: light; }
body {
    margin: 0; background: #f5f2eb; color: #202a2b;
    font: 1rem/1.55 system-ui, sans-serif; overflow-wrap: anywhere;
}
header, main { width: min(78rem, 100% - 3rem); margin-inline: auto; }
header { padding: 2rem 0 1rem; border-bottom: 1px solid #b9c0b9; }
h1, h2 { font-family: Georgia, serif; font-weight: normal; line-height: 1.1; }
h1 { margin: 0; font-size: clamp(2rem, 6vw, 3.5rem); }
h2 { margin: 0 0 .8rem; font-size: 1.75rem; }
h3 { margin: .2rem 0 .55rem; font-size: 1.04rem; }
p { margin: 0 0 .55rem; }
a { color: #135754; text-underline-offset: .15em; }
nav { display: flex; flex-wrap: wrap; gap: .35rem 1.2rem; margin-top: 1rem; }
main { padding-block: 1.5rem 3rem; }
.columns {
    display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
    grid-template-areas: "features components" "tasks components";
    grid-template-rows: auto 1fr; align-items: start; column-gap: 1.5rem;
}
#features { grid-area: features; }
#components { grid-area: components; }
#tasks { grid-area: tasks; }
.panel { margin: 0 0 1.5rem; min-width: 0; }
article, #sources {
    background: #fffdf8; border: 1px solid #d3d5ca; border-radius: .35rem;
    padding: 1rem; margin-bottom: .65rem; scroll-margin-top: 1rem;
}
article:target { border-color: #135754; outline: 2px solid #135754; }
.meta { color: #4a5551; font-size: .85rem; }
.state {
    display: inline-block; background: #e7ede5; color: #304642;
    padding: .1rem .45rem; border-radius: .2rem; font-size: .8rem;
}
.state[data-state="missing"], .state[data-state="stale"], .state[data-state="invalid"] {
    background: #f8e5ce; color: #723900;
}
ul { margin: .35rem 0 .65rem; padding-inline-start: 1.25rem; }
li + li { margin-top: .25rem; }
dl {
    display: grid; grid-template-columns: auto minmax(0, 1fr); gap: .2rem .8rem;
    margin: .6rem 0 0;
}
dt { color: #4a5551; }
dd { margin: 0; }
code { font-family: ui-monospace, monospace; font-size: .86em; }
@media (max-width: 45rem) {
    header, main { width: calc(100% - 1.75rem); }
    .columns {
        grid-template-columns: minmax(0, 1fr); grid-template-rows: auto;
        grid-template-areas: "features" "components" "tasks";
    }
}
"""


def _code(value: str) -> str:
    return f"<code>{escape(value)}</code>"


def _state(value: str) -> str:
    value = escape(value)
    return f'<span class="state" data-state="{value}">{value}</span>'


def _anchor(kind: str, value: str) -> str:
    return escape(f"{kind}-{value.replace('/', '-')}")


def _link(kind: str, value: str, label: str) -> str:
    return f'<a href="#{_anchor(kind, value)}">{escape(label)}</a>'


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"


def _architecture(row: ArchRow, labels: dict[str, str]) -> str:
    target = _code(row.ref)
    if row.target is not None and row.target in labels:
        target = f"{_link('component', row.target, labels[row.target])} {target}"
    return f"{target} · {escape(row.relation)} · {_state(row.state)} · {escape(row.provenance)}"


def _feature(row: FeatureRow, labels: dict[str, str], tasks: set[str]) -> str:
    stage = _state(row.state)
    if row.state != row.status:
        stage += f" · Intent {_state(row.status)}"
    entries = [
        f'<article id="{_anchor("feature", row.id)}" tabindex="-1">',
        f'<p class="meta">{_code(row.id)}</p>',
        f"<h3>{escape(row.title)}</h3>",
        f"<p>{stage}</p>",
    ]
    if row.outcome:
        entries.append(f"<p>{escape(row.outcome)}</p>")
    if row.architecture:
        entries.append("<p>Architecture</p>")
        entries.append(_list([_architecture(item, labels) for item in row.architecture]))
    if row.tasks:
        entries.append("<p>Tasks</p>")
        entries.append(
            _list(
                [
                    _link("task", key, key)
                    if key in tasks
                    else f"{_code(key)} · {_state('unverified')}"
                    for key in row.tasks
                ]
            )
        )
    return "".join(entries) + "</article>"


def _component(row: ComponentRow, labels: dict[str, str], features: list[FeatureRow]) -> str:
    review = "reviewed" if row.reviewed else "unreviewed"
    entries = [
        f'<article id="{_anchor("component", row.id)}" tabindex="-1">',
        f'<p class="meta">{_code(row.id)}</p>',
        f"<h3>{escape(row.label)}</h3>",
        f"<p>{escape(row.kind)} · {_state(row.provenance)}</p>",
    ]
    if row.parent is not None and row.parent in labels:
        entries.append(f"<p>Parent {_link('component', row.parent, labels[row.parent])}</p>")
    if row.owner:
        entries.append(f"<p>Owner {escape(row.owner)}</p>")
    if row.summary:
        entries.append(f"<p>{escape(row.summary)}</p>")
        if row.summary_provenance:
            entries.append(
                f'<p class="meta">Summary {escape(row.summary_provenance)} · {_state(review)}</p>'
            )
    if row.paths:
        entries.append("<p>Ownership paths</p>" + _list([_code(path) for path in row.paths]))
    if features:
        entries.append("<p>Linked features</p>")
        entries.append(_list([_link("feature", f.id, f.title) for f in features]))
    return "".join(entries) + "</article>"


def _task(row: TaskRow) -> str:
    evidence = []
    for rung in fields(row.evidence):
        refs = getattr(row.evidence, rung.name)
        value = _state(refs) if isinstance(refs, str) else ", ".join(map(_code, refs))
        evidence.append(f"<dt>{escape(rung.name.capitalize())}</dt><dd>{value}</dd>")
    return (
        f'<article id="{_anchor("task", row.id)}" tabindex="-1">'
        f'<p class="meta">{_code(row.id)}</p><h3>{escape(row.title)}</h3>'
        f"<p>{_state(row.state)}</p><dl>{''.join(evidence)}</dl></article>"
    )


def _sources(view: PlanningView) -> str:
    statuses = _list([f"{escape(row.label)} {_state(row.status)}" for row in view.sources])
    issues = [
        f"{_code(issue.path)}{_issue_field(issue.field)} · {escape(issue.message)}"
        for issue in view.issues
    ]
    details = "<h3>Input issues</h3>" + _list(issues) if issues else ""
    return f'<section id="sources"><h2>Sources</h2>{statuses}{details}</section>'


def _issue_field(field: str | None) -> str:
    return f" · {escape(field)}" if field else ""


def _section(key: str, title: str, rows: list[str]) -> str:
    contents = "".join(rows) or f"<p>No {title.lower()} recorded.</p>"
    return f'<section class="panel" id="{key}"><h2>{title}</h2>{contents}</section>'


def render(view: PlanningView) -> str:
    project = escape(view.project)
    labels = {row.id: row.label for row in view.components}
    tasks = {row.id for row in view.tasks}
    features = _section(
        "features", "Features", [_feature(row, labels, tasks) for row in view.features]
    )
    linked: dict[str, list[FeatureRow]] = defaultdict(list)
    for feature in view.features:
        for target in dict.fromkeys(link.target for link in feature.architecture):
            if target is not None:
                linked[target].append(feature)
    components = _section(
        "components",
        "Components",
        [_component(row, labels, linked[row.id]) for row in view.components],
    )
    progress = _section("tasks", "Tasks", [_task(row) for row in view.tasks])
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{project} planning</title><style>{_STYLE}</style></head>"
        f'<body><header><h1>{project} planning</h1><nav aria-label="Planning sections">'
        '<a href="#features">Features</a><a href="#components">Components</a>'
        '<a href="#tasks">Tasks</a><a href="#sources">Sources</a></nav></header>'
        f'<main><div class="columns">{features}{components}{progress}</div>'
        f"{_sources(view)}</main></body></html>"
    )
