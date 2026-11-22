# Trail adapter

`etat_major.trail.load_wiring(path, indexed_revision=None)` reads a local UTF-8
`wiring.json`. The adapter is pinned to the graph shape recorded from Trail
0.30.5 and requires the JSON integer `1` at `meta.version`. The input must be a
regular file of at most 64 MiB, reached through symlink-free directories. Invalid
artifacts raise `TrailError` with the basename and the failing field or `JSON`.

The immutable `SymbolIndex` contains node and edge tuples in graph order.
Nodes keep the ID, kind, repository-relative path and inclusive one-based start
and end lines from `L<start>-L<end>`. File IDs are their paths. Class,
function and method IDs use `<path>#<symbol>`. The reader keeps the metadata
needed for coverage and discards other fields, including source bodies and
repository metadata.

Edges retain the original source, target, relation and confidence strings.
An endpoint can identify an external target with no matching node.

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
  kind and edges by relation. `files_without_symbols` reports paths with a file
  node and no class, function or method node.
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
