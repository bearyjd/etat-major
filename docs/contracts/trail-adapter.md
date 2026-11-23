# Trail adapter

`etat_major.trail.load_wiring(path, indexed_revision=None)` reads a local UTF-8
`wiring.json`. The adapter is pinned to the graph shape recorded from Trail
0.30.5 and requires the JSON integer `1` at `meta.version`. The input must be a
regular file of at most 64 MiB, reached through symlink-free directories. Invalid
artifacts raise `TrailError` with the basename and the failing field or `JSON`.

The immutable `SymbolIndex` contains node and edge tuples in graph order.
Nodes keep the ID, kind, repository-relative path and inclusive one-based start
and end lines from `L<start>-L<end>`. The recognized kinds are `file`, `class`,
`function`, `method`, `interface`, `type`, `enum`, `struct`, `trait`, `module`,
`constant` and `variable`. File IDs are their paths. Other recognized kinds
use `<path>#<symbol>`, including Kotlin names with spaces inside backticks.
Unknown kind labels are retained, set `unknown_kind` on the node and appear
in `coverage.unknown_kinds`. Unknown kinds can use either ID form.
The reader discards unused fields, including source bodies and repository
metadata. The joined JSON snapshot uses `unknown` for kind labels that cannot
be printed safely.

Edges retain the original source, target, relation and confidence strings.
An import can reference an external target with no matching node. The adapter
keeps the edge and counts it as unresolved, preserving the given confidence
and provenance.

| Confidence | Provenance |
| --- | --- |
| `extracted`, `lsp_resolved` | `verified` |
| `inferred`, `lsp_dispatch` | `inferred` |
| Any other string | `inferred`, with `unknown_confidence` set |

The recognized relations are `calls`, `contains`, `imports`, `extends`,
`references` and `implements`. Other values set `unknown_relation` and
participate in relation counts under their original labels.

- `symbols_in(path)` returns all nodes with that exact path, including a file
  node if present. `has_symbol(id)` checks for an exact node ID.
- `callers(id)` and `callees(id)` return incoming and outgoing `calls`
  edges, respectively. Results include confidence and provenance and cover one hop.
- Coverage uses `meta.languages` (empty if absent) and counts actual nodes by
  kind and edges by relation, including unrecognized labels.
  `coverage.unresolved_relations` counts edges by relation whose target ID
  has no matching node. These edges also contribute to the total relation counts.
  `files_without_symbols` reports paths with a file node and no other kind of node.
- `module_scopes` on the index and its coverage contains the ordered tuple of
  repository-relative prefixes from `meta.scopes[].prefix`, including Gradle
  modules. An empty prefix denotes the repository root. If `meta.scopes` is
  absent, the tuple is empty. Scope labels and markers are ignored.
- `freshness(current_revision)` compares the two caller-supplied revision
  strings. Equal revisions are `fresh`, different revisions are `stale`,
  and a missing revision gives `unknown`. The reader performs no Git lookup.

```sh
etat-major trace feature:netlens/0031 --workspace workspace --trail wiring.json
```

`trail:<path>#<symbol>` links are `unverified` without `--trail`. With a
supplied graph, present symbols are `built` for `new` links and `existing`
for `modifies` or `uses`. Missing symbols are `gap` for `new` and `stale`
for `modifies` or `uses`. These states describe the supplied snapshot.
`--graph` can also be supplied to resolve Floorplan links. An invalid or
unreadable Trail graph gives CLI exit code 2.

## Building a fresh local graph

The Python API wraps the pinned Trail 0.30.5 executable. Supply a separate
disposable copy or Git worktree and keep it exclusively available to the runner
until the call finishes. Use a disposable tree free of mounted or aliased
subtrees, including same-filesystem bind mounts. Its parent must be writable
so the runner can create an isolated sibling directory. Pass the original checkout as
`source_root` and the absolute path of the trusted installed Trail executable as
`executable`. If Node or Git is outside the system search path, pass the required
trusted directories in `runtime_path`, separated by the platform's PATH
separator.

```python
from pathlib import Path

from etat_major.trail_runner import run_trail

result = run_trail(
    Path("/tmp/project-index-copy"),
    source_root=Path("/work/project"),
    executable=Path("/opt/trail/bin/trail"),
)
```

The runner invokes `trail build` in structural mode, disables telemetry
and ignore-file updates, and gives Trail a temporary home outside both
checkouts. Trail's Git subprocesses use temporary Git metadata generated
by the runner in that directory. The
checkout's Git configuration, index and linked worktree metadata are outside
that Git context. Git applies the checkout's ignore rules as it would for
untracked files, so tracked files that match ignore rules can be missing from
the graph. The runner disables worktree cache seeding and traversal of
submodules and nested repositories.

The installed 0.30.5 package defines `--deep` and `--lsp` as opt-in
switches without defaults (`dist/cli.js:451`, `dist/cli.js:462`). The build
handler derives model processing from `opts.deep` and passes `opts.lsp`
directly to the graph engine (`dist/cli.js:570`, `dist/cli.js:632–638`).
The engine constructs a model summarizer only when `opts.llm` is truthy
(`dist/engine.js:60–68`), and the graph starts language-server enrichment
only when `opts.lsp` is truthy (`dist/graph/build.js:309`). The checkout's
persisted build configuration is consulted for traversal choices
(`dist/graph/build.js:136–140`). It does not supply either switch.
The runner omits both switches. Recheck these defaults when upgrading the
pinned executable.

The runner rejects workspace builds, symlinks and special files in the
disposable tree. It caps build time at 120 seconds and combined subprocess
output at 2 MiB. It signals the invocation's process group before reaping
the leader. This covers subprocesses that stay in the group. If group
signaling fails while the leader still runs, the runner attempts to signal it
directly. The runner waits up to one additional second to reap the process.
A timeout or output failure remains the primary error if cleanup also
fails. A cleanup failure after an otherwise successful build is reported
as a cleanup error. Build diagnostics omit subprocess output.

`result.artifact` is the checkout-relative path of the fresh artifact, either
`graft/.graph/wiring.json` or `.trail/cache/.graph/wiring.json`. `result.index`
contains the loaded, version-checked symbol index. A failed or missing build
raises `TrailRunError`. Invalid graph data raises `TrailError`.
