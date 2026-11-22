import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from etat_major.events import (
    ADAPTERS,
    CAPABILITIES,
    KINDS,
    FailurePayload,
    capabilities_for,
    parse_event,
)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "docs/contracts/event-schema.schema.json").read_text())

PAYLOADS = {
    "launch": {"auth_mode": "subscription"},
    "failure": {"reason": "tests failed after 3 retries"},
    "pr_merged": {"repo": "example-service", "number": 7, "merge_sha": "abc1234"},
    "test_result": {"suite": "unit", "passed": 10, "failed": 0, "skipped": 1},
    "release": {"version": "1.2.0"},
    "session_start": {},
    "session_end": {"exit_reason": "completed"},
    "needs_input": {"request": "approval", "prompt": "Run migration?"},
    "usage": {"input_tokens": 100, "output_tokens": 50},
}


def make(kind="launch", **over):
    base = {
        "event_id": "evt-1",
        "idempotency_key": "sess-1:1",
        "session_id": "sess-1",
        "task_id": "0042",
        "adapter": "claude-code",
        "kind": kind,
        "ts": "2026-11-21T10:00:00Z",
        "payload": PAYLOADS[kind],
    }
    base.update(over)
    return base


def test_all_kinds_covered():
    assert set(KINDS) == set(PAYLOADS)


@pytest.mark.parametrize("kind", sorted(PAYLOADS))
def test_valid_event_passes_model_and_schema(kind):
    data = make(kind)
    jsonschema.validate(data, SCHEMA)
    assert parse_event(data).kind == kind


@pytest.mark.parametrize("kind", sorted(PAYLOADS))
def test_schema_rejects_empty_required_payload(kind):
    if kind in ("session_start", "session_end"):
        return
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(make(kind, payload={}), SCHEMA)
    with pytest.raises(ValidationError):
        parse_event(make(kind, payload={}))


def test_launch_auth_mode_enum():
    bad = make("launch", payload={"auth_mode": "oauth_pool"})
    with pytest.raises(ValidationError):
        parse_event(bad)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)
    ok = parse_event(make("launch", payload={"auth_mode": "metered_key"}))
    assert ok.payload.auth_mode == "metered_key"


def test_failure_requires_nonempty_reason():
    bad = make("failure", payload={"reason": ""})
    with pytest.raises(ValidationError):
        parse_event(bad)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)


def test_usage_rejects_cost_fields():
    for extra in ("cost_usd", "multiplier", "cost"):
        bad = make("usage", payload={"input_tokens": 1, "output_tokens": 1, extra: 2})
        with pytest.raises(ValidationError):
            parse_event(bad)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, SCHEMA)


def test_usage_rejects_negative_and_float():
    for bad_val in (-1, 1.5, True):
        bad = make("usage", payload={"input_tokens": bad_val, "output_tokens": 1})
        with pytest.raises(ValidationError):
            parse_event(bad)


@pytest.mark.parametrize("field", ["event_id", "idempotency_key", "session_id"])
def test_required_top_level_fields(field):
    data = make()
    del data[field]
    with pytest.raises(ValidationError):
        parse_event(data)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, SCHEMA)


def test_task_id_optional():
    data = make()
    del data["task_id"]
    jsonschema.validate(data, SCHEMA)
    assert parse_event(data).task_id is None


def test_unknown_adapter_kind_and_field_rejected():
    for over in ({"adapter": "gemini"}, {"kind": "nope"}, {"extra": 1}):
        data = make(**over) if over.keys() != {"kind"} else {**make(), **over}
        with pytest.raises(ValidationError):
            parse_event(data)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, SCHEMA)


def test_ts_must_have_timezone():
    with pytest.raises(ValidationError):
        parse_event(make(ts="2026-11-21T10:00:00"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(make(ts="2026-11-21T10:00:00"), SCHEMA)


def test_payload_kind_mismatch_rejected():
    with pytest.raises(ValidationError):
        parse_event(make("launch", payload=PAYLOADS["usage"]))


def test_event_is_immutable_and_hint():
    ev = parse_event(make())
    with pytest.raises(ValidationError):
        ev.kind = "failure"
    assert ev.is_hint is True


def test_capabilities():
    assert set(CAPABILITIES) == set(ADAPTERS) == {"claude-code", "codex"}
    cc = capabilities_for("claude-code")
    assert cc.hooks is True
    with pytest.raises(ValidationError):
        cc.hooks = False
    with pytest.raises(KeyError):
        capabilities_for("gemini")
    for caps in CAPABILITIES.values():
        assert set(caps.model_dump()) == {
            "hooks",
            "usage_reporting",
            "needs_input_detection",
            "resume",
        }


def test_mismatched_payload_instance_rejected():

    data = make("launch", payload=FailurePayload(reason="x"))
    with pytest.raises(ValidationError):
        parse_event(data)


def _leaks(err: ValidationError, secret: str) -> bool:
    chain = [err, err.__cause__, err.__context__]
    return any(
        secret in text
        for e in chain
        if isinstance(e, ValidationError)
        for text in (str(e), repr(e), repr(e.errors()), e.json())
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"event_id": None},  # missing-style error: input is the whole report
        {"extra": 1},
        {"ts": "nope"},
        {"payload": {}},
        {"payload": PAYLOADS["usage"]},  # kind mismatch (after validator)
        {"hook_token": ["tok-secret-9"]},  # nested, not only a plain string
    ],
)
def test_credential_in_body_not_in_validation_errors(bad):
    from etat_major.events import Event

    data = make(**{"hook_token": "tok-secret-9", **bad})
    if bad == {"event_id": None}:
        del data["event_id"]
    for parse in (parse_event, Event.model_validate, lambda d: Event(**d)):
        with pytest.raises(ValidationError) as exc:
            parse(data)
        assert exc.value.error_count() >= 1
        assert not _leaks(exc.value, "tok-secret-9")


@pytest.mark.parametrize(
    "bad",
    [
        {"x-tok-secret-9": 1},  # unknown envelope field named after the token
        {"payload": {"auth_mode": "subscription", "tok-secret-9": 1}},
        {"payload": {"tok-secret-9": 1}},
        {"extra": {"tok-secret-9": ["tok-secret-9"]}},
    ],
)
def test_credential_in_body_not_in_error_field_names(bad):
    from etat_major.events import Event

    data = make(**{"hook_token": "tok-secret-9", **bad})
    for parse in (parse_event, Event.model_validate, lambda d: Event(**d)):
        with pytest.raises(ValidationError) as exc:
            parse(data)
        assert exc.value.error_count() >= 1
        assert not _leaks(exc.value, "tok-secret-9")


def test_event_model_and_schema_carry_no_credential():
    from etat_major.events import Event

    assert "hook_token" not in Event.model_fields
    assert "hook_token" not in SCHEMA["properties"]
    assert "hook_token" not in SCHEMA["required"]
    data = make()
    assert "hook_token" not in dict(parse_event(data))
    legacy = {**data, "hook_token": "tok-secret-9"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(legacy, SCHEMA)
    with pytest.raises(ValidationError) as exc:
        parse_event(legacy)
    assert not _leaks(exc.value, "tok-secret-9")


@pytest.mark.parametrize("cut", [1, 20])
def test_malformed_json_error_does_not_echo_body(cut):
    from etat_major.events import Event

    raw = json.dumps({**make(), "reason": "Bearer tok-secret-9", "pad": "x" * 20})[:-cut]
    assert "tok-secret-9" in raw
    for body in (raw, raw.encode()):
        with pytest.raises(ValidationError) as exc:
            Event.model_validate_json(body)
        assert exc.value.error_count() >= 1
        assert not _leaks(exc.value, "tok-secret-9")
