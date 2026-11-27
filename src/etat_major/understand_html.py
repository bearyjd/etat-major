"""Bounded, server-rendered navigation through a single recorded code snapshot."""

from bisect import bisect_left
from dataclasses import dataclass
from html import escape
from urllib.parse import urlencode

from etat_major.components_seed import PROPOSAL_KIND
from etat_major.planning_issues import planning_text
from etat_major.understand import PAGE, TIES, UNOWNED, Understand, excerpt, token

LIMIT = 256 * 1024
_LEVELS = ("component", "file", "symbol")
_LISTS = ("components", "files", "symbols", "callers", "callees", "ties")
_STYLE = """
*{box-sizing:border-box}body{margin:0;background:#f7f7f2;color:#1e302b;
font:1rem/1.5 system-ui,sans-serif;overflow-wrap:anywhere}header,main{max-width:84rem;
margin:auto;padding:1rem}nav a,a{color:#064f56;text-underline-offset:.18em}
a{display:inline-block;padding:.25rem 0}a:focus-visible,[tabindex]:focus-visible{
outline:3px solid #945300;outline-offset:2px}section{background:white;padding:1rem;
border:1px solid #ccd4d0;border-radius:.4rem;margin-bottom:1rem;min-width:0}
h1,h2,h3,p{margin:.3em 0}li{margin:.3rem 0}pre{overflow:auto;max-width:100%;
background:#eff2ee;padding:.8rem;tab-size:4}main{display:grid;gap:1rem;
align-items:start}main>div{min-width:0}@media(min-width:50rem){
main{grid-template-columns:minmax(14rem,1fr) minmax(0,2fr)}}"""


def display(text, *, multiline=False):
    return escape(planning_text(text, multiline=multiline))


def _url(params, anchor=""):
    return "./understand?" + escape(urlencode(params)) + ("#" + anchor if anchor else "")


def _page(keys, key):
    return bisect_left(keys, key) // PAGE + 1


def component_href(view, key):
    ident = token("component", key)
    return _url({"component": ident, "components": _page(view.groups, key)}, ident)


@dataclass(frozen=True)
class Inspector:
    view: Understand
    selected: dict[str, str]
    pages: dict[str, int]

    def params(self):
        return {kind: token(kind, key) for kind, key in self.selected.items()} | self.pages

    def target(self, kind, key):
        if self.selected.get(kind) == key:
            return "#" + token(kind, key)
        if kind == "component":
            return component_href(self.view, key)
        path = key if kind == "file" else self.view.symbols[key].path
        group = self.view.owner[path]
        params = {
            "component": token("component", group),
            "components": _page(self.view.groups, group),
            "file": token("file", path),
            "files": _page(self.view.files[group], path),
        }
        if kind == "symbol":
            params.update(symbol=token(kind, key), symbols=self.view.symbol_pages[key])
        return _url(params, token(kind, key))

    def link(self, kind, key, label=None):
        return f'<a href="{self.target(kind, key)}">{display(label or key)}</a>'

    def listing(self, name, rows, render, empty):
        count = len(rows)
        pages = max(1, (count + PAGE - 1) // PAGE)
        page = min(self.pages.get(name, 1), pages)
        start = (page - 1) * PAGE
        items = "".join(f"<li>{render(row)}</li>" for row in rows[start : start + PAGE])
        links = []
        for label, number in (("Previous", page - 1), ("Next", page + 1)):
            if 1 <= number <= pages:
                href = _url(self.params() | {name: number}, "list-" + name)
                links.append(f'<a aria-label="{label} {name}" href="{href}">{label}</a>')
        return (
            f'<section id="list-{name}"><h2>{name.title()}</h2>'
            f"<p>{count} total · page {page} of {pages} {' · '.join(links)}</p>"
            + (f"<ul>{items}</ul>" if items else f"<p>{empty}</p>")
            + "</section>"
        )


def _selection(view, query):
    if any(key not in (*_LEVELS, *_LISTS) for key in query):
        raise ValueError
    selected, pages = {}, {}
    for key in query:
        values = query.getlist(key)
        if len(values) != 1:
            raise ValueError
        value = values[0]
        if key in _LEVELS:
            record = view.lookup.get(value)
            if record is None or record[0] != key:
                raise ValueError
            selected[key] = record[1]
        elif value.isascii() and value.isdigit() and 0 < len(value) <= 8 and int(value) > 0:
            pages[key] = int(value)
        else:
            raise ValueError
    if "file" in selected and view.owner[selected["file"]] != selected.get("component"):
        raise ValueError
    if "symbol" in selected and view.symbols[selected["symbol"]].path != selected.get("file"):
        raise ValueError
    return Inspector(view, selected, pages)


def _status(view):
    values = [
        f"{a.label}: {a.status} · {a.freshness} · snapshot {display(a.revision or 'unknown')}"
        for a in view.artifacts
    ]
    owned = len(view.owner) - len(view.files.get(UNOWNED, ())) - len(view.files.get(TIES, ()))
    if all(a.status != "present" for a in view.artifacts):
        values.append("File coverage unavailable.")
    else:
        values.append(f"Ownership coverage of recorded inventory: {owned} of {len(view.owner)}.")
    if view.unmatchable:
        values.append(
            f"{view.unmatchable} recorded paths outside the ownership grammar are unowned."
        )
    return "".join(f"<p>{value}</p>" for value in values)


def _heading(kind, key):
    return f'<h2 tabindex="-1" id="{token(kind, key)}">{display(key)}</h2>'


def _component(nav, key):
    row = nav.view.components.get(key)
    parts = [_heading("component", key)]
    if row:
        parts.append(f"<p>{display(row.label)} · {display(row.kind)}")
        parts.append(" · seeded proposal</p>" if row.kind == PROPOSAL_KIND else " · declared</p>")
        if row.parent in nav.view.components:
            parts.append(f"<p>Parent {nav.link('component', row.parent)}</p>")
        if (s := row.summary) is not None:
            review = (
                f"reviewed by {display(s.reviewed_by)} on {s.reviewed_on}"
                if s.reviewed_on
                else "unreviewed"
            )
            text = display(s.text, multiline=True)
            parts.append(f"<p>{text}</p><p>{display(s.provenance)} · {review}</p>")
    files = nav.view.files.get(key, ())
    return (
        "<section>"
        + "".join(parts)
        + "</section>"
        + nav.listing(
            "files",
            files,
            lambda path: nav.link("file", path),
            "No recorded files in this component.",
        )
    )


def _file(nav, path):
    result = "<section>" + _heading("file", path) + "</section>"
    if path in nav.view.ties:
        result += nav.listing(
            "ties", nav.view.ties[path], lambda key: nav.link("component", key), ""
        )
    symbols = sorted({s.id for s in nav.view.trail.symbols_in(path)}) if nav.view.trail else []
    return result + nav.listing(
        "symbols", symbols, lambda key: nav.link("symbol", key), "No matching recorded symbols."
    )


def _edges(nav, name, key):
    trail = nav.view.trail
    rows = trail.callers(key) if name == "callers" else trail.callees(key)
    endpoint = "source" if name == "callers" else "target"
    rows = sorted(rows, key=lambda e: (getattr(e, endpoint), e.source, e.target, e.confidence))

    def edge(row):
        other = getattr(row, endpoint)
        resolved = nav.view.symbols.get(other)
        label = (
            nav.link("symbol", other)
            if resolved and resolved.path in nav.view.owner
            else (display(other) + " · unresolved")
        )
        return f"{label} · {row.provenance} · confidence {display(row.confidence)}"

    return nav.listing(name, rows, edge, "No matching calls recorded in this artifact.")


def _symbol(nav, key):
    view = nav.view
    sym = view.symbols[key]
    text, note = excerpt(view.root, view.artifacts[1].freshness, sym)
    head = (
        f"<section>{_heading('symbol', key)}<p>{display(sym.kind)} · {sym.provenance}</p></section>"
    )
    body = f"<section><h2>Source excerpt</h2><p>{display(note)}</p>"
    if text:
        body += f"<pre><code>{escape(text)}</code></pre>"
    details = head + _edges(nav, "callers", key) + _edges(nav, "callees", key) + body + "</section>"
    return details, note


def render(nav):
    view = nav.view
    header = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Understand · {display(view.project)}</title><style>{_STYLE}</style></head><body>"
        '<header><nav><a href="./planning">Planning</a></nav>'
        f"<h1>{display(view.project)} · Understand</h1>"
        f"{_status(view)}</header>"
    )
    components = nav.listing(
        "components",
        view.groups,
        lambda k: nav.link("component", k),
        "No recorded component declarations.",
    )
    details = []
    note = ""
    for kind, draw in (("component", _component), ("file", _file)):
        if kind in nav.selected:
            details.append(draw(nav, nav.selected[kind]))
    if "symbol" in nav.selected:
        symbol, note = _symbol(nav, nav.selected["symbol"])
        details.append(symbol)
    if not details:
        details.append("<p>Select a component to inspect its recorded files.</p>")
    html = (
        header + "<main>" + components + "<div>" + "".join(details) + "</div></main></body></html>"
    )
    if len(html.encode()) >= LIMIT:
        selected = "".join(_heading(kind, key) for kind, key in nav.selected.items())
        html = (
            header
            + f"<main><div>{selected}<p>{display(note)}</p>"
            + "<p>Display truncated. Narrow the selection.</p>"
            + ('<a href="./understand">Return to components</a></div></main></body></html>')
        )
    return html


def register(app, current, headers):
    from fastapi import Request
    from fastapi.responses import HTMLResponse

    @app.get("/understand")
    def understand(request: Request):
        view = current()
        if view is None:
            return HTMLResponse(
                "Understand snapshot unavailable.", status_code=404, headers=headers
            )
        try:
            nav = _selection(view, request.query_params)
        except ValueError:
            return HTMLResponse(
                'Invalid Understand selection. <a href="./understand">Return to Understand</a>',
                status_code=400,
                headers=headers,
            )
        return HTMLResponse(render(nav), headers=headers)
