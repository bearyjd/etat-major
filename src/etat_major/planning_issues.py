"""Scope and sanitize diagnostics in a Planning snapshot."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from hashlib import sha256
from unicodedata import normalize

from etat_major.component_paths import component_file_path
from etat_major.refs import RefError, parse_ref
from etat_major.text_safety import public_text, redact_escaped_locations, safe, safe_field
from etat_major.workspace import Issue

_REFRESH_ERROR_LIMIT = 512
_PATH_PUNCTUATION = str.maketrans("%#", "__")


def planning_text(
    value: str,
    *,
    limit: int = 512,
    prose: bool = True,
    multiline: bool = False,
    match_escaped: bool = False,
) -> str:
    """Redact and escape one payload field.

    ``prose`` selects the scp-remote redaction; ``multiline`` keeps line feeds.
    ``match_escaped`` also redacts matches that only the escaped form shows.
    """
    public = public_text(value, scp_remotes=prose)
    if match_escaped:
        public = redact_escaped_locations(public)
    return safe_field(public, multiline=multiline, limit=limit)


def planning_path(value: str) -> str:
    try:
        component_file_path(normalize("NFKC", value).translate(_PATH_PUNCTUATION))
    except ValueError:
        return "[redacted location]"
    return safe(value, limit=256)


def _issue_path(value: str) -> str:
    if value.startswith(("feature:", "task:", "milestone:")):
        try:
            parse_ref(value)
        except RefError:
            pass
        else:
            return safe(value, limit=256)
    return planning_path(value)


def public_issue(issue: Issue) -> Issue:
    return replace(
        issue,
        path=_issue_path(issue.path),
        field=planning_text(issue.field or "file", limit=80),
        message=planning_text(issue.message),
    )


@dataclass(frozen=True)
class RefreshDiagnostics:
    errors: tuple[bytes, ...]
    overflow: str | None

    def adds_errors(self, previous: RefreshDiagnostics) -> bool:
        return bool(Counter(self.errors) - Counter(previous.errors)) or (
            self.overflow is not None and self.overflow != previous.overflow
        )


class RefreshIssueLog:
    def __init__(self) -> None:
        self.errors: list[bytes] = []
        self.overflow = sha256()
        self.has_overflow = False

    def record(self, issue: Issue) -> None:
        if issue.severity != "error":
            return
        fingerprint = sha256(repr(issue).encode("utf-8", errors="surrogatepass")).digest()
        if len(self.errors) < _REFRESH_ERROR_LIMIT:
            self.errors.append(fingerprint)
        else:
            self.has_overflow = True
            self.overflow.update(fingerprint)

    def snapshot(self) -> RefreshDiagnostics:
        overflow = self.overflow.hexdigest() if self.has_overflow else None
        return RefreshDiagnostics(tuple(self.errors), overflow)


def project_issue_filter(
    project: str, shared: Counter[str], refresh: RefreshIssueLog
) -> Callable[[Issue], bool]:
    sections = ("features", "tasks", "milestones")
    folders = tuple(f"{section}/{project}" for section in sections)
    exact_paths = frozenset((*sections, *folders))
    prefixes = (
        *(f"{kind}:{project}/" for kind in ("feature", "task", "milestone")),
        *(folder + "/" for folder in folders),
    )

    def accept(issue: Issue) -> bool:
        for section, ref_prefix in (("decisions", "decision:"), ("research", "research:")):
            if issue.path == section or issue.path.startswith((section + "/", ref_prefix)):
                shared[section] += 1
                refresh.record(issue)
                return False
        belongs = issue.path in exact_paths or issue.path.startswith(prefixes)
        if belongs:
            refresh.record(issue)
        return belongs

    return accept


def issue_summary(shared: Counter[str], omitted: int) -> Iterator[Issue]:
    for section, count in sorted(shared.items()):
        noun = "diagnostic" if count == 1 else "diagnostics"
        yield Issue(section, "records", f"{count} {noun} in shared {section}")
    if omitted:
        yield Issue("workspace", "records", f"{omitted} more project issues")
