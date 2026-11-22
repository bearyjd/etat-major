# Reviewed component model

Store one version 1 YAML file per project at `components/PROJECT.yaml` in the
workspace. The filename stem and `project` agree. Git stores the declarations
reviewed by the maintainer. Floorplan file paths and Trail module scopes
supply evidence for coverage and proposals.

```yaml
version: 1
project: example
components:
  - id: feature
    label: Features
    kind: group
    paths: []
  - id: feature.ping
    label: Ping
    parent: feature
    kind: module
    paths: [feature/ping]
    owner: Networking
    summary:
      text: Reports round-trip latency.
      provenance: human
      reviewed_by: Architecture maintainer
      reviewed_on: 2026-11-22
```

IDs consist of one or more dot-separated lowercase segments. Each segment
starts with a lowercase letter or digit and can also contain underscores
and hyphens. IDs are unique within the project. A parent must name a component
in the same model, and parent links must be acyclic. A component may declare
an empty `paths` list when it has children. The `kind` field accepts any
nonempty string. `parent`, `owner` and `summary` are optional.

A summary always has text and one provenance value from `human`,
`ai-generated`, `inferred` and `verified`. A person may attest to review of
any summary by providing both a nonblank `reviewed_by` and an ISO calendar
date `reviewed_on`. This attestation leaves the original provenance intact.
The loader preserves these values when supplied. Seed proposals omit summaries
and review fields.

## Ownership

A literal directory matches itself and its descendants at a slash boundary.
Globs match the entire repository-relative path. Within one segment, `*`
matches any number of characters, `?` matches one character, and bracket
expressions match a character class. A segment consisting of `**` matches
zero or more whole segments. Matching is case-sensitive.

Paths follow the `fp:f:` path rules, with colons also disallowed. Use
nonempty slash-separated segments and omit dot and parent segments, leading
home or drive prefixes, whitespace, backslashes, percent signs, hash signs,
Unicode slash lookalikes and control characters. Queries for actual files
allow spaces. The matching declaration with the longest literal prefix
before the first wildcard wins. An equal score across different components
reports a tie and leaves the file unowned. Sibling declarations that can
match a common path produce a warning, including siblings at the root.

Coverage partitions unique recorded Floorplan paths into sorted owned and
unowned lists. It divides owned files by the input count and multiplies by
100. Empty input reports zero percent. Parents appear nearest first.

## Validation and proposals

The [JSON Schema](schemas/components.schema.json) describes the decoded
YAML. The loader checks cross-component constraints and enforces limits of
1 MiB, 32 YAML nesting levels, 20,000 YAML events, 500 components and 1,000
total path declarations. It rejects duplicate YAML keys, aliases, symlinks
and models that exceed the sibling-glob overlap work limit.

```sh
etat-major components validate --workspace workspace
etat-major components map --workspace workspace --project example --path feature/ping/Ping.kt
etat-major components coverage --workspace workspace --project example --graph graph.json
etat-major components seed --root repo-dir --project example --trail wiring.json --out workspace/components/example.yaml
etat-major components seed --root repo-dir --project example --proposal-for workspace/components/example.yaml
```

Seed reads Gradle settings and build scripts as text and optionally uses
recorded Trail `module_scopes`. It groups nested modules by their first
directory segment and marks proposed entries with `inferred_from_gradle` and
a review comment. Both output modes require a new destination. The
`--proposal-for` option writes `EXISTING_FILE.proposed` with only missing
components, for manual review and merge. A delta can reference a parent
already present in the existing file.

Use `component:PROJECT/ID` in a Feature ArchitectureLink. Pass
`etat-major trace --components DIR_OR_FILE` to resolve a link against these
declarations. See the [CLI JSON contract](cli-json.md) for output formats.
