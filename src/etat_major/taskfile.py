"""Parse and validate task, project and initiative files (markdown + YAML frontmatter).

Contract: docs/contracts/task-file.md. Only intent statuses are valid in files.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from markdown_it import MarkdownIt, rules_inline
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from etat_major.localfiles import open_directory, read_text
from etat_major.refs import Ref, RefError, parse_ref
from etat_major.text_safety import bounded_repr, safe

INTENT_STATUSES = ("draft", "ready", "blocked", "done")
DERIVED_STATUSES = ("running", "needs-you", "review", "failed", "in-progress")

Text = Annotated[StrictStr, Field(min_length=1)]
MilestoneId = Annotated[StrictStr, Field(pattern=r"^[a-z0-9]+$")]


class TaskFileError(ValueError):
    """A file violates the contract; names the file and the offending field."""

    def __init__(
        self, path: Path, field: str | None, message: str, *, default_field: str = "file"
    ) -> None:
        self.path = path
        self.field = field
        self.message = message
        name = safe(path.name, limit=256)
        where = f"{name}: field '{safe(field or default_field, limit=80)}'"
        super().__init__(f"{where}: {safe(message, limit=512)}")


class _KeyError(Exception):
    def __init__(self, key: str, message: str) -> None:
        self.key = key
        self.message = message


class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps zero-padded numbers such as 0042 as strings
    and rejects merge keys and keys repeated within one mapping, either of
    which would let one value silently replace another before validation."""

    aliases = 0

    def compose_node(self, parent: yaml.Node | None, index: Any) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):
            self.aliases += 1
            if self.aliases > 64:
                raise _KeyError("frontmatter", "YAML frontmatter exceeds the 64-alias limit")
        return super().compose_node(parent, index)

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[str] = set()
        for key_node, value_node in node.value:
            line = key_node.start_mark.line + 1
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise _KeyError(
                    "<<", f"YAML merge key on frontmatter line {line}; write each field out"
                )
            if isinstance(key_node, yaml.ScalarNode):
                if key_node.value in seen:
                    raise _KeyError(
                        key_node.value,
                        f"duplicate key on frontmatter line {line}; write each key once",
                    )
                seen.add(key_node.value)
                if value_node.tag == "tag:yaml.org,2002:timestamp":
                    try:
                        self.construct_object(value_node, deep=deep)
                    except (AttributeError, ValueError, OverflowError) as exc:
                        raise _KeyError(key_node.value, "invalid YAML calendar date") from exc
        return super().construct_mapping(node, deep)


_Loader.yaml_implicit_resolvers = {
    k: [(t, r) for t, r in v if t != "tag:yaml.org,2002:int"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:int", re.compile(r"^[-+]?(?:0|[1-9][0-9]*)$"), list("-+0123456789")
)


class MarkdownRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    body: str = ""
    warnings: tuple[str, ...] = ()


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["pr", "test-run", "release"]
    ref: Text


def _id_text(value: Any) -> Any:
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else value


def _target_ref(value: Any) -> Ref:
    try:
        ref = parse_ref(value)
    except RefError:
        pass
    else:
        if ref.kind in ("fp:n", "fp:f", "trail"):
            return ref
    raise ValueError("expected a code reference (fp:n:, fp:f: or trail:)")


_TaskId = Annotated[StrictStr, Field(pattern=r"^[0-9]+$"), BeforeValidator(_id_text)]
_TargetRef = Annotated[Ref, BeforeValidator(_target_ref)]


def _calendar_date(value: Any) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError("expected an ISO calendar date (YYYY-MM-DD)")


CalendarDate = Annotated[date, BeforeValidator(_calendar_date)]


class Task(MarkdownRecord):
    id: _TaskId
    title: Text
    initiative: Text
    project: Text
    owner: Text
    status: Literal["draft", "ready", "blocked", "done"]
    priority: Annotated[StrictInt, Field(ge=1)] | None = None
    acceptance: tuple[Text, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    milestone: MilestoneId | None = None
    depends_on: tuple[_TaskId, ...] = ()
    targets: tuple[_TargetRef, ...] = ()
    accepted_by: Text | None = None
    accepted_on: CalendarDate | None = None

    @model_validator(mode="before")
    @classmethod
    def _check_task_fields(cls, meta: Any) -> Any:
        if not isinstance(meta, dict):
            return meta
        status = meta.get("status")
        violations = {}
        if "budget_tokens" in meta:
            violations["budget_tokens"] = "removed field; delete it from the task file"
        for field in ("accepted_by", "accepted_on"):
            if status == "done" and meta.get(field) is None:
                violations[field] = "required when status is done"
            elif status in ("draft", "ready", "blocked") and field in meta:
                violations[field] = "only allowed when status is done"
        if violations:
            raise ValidationError.from_exception_data(
                cls.__name__,
                [
                    {
                        "type": "value_error",
                        "loc": (field,),
                        "input": None,
                        "ctx": {"error": ValueError(message)},
                    }
                    for field, message in violations.items()
                ],
            )
        return meta

    @field_validator("accepted_by")
    @classmethod
    def _acceptance_author(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("expected a nonempty acceptance author")
        return value

    @field_validator("status", mode="before")
    @classmethod
    def _status_intent_only(cls, v: Any) -> Any:
        if v in DERIVED_STATUSES:
            raise ValueError(
                f"'{v}' is derived from runtime state and never written to a file; "
                f"use one of {', '.join(INTENT_STATUSES)}"
            )
        return v


class Project(MarkdownRecord):
    id: Text
    title: Text
    initiative: Text
    owner: Text
    repo: Text | None = None


class Initiative(MarkdownRecord):
    id: Text
    title: Text
    owner: Text
    target_date: date
    outcome: Text


def split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    """Return (frontmatter mapping, body)."""
    m = re.match(r"\A---[ \t]*\r?\n(.*?\r?\n)?---[ \t]*(?:\r?\n|\Z)", text, re.DOTALL)
    if not m:
        raise TaskFileError(
            path, None, "missing or unclosed YAML frontmatter", default_field="frontmatter"
        )
    try:
        meta = yaml.load(m.group(1) or "", Loader=_Loader)  # noqa: S506 - safe subclass
    except _KeyError as exc:
        raise TaskFileError(path, _field_name(exc.key), exc.message) from None
    # Explicit YAML scalar tags can fail inside their constructors.
    except (
        yaml.YAMLError,
        ValueError,
        LookupError,
        AttributeError,
        RecursionError,
        OverflowError,
    ):
        raise TaskFileError(path, "frontmatter", "invalid YAML frontmatter") from None
    if not isinstance(meta, dict):
        raise TaskFileError(path, "frontmatter", "frontmatter must be a YAML mapping")
    return meta, text[m.end() :]


_SCRIPT_URL = re.compile(r"\s*(?:javascript|vbscript|data):", re.IGNORECASE)
_URL_ATTR = {"link_open": "href", "image": "src"}


def _with_line(rule: Any) -> Any:
    """Wrap an inline rule so the token it emits records its line within the block."""

    def wrapped(state: Any, silent: bool) -> bool:
        pos, n = state.pos, len(state.tokens)
        ok = rule(state, silent)
        if ok and not silent:
            token = next(t for t in state.tokens[n:] if t.type != "text")
            token.meta = {"line": state.src.count("\n", 0, pos)}
        return bool(ok)

    return wrapped


_MD = MarkdownIt("commonmark")
_MD.validateLink = lambda url: True  # type: ignore[method-assign]  # keep script links as links
for _name, _rule in (
    ("html_inline", rules_inline.html_inline),
    ("link", rules_inline.link),
    ("image", rules_inline.image),
    ("autolink", rules_inline.autolink),
):
    _MD.inline.ruler.at(_name, _with_line(_rule))


def scan_markup(body: str) -> tuple[str, ...]:
    """Flag raw HTML and script links as a Markdown renderer would see them.

    One message per source line on which such markup starts.
    """
    lines: set[int] = set()
    for block in _MD.parse(body):
        if block.type == "html_block" and block.map:
            lines.add(block.map[0] + 1)
        for child in block.children or ():
            url = child.attrGet(_URL_ATTR.get(child.type, ""))
            if child.type == "html_inline" or (url and _SCRIPT_URL.match(str(url))):
                lines.add(block.map[0] + child.meta["line"] + 1)  # type: ignore[index]
    return tuple(f"line {n}: raw HTML or script markup in body" for n in sorted(lines))


def _brief(value: str) -> str:
    return value if len(value) <= 80 else value[:80] + "…"


def _field_name(value: str) -> str:
    if value == "<<" or re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", value):
        return _brief(value)
    return "frontmatter"


def first_error(path: Path, exc: ValidationError) -> TaskFileError:
    err = exc.errors(include_input=False, include_url=False)[0]
    field = _field_name(".".join(str(p) for p in err["loc"]))
    msg = err["msg"].removeprefix("Value error, ")
    return TaskFileError(path, field, msg)


def _read_markdown(path: Path, dir_fd: int | None) -> str:
    if dir_fd is not None:
        return read_text(path, 1, dir_fd=dir_fd)
    with open_directory(path.parent) as fd:
        return read_text(path, 1, dir_fd=fd)


def load_frontmatter_model[T: BaseModel](
    path: Path,
    model: type[T],
    *,
    filename_prefix: bool = False,
    include_body: bool = False,
    dir_fd: int | None = None,
) -> T:
    """Read and validate a bounded Markdown record with optional filename and body checks."""
    if include_body and "drafts" in path.parts:
        raise TaskFileError(
            path,
            "file",
            "files in a 'drafts' folder are native Backlog.md drafts, "
            "not task files; set status: draft on a normal task instead",
        )
    try:
        text = _read_markdown(path, dir_fd)
    except (OSError, ValueError) as exc:
        detail = exc.strerror if isinstance(exc, OSError) else str(exc)
        raise TaskFileError(
            path, None, f"cannot read file: {_brief(detail or 'I/O error')}"
        ) from None
    meta, body = split_frontmatter(text, path)
    if include_body:
        meta = {**meta, "body": body, "warnings": scan_markup(body)}
    try:
        record = model.model_validate(meta)
    except ValidationError as exc:
        raise first_error(path, exc) from None
    if filename_prefix:
        prefix = path.name.split("-", 1)[0].removesuffix(".md")
        if (ident := record.id) != prefix:
            raise TaskFileError(
                path,
                "id",
                f"id {bounded_repr(ident)} does not match filename prefix {bounded_repr(prefix)}",
            )
    return record


def _require_stem(path: Path, value: str, label: str) -> None:
    if value != path.stem:
        raise TaskFileError(path, "id", f"id must equal the filename ({label})")


def parse_task(path: Path, *, dir_fd: int | None = None) -> Task:
    return load_frontmatter_model(
        path, Task, filename_prefix=True, include_body=True, dir_fd=dir_fd
    )


def parse_project(path: Path) -> Project:
    project = load_frontmatter_model(path, Project, include_body=True)
    _require_stem(path, project.id, "without .md")
    return project


def parse_initiative(path: Path) -> Initiative:
    initiative = load_frontmatter_model(path, Initiative, include_body=True)
    _require_stem(path, initiative.id, "without .md")
    return initiative
