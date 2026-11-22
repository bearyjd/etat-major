# Recorded Gradle dependencies and drift

```text
etat-major gradle deps --root DIR [--format text|json]
etat-major gradle drift --root DIR --graph FLOORPLAN_JSON [--trail TRAIL_JSON] [--format text|json]
```

The adapter reads scripts and recorded indexes as local data. It never runs
Gradle, a wrapper, build code, Git, or an indexer. It opens directories and
regular files without following symlinks. Settings and build scripts are
limited to 256 KiB each.
Discovery probes at most 5,000 settings and build file paths. Project paths,
comment nesting and delimiter nesting are limited to 64 levels.

## Declared dependencies

The settings file is required. For both settings and build scripts, the
`.gradle.kts` form takes precedence when both forms exist. Literal `include`
entries can span lines and end with a trailing comma. A project ID such as
`:core:data` maps to `core/data`. The root project ID is `:`, with an empty
directory string. The adapter reads the root build script when present and
probes the explicitly included projects. An included project can be a
container with no build script.

The supported override is `project(":app").projectDir = file("clients/app")`
with a simple repository-relative directory. Computed overrides, composite
builds, flat includes, custom build script names and dynamic includes are
outside the literal subset. The adapter reports recognized unsupported forms,
and skips projects whose directory override it cannot resolve.

In top-level `dependencies { ... }` blocks, literal project arguments can
use `project(":core:data")`, `project(path = ":core:data")`, Groovy
`project(path: ':core:data')`, or `projects.core.data`. The configuration can
use call or Groovy command syntax. Literal `add("configuration", ...)` calls
and `testFixtures(...)` wrappers also work. The accessor resolver builds
camel-case names from the included project IDs, so `projects.core.scanTesting`
can resolve to `:core:scan-testing`. Unresolved or ambiguous names produce a
diagnostic. Recognized dynamic project expressions are reported when they
cannot be resolved. The parser skips comments and quoted text. Declarations
supplied indirectly by convention plugins, applied scripts, shared closures,
or computed configurations can be absent from the result.

Each edge has `source` and `target` project IDs, `configuration`, a
repository-relative `file`, and the one-based `line` of the configuration
call. `test_only` marks configurations beginning with `test` or `androidTest`
and declarations wrapped in `testFixtures(...)`. Other configurations,
including build variants, keep their names verbatim. The same pair may have
multiple declarations.

## Drift

`drift` reads Floorplan file-to-file imports and optionally Trail calls and
extends edges with known symbol endpoints. Each recorded graph reader enforces
its own schema and limits, including a 64 MiB file cap for each input.
The comparison assigns each recorded file to
the longest matching non-root Gradle directory or Trail scope on a path
boundary. Unmatched files use the directory preceding `/src/` in conventional
source layouts, then the root project if available. Observed-only directories
use colon-separated IDs derived from their paths. A module can appear in the
observed set through an indexed file or a Trail scope even with zero edges.
Files without an applicable directory and within-module links do not
contribute dependency evidence.

Each directed pair appears in one of `declared_and_used`,
`declared_but_unused`, or `used_but_undeclared`. A row retains its
declarations and groups its observations by layer, relation, provenance and
confidence. `evidence_count` is the sum of those observations. Floorplan
imports carry `inferred` provenance. Trail retains its adapter provenance
and original confidence label. `modules_only_declared` and
`modules_only_observed` report project IDs in only one source.

The comparison is pair-level. Evidence does not establish that a specific
configuration or source set uses the dependency. An unused edge is a
candidate for review, including test-only edges that the recorded indexes may
not cover. An undeclared edge can indicate transitive usage or a declaration
the static parser could not resolve.

## Output

The [CLI JSON contract](cli-json.md) defines the common envelope and exit
codes. Gradle uses `0` for a complete read with no findings, `1` for partial
results or candidate drift, and `2` for invalid arguments or unusable
required inputs. A malformed build script is scoped to its project and
reported alongside remaining declarations. Each diagnostic identifies a file
or command and field. JSON uses the
[deps](schemas/gradle-deps.schema.json) and
[drift](schemas/gradle-drift.schema.json) version 1 schemas.
