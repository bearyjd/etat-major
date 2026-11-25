# CLI JSON contract

Select `--format json` on any command in the table. The default is text.
JSON mode writes one UTF-8 document to stdout and leaves stderr empty for
command results and errors. Help uses the regular CLI help format.

| Command | Schema | `data` on a completed read |
| --- | --- | --- |
| `trace feature:<project>/<id>` | [`etat-major/trace@1`](schemas/trace.schema.json) | Feature summary, research and findings, linked and related decisions with citations, architecture states, acceptance items, and task and milestone references |
| `decisions list` | [`etat-major/decisions-list@1`](schemas/decisions-list.schema.json) | `decisions` sorted by ID, including proposed, approved, rejected, postponed, and superseded decisions |
| `index` | [`etat-major/index@1`](schemas/index.schema.json) | [RepoIndex](repo-index.md) version 1 snapshot |
| `progress` | [`etat-major/progress@1`](schemas/progress.schema.json) | [ProgressEvidence](progress-evidence.md) report and optional evaluation date |
| `gradle deps --root DIR` | [`etat-major/gradle-deps@1`](schemas/gradle-deps.schema.json) | [Gradle modules and declarations](gradle-adapter.md) |
| `gradle drift --root DIR --graph FILE` | [`etat-major/gradle-drift@1`](schemas/gradle-drift.schema.json) | [Dependency and module comparisons](gradle-adapter.md) with evidence counts |
| `components validate --workspace DIR` | [`etat-major/components-validate@1`](schemas/components-validate.schema.json) | Empty object. Component model validation results appear in `issues`. |
| `components map --workspace DIR --project P --path FILE` | [`etat-major/components-map@1`](schemas/components-map.schema.json) | The project, queried path, owning component ID or null, ancestor IDs nearest first, and tied IDs sorted by ID |
| `components coverage --workspace DIR --project P --graph FILE` | [`etat-major/components-coverage@1`](schemas/components-coverage.schema.json) | The project, sorted owned and unowned Floorplan file paths, and percentage owned |
| `components seed --root DIR --project P --out FILE` | [`etat-major/components-seed@1`](schemas/components-seed.schema.json) | The project, the created file's basename, and the proposed component IDs in file order. Use `--proposal-for FILE` in place of `--out FILE` to propose additions to an existing model. |
| `workspace validate --workspace D` | [`etat-major/workspace-validate@1`](schemas/workspace-validate.schema.json) | Empty object. Validation results appear in `issues`. |

Each schema uses JSON Schema Draft 2020-12 and can be validated locally.

```json
{
  "data": {},
  "issues": [],
  "ok": true,
  "schema": "etat-major/workspace-validate@1"
}
```

## Exit codes and issues

| Exit | `ok` | `data` | Meaning |
| --- | --- | --- | --- |
| 0 | `true` | Object | Successful read. Warnings and unsourced findings can coexist with success. |
| 1 | `false` | Object | The command returns available data alongside workspace validation errors or missing, stale, or planned-gap trace items. |
| 2 | `false` | `null` | The command could not produce data. Examples include bad arguments, unknown features, and unreadable or invalid required inputs. |

An issue has `path`, `field`, `message`, and `severity` (`error` or
`warning`). The path is workspace-relative, an external input's basename, a
record reference for a cross-record problem, or the command name for an
argument error. Clients should use the exit code and structured fields for
control flow. The message is for display.

`workspace validate` reports every detected error and warning for research,
decisions, features, tasks, milestones, and visions. The workspace walker
applies its directory and file limits. The other workspace commands retain
the first 200 workspace errors and put the remaining count in
`data.omitted_issues`. Trace adds architecture diagnostics for the selected
feature. Progress findings, such as disconnected commits, are available
inside the report.
Gradle includes usable partial results alongside build-file diagnostics.
Candidate drift produces exit 1 and a summary issue, with individual
differences in `data`.

Component validation reports errors with exit 1. Map and coverage can return
data with diagnostics for other workspace component files. An unavailable
selected model, invalid graph, or unavailable seed destination returns exit 2.
Trace returns exit 2 for an invalid `--components` input, including an invalid
model in a supplied component directory. A single file scopes this validation
to that model. Ownership ties are warnings and count as unowned paths. Coverage uses distinct
recorded paths and is 0 percent when the Floorplan file list is empty.

## `export planning --json`

`etat-major export planning --json --workspace DIR --project P` prints the
Planning payload to stdout. It accepts the same input flags as `serve`
(except `--port`) and needs no web extra: it does not import fastapi,
starlette or uvicorn. `--json` is required and is the only supported format.

The document is the bare payload, not the `data`/`issues` envelope above. It
carries the top-level marker `"schema": "etat-major/planning@1"`, described by
[`planning.schema.json`](schemas/planning.schema.json) (JSON Schema Draft
2020-12). The marker is an additive change: `version` stays `1` and every
existing key is unchanged, so clients that ignore unknown keys are unaffected.
It is the same object that `serve` returns at `/project.json`, produced by one
shared function, so the two cannot drift. Task `state` is the derived board
column (`draft`, `ready`, `in-progress`, `review`, `done`, `blocked`), not the
stored status.

The schema is strict (`additionalProperties: false`), so any new key needs a
schema update or an `@2` marker. A client must treat `schema` as the
compatibility gate and reject values it does not know.
Top-level keys include `schema`, `project`, `features`, `components`, `tasks`,
`sources`, `issues` and `version`. The `meute`, `manual_review` and
`execution_links` keys appear only when those inputs are supplied. Keys are
sorted, output is indented two spaces and ends with one newline, so the same
inputs produce identical bytes.

A bad workspace or project prints a file-and-field message on stderr, leaves
stdout empty and exits 2, with no traceback; the message names
`export planning`. A missing `--json` is an argument error and also exits 2.
A bad recorded input, such as an unreadable `--graph`, can still exit 0: the
problem is listed in the payload's `issues` instead. Check `issues` before
trusting the data.

`export understand --json` is specified, not yet implemented: see the
[Understand export contract](understand-export.md).

## Stability and input handling

Object keys are sorted. Arrays follow the command's stable order, including
authored order where it carries meaning. The same inputs produce identical
bytes, including the final newline. `index` exports the caller-provided
`--indexed-at` timestamp when supplied. Its coverage includes
`unknown_node_kinds` and `unknown_link_kinds` from the Floorplan layer.
`progress --as-of YYYY-MM-DD`
evaluates overdue milestones against that date and echoes it in
`data.as_of`. Without that flag, JSON uses `as_of: null` and an empty
`stale_milestones` array. The text progress report defaults to the current
UTC date.

JSON encodes untrusted text as values and escapes control and Unicode
formatting characters. Workspace prose and diagnostics redact filesystem
locations and remote URLs. Research citations remain URLs in their
dedicated source fields, and index route paths remain HTTP paths. Treat
decoded strings as untrusted when displaying them.
