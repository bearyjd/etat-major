"""Parse and validate task, project and initiative files (markdown + YAML frontmatter).

Contract: docs/contracts/task-file.md. Only intent statuses are valid in files.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)

INTENT_STATUSES = ("draft", "ready", "blocked", "done")
DERIVED_STATUSES = ("running", "needs-you", "review", "failed")

Text = Annotated[StrictStr, Field(min_length=1)]


class TaskFileError(ValueError):
    """A file violates the contract; names the file and the offending field."""

    def __init__(self, path: Path, field: str | None, message: str) -> None:
        self.path = path
        self.field = field
        where = f"{path.name}: field '{field}'" if field else path.name
        super().__init__(f"{where}: {message}")


class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps zero-padded numbers such as 0042 as strings."""


_Loader.yaml_implicit_resolvers = {
    k: [(t, r) for t, r in v if t != "tag:yaml.org,2002:int"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:int", re.compile(r"^[-+]?(?:0|[1-9][0-9]*)$"), list("-+0123456789")
)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    body: str = ""
    warnings: tuple[str, ...] = ()


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["pr", "test-run", "release"]
    ref: Text


class Task(_Model):
    id: Annotated[str, Field(pattern=r"^[0-9]+$")]
    title: Text
    initiative: Text
    project: Text
    owner: Text
    status: Literal["draft", "ready", "blocked", "done"]
    priority: Annotated[StrictInt, Field(ge=1)] | None = None
    acceptance: tuple[Text, ...] = ()
    budget_tokens: Annotated[StrictInt, Field(gt=0)] | None = None
    evidence: tuple[Evidence, ...] = ()

    @field_validator("id", mode="before")
    @classmethod
    def _id_text(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int) and not isinstance(v, bool) else v

    @field_validator("status", mode="before")
    @classmethod
    def _status_intent_only(cls, v: Any) -> Any:
        if v in DERIVED_STATUSES:
            raise ValueError(
                f"'{v}' is derived from runtime state and never written to a file; "
                f"use one of {', '.join(INTENT_STATUSES)}"
            )
        return v


class Project(_Model):
    id: Text
    title: Text
    initiative: Text
    owner: Text
    repo: Text | None = None


class Initiative(_Model):
    id: Text
    title: Text
    owner: Text
    target_date: date
    outcome: Text


def split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    """Return (frontmatter mapping, body)."""
    m = re.match(r"\A---[ \t]*\r?\n(.*?\r?\n)?---[ \t]*(?:\r?\n|\Z)", text, re.DOTALL)
    if not m:
        raise TaskFileError(path, None, "missing or unclosed YAML frontmatter ('---' block)")
    try:
        meta = yaml.load(m.group(1) or "", Loader=_Loader)  # noqa: S506 - safe subclass
    except yaml.YAMLError as exc:
        raise TaskFileError(path, None, f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise TaskFileError(path, None, "frontmatter must be a YAML mapping")
    return meta, text[m.end() :]


_FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.DOTALL | re.MULTILINE)
_INLINE = re.compile(r"`[^`\n]*`")
_TAG = re.compile(r"</?[A-Za-z!][A-Za-z0-9-]*(?=[\s/>])[^>]*>|<!--")
_JS_URL = re.compile(r"\]\(\s*(?:javascript|vbscript|data):", re.IGNORECASE)


def scan_markup(body: str) -> tuple[str, ...]:
    """Flag raw HTML or script markup outside code spans; one message per line."""
    blanked = _FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), body)
    found = []
    for n, line in enumerate(blanked.splitlines(), 1):
        line = _INLINE.sub("", line)
        if _TAG.search(line) or _JS_URL.search(line):
            found.append(f"line {n}: raw HTML or script markup in body")
    return tuple(found)


def _first_error(path: Path, exc: ValidationError) -> TaskFileError:
    err = exc.errors()[0]
    field = ".".join(str(p) for p in err["loc"]) or None
    msg = err["msg"].removeprefix("Value error, ")
    return TaskFileError(path, field, msg)


def _load(path: Path, model: type[Any]) -> Any:
    if "drafts" in path.parts:
        raise TaskFileError(
            path,
            None,
            "files in a 'drafts' folder are native Backlog.md drafts, "
            "not task files; set status: draft on a normal task instead",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TaskFileError(path, None, f"cannot read file: {exc}") from exc
    meta, body = split_frontmatter(text, path)
    try:
        return model.model_validate({**meta, "body": body, "warnings": scan_markup(body)})
    except ValidationError as exc:
        raise _first_error(path, exc) from exc


def _require_stem(path: Path, value: str, label: str) -> None:
    if value != path.stem:
        raise TaskFileError(path, "id", f"id '{value}' must equal the filename ({label})")


def parse_task(path: Path) -> Task:
    task = _load(path, Task)
    prefix = path.name.split("-", 1)[0].removesuffix(".md")
    if task.id != prefix:
        raise TaskFileError(path, "id", f"id '{task.id}' does not match filename prefix '{prefix}'")
    return task


def parse_project(path: Path) -> Project:
    project = _load(path, Project)
    _require_stem(path, project.id, "without .md")
    return project


def parse_initiative(path: Path) -> Initiative:
    initiative = _load(path, Initiative)
    _require_stem(path, initiative.id, "without .md")
    return initiative
