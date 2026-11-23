"""Scope and sanitize diagnostics in a Planning snapshot."""

from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import replace
from unicodedata import normalize

from etat_major.component_paths import component_file_path
from etat_major.refs import RefError, parse_ref
from etat_major.text_safety import public_text, safe
from etat_major.workspace import Issue

_PATH_PUNCTUATION = str.maketrans("%#", "__")


def planning_text(value: str, *, limit: int = 512, prose: bool = True) -> str:
    return safe(public_text(value, scp_remotes=prose), limit=limit)


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


def project_issue_filter(project: str, shared: Counter[str]) -> Callable[[Issue], bool]:
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
                return False
        return issue.path in exact_paths or issue.path.startswith(prefixes)

    return accept


def issue_summary(shared: Counter[str], omitted: int) -> Iterator[Issue]:
    for section, count in sorted(shared.items()):
        noun = "diagnostic" if count == 1 else "diagnostics"
        yield Issue(section, "records", f"{count} {noun} in shared {section}")
    if omitted:
        yield Issue("workspace", "records", f"{omitted} more project issues")
