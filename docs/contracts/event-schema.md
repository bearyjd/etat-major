# Contract: event schema

Status: v1. Implemented by `src/etat_major/events.py`; machine-readable form in
[`event-schema.schema.json`](event-schema.schema.json). Hooks and webhooks post these reports to
the local API, which writes them to the runtime store (never to git).

## Reports are hints

A report says what an agent or its hook *claims* happened. It is never authoritative:

- The control plane corroborates before it changes derived state: session liveness from tmux,
  merges from git or the forge, test results from CI, spend from adapter usage.
- A `pr_merged`, `test_result` or `release` report is a pointer to evidence to check, not evidence.
  Roll-ups are built from verified evidence, never from agent self-estimates.
- `failure` and `needs_input` may raise a card to the human early, since a false alarm is cheap.
  Nothing a report says can write `done` (only a human does) or approve a merge or push.
- Reports can be lost, duplicated, reordered or forged. Consumers dedupe on `idempotency_key`
  and order by `ts` only as a hint.
- `Event.is_hint` is always `True` in the models, as a reminder at call sites.

## Envelope

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `event_id` | string | yes | Unique id of this report |
| `idempotency_key` | string | yes | Same key = same logical event; a retry reuses it, the store keeps one |
| `session_id` | string | yes | The agent session that produced it |
| `task_id` | string | no | Task the session is bound to, when known |
| `adapter` | `claude-code` \| `codex` | yes | Producing agent CLI |
| `kind` | see below | yes | Selects the payload shape |
| `ts` | RFC 3339 string | yes | Must carry a timezone (`Z` or an offset) |
| `payload` | object | yes | Shape depends on `kind` |
| `hook_token` | string | yes | Per-session token that authenticates the report |

Unknown fields are rejected, at the envelope and in every payload.

**`hook_token`.** Each session gets its own token. The receiver checks it against the session and
rejects mismatches. It is a wire-only credential: the model keeps it out of `model_dump`, JSON,
`repr` and validation errors; the store must not persist it. A valid token is still only a hint.

## Kinds and payloads

| Kind | Required payload | Optional |
| --- | --- | --- |
| `launch` | `auth_mode`: `subscription` \| `metered_key` | `profile`, `model` |
| `failure` | `reason` (non-empty, persisted) | |
| `pr_merged` | `repo`, `number` (>= 1), `merge_sha` | `url` |
| `test_result` | `suite`, `passed`, `failed` (counts >= 0) | `skipped` (default 0) |
| `release` | `version` | `tag` |
| `session_start` | none | |
| `session_end` | none | `exit_reason` |
| `needs_input` | `request`: `approval` \| `question`, `prompt` | |
| `usage` | `input_tokens`, `output_tokens` | `cache_read_tokens`, `cache_write_tokens`, `model` |

- **`launch`** makes the auth mode visible at every start. A stray `ANTHROPIC_API_KEY` can
  override a subscription login and bill silently, so the UI shows `auth_mode` for each launch.
  `profile` is a profile name, never a secret or path.
- **`failure`** always carries a human-readable `reason`, and the store keeps it so the
  needs-you strip can say why.
- **`usage`** carries raw counts as integers. No cost, price or multiplier field exists and
  extra fields are rejected. Cost is computed later from measured numbers, never encoded here.

## Adapter capability flags

Adapters declare what they can report; consumers must not assume more. Exposed as
`CAPABILITIES` and `capabilities_for(adapter)` (frozen models).

| Flag | Meaning | `claude-code` | `codex` |
| --- | --- | --- | --- |
| `hooks` | Pushes events through hooks | yes | no |
| `usage_reporting` | Emits `usage` events | yes | no |
| `needs_input_detection` | Emits `needs_input` | yes | no |
| `resume` | Can resume a session | yes | yes |

The Codex row is conservative until its adapter exists: status comes from log parsing, which is
also a hint. Update the flags when the adapter lands, with a test.

## Example

```json
{
  "event_id": "evt-0001",
  "idempotency_key": "sess-demo-1:launch",
  "session_id": "sess-demo-1",
  "task_id": "0042",
  "adapter": "claude-code",
  "kind": "launch",
  "ts": "2026-11-21T10:00:00Z",
  "payload": { "auth_mode": "subscription" },
  "hook_token": "<per-session token>"
}
```
