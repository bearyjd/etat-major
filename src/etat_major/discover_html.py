"""Server-rendered, read-only Discover page: research and decisions with provenance."""

from html import escape

from etat_major.discover_view import MAX_QUERY, DiscoverView, filter_decisions
from etat_major.planning_issues import planning_text

LIMIT = 256 * 1024
_STYLE = """
*{box-sizing:border-box}body{margin:0;background:#f7f7f2;color:#1e302b;
font:1rem/1.5 system-ui,sans-serif;overflow-wrap:anywhere}header,main{max-width:64rem;
margin:auto;padding:1rem}a{color:#064f56;text-underline-offset:.18em;display:inline-block;
padding:.25rem 0}a:focus-visible{outline:3px solid #945300;outline-offset:2px}
section,article{background:white;padding:1rem;border:1px solid #ccd4d0;
border-radius:.4rem;margin-bottom:1rem}h1,h2,h3,p{margin:.3em 0}li{margin:.3rem 0}
.badge{border:1px solid #1e302b;border-radius:.3rem;padding:0 .35rem;margin-right:.3rem;
font-size:.875rem}.notice{border-left:.3rem solid #945300;padding-left:.6rem}"""


def _t(text):
    return escape(planning_text(text))


def _badges(*values):
    return "".join(f'<span class="badge">{escape(v)}</span>' for v in values if v)


def _omitted(count, noun):
    return f'<p class="notice">{count} more {noun} omitted.</p>' if count else ""


def _finding(row):
    if row.unsourced:
        source = "no dated source"
    else:
        source = f"{escape(row.source or '[source redacted]')} · {row.source_date}"
    state = "unsourced" if row.unsourced else "sourced"
    return f"<li>{_badges(state)}{_t(row.text)} <small>{source}</small></li>"


def _research(row):
    project = escape(row.project) if row.project else "not linked to a project"
    features = ", ".join(map(escape, row.features)) or "none"
    return (
        f'<article id="research-{escape(row.id)}"><h3>{escape(row.id)} · {_t(row.title)}</h3>'
        f"<p>{_badges(row.status, row.provenance)} project: {project} · features: {features}</p>"
        f"<ul>{''.join(map(_finding, row.findings))}</ul>"
        f"{_omitted(row.omitted_findings, 'findings')}</article>"
    )


def _cite(row):
    cited = _badges(row.status, row.provenance)
    return f"<li>{_t(row.ref)} {_badges(row.state)}{cited}</li>"


def _decision(row):
    alternatives = "".join(
        f"<li>{_t(option)}: not chosen because {_t(why)}</li>" for option, why in row.alternatives
    )
    features = ", ".join(map(escape, row.features)) or "none"
    when = f" · decided {row.decided_on}" if row.decided_on else ""
    parts = [f'<article id="decision-{escape(row.id)}"><h3>{escape(row.id)} · {_t(row.question)}']
    parts.append(f"</h3><p>{_badges(row.status)}{when} · features: {features}</p>")
    if row.chosen:
        parts.append(f"<p>Chosen: {_t(row.chosen)}</p>")
    if row.rationale:
        parts.append(f"<p>Rationale: {_t(row.rationale)}</p>")
    if alternatives:
        parts.append(f"<h4>Alternatives</h4><ul>{alternatives}</ul>")
        parts.append(_omitted(row.omitted_alternatives, "alternatives"))
    if row.cites:
        parts.append(f"<h4>Cited research</h4><ul>{''.join(map(_cite, row.cites))}</ul>")
        parts.append(_omitted(row.omitted_cites, "citations"))
    return "".join(parts) + "</article>"


def _banner(view, stale):
    notes = []
    if stale:
        notes.append("Update unavailable. Showing the previous snapshot.")
    if view.issue_count:
        notes.append(f"{view.issue_count} records failed to load.")
    notes.append(
        "Research and decisions are not scoped to a project: all are shown with the project "
        "and features they link to. A citation badge only means the citation resolves, not "
        "that the research was reviewed. Review means a person edits the record file."
    )
    return "".join(f'<p class="notice">{escape(n)}</p>' for n in notes)


def _decisions(view):
    if view.decisions:
        body = "".join(map(_decision, view.decisions))
    elif view.query:
        body = "<p>No prior decision found for this query.</p>"
    else:
        body = "<p>No decisions recorded.</p>"
    query = f"<p>Filter: {_t(view.query)}</p>" if view.query else ""
    note = _omitted(view.omitted_decisions, "decisions") + (
        "<p>The filter searches the decisions shown here.</p>" if view.omitted_decisions else ""
    )
    return f"<section><h2>Decisions</h2>{query}{body}{note}</section>"


def render(view: DiscoverView, *, stale: bool = False) -> str:
    head = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Discover</title><style>{_STYLE}</style></head><body>"
        '<header><nav><a href="./planning">Planning</a></nav><h1>Discover</h1>'
        f"{_banner(view, stale)}</header>"
    )
    research = "".join(map(_research, view.research)) or "<p>No research recorded.</p>"
    html = (
        head
        + _decisions(view)
        + f"<section><h2>Research</h2>{research}{_omitted(view.omitted_research, 'research')}"
        + "</section></body></html>"
    )
    if len(html.encode()) >= LIMIT:
        return (
            head
            + "<main><p>Display truncated. Narrow the decisions with ?q=.</p></main></body></html>"
        )
    return html


def _query(params):
    if any(key != "q" for key in params):
        raise ValueError("unexpected parameter")
    values = params.getlist("q")
    if len(values) > 1:
        raise ValueError("repeated query")
    return values[0] if values else ""


def register(app, current, stale, headers):
    from fastapi import Request
    from fastapi.responses import HTMLResponse

    @app.get("/discover")
    def discover(request: Request):
        view = current()
        if view is None:
            return HTMLResponse("Discover snapshot unavailable.", status_code=404, headers=headers)
        try:
            filtered = filter_decisions(view, _query(request.query_params))
        except ValueError:
            return HTMLResponse(
                f"Invalid Discover query (at most {MAX_QUERY} printable characters). "
                '<a href="./discover">Return to Discover</a>',
                status_code=400,
                headers=headers,
            )
        return HTMLResponse(render(filtered, stale=stale()), headers=headers)
