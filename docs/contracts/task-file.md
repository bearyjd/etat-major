# Contract: task file format

Status: v1. Implemented by `src/etat_major/taskfile.py`; machine-readable form in
[`task-file.schema.json`](task-file.schema.json). Decision basis:
[`docs/spikes/phase1-spike.md`](../spikes/phase1-spike.md) (own format, Backlog.md is not a dependency).

Git holds intent. Runtime state (sessions, spend, approvals) never appears in these files.

## Layout

```text
workspace/
  initiatives/example-initiative.md
  projects/example-service.md
  tasks/example-service/0042-schema-mapper.md
```

Each file is markdown with a YAML frontmatter block (`---` fences) followed by a free-form body.
Unknown frontmatter fields are rejected. Files in a `drafts/` folder (native Backlog.md drafts)
are not task files and are rejected; use `status: draft` on a normal task.

## Task

```yaml
---
id: 0042
title: Schema mapper for the example service
initiative: example-initiative
project: example-service
owner: alice
status: ready
priority: 2
acceptance:
  - Maps all source tables listed in docs/sources.md
budget_tokens: 400000
evidence:
  - kind: pr
    ref: example-org/example-service#12
---
```

| Field | Required | Rule |
| --- | --- | --- |
| `id` | yes | Digits only. Must equal the filename prefix before the first `-` (`0042-x.md` needs `0042`). Zero-padded numbers are read as text, not octal. |
| `title` | yes | Non-empty string |
| `initiative` | yes | Initiative id |
| `project` | yes | Project id |
| `owner` | yes | Exactly one non-empty string (no list) |
| `status` | yes | `draft`, `ready`, `blocked` or `done` |
| `priority` | no | Integer, 1 or more (1 is highest by convention) |
| `acceptance` | no | List of non-empty strings; default empty |
| `budget_tokens` | no | Integer above 0 |
| `evidence` | no | List of `{kind, ref}`; `kind` is `pr`, `test-run` or `release`; `ref` is a non-empty string such as `org/repo#12`. Default empty |

### Status

Only intent statuses are valid in a file. `running`, `needs-you`, `review` and `failed` are
derived from runtime state and are rejected with an error naming the file and the `status` field.

**"Only a human writes `done`"** cannot be proven from file content, so the validator accepts
`done` and does not try to. Enforcement belongs to the git workflow: protect `main`, require human
review of any change that sets `done`, and have agent sessions work in worktrees without
permission to merge. Roll-ups count `done` only together with `evidence`.

## Initiative

Fields: `id` (equals filename stem), `title`, `owner`, `target_date` (ISO date), `outcome`. All required.

## Project

Fields: `id` (equals filename stem), `title`, `initiative`, `owner` required; `repo` optional.

## Body safety

The body may be agent-written. The parser returns `warnings` (one per line, with line number) when
the body contains raw HTML tags, HTML comments or `javascript:`/`vbscript:`/`data:` link targets
outside code spans and fenced code. Flagging does not reject the file; renderers must still
sanitise or escape the body and must show or drop flagged content.

## Errors

`TaskFileError` messages read `<filename>: field '<field>': <reason>`; nested fields use dotted
paths (`evidence.0.kind`). Only the first problem is reported.
