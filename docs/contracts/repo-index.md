# RepoIndex export, version 1

`etat-major index --graph graph.json --trail wiring.json [--format json|text]`
reads a Floorplan `floorplan/graph@1` artifact and a Trail `meta.version: 1`
artifact. Text is the default. Exit code 0 includes snapshots with coverage
gaps. Exit code 2 reports an invalid or unreadable artifact by basename and
field. Both inputs must be regular UTF-8 files reached without symlinks, each
at most 64 MiB.

The input pair should come from the same repository and source revision. The
repository ID comes from Floorplan's `project` field when present. Use
`--revision SHA` and `--indexed-at TIMESTAMP` to supply the pair's full
lowercase Git SHA and RFC 3339 index time. The CLI exports `null` for unknown
metadata. Python callers can supply the same values with
`load_repo_index(graph_path, trail_path, revision=..., indexed_at=...)`.
The loader normalizes the time to UTC. The caller supplies the evidence that
both artifacts describe that revision. Indexer pins describe the adapter
targets maintained in `pins.toml`, with `human` provenance. The loader
checks each wire schema.

## JSON shape

```json
{
  "version": 1,
  "repository": "example-service",
  "revision": null,
  "indexed_at": null,
  "indexers": [
    {
      "layer": "architecture",
      "name": "floorplan",
      "provenance": "human",
      "schema": "floorplan/graph@1",
      "commit": "94f81b463b7617e06d873ac71323ce71644c8399",
      "version": null
    },
    {
      "layer": "symbols",
      "name": "trail",
      "provenance": "human",
      "schema": null,
      "commit": null,
      "version": "0.30.5"
    }
  ],
  "coverage": {
    "languages": ["python"],
    "files_indexed": 2,
    "files_skipped": null,
    "architecture_only": ["app/main.py"],
    "symbols_only": []
  },
  "architecture": {
    "components": [
      {"id": "service", "kind": "dir", "layer": "architecture", "provenance": "inferred"}
    ],
    "files": [
      {
        "path": "app/main.py", "component_id": "service", "language": "python",
        "lines": 12, "layer": "architecture", "provenance": "verified"
      },
      {
        "path": "lib/health.py", "component_id": "service", "language": "python",
        "lines": 8, "layer": "architecture", "provenance": "verified"
      }
    ],
    "links": [
      {
        "source": "f:app/main.py", "target": "f:lib/health.py", "kind": "import",
        "layer": "architecture", "provenance": "inferred"
      }
    ],
    "routes": [
      {
        "id": "r:0", "method": "GET", "path": "/health", "file": "app/main.py",
        "layer": "architecture", "provenance": "inferred"
      }
    ],
    "modules": [
      {
        "path": "app", "imports": ["lib"], "kind": "module",
        "layer": "architecture", "provenance": "inferred"
      },
      {
        "path": "lib", "imports": [], "kind": "module",
        "layer": "architecture", "provenance": "inferred"
      }
    ]
  },
  "symbols": {
    "nodes": [
      {
        "id": "lib/health.py", "kind": "file", "path": "lib/health.py",
        "range": [1, 8], "layer": "symbols", "provenance": "verified"
      },
      {
        "id": "lib/health.py#check", "kind": "function", "path": "lib/health.py",
        "range": [2, 8], "layer": "symbols", "provenance": "verified"
      }
    ],
    "edges": [
      {
        "from": "lib/health.py", "to": "lib/health.py#check", "relation": "contains",
        "confidence": "extracted", "layer": "symbols", "provenance": "verified"
      }
    ]
  }
}
```

- `architecture.files[].path`, `architecture.routes[].file` and
  `symbols.nodes[].path` use repository-relative paths. A route's `path`
  is the HTTP endpoint path. Route IDs are local to the Floorplan artifact.
  A component's `kind`, a file's `component_id`, `language` and `lines`, and
  a route's `file` are nullable when the artifact omits them.
- Each module groups Floorplan files by their immediate directory, with `.`
  for repository-root files. Its `imports` are unique outbound directories
  from inter-directory Floorplan file imports.
- Trail ranges are inclusive and one-based. Symbol IDs use
  `path#qualified.name`. File node IDs are paths. Edge endpoints can also
  name an external symbol. Trail's relation and confidence labels retain
  their original spelling. `extracted` and `lsp_resolved` map to `verified`
  provenance. Other confidence labels map to `inferred`.
- `files_indexed` counts the union of both layers' paths, including Trail
  file nodes without symbols and paths supplied only by a Trail symbol.
  `files_skipped` is `null` because the artifacts do not inventory all files
  in the source tree. `languages` is the union of the declared languages.
- JSON object keys and graph records have stable sort orders. Components
  and routes sort by ID, files and modules by path, and Floorplan links by
  source, target and kind. Trail nodes sort by ID, line range and kind. Trail edges
  sort by endpoints, relation and confidence. Coverage paths, languages and
  outbound module directories sort lexically.
- The loader drops tool roots, remote URLs, external Floorplan links,
  free-form descriptions and source bodies. It bounds disk reads and
  escapes unsafe display characters in text and JSON.

`files_with_symbols()` returns Floorplan file records whose paths have at
least one Trail function, class or method. `symbols_for_component(id)` returns
those Trail nodes for the files owned by that component. `component_of(path)`
returns the Floorplan component or `None`. These queries use exact path matches
and retain the provenance of each record.
