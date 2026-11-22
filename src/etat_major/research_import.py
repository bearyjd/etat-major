"""Turn a pasted research answer into an unreviewed local artifact."""

import os
import re
from datetime import date
from itertools import islice
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from etat_major.localfiles import open_directory, read_text, write_new_text
from etat_major.records import Evidence, Finding, ResearchArtifact, Source, SourceKind, Text, Url
from etat_major.taskfile import TaskFileError, first_error
from etat_major.text_safety import is_control

_FIELDS = {
    "claim": "Claim",
    "url": "Source URL",
    "date": "Date",
    "kind": "Kind",
    "evidence": "Evidence",
    "conflicts": "Conflicts",
    "not_verified": "Not verified",
}
_FINDING_ID = r"F[1-9][0-9]*"
_HUMAN_ONLY = re.compile(r"\b(?:approved|reviewed|decided_by|accepted_by|accepted_on)\b", re.I)


class _AnswerFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim: Text
    url: Url | None
    date: date | None
    kind: SourceKind
    evidence: Evidence
    conflicts: str | None
    not_verified: str | None

    @field_validator("url")
    @classmethod
    def _valid_host(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                parsed = urlsplit(value)
                host, _port = parsed.hostname, parsed.port
            except ValueError:
                host = None
            if not host or "\\" in value:
                raise ValueError("expected an HTTP(S) URL with a valid host and optional port")
        return value

    @field_validator("date", mode="before")
    @classmethod
    def _iso_date(cls, value: str | None) -> date | None:
        if value is None:
            return None
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("expected a date in YYYY-MM-DD format")
        return date.fromisoformat(value)

    def source(self) -> Source | None:
        if self.url is None or self.date is None:
            return None
        return Source(url=self.url, date=self.date, kind=self.kind, evidence=self.evidence)


def _field_value(path: Path, lines: list[str], index: int, field: str) -> str:
    prefix = f"{field}:"
    if index >= len(lines) or not lines[index].startswith(prefix):
        raise TaskFileError(path, field, f"line {index + 1}: expected {prefix}")
    text = lines[index][len(prefix) :]
    if any(map(is_control, text)):
        raise TaskFileError(path, field, f"line {index + 1}: control characters are forbidden")
    if "<" in text or ">" in text:
        raise TaskFileError(path, field, f"line {index + 1}: angle brackets are forbidden")
    if _HUMAN_ONLY.search(text):
        raise TaskFileError(path, field, f"line {index + 1}: human-only entries are forbidden")
    return text.strip()


def _parse_block(path: Path, lines: list[str], index: int) -> _AnswerFinding:
    data = {}
    for name, field in _FIELDS.items():
        index += 1
        value = _field_value(path, lines, index, field)
        data[name] = (
            None
            if name in {"url", "date", "conflicts", "not_verified"} and (value in {"", "not found"})
            else value
        )
    try:
        return _AnswerFinding.model_validate(data)
    except ValidationError as exc:
        error = first_error(path, exc)
        field = error.field or "claim"
        line = index - len(_FIELDS) + 2 + list(_FIELDS).index(field)
        raise TaskFileError(path, _FIELDS[field], f"line {line}: {error.message}") from None


def _parse_answer(path: Path, text: str) -> dict[str, tuple[int, _AnswerFinding]]:
    lines = text.split("\n")
    blocks = {}
    index = 0
    while index < len(lines):
        if not lines[index].strip(" "):
            index += 1
            continue
        heading = re.fullmatch(rf"### ({_FINDING_ID})", lines[index])
        if not heading:
            raise TaskFileError(path, "heading", f"line {index + 1}: expected ### F<n>")
        record_id = heading[1].lower()
        if record_id in blocks:
            raise TaskFileError(path, "heading", f"line {index + 1}: duplicate finding ID")
        blocks[record_id] = (index + 1, _parse_block(path, lines, index))
        index += len(_FIELDS) + 1
    if not blocks:
        raise TaskFileError(path, "heading", "line 1: expected at least one finding")
    return blocks


def _conflict_refs(text: str | None) -> tuple[str, ...]:
    if text and re.fullmatch(rf"{_FINDING_ID}(?:, *{_FINDING_ID})*", text):
        return tuple(dict.fromkeys(part.strip().lower() for part in text.split(",")))
    return ()


def _artifact(path: Path, record_id: str, text: str) -> ResearchArtifact:
    blocks = _parse_answer(path, text)
    sources, findings, unresolved = {}, [], []
    for finding_id, (line, block) in blocks.items():
        source = block.source()
        if source:
            sources.setdefault((source.url, source.date, source.kind, source.evidence), source)
        conflicts = _conflict_refs(block.conflicts)
        if any(ref == finding_id or ref not in blocks for ref in conflicts):
            raise TaskFileError(
                path, "Conflicts", f"line {line + 6}: expected IDs of other findings"
            )
        if block.conflicts and not conflicts:
            unresolved.append(f"{finding_id} conflicts: {block.conflicts}")
        if block.not_verified:
            unresolved.append(f"{finding_id}: {block.not_verified}")
        findings.append(
            Finding(
                id=finding_id,
                text=block.claim,
                source=block.url,
                source_date_missing=True if block.url and not block.date else None,
                evidence=block.evidence if source else "unverified",
                conflicts_with=conflicts,
            )
        )
    return ResearchArtifact(
        id=record_id,
        title="ChatGPT research",
        status="unreviewed",
        provenance="ai-generated",
        collected_by="chatgpt",
        sources=tuple(sources.values()),
        findings=tuple(findings),
        unresolved=tuple(unresolved),
    )


def _read_answer(path: Path) -> str:
    try:
        with open_directory(path.parent) as fd:
            return read_text(path, 1, dir_fd=fd)
    except (OSError, ValueError) as exc:
        detail = exc.strerror if isinstance(exc, OSError) else str(exc)
        raise TaskFileError(path, "file", detail or "cannot read answer") from None


def _write_artifact(workspace: Path, out: Path, research_id: str, text: str) -> None:
    try:
        with open_directory(workspace) as root:
            try:
                os.mkdir("research", dir_fd=root)
            except FileExistsError:
                pass
            with open_directory(Path("research"), root) as fd:
                with os.scandir(fd) as entries:
                    names = [entry.name for entry in islice(entries, 2001)]
                if len(names) > 2000:
                    raise ValueError("research directory exceeds 2000 entries")
                if any(
                    name.endswith(".md") and name[:-3].split("-", 1)[0] == research_id
                    for name in names
                ):
                    raise FileExistsError
                write_new_text(out, text, dir_fd=fd)
    except FileExistsError:
        raise TaskFileError(out, "id", "a research file with this ID already exists") from None
    except (OSError, ValueError) as exc:
        detail = exc.strerror if isinstance(exc, OSError) else str(exc)
        raise TaskFileError(out, "file", detail or "cannot write artifact") from None


def import_answer(answer: Path, workspace: Path, research_id: str) -> None:
    """Read a bounded answer and exclusively publish its draft research file."""
    if not re.fullmatch(r"[0-9]{4}", research_id):
        raise TaskFileError(answer, "id", "expected four ASCII digits")
    artifact = _artifact(answer, research_id, _read_answer(answer))
    metadata = yaml.safe_dump(
        artifact.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True
    )
    out = Path(f"{research_id}-chatgpt-research.md")
    _write_artifact(workspace, out, research_id, f"---\n{metadata}---\n")
