"""Load offline pointers from Planning tasks to Codeman sessions or Meute jobs."""

import re
from collections.abc import Set
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from etat_major.components import MAX_PROJECT_ID_LENGTH
from etat_major.evidence_records import RecordedRef, RecordedTimestamp, TaskKey
from etat_major.localfiles import open_directory, read_text_kib
from etat_major.recorded_yaml import parse_bounded_yaml_mapping
from etat_major.refs import PROJECT_ID
from etat_major.taskfile import TaskFileError, first_error
from etat_major.text_safety import safe

EXECUTION_LINKS_LABEL = "Recorded execution links"
_Kind = Literal["codeman-session", "meute-job"]
_MAX_ROWS = 256
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_DNS_LABEL = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
_HOST = rf"(?:{_DNS_LABEL}(?:\.{_DNS_LABEL})*\.?|\[[a-fA-F0-9:.]+\])"
_ORIGIN = re.compile(rf"https://{_HOST}(?::[0-9]{{1,5}})?/?")


class _Link(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task: Annotated[TaskKey, Field(max_length=160)]
    kind: _Kind
    ref: RecordedRef
    seen_at: RecordedTimestamp

    @field_validator("ref")
    @classmethod
    def _session_ref(cls, value: str, info: ValidationInfo) -> str:
        if info.data.get("kind") == "codeman-session":
            if not _UUID.fullmatch(value):
                raise ValueError("expected a UUID-shaped Codeman session ID")
            return value.lower()
        return value


class _Snapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Annotated[StrictInt, Field(ge=1, le=1)]
    project: Annotated[
        StrictStr, Field(pattern=rf"^{PROJECT_ID}$", max_length=MAX_PROJECT_ID_LENGTH)
    ]
    links: Annotated[tuple[_Link, ...], Field(max_length=_MAX_ROWS)]


@dataclass(frozen=True)
class ExecutionLink:
    task: str
    kind: _Kind
    ref: str
    seen_at: str
    url: str | None


@dataclass(frozen=True)
class ExecutionLinks:
    version: Literal[1]
    project: str
    links: tuple[ExecutionLink, ...]


def codeman_origin(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        if len(value) > 300 or not _ORIGIN.fullmatch(value):
            raise ValueError
        origin = urlsplit(value)
        if origin.port == 0:
            raise ValueError
    except ValueError:
        raise TaskFileError(Path("serve"), "codeman-origin", "expected an HTTPS origin") from None
    return f"https://{origin.netloc.lower()}"


def _read_snapshot(path: Path) -> _Snapshot:
    try:
        with open_directory(path.parent) as fd:
            text = read_text_kib(path, 64, dir_fd=fd)
    except (OSError, ValueError):
        raise TaskFileError(path, "file", "expected a regular UTF-8 file up to 64 KiB") from None
    try:
        data = parse_bounded_yaml_mapping(
            text, path, field="snapshot", label="execution links", max_depth=3
        )
        return _Snapshot.model_validate(data)
    except ValidationError as exc:
        error = exc.errors(include_input=False, include_url=False)[0]
        if error["type"] in {"extra_forbidden", "invalid_key"}:
            raise TaskFileError(path, "snapshot", "unexpected snapshot field") from None
        raise first_error(path, error) from None
    except TaskFileError as exc:
        if (
            exc.field_name not in _Snapshot.model_fields
            and exc.field_name not in _Link.model_fields
        ):
            raise TaskFileError(path, "snapshot", "invalid snapshot mapping") from None
        raise


def load_execution_links(
    path: Path, *, project: str, tasks: Set[str], origin: str | None
) -> ExecutionLinks:
    snapshot = _read_snapshot(path)
    if snapshot.project != project:
        raise TaskFileError(path, "project", "expected the configured project")
    links: dict[tuple[_Kind, str], _Link] = {}
    for index, row in enumerate(snapshot.links):
        if row.task.partition("/")[0] != project or row.task not in tasks:
            raise TaskFileError(
                path, f"links.{index}.task", "expected an existing task in the configured project"
            )
        previous = links.setdefault((row.kind, row.ref), row)
        if previous != row:
            raise TaskFileError(path, f"links.{index}.ref", "conflicting execution link rows")
    return ExecutionLinks(
        1,
        safe(project),
        tuple(
            ExecutionLink(
                safe(row.task),
                row.kind,
                safe(row.ref),
                safe(row.seen_at),
                f"{origin}/session/{row.ref}" if origin and row.kind == "codeman-session" else None,
            )
            for row in links.values()
        ),
    )
