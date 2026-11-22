# Floorplan adapter

The adapter reads local artifacts. The recorded Floorplan fixture and its tool pin in
`pins.toml` come from Floorplan 0.11.0. The pins file also records the Trail version.

## Inputs

| Reader | Accepted input | Retained data |
| --- | --- | --- |
| `load_graph(path)` | A UTF-8 `floorplan/graph@1` JSON object. | Frozen sets of component IDs and file paths. |
| `load_graph(path, architecture=True)` | The same graph, with validation of retained architecture fields. | Frozen project name, components, files, routes and links. |
| `load_plan(path)` | A UTF-8 JSON object with `$schema` or `schema` set to `"floorplan/plan@1"`. Both keys must agree if supplied together. A markerless plan is accepted when it has the same shape. | A frozen set of planned file paths. |
| `load_renames(repo, old_revision, new_revision)` | A standalone Git repository with a local `.git` directory and two revisions that resolve to commits. | An immutable mapping from original repository-relative paths to renamed paths. |

### Recorded graph

Floorplan 0.11.0 emits the following fields in `graph.json`.

| Field | Wire shape and adapter behavior |
| --- | --- |
| `schema` | Only `floorplan/graph@1` is accepted. |
| `project` | An object with `name`, `summary` and `entrypoints`. The architecture reader retains `name` and also accepts a legacy project string. |
| `meta` | Metadata includes `generatedAt`, `scanAt`, `rootName`, `audience`, `agent`, `repos` and `counts`. Each repo can carry `path`, `name`, `branch` and `head`. The adapter discards this metadata, including any absolute root or remote. |
| `nodes` | A list of objects with `id`, nullable `parent`, `label`, `kind`, `summary`, `details`, `tags`, `paths`, `packages`, `hosts` and `stats`. Paths are globs and the list can be empty. The architecture reader retains `id` and `kind`. |
| `files` | A list of objects with `p` (repository-relative path), `n` (owning node ID), `r` (repo), `l` (language), `loc`, `name`, `d`, `doc`, `h`, `s` (symbols), `sig` and `auto`. The architecture reader retains `p`, `n`, `l` and `loc`. |
| `links` | A list of objects with endpoints `a` and `b`, kind `k`, weight `w` and optional `desc`, `inferred`, `labels` and `names`. The architecture reader retains `a`, `b` and `k`. |
| `routes` | The architecture reader retains route IDs, methods, HTTP paths and optional file paths. |
| `flows`, `tour`, `health`, `screens` | Ignored. |

The plain reader collects only `nodes[].id` and `files[].p`. Both readers ignore
extra keys at every level. Architecture links support file-to-file, file-to-node
and node-to-node endpoints using `f:<path>` and `n:<id>`. The reader also accepts
legacy `r:<id>` route endpoints and drops legacy external links that point at
absolute locations or remotes.

Node kinds are open to any non-empty string. Known kinds are `feature`, `test`,
`library`, `ui`, `external`, `data`, `worker`, `infra`, `config`, `script` and
`service`. Older nodes may omit the kind. Link kinds are open to any string.
Known kinds are `import`, `http`, `queue`, `data`, `call` and `event`.
RepoIndex coverage reports other values as `unknown_node_kinds` and
`unknown_link_kinds`. Index output escapes these labels and redacts locations.

### Blueprint

A plan requires a `files` list whose entries have string `path`, `name` and
`description` fields. When supplied, `source` is a string, `stack` and
`assumptions` are lists of strings, and `questions` and `endpoints` are lists
of objects. Extra fields are ignored. Both readers discard source metadata,
absolute roots, remotes and prose. The blueprint index also drops fields such
as `uses` and endpoint details. Renderers escape retained text with `safe()`.

### Local file and Git limits

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
