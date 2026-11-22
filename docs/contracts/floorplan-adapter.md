# Floorplan adapter

The adapter reads local artifacts. The recorded Floorplan fixture and its tool pin in
`pins.toml` come from Floorplan 0.11.0. The pins file also records the Trail version.

## Inputs

| Reader | Accepted input | Retained data |
| --- | --- | --- |
| `load_graph(path)` | A UTF-8 JSON object with `schema: "floorplan/graph@1"`, a `nodes` list containing string `id` fields and a `files` list containing repository-relative string `p` fields. | Frozen sets of component ids and file paths. |
| `load_plan(path)` | A UTF-8 JSON object with `$schema` or `schema` set to `"floorplan/plan@1"`. Both keys must agree if supplied together. A markerless plan is accepted when it has the same shape. | A frozen set of planned file paths. |
| `load_renames(repo, old_revision, new_revision)` | A standalone Git repository with a local `.git` directory and two revisions that resolve to commits. | An immutable mapping from original repository-relative paths to renamed paths. |

A plan requires a `files` list whose entries have string `path`, `name` and
`description` fields. When supplied, `source` is a string, `stack` and
`assumptions` are lists of strings, and `questions` and `endpoints` are lists
of objects. Extra fields are ignored. Both readers discard source metadata,
absolute roots, remotes and prose. The blueprint index also drops fields such
as `uses` and endpoint details. Renderers escape retained text with `safe()`.

Each JSON artifact is capped at 64 MiB. Readers reject symlinks in artifact
paths and report errors by filename and field. File paths use forward slashes
and repository-relative segments.

Git compares the two commits in order using `git diff -M --name-status` with
NUL-delimited records and the default rename similarity threshold. Exact renames
and sufficiently similar moves appear in the mapping. Other changes, including
independent adds and deletes, produce no mapping entry. Git subprocesses run
with bounded output and a timeout. The adapter checks the Git metadata before
invocation and rejects symlinks, indirect metadata such as linked worktrees or
object alternates, config includes, and metadata files larger than 64 MiB. Use
a repository snapshot whose Git metadata stays stable during the comparison.

## Overlay and trace

`classify_files(plan, graph, renames=None)` returns an immutable mapping keyed by
`f:<path>`.

| State | Rule |
| --- | --- |
| `planned-only` | The plan contains the file and the code map has no matching file. |
| `built` | The same file is in the plan and the code map, directly or through a rename. |
| `existing` | The code map contains the file and the plan has no matching file. |

A rename maps a planned path to its destination in the current graph and the
overlay uses that destination's id. If the destination is absent, the overlay
uses the original planned id. The map applies one old-to-new lookup between the
two snapshots.

Python callers can pass the same optional mapping to `trace_feature(..., renames=...)`.
A matching `fp:f:<path>` link resolves via the destination and retains its original
reference in the trace. A resolved `new` link is `built`. A resolved `modifies` or
`uses` link is `existing`. Component and Trail links keep their usual resolution
rules.
