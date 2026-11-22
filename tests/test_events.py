import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from etat_major.events import (
    ADAPTERS,
    CAPABILITIES,
    KINDS,
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
        "hook_token": "tok-demo",
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


@pytest.mark.parametrize("field", ["event_id", "idempotency_key", "session_id", "hook_token"])
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


def test_hook_token_never_serialised_or_repr():
    ev = parse_event(make())
    assert "tok-demo" not in repr(ev)
    assert "hook_token" not in ev.model_dump()
    assert "tok-demo" not in ev.model_dump_json()


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
    from etat_major.events import FailurePayload

    data = make("launch", payload=FailurePayload(reason="x"))
    with pytest.raises(ValidationError):
        parse_event(data)
