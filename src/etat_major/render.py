"""Plain-text rendering of a Trace. Deterministic: same input, same bytes."""

from __future__ import annotations

from etat_major.text_safety import safe
from etat_major.trace import DecisionLine, ResearchLine, Trace


def _research(r: ResearchLine) -> list[str]:
    lines = [safe(f"  {r.ref}  {r.status}  {r.provenance}  {r.title}").rstrip()]
    for f in r.findings:
        flag = "unsourced" if f.unsourced else "sourced"
        src = f" ({f.source})" if f.source else ""
        lines.append(f"    {f.id}  {flag}  {f.provenance}  {f.text}{src}")
    return lines


def _decision(d: DecisionLine) -> list[str]:
    lines = [safe(f"  {d.ref}  {d.status}  {d.relation}  {d.provenance}  {d.question}").rstrip()]
    lines += [f"    cites {c.ref}  {c.state}" for c in d.cites]
    return lines


def render_trace(trace: Trace) -> str:
    f = trace.feature
    out = [f"feature:{f.project}/{f.id}  {f.status}  human  {f.title}"]
    if f.outcome:
        out.append(f"  outcome: {f.outcome}")
    out.append("RESEARCH")
    out += [line for r in trace.research for line in _research(r)] or ["  (none)  unverified"]
    out.append("DECISIONS")
    out += [line for d in trace.decisions for line in _decision(d)] or ["  (none)  unverified"]
    out.append("ARCHITECTURE")
    out += [f"  {a.ref}  {a.relation}  {a.state}  {a.provenance}" for a in trace.architecture]
    if not trace.architecture:
        out.append("  (none)  unverified")
    out.append("ACCEPTANCE")
    out += [f"  {a.id}  {a.state}  {a.provenance}  {a.text}" for a in trace.acceptance]
    if trace.links:
        out.append("TASKS AND MILESTONES")
        out += [f"  {link.ref}  {link.state}" for link in trace.links]
    if trace.warnings:
        out.append("WARNINGS")
        out += [f"  {w}" for w in trace.warnings]
    return "\n".join(map(safe, out)) + "\n"
