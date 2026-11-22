# Contract: task file format

Status: v1. Implemented by `src/etat_major/taskfile.py`; machine-readable form in
[`task-file.schema.json`](task-file.schema.json). Decision basis:
[`docs/spikes/phase1-spike.md`](../spikes/phase1-spike.md) (own format, Backlog.md is not a dependency).

Git holds intent and recorded human acceptance. Sessions and spend stay outside this contract.

## Layout

```text
workspace/
  initiatives/example-initiative.md
  projects/example-service.md
  visions/example-service.md
  milestones/example-service/m3-latency.md
  tasks/example-service/0042-schema-mapper.md
  diagrams/overview.mmd
```

Each file is markdown with a YAML frontmatter block (`---` fences) followed by a free-form body.
Unknown or repeated frontmatter fields and YAML merge keys (`<<`) are rejected. Each Markdown
file is limited to 1 MiB, with up to 64 YAML aliases. Use `status: draft` on a normal task
instead of placing it in a native Backlog.md `drafts/` folder.

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
milestone: m3
depends_on: [0041]
targets: [fp:f:src/schema.py, trail:src/schema.py#map_row]
acceptance:
  - Maps all source tables listed in docs/sources.md
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
| `milestone` | no | Lowercase alphanumeric milestone ID in the same project |
| `depends_on` | no | List of task IDs in the same project. Zero padding is preserved. Default empty |
| `targets` | no | List of [code references](../TRACEABILITY.md#layout) using `fp:n:`, `fp:f:` or `trail:`. Default empty |
| `accepted_by` | when done | Nonblank string identifying the person who accepted the task |
| `accepted_on` | when done | ISO calendar date (`YYYY-MM-DD`) |
| `evidence` | no | List of `{kind, ref}`; `kind` is `pr`, `test-run` or `release`; `ref` is a non-empty string such as `org/repo#12`. Default empty |

The `budget_tokens` field was removed. Delete it from older task files.

### Status

Only `draft`, `ready`, `blocked` and `done` are valid in a file. The validator rejects derived
statuses including `in-progress` and `review`. A person records both acceptance fields with
`status: done`. Both fields must be absent for the other stored statuses.

The fields record an acceptance claim. The Git review workflow is responsible for verifying who
made it. An `evidence` entry counts as proof after Git or GitHub confirms the referenced item.

`planning.derive_board_column(task, dependency_states, evidence=None)` takes a mapping from local
task ID to stored status. Accepted `done` takes precedence. A task with any missing or unfinished
dependency lands in `blocked`. Otherwise the column is its stored status. Evidence-based
`in-progress` and `review` columns are reserved for the progress evidence phase.

The workspace loader checks task IDs within each project and collects unknown dependencies and
cyclic groups, including self-dependencies. The case of an unknown ID in one project is independent
of whether another project has the same ID.

## Initiative

Fields: `id` (equals filename stem), `title`, `owner`, `target_date` (ISO date), `outcome`. All required.

## Project

Fields: `id` (equals filename stem), `title`, `initiative`, `owner` required; `repo` optional.

## Vision

`planning.parse_vision` loads `visions/<project>.md`. Frontmatter contains `project` (the filename
stem), `vision` (a non-empty string), `goals` (a non-empty list of non-empty strings) and optional
`diagrams` (a list of workspace-relative `diagrams/*.mmd` links). The body can add context.

## Milestone

`planning.parse_milestone` loads `milestones/<project>/<id>-<slug>.md`. Frontmatter requires `id`
(lowercase alphanumeric, matching the filename prefix), `title`, `outcome` and `horizon` (`now`,
`next` or `later`). `target_date` is an optional ISO calendar date.

## Body safety

The body may be agent-written. The parser tokenizes it as CommonMark and returns `warnings` (one
per line, numbered where the markup starts) for raw HTML and `javascript:`/`vbscript:`/`data:`
link or image targets outside code. Flagging does not reject the file; renderers must still
sanitise or escape the body and must show or drop flagged content.

## Errors

`TaskFileError` messages identify the filename and field. Nested fields use dotted paths such as
`evidence.0.kind`. Individual parsers report the first problem with a file. Workspace validation
collects issues across files and reports omitted issues once it reaches the display cap.
