"""Build a local Markdown prompt for manual research."""

import re
import stat
from html import escape
from pathlib import Path
from unicodedata import category, normalize

from etat_major.localfiles import open_directory, write_new_text
from etat_major.records import Feature, load_feature
from etat_major.refs import Ref, RefError, parse_ref
from etat_major.taskfile import TaskFileError
from etat_major.text_safety import safe
from etat_major.workspace import _entries, _IssueLog

_DIAGNOSTIC = Path("research brief")
_SENSITIVE = re.compile(
    r"""(?ix)
    # Absolute POSIX paths, drive-rooted paths, and UNC paths.
    (?<![\w/／∕])(?:[a-z]:[\\/／∕]|\\\\|~?[/／∕](?:[^\s)\]}>]|$))
    # Email addresses, DNS names, IP addresses, and common local host syntax.
    | [\w.+%\-]+@[\w\-]+
    | (?<![\w.。．｡-])(?!node[.。．｡]js(?![\w-]|[.。．｡][^\W_]))
        (?:[^\W_][\w-]*[.。．｡])+[^\W\d_]{2,}(?![\w-])
    | (?<!\d)(?:[0-9]{1,3}[.。．｡]){3}[0-9]{1,3}(?!\d)
    | (?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])
    | \blocalhost\b
    | \bhost(?:name)?\s*[:=]\s*["']?[a-z0-9][\w-]*
    | \bssh\s+[a-z0-9][\w-]*
    # Credential labels, common key formats, and private key headers.
    | \b(?:api[-_ ]?key|access[-_ ]?key|client[-_ ]?secret|password|passwd|token|secret)
        \s*["']?\s*(?:[:=]|\bis\b)\s*["']?\S+
    | \bbearer\s+[a-z0-9_.~+/-]{8,}
    | \bsk[-_][a-z0-9_-]+
    | \b(?:gh[pousr]|github_pat|glpat|xox[baprs])[-_][a-z0-9_-]{8,}
    | \b(?:akia|asia)[a-z0-9]{16}\b
    | -----begin\s+(?:[a-z]+\s+)*private\s+key-----
    | \b[a-z0-9_+/=-]{32,}\b
    """
)
_TEMPLATE = """## Sources

Search Reddit, GitHub issues, and official documentation.

## Answer format

Repeat the following block for each finding, numbering headings from 1.
Use a full HTTP(S) source URL and a publication date in YYYY-MM-DD format when available.
Use one listed value for Kind and Evidence. Include conflicting views and their URLs
when available, and describe anything you could not verify.
If a detail is missing, do not invent threads or citations; write not found instead.
Use one line per field. Return the blocks without an introduction or code fences.

~~~text
### F<n>
Claim:
Source URL:
Date:
Kind: reddit|github-issue|docs|article|store-review|other
Evidence: firsthand|author|secondhand|opinion|unverified
Conflicts:
Not verified:
~~~
"""


def _matches(path: Path, record_id: str) -> bool:
    return path.suffix == ".md" and path.stem.split("-", 1)[0] == record_id


def _select_file(project: Path, fd: int, record_id: str) -> Path:
    issues = _IssueLog()
    matches = []
    for path, mode in _entries(project, project, fd, issues):
        if _matches(path, record_id):
            if not stat.S_ISREG(mode):
                raise TaskFileError(_diagnostic_name(path), "file", "expected a regular file")
            matches.append(path)
    for issue in issues.issues:
        path = Path(issue.path)
        if issue.path == "." or _matches(path, record_id):
            raise TaskFileError(_diagnostic_name(path), "file", issue.message)
    if issues.omitted:
        raise TaskFileError(_DIAGNOSTIC, "feature", "too many invalid feature entries")
    if len(matches) != 1:
        detail = "unknown feature" if not matches else "feature reference is ambiguous"
        raise TaskFileError(_DIAGNOSTIC, "feature", detail)
    return matches[0]


def _contains_sensitive(value: str) -> bool:
    normalized = "".join(c for c in normalize("NFKC", value) if category(c) != "Cf")
    return bool(_SENSITIVE.search(value) or _SENSITIVE.search(normalized))


def _diagnostic_name(path: Path) -> Path:
    # Dots in the extension are expected. Check the caller-controlled stem.
    return _DIAGNOSTIC if _contains_sensitive(path.stem) else path


def _load_feature(workspace: Path, ref: Ref) -> tuple[Path, Feature]:
    project = Path(ref.project or "")
    with (
        open_directory(workspace) as root_fd,
        open_directory(Path("features"), root_fd) as features_fd,
        open_directory(project, features_fd) as project_fd,
    ):
        path = _select_file(project, project_fd, ref.id)
        try:
            feature = load_feature(path, dir_fd=project_fd)
        except TaskFileError as exc:
            field = exc.field or "file"
            if _contains_sensitive(field):
                field = "frontmatter"
            raise TaskFileError(_diagnostic_name(path), field, "invalid feature record") from None
    if feature.project != ref.project:
        raise TaskFileError(_diagnostic_name(path), "project", "does not match its directory")
    return path, feature


def _checked(path: Path, field: str, value: str) -> str:
    escaped = safe(value)
    if _contains_sensitive(value):
        raise TaskFileError(
            _diagnostic_name(path), field, "redaction check found sensitive content in brief"
        )
    return escape(escaped, quote=False)


def _render(path: Path, feature: Feature) -> str:
    context = [
        "# Research brief",
        "",
        "## Project context",
        "",
        f"- Project: {_checked(path, 'project', feature.project)}",
        f"- Feature: {_checked(path, 'title', feature.title)}",
    ]
    if feature.problem is not None:
        context.append(f"- Problem: {_checked(path, 'problem', feature.problem)}")
    if feature.outcome is not None:
        context.append(f"- Desired outcome: {_checked(path, 'outcome', feature.outcome)}")

    questions = list(feature.research_questions)
    if not feature.research_questions:
        if feature.problem:
            questions.append(f"What approaches address this problem? {feature.problem}")
        if feature.outcome:
            questions.append(f"What evidence shows this outcome is achievable? {feature.outcome}")
    if not questions:
        questions.append(f"What approaches exist for {feature.title}?")
    bullets = [f"- {_checked(path, 'research_questions', q)}" for q in questions]
    return "\n".join([*context, "", "## Questions", "", *bullets, "", _TEMPLATE])


def write_brief(reference: str, workspace: Path, out: Path) -> None:
    """Write a new brief after checking the selected Feature text for sensitive content."""
    try:
        ref = parse_ref(reference)
    except RefError:
        raise TaskFileError(_DIAGNOSTIC, "feature", "expected a feature reference") from None
    if ref.kind != "feature":
        raise TaskFileError(_DIAGNOSTIC, "feature", "expected a feature reference")
    try:
        path, feature = _load_feature(workspace, ref)
    except TaskFileError:
        raise
    except (OSError, ValueError):
        raise TaskFileError(_DIAGNOSTIC, "feature", "cannot open feature directory") from None
    brief = _render(path, feature)
    try:
        write_new_text(out, brief)
    except FileExistsError:
        raise TaskFileError(_diagnostic_name(out), "out", "brief output already exists") from None
    except (OSError, ValueError) as exc:
        detail = exc.strerror if isinstance(exc, OSError) else str(exc)
        raise TaskFileError(_diagnostic_name(out), "out", detail or "cannot create brief") from None
