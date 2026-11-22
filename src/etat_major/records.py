"""Strict models and loaders for ResearchArtifact, Decision and Feature files.

Contract: docs/TRACEABILITY.md. Only stored intent is accepted: derived values
(``unsourced``, lifecycle stages past ``planned``) are computed elsewhere, never read here.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from etat_major.refs import Ref, parse_ref
from etat_major.taskfile import TaskFileError, _first_error, split_frontmatter

Text = Annotated[StrictStr, Field(min_length=1)]
RecordId = Annotated[str, Field(pattern=r"^[0-9]+$")]
Url = Annotated[StrictStr, Field(pattern=r"^https?://\S+$")]
DERIVED_FEATURE_STATUSES = (
    "approved",
    "rejected",
    "postponed",
    "implementing",
    "verified",
    "released",
)
STORED_FEATURE_STATUSES = ("idea", "researching", "proposed", "planned")
DECIDED_STATUSES = ("approved", "rejected", "postponed")
CODE_KINDS = ("fp:n", "fp:f", "trail")


def _ref_of(*kinds: str, label: str) -> Any:
    def parse(value: Any) -> Ref:
        ref = parse_ref(value)
        if ref.kind not in kinds:
            raise ValueError(f"expected a {label} reference, got {value!r}")
        return ref

    return Annotated[Ref, BeforeValidator(parse)]


ResearchRef = _ref_of("research", label="research")
DecisionRef = _ref_of("decision", label="decision")
FeatureRef = _ref_of("feature", label="feature")
TaskRef = _ref_of("task", label="task")
MilestoneRef = _ref_of("milestone", label="milestone")
CodeRef = _ref_of(*CODE_KINDS, label="code (fp:n:, fp:f: or trail:)")


def _id_text(v: Any) -> Any:
    return str(v) if isinstance(v, int) and not isinstance(v, bool) else v


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Identified(_Record):
    id: Annotated[RecordId, BeforeValidator(_id_text)]


class Source(_Record):
    url: Url
    date: date
    kind: Literal["reddit", "github-issue", "docs", "article", "store-review", "other"] | None = (
        None
    )
    evidence: Literal["firsthand", "author", "secondhand", "opinion", "unverified"] | None = None


class Finding(_Record):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$")]
    text: Text
    source: Url | None = None
    evidence: Literal["firsthand", "author", "secondhand", "opinion", "unverified"] | None = None
    confidence: Literal["low", "medium", "high"] | None = None

    @field_validator("evidence")
    @classmethod
    def _unsourced_means_unverified(cls, v: Any, info: ValidationInfo) -> Any:
        if v not in (None, "unverified") and info.data.get("source") is None:
            raise ValueError("a finding without a source may only have evidence 'unverified'")
        return v


class ResearchArtifact(_Identified):
    title: Text
    status: Literal["unreviewed", "reviewed", "superseded"]
    provenance: Literal["verified", "inferred", "ai-generated", "human"]
    sources: Annotated[tuple[Source, ...], Field(min_length=1)]
    findings: tuple[Finding, ...] = ()
    question: Text | None = None
    unresolved: tuple[Text, ...] = ()

    def is_unsourced(self, finding: Finding) -> bool:
        """Computed, never stored: no source URL, or one that is not a dated source here."""
        return finding.source is None or finding.source not in {s.url for s in self.sources}


class Alternative(_Record):
    option: Text
    why_not: Text


class Decision(_Identified):
    question: Text
    status: Literal["proposed", "approved", "rejected", "postponed", "superseded"]
    decided_on: date | None = None
    decided_by: Annotated[Literal["human"] | None, Field(validate_default=True)] = None
    chosen: Text | None = None
    rationale: Text | None = None
    alternatives: tuple[Alternative, ...] = ()
    evidence: tuple[ResearchRef, ...] = ()
    features: tuple[FeatureRef, ...] = ()

    @field_validator("decided_by")
    @classmethod
    def _decided_requires_human(cls, v: Any, info: ValidationInfo) -> Any:
        status = info.data.get("status")
        if status in DECIDED_STATUSES and v != "human":
            raise ValueError(f"status '{status}' requires decided_by: human")
        return v


class Acceptance(_Record):
    id: Text
    text: Text


class ArchitectureLink(_Record):
    ref: CodeRef
    relation: Literal["new", "modifies", "uses"]


class Feature(_Identified):
    project: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")]
    title: Text
    status: Literal["idea", "researching", "proposed", "planned"]
    problem: Text | None = None
    outcome: Text | None = None
    priority: Annotated[StrictInt, Field(ge=1)] | None = None
    research: tuple[ResearchRef, ...] = ()
    decisions: tuple[DecisionRef, ...] = ()
    milestones: tuple[MilestoneRef, ...] = ()
    tasks: tuple[TaskRef, ...] = ()
    acceptance: tuple[Acceptance, ...] = ()
    architecture: tuple[ArchitectureLink, ...] = ()

    @field_validator("status", mode="before")
    @classmethod
    def _stored_status_only(cls, v: Any) -> Any:
        if v in DERIVED_FEATURE_STATUSES:
            raise ValueError(
                f"'{v}' is derived from the linked Decision or from Git evidence and is never "
                f"written to a feature file; use one of {', '.join(STORED_FEATURE_STATUSES)}"
            )
        return v


def _load[T: _Identified](path: Path, model: type[T]) -> T:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TaskFileError(path, None, f"cannot read file: {exc}") from exc
    meta, _body = split_frontmatter(text, path)
    try:
        record = model.model_validate(meta)
    except ValidationError as exc:
        raise _first_error(path, exc) from exc
    prefix = path.name.split("-", 1)[0].removesuffix(".md")
    if record.id != prefix:
        raise TaskFileError(
            path, "id", f"id '{record.id}' does not match filename prefix '{prefix}' (filename)"
        )
    return record


def load_research(path: Path) -> ResearchArtifact:
    return _load(path, ResearchArtifact)


def load_decision(path: Path) -> Decision:
    return _load(path, Decision)


def load_feature(path: Path) -> Feature:
    return _load(path, Feature)
