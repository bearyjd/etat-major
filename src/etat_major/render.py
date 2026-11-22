"""Plain-text rendering of a Trace. Deterministic: same input, same bytes."""

from __future__ import annotations

from etat_major.text_safety import public_text, safe
from etat_major.trace import DecisionLine, ResearchLine, Trace


def _research(r: ResearchLine) -> list[str]:
    lines = [safe(f"  {r.ref}  {r.status}  {r.provenance}  {public_text(r.title)}").rstrip()]
    for f in r.findings:
        flag = "unsourced" if f.unsourced else "sourced"
        src = f" ({f.source})" if f.source else ""
        lines.append(f"    {f.id}  {flag}  {f.provenance}  {public_text(f.text)}{src}")
    return lines


def _decision(d: DecisionLine) -> list[str]:
    lines = [
        safe(
            f"  {d.ref}  {d.status}  {d.relation}  {d.provenance}  {public_text(d.question)}"
        ).rstrip()
    ]
    lines += [f"    cites {c.ref}  {c.state}" for c in d.cites]
    return lines


def render_trace(trace: Trace) -> str:
    f = trace.feature
    out = [f"feature:{f.project}/{f.id}  {f.status}  human  {public_text(f.title)}"]
    if f.outcome:
        out.append(f"  outcome: {public_text(f.outcome)}")
    out.append("RESEARCH")
    out += [line for r in trace.research for line in _research(r)] or ["  (none)  unverified"]
    out.append("DECISIONS")
    out += [line for d in trace.decisions for line in _decision(d)] or ["  (none)  unverified"]
    out.append("ARCHITECTURE")
    out += [
        f"  {public_text(str(a.ref))}  {a.relation}  {a.state}  {a.provenance}"
        for a in trace.architecture
    ]
    if not trace.architecture:
        out.append("  (none)  unverified")
    out.append("ACCEPTANCE")
    out += [
        f"  {public_text(a.id)}  {a.state}  {a.provenance}  {public_text(a.text)}"
        for a in trace.acceptance
    ]
    if trace.links:
        out.append("TASKS AND MILESTONES")
        out += [f"  {link.ref}  {link.state}" for link in trace.links]
    if trace.warnings:
        out.append("WARNINGS")
        out += [f"  {public_text(w)}" for w in trace.warnings]
    return "\n".join(map(safe, out)) + "\n"
