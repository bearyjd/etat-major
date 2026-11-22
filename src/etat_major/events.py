"""Event schema for hook and webhook reports.

Contract: docs/contracts/event-schema.md. Every report is a hint, not a fact: the
control plane must corroborate it (session liveness, git, CI) before it changes
derived state. The per-session ``hook_token`` authenticates a report on the wire
and is never stored, serialised or shown in ``repr``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, get_args

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    ValidatorFunctionWrapHandler,
    model_validator,
)

Adapter = Literal["claude-code", "codex"]
Kind = Literal[
    "launch",
    "failure",
    "pr_merged",
    "test_result",
    "release",
    "session_start",
    "session_end",
    "needs_input",
    "usage",
]
ADAPTERS: tuple[str, ...] = get_args(Adapter)
KINDS: tuple[str, ...] = get_args(Kind)

Text = Annotated[StrictStr, Field(min_length=1)]
Count = Annotated[StrictInt, Field(ge=0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LaunchPayload(_Strict):
    auth_mode: Literal["subscription", "metered_key"]
    profile: Text | None = None
    model: Text | None = None


class FailurePayload(_Strict):
    reason: Text


class PrMergedPayload(_Strict):
    repo: Text
    number: Annotated[StrictInt, Field(ge=1)]
    merge_sha: Text
    url: Text | None = None


class TestResultPayload(_Strict):
    __test__ = False  # not a pytest class

    suite: Text
    passed: Count
    failed: Count
    skipped: Count = 0


class ReleasePayload(_Strict):
    version: Text
    tag: Text | None = None


class SessionStartPayload(_Strict):
    pass


class SessionEndPayload(_Strict):
    exit_reason: Text | None = None


class NeedsInputPayload(_Strict):
    request: Literal["approval", "question"]
    prompt: Text


class UsagePayload(_Strict):
    """Raw token counts only; cost and multipliers are never carried."""

    input_tokens: Count
    output_tokens: Count
    cache_read_tokens: Count = 0
    cache_write_tokens: Count = 0
    model: Text | None = None


PAYLOADS: dict[str, type[_Strict]] = {
    "launch": LaunchPayload,
    "failure": FailurePayload,
    "pr_merged": PrMergedPayload,
    "test_result": TestResultPayload,
    "release": ReleasePayload,
    "session_start": SessionStartPayload,
    "session_end": SessionEndPayload,
    "needs_input": NeedsInputPayload,
    "usage": UsagePayload,
}

Payload = (
    LaunchPayload
    | FailurePayload
    | PrMergedPayload
    | TestResultPayload
    | ReleasePayload
    | SessionStartPayload
    | SessionEndPayload
    | NeedsInputPayload
    | UsagePayload
)


class Event(_Strict):
    event_id: Text
    idempotency_key: Text
    session_id: Text
    task_id: Text | None = None
    adapter: Adapter
    kind: Kind
    ts: AwareDatetime
    payload: Payload
    hook_token: Text = Field(exclude=True, repr=False)

    @property
    def is_hint(self) -> bool:
        """Reports are never authoritative; see the contract."""
        return True

    @model_validator(mode="wrap")
    @classmethod
    def _no_input_in_errors(cls, data: Any, handler: ValidatorFunctionWrapHandler) -> Event:
        """Drop raw input from errors: it can hold the ``hook_token``."""
        try:
            return handler(data)
        except ValidationError as exc:
            errors = [{**e, "input": None} for e in exc.errors(include_url=False)]
            title = exc.title
        # Raised outside the handler so the original error is not chained.
        raise ValidationError.from_exception_data(title, errors, hide_input=True)

    @model_validator(mode="before")
    @classmethod
    def _typed_payload(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("kind") in PAYLOADS:
            raw = data.get("payload")
            if isinstance(raw, dict):
                data = {**data, "payload": PAYLOADS[data["kind"]].model_validate(raw)}
        return data

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> Event:
        if type(self.payload) is not PAYLOADS[self.kind]:
            raise ValueError(f"payload does not match kind '{self.kind}'")
        return self


class Capabilities(_Strict):
    """What an adapter can report; consumers must not assume more."""

    hooks: bool
    usage_reporting: bool
    needs_input_detection: bool
    resume: bool


CAPABILITIES: dict[str, Capabilities] = {
    "claude-code": Capabilities(
        hooks=True, usage_reporting=True, needs_input_detection=True, resume=True
    ),
    # Conservative until the Codex adapter lands: status comes from log parsing.
    "codex": Capabilities(
        hooks=False, usage_reporting=False, needs_input_detection=False, resume=True
    ),
}


def capabilities_for(adapter: str) -> Capabilities:
    return CAPABILITIES[adapter]


def parse_event(data: dict[str, Any]) -> Event:
    """Validate a raw report; raises pydantic.ValidationError."""
    return Event.model_validate(data)


__all__ = [
    "ADAPTERS",
    "CAPABILITIES",
    "KINDS",
    "PAYLOADS",
    "Capabilities",
    "Event",
    "capabilities_for",
    "parse_event",
]
