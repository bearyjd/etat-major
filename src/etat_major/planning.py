"""Git-backed planning records and pure board column derivation."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StrictStr

from etat_major.refs import RefError, parse_ref
from etat_major.taskfile import (
    CalendarDate,
    MarkdownRecord,
    MilestoneId,
    Task,
    TaskFileError,
    Text,
    load_frontmatter_model,
)

BoardColumn = Literal["draft", "ready", "in-progress", "review", "done", "blocked"]


def _diagram_path(value: str) -> str:
    folder, _, filename = value.partition("/")
    if folder == "diagrams" and "/" not in filename and filename.endswith(".mmd"):
        try:
            parse_ref(f"fp:f:{value}")
            return value
        except RefError:
            pass
    raise ValueError("expected a workspace-relative diagrams/*.mmd path")


class Milestone(MarkdownRecord):
    id: MilestoneId
    title: Text
    target_date: CalendarDate | None = None
    horizon: Literal["now", "next", "later"]
    outcome: Text


class Vision(MarkdownRecord):
    project: Annotated[StrictStr, Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")]
    vision: Text
    goals: Annotated[tuple[Text, ...], Field(min_length=1)]
    diagrams: tuple[Annotated[StrictStr, AfterValidator(_diagram_path)], ...] = ()


def parse_milestone(path: Path, *, dir_fd: int | None = None) -> Milestone:
    return load_frontmatter_model(
        path, Milestone, filename_prefix=True, include_body=True, dir_fd=dir_fd
    )


def parse_vision(path: Path, *, dir_fd: int | None = None) -> Vision:
    vision = load_frontmatter_model(path, Vision, include_body=True, dir_fd=dir_fd)
    if vision.project != path.stem:
        raise TaskFileError(path, "project", "project must equal the filename stem")
    return vision


@dataclass(frozen=True)
class BoardEvidence:
    branch_open: bool = False
    pr_open_draft: bool = False
    pr_open_ready: bool = False
    pr_merged: bool = False


def derive_board_column(
    task: Task, dependency_states: Mapping[str, str], evidence: BoardEvidence | None = None
) -> BoardColumn:
    """Derive a column from accepted intent and project-local dependency statuses."""
    if task.status == "done":
        return "done"
    if any(dependency_states.get(dependency) != "done" for dependency in task.depends_on):
        return "blocked"
    return task.status
