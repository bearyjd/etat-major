"""Read a local descriptor for a manually recorded Anthropic API review."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
)

from etat_major.evidence_records import RecordedRef, RecordedTimestamp, TaskKey
from etat_major.localfiles import open_directory, read_text_kib
from etat_major.recorded_yaml import parse_bounded_yaml_mapping
from etat_major.taskfile import TaskFileError, first_error
from etat_major.text_safety import public_text, safe

MANUAL_REVIEW_LABEL = "Manual Anthropic API review"
_SOURCE = Literal["manual-anthropic-api-review"]


class _Review(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Annotated[StrictInt, Field(ge=1, le=1)]
    source: _SOURCE
    task: Annotated[TaskKey, Field(max_length=160)]
    ref: RecordedRef
    recorded_at: RecordedTimestamp
    outcome: Annotated[StrictStr, Field(min_length=1, max_length=256, pattern=r"\S")]
    commit: Annotated[StrictStr, Field(pattern=r"^[0-9a-fA-F]{40}$")]
    report_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-fA-F]{64}$")]


@dataclass(frozen=True)
class ManualReview:
    version: int
    source: _SOURCE
    task: str
    ref: str
    recorded_at: str
    outcome: str
    commit: str
    report_sha256: str


def load_manual_review(path: Path, *, project: str, tasks: set[str]) -> ManualReview:
    try:
        with open_directory(path.parent) as fd:
            text = read_text_kib(path, 8, dir_fd=fd)
    except (OSError, ValueError):
        raise TaskFileError(path, "file", "expected a regular UTF-8 file up to 8 KiB") from None
    try:
        data = parse_bounded_yaml_mapping(
            text, path, field="review", label=MANUAL_REVIEW_LABEL, max_depth=1
        )
        record = _Review.model_validate(data)
    except ValidationError as exc:
        error = exc.errors(include_input=False, include_url=False)[0]
        if error["type"] in {"extra_forbidden", "invalid_key"}:
            raise TaskFileError(path, "review", "unexpected review field") from None
        raise first_error(path, error) from None
    except TaskFileError as exc:
        if exc.field_name not in _Review.model_fields:
            raise TaskFileError(path, "review", "invalid review mapping") from None
        raise
    if record.task.partition("/")[0] != project or record.task not in tasks:
        raise TaskFileError(path, "task", "expected an existing task in the configured project")
    outcome = safe(public_text(record.outcome, scp_remotes=True), limit=256)
    return ManualReview(**record.model_dump(exclude={"outcome"}), outcome=outcome)
