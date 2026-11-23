"""Read État-major's bounded interchange format for recorded Meute reports."""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictStr, ValidationError

from etat_major.evidence_records import ArtifactRef, GeneratedArtifact, TaskKey, Timestamp
from etat_major.localfiles import open_directory, read_text_kib
from etat_major.recorded_yaml import parse_bounded_yaml_mapping
from etat_major.refs import PROJECT_ID
from etat_major.taskfile import TaskFileError, first_error
from etat_major.text_safety import safe

_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
_MAX_REPORTS = 256
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
_FIELDS = {
    "snapshot",
    "version",
    "project",
    "exported_at",
    "reports",
    "ref",
    "recorded_at",
    "outcome",
    "task",
}


def _timestamp(value: object) -> object:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError("expected an RFC 3339 timestamp with a time zone")
    return value


def _version(value: object) -> object:
    if type(value) is not int or value != 1:
        raise ValueError("only integer version 1 is supported")
    return value


def _report_limit(value: object) -> object:
    if not isinstance(value, list):
        raise ValueError("expected a sequence of report rows")
    if len(value) > _MAX_REPORTS:
        raise ValueError(f"expected at most {_MAX_REPORTS} report rows")
    return value


_RecordedAt = Annotated[Timestamp, BeforeValidator(_timestamp)]


class _Report(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: Annotated[ArtifactRef, Field(pattern=rf"^{_SEGMENT}(?:/{_SEGMENT})*$")]
    recorded_at: _RecordedAt
    outcome: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]
    task: Annotated[TaskKey, Field(max_length=160)] | None = None


class MeuteSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Annotated[Literal[1], BeforeValidator(_version)]
    project: Annotated[StrictStr, Field(pattern=rf"^{PROJECT_ID}$", max_length=128)]
    exported_at: _RecordedAt
    reports: Annotated[
        tuple[_Report, ...], Field(max_length=_MAX_REPORTS), BeforeValidator(_report_limit)
    ]


@dataclass(frozen=True)
class MeuteReportEvidence:
    ref: str
    recorded_at: str
    outcome: str
    task: str | None
    linked: bool


@dataclass(frozen=True)
class MeuteEvidence:
    version: Literal[1]
    project: str
    exported_at: str
    reports: tuple[MeuteReportEvidence, ...]

    def artifacts(self) -> tuple[GeneratedArtifact, ...]:
        return tuple(
            GeneratedArtifact(row.task, row.ref)
            for row in self.reports
            if row.linked and row.task is not None
        )


def _read_snapshot(path: Path) -> MeuteSnapshot:
    try:
        with open_directory(path.parent) as fd:
            text = read_text_kib(path, 256, dir_fd=fd)
    except (OSError, ValueError):
        raise TaskFileError(path, "file", "expected a regular UTF-8 file up to 256 KiB") from None
    try:
        data = parse_bounded_yaml_mapping(text, path, field="snapshot", label="Meute", max_depth=3)
        return MeuteSnapshot.model_validate(data)
    except ValidationError as exc:
        error = exc.errors(include_input=False, include_url=False)[0]
        if error["type"] in {"extra_forbidden", "invalid_key"}:
            raise TaskFileError(path, "snapshot", "unexpected snapshot field") from None
        raise first_error(path, error) from None
    except TaskFileError as exc:
        if exc.field_name not in _FIELDS:
            raise TaskFileError(path, "snapshot", "invalid snapshot mapping") from None
        raise


def load_meute(path: Path, *, project: str | None = None) -> MeuteSnapshot:
    snapshot = _read_snapshot(path)
    if project is not None and snapshot.project != project:
        raise TaskFileError(path, "project", "expected the configured project")
    reports: dict[str, _Report] = {}
    for index, row in enumerate(snapshot.reports):
        if row.recorded_at > snapshot.exported_at:
            raise TaskFileError(path, f"reports.{index}.recorded_at", "later than the snapshot")
        previous = reports.setdefault(row.ref, row)
        if previous is not row and previous.model_dump(mode="json") != row.model_dump(mode="json"):
            raise TaskFileError(path, f"reports.{index}.ref", "conflicting report rows")
    return snapshot.model_copy(update={"reports": tuple(reports.values())})


def _time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def resolve_meute(snapshot: MeuteSnapshot, known: frozenset[str]) -> MeuteEvidence:
    scoped = {key for key in known if key.partition("/")[0] == snapshot.project}
    rows = tuple(
        MeuteReportEvidence(
            safe(row.ref),
            _time(row.recorded_at),
            safe(row.outcome),
            safe(row.task) if row.task is not None else None,
            row.task in scoped,
        )
        for row in snapshot.reports
    )
    return MeuteEvidence(
        snapshot.version, safe(snapshot.project), _time(snapshot.exported_at), rows
    )
