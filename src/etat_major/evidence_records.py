"""Read bounded, recorded GitHub evidence and resolve task link keys."""

import json
import re
from collections.abc import Set
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
)

from etat_major.localfiles import open_directory, read_text
from etat_major.taskfile import TaskFileError, check_recorded_array, first_error
from etat_major.text_safety import is_control

_TASK_KEY = r"[a-z0-9][a-z0-9_-]*/[0-9]+"
_KEY = re.compile(_TASK_KEY)
_BODY_LINK = re.compile(rf"^[ \t]*Task:[ \t]*({_TASK_KEY})[ \t]*$", re.MULTILINE)
_BRANCH_ID = re.compile(r"-([0-9]+)(?=-.)")
_BRANCH_PREFIX = re.compile(r"[a-z0-9][a-z0-9_-]*")
OID_PATTERN = r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"
Oid = Annotated[StrictStr, Field(pattern=OID_PATTERN)]
TaskKey = Annotated[StrictStr, Field(pattern=rf"^{_TASK_KEY}$")]


def _relative_identifier(value: str) -> str:
    if any(part in {"", ".", ".."} for part in value.split("/")) or any(
        char in ":\\@" or is_control(char) for char in value
    ):
        raise ValueError("expected a relative identifier")
    return value


def _tag(value: str) -> str:
    if (
        any(part.startswith(".") or part.endswith(".lock") for part in value.split("/"))
        or ".." in value
        or value.endswith(".")
        or any(char.isspace() or char in "~^?*[" for char in value)
    ):
        raise ValueError("expected a Git tag name")
    return _relative_identifier(value)


def _timestamp(value: object) -> object:
    if not isinstance(value, str):
        raise ValueError("expected a timestamp string")
    return value


Timestamp = Annotated[AwareDatetime, BeforeValidator(_timestamp)]
TagName = Annotated[StrictStr, Field(max_length=255), AfterValidator(_tag)]
ArtifactRef = Annotated[StrictStr, Field(max_length=512), AfterValidator(_relative_identifier)]


class _Recorded(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class GeneratedArtifact(BaseModel):
    """A caller-supplied Meute artifact descriptor, with a task key and relative reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    task: TaskKey
    ref: ArtifactRef

    def __init__(self, task: str, ref: str) -> None:
        super().__init__(task=task, ref=ref)


class CommitRef(_Recorded):
    oid: Oid


class CheckRun(_Recorded):
    kind: Literal["CheckRun"] = Field(alias="__typename")
    status: StrictStr
    conclusion: StrictStr | None
    commit_oid: Oid | None = Field(default=None, alias="commitOid")

    @property
    def passed(self) -> bool:
        return self.status == "COMPLETED" and self.conclusion == "SUCCESS"


class StatusContext(_Recorded):
    kind: Literal["StatusContext"] = Field(alias="__typename")
    state: StrictStr
    commit_oid: Oid | None = Field(default=None, alias="commitOid")

    @property
    def passed(self) -> bool:
        return self.state == "SUCCESS"


Check = Annotated[CheckRun | StatusContext, Field(discriminator="kind")]


class PullRequest(_Recorded):
    number: Annotated[StrictInt, Field(gt=0)]
    title: StrictStr
    body: StrictStr
    state: Literal["OPEN", "CLOSED", "MERGED"]
    is_draft: StrictBool = Field(alias="isDraft")
    merged_at: Timestamp | None = Field(alias="mergedAt")
    head: StrictStr = Field(alias="headRefName")
    review_decision: Literal["", "APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED"] | None = Field(
        alias="reviewDecision"
    )
    checks: tuple[Check, ...] | None = Field(alias="statusCheckRollup")
    merge_commit: CommitRef | None = Field(alias="mergeCommit")
    head_oid: Oid | None = Field(default=None, alias="headRefOid")


class Release(_Recorded):
    tag: TagName = Field(alias="tagName")
    published_at: Timestamp | None = Field(alias="publishedAt")


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("invalid JSON constant")


def _load_rows[T: BaseModel](path: Path, adapter: TypeAdapter[tuple[T, ...]]) -> tuple[T, ...]:
    try:
        with open_directory(path.parent) as fd:
            raw = read_text(path, 4, dir_fd=fd)
    except (OSError, ValueError) as exc:
        detail = exc.strerror if isinstance(exc, OSError) else "expected bounded UTF-8 regular file"
        raise TaskFileError(path, "file", detail or "cannot read input") from None
    try:
        data = json.loads(raw, object_pairs_hook=_json_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise TaskFileError(path, "json", "expected valid JSON with unique keys") from None
    check_recorded_array(path, "json", data)
    if isinstance(data, list) and adapter is _PR_ROWS:
        for index, row in enumerate(data):
            if isinstance(row, dict):
                field = "statusCheckRollup"
                check_recorded_array(path, f"{index}.{field}", row.get(field))
    try:
        return adapter.validate_python(data)
    except ValidationError as exc:
        location = first_error(path, exc)
        raise TaskFileError(path, location.field or "json", "invalid recorded value") from None


_PR_ROWS = TypeAdapter(tuple[PullRequest, ...])


def load_prs(path: Path) -> tuple[PullRequest, ...]:
    rows = _load_rows(path, _PR_ROWS)
    seen = set()
    for index, row in enumerate(rows):
        if row.number in seen:
            raise TaskFileError(path, f"{index}.number", "duplicate pull request number")
        seen.add(row.number)
    return rows


def load_releases(path: Path) -> tuple[Release, ...]:
    return _load_rows(path, TypeAdapter(tuple[Release, ...]))


def branch_task(branch: str, known: Set[str]) -> str | None:
    if len(branch) > 255 or not branch.startswith("task/") or any(c in branch for c in "\r\n"):
        return None
    name = branch.removeprefix("task/")
    prefix = _BRANCH_PREFIX.match(name)
    if prefix is None:
        return None
    first = known_key = None
    ambiguous = False
    for match in _BRANCH_ID.finditer(name):
        if match.end() > prefix.end():
            break
        key = f"{name[:match.start()]}/{match[1]}"
        ambiguous |= first is not None
        first = first or key
        if key in known:
            if known_key is not None:
                return None
            known_key = key
    return known_key or (None if ambiguous else first)


def resolve_task_keys(
    *,
    trailers: tuple[str, ...] = (),
    branch: str = "",
    body: str = "",
    known: Set[str] = frozenset(),
) -> tuple[str, ...]:
    """Return all keys at the highest-priority source that supplies a valid key."""
    if keys := tuple(dict.fromkeys(value for value in trailers if _KEY.fullmatch(value))):
        return keys
    if key := branch_task(branch, known):
        return (key,)
    return tuple(dict.fromkeys(_BODY_LINK.findall(body.replace("\r\n", "\n"))))
