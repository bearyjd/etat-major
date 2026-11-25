# Understand export contract

**Status: proposed contract. Nothing here is implemented.** It specifies a
future `etat-major export understand --json`, the Understand counterpart of
[`export planning --json`](cli-json.md#export-planning---json). Answers marked
"recommended" in [Open questions](#open-questions) are proposals for the
maintainer, not decisions.

Sources read to write this contract: `understand.py` (the `Understand` lookup
and `build`), `understand_html.py` (the `/understand` route), `components.py`
(`Component`, `Summary`), `trail.py` (`Symbol`, `SymbolIndex`,
`SymbolCoverage`) and the [Understand MVP](../UNDERSTAND-MVP.md).

## Purpose and shape

A machine-readable, read-only snapshot of how one project works: its reviewed
components, what the recorded artifacts cover, a symbol summary and the
issues found while reading. It exports what the Understand page shows, minus
anything that exists only for browser navigation.

- Marker: `"schema": "etat-major/understand@1"`, plus `"version": 1`.
- The document is the bare payload, not the `data`/`issues` envelope, like
  `export planning`.
- Flags mirror `export planning`: `--json` (required, only format),
  `--workspace DIR`, `--project P`, and the same recorded-input flags as
  `serve` (graph, Trail wiring, revisions, components) except `--port`.
  No web extra is needed.
- Deterministic: sorted keys, two-space indent, one trailing newline, same
  inputs give identical bytes.
- Built by one shared function, so a future JSON route cannot drift from the
  CLI. The export reuses `understand.build` and reads no new input.
- The CLI makes no network or `gh` call and runs no tool. Errors exit 2 with a
  file-and-field message on stderr naming `export understand`, empty stdout.
- A JSON Schema (`schemas/understand.schema.json`, Draft 2020-12,
  `additionalProperties: false`) ships with the implementation. A client must
  reject a `schema` value it does not know.

## Exported fields

| Key | Content |
| --- | --- |
| `schema`, `version`, `project` | Marker, `1`, project ID |
| `artifacts` | Exactly two rows, `Floorplan` then `Trail`: `label`, `status` (`present`, `missing`, `invalid`), `freshness` (`fresh`, `stale`, `unknown`), `revision` (full commit SHA or null), `digest` (hex SHA-256 of the recorded bytes or null) |
| `coverage` | Limits, see [Coverage limits](#coverage-limits) |
| `components` | Array sorted by `id`, see [Components](#components) |
| `files` | Optional. Sorted workspace-relative paths per owner, see [Files](#files) |
| `symbols` | Summary only, see [Symbol summary](#symbol-summary) |
| `issues` | Sorted `path`, `field`, `message`, `severity` rows, same shape as the CLI envelope |

Source revision, not a clock: no key holds a generation time, so output is
reproducible.

### Components

One row per `Component` in the reviewed model, sorted by `id`:

| Key | From | Notes |
| --- | --- | --- |
| `id`, `label`, `kind`, `parent`, `owner` | `Component` | `parent` and `owner` are null when absent |
| `paths` | `Component.paths` | Workspace-relative globs/prefixes, at most 1000 each |
| `summary` | `Component.summary.text` | Null when absent. Passed through the public-text sanitizer |
| `provenance` | `Component.summary.provenance` | `human`, `ai-generated`, `inferred`, `verified`; null when no summary |
| `reviewed` | `Summary.reviewed_by` and `reviewed_on` | Boolean only. Reviewer name and date are not exported (see Q4) |
| `proposal` | `kind` equals the seed proposal kind | Boolean. A seeded proposal is not reviewed intent |
| `files` | Derived count | Files owned in the recorded inventory |
| `symbols` | Derived count | Trail symbols in those files |

Conversion: the pydantic `Component` is frozen with tuple fields. Export builds
plain dicts by explicit field mapping (as `ComponentRow` does for planning),
never `model_dump()` of the whole model, so a field added to the model later
is not exported until the schema says so. Tuples become JSON arrays in
declared order. `Summary` flattens into `summary` plus `provenance`.

### Files

Opt-in with `--include-files`, default off. When on, `files` maps each
component `id` (plus the two synthetic groups `[Unowned files]` and
`[Tied ownership]`) to its sorted workspace-relative paths. Paths come from
the union of the recorded Floorplan file list and Trail symbol paths, after
the same path validation the loaders apply. Ties list the competing component
IDs, sorted.

### Symbol summary

Never one row per symbol. Per component and in total:

- counts by `kind`, from `Symbol.kind` (unknown kinds reported under
  `unknown_kinds`, a sorted list, as in `index`)
- counts of recorded edges by `relation` and `confidence`
- `unresolved_relations` counts from `SymbolCoverage`
- `languages` and `module_scopes` from `SymbolCoverage`
- `files_without_symbols` as a count (the list only with `--include-files`)

`Symbol` is a frozen dataclass, so it is never serialized directly. Its `id`
is a Trail node ID and its `provenance` is always `verified`. Individual
symbols are excluded in `@1`; see Q2.

### Coverage limits

Always present, never omitted, so a reader cannot mistake absence for health:

- `owned`, `unowned`, `tied`, `unmatchable` file counts and `percentage_owned`,
  stated as coverage of the recorded inventory, not of the repository
- per artifact: status and freshness (above), so a stale or missing Trail is
  visible beside the numbers it affects
- `notes`: fixed strings, for example "Kotlin calls are name-matched and
  inferred", "Trail imports are unresolved for Kotlin"
- when both artifacts are missing, `components` is still exported and
  `coverage.inventory` is `unavailable`

## Provenance labels

| Label | Meaning in this export |
| --- | --- |
| `verified` | Recorded by a deterministic tool and not model-written: Trail symbols, Floorplan file lists, and a component summary the model marks `verified` |
| `inferred` | Derived by heuristic: name-matched calls, seeded component proposals, summaries marked `inferred` |
| `ai-generated` | Written by a model. Always paired with `reviewed: false` until a person records review |
| `human` | Authored by a person. Exported as in the component model; clients treat it as reviewed intent |

The export must not upgrade a label. `reviewed: true` requires both
`reviewed_by` and `reviewed_on` in the model. An edge with `inferred`
provenance stays `inferred` even when both endpoints resolve.

## Excluded

Never exported, and the schema forbids them (`additionalProperties: false`):

1. Navigation tokens: the `u-` + 32 hex SHA-256 IDs, and the `lookup` table
   that maps them back. They are per-startup UI handles, not identity. Use
   component `id` and workspace-relative paths.
2. `symbol_pages` and `PAGE` paging, `groups`, and the reverse `owner` map.
3. Absolute paths, the `immutable_source` root, home directories, hostnames,
   and Git remotes or URLs found in third-party data. Paths are always
   workspace-relative and re-validated.
4. Source excerpts, file bodies and anything read from the scanned repository
   other than paths and recorded symbol metadata.
5. Raw Floorplan or Trail records, including model-written Floorplan layers,
   blueprints and edge lists. Floorplan is advisory and has no stable contract.
6. Credentials, environment values and tool output.
7. Anything unsanitized. All free text (`label`, `summary`, `owner`, issue
   messages) passes the same `public_text` redaction and control-character
   escaping as `export planning`. JSON also escapes Unicode formatting
   characters. A string that cannot be sanitized is dropped with an `issues`
   row, not exported raw.

Treat decoded strings as untrusted when displaying them.

## Size caps

The export is bounded independently of the 64 MiB input caps in
[LIMITS](../LIMITS.md):

| Cap | Proposed value |
| --- | --- |
| Components | 500 (`MAX_COMPONENTS`) |
| Paths per component | 1000 (`MAX_PATHS`) |
| Files with `--include-files` | 20,000 total, then truncated with `files_truncated: true` and an `issues` warning |
| `summary` text | 2,000 characters |
| `issues` | 200 rows, the rest as `omitted_issues` (as other workspace commands) |
| Whole document | 4 MiB. Over the cap exits 2 with a message naming `export understand` and the cap, never a silent cut |

Truncation is always declared in the payload. The caps are constants in one
module and are pinned by tests when implemented.

## Stability

`@1` is additive: new optional keys need a schema update; removing or
changing a key needs `@2`. `version` stays `1` within `@1`. Arrays have a
stable order (sorted by `id` or path). No timestamps, so identical inputs give
identical bytes.

## Open questions

| # | Question | Recommended answer |
| --- | --- | --- |
| Q1 | Envelope or bare payload? | Bare payload with the marker, matching `export planning`. |
| Q2 | Export individual symbols? | No in `@1`; summary counts only. Per-file symbols can arrive as `@2` or a separate `--file` export once a consumer exists. |
| Q3 | Include file lists? | Opt-in `--include-files`, default off, capped. Large and mostly derivable from component `paths`. |
| Q4 | Export reviewer name and review date? | Boolean `reviewed` only. Names are personal data in a public-repo setting; the Git history already holds them. |
| Q5 | Export `ai-generated` summaries? | Yes, labeled and with `reviewed: false`, so a consumer can filter. Never relabel. |
| Q6 | Include stale artifacts? | Yes, with `freshness: stale` and a warning issue. Omitting would hide that a map exists. |
| Q7 | Exit code when an artifact is missing? | 0 with an `issues` row and `coverage` showing `unavailable`. Exit 2 only if no component model loads and no artifact exists. |
| Q8 | Whole-document cap value? | 4 MiB, error not truncation. Revisit after measuring a large recording; behavior near the input cap is unmeasured. |
| Q9 | Should the Understand web route expose the same JSON (`/understand.json`)? | Not in the first PR. Add it later through the same shared function, as `/project.json` does for planning. |
| Q10 | Should the CLI accept the Floorplan graph and Trail wiring as flags, without `serve`? | Yes, same flags as `serve`, read through the existing loaders. No new reader. |
