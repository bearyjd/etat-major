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

## Stability and input handling

Object keys are sorted. Arrays follow the command's stable order, including
authored order where it carries meaning. The same inputs produce identical
bytes, including the final newline. `index` exports the caller-provided
`--indexed-at` timestamp when supplied. `progress --as-of YYYY-MM-DD`
evaluates overdue milestones against that date and echoes it in
`data.as_of`. Without that flag, JSON uses `as_of: null` and an empty
`stale_milestones` array. The text progress report defaults to the current
UTC date.

JSON encodes untrusted text as values and escapes control and Unicode
formatting characters. Workspace prose and diagnostics redact filesystem
locations and remote URLs. Research citations remain URLs in their
dedicated source fields, and index route paths remain HTTP paths. Treat
decoded strings as untrusted when displaying them.
