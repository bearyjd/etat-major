# Recorded Gradle dependencies and drift

```text
etat-major gradle deps --root DIR [--format text|json]
etat-major gradle drift --root DIR --graph FLOORPLAN_JSON [--trail TRAIL_JSON] [--format text|json] [--verbose]
```

The adapter reads scripts and recorded indexes as local data. It never runs
Gradle, a wrapper, build code, Git, or an indexer. It opens directories and
regular files without following symlinks. Settings, build scripts, convention
sources and the version catalog are limited to 256 KiB each.
Discovery probes at most 5,000 settings and build file paths. Project paths,
directory depth, comment nesting and delimiter nesting are limited to 64 levels.
Convention discovery has a separate budget of 1,000 directory entries and
follows up to 32 plugins along a composition path.

## Declared dependencies

The settings file is required. For both settings and build scripts, the
`.gradle.kts` form takes precedence when both forms exist. Literal `include`
entries can span lines and end with a trailing comma. A project ID such as
`:core:data` maps to `core/data`. The root project ID is `:`, with an empty
directory string. The adapter reads the root build script when present and
probes the explicitly included projects. An included project can be a
container with no build script.

The supported override is `project(":app").projectDir = file("clients/app")`
with a simple repository-relative directory. The adapter reads literal
`includeBuild("dir")` directives at the top level and in `pluginManagement`.
It ignores repository declarations, `dependencyResolutionManagement`,
`enableFeaturePreview`, and `rootProject.name`.
Computed overrides, flat includes, custom build script names and dynamic
includes produce diagnostics when recognized. The adapter skips projects
whose directory override it cannot resolve.

In top-level `dependencies { ... }` blocks, literal project arguments can
use `project(":core:data")`, `project(path = ":core:data")`, Groovy
`project(path: ':core:data')`, or `projects.core.data`. The configuration can
use call or Groovy command syntax. Literal `add("configuration", ...)` calls
and `testFixtures(...)` wrappers also work. The accessor resolver builds
camel-case names from the included project IDs, so `projects.core.scanTesting`
can resolve to `:core:scan-testing`. Unresolved or ambiguous names produce a
diagnostic. Recognized dynamic project expressions are reported when they
cannot be resolved. The parser skips comments and nonliteral expressions.

Each edge has `source` and `target` project IDs, `configuration`, a
repository-relative `file`, and the one-based `line` of the configuration
call. `test_only` marks configurations beginning with `test` or `androidTest`
and declarations wrapped in `testFixtures(...)`. Other configurations,
including build variants, keep their names verbatim. The same pair may have
multiple declarations.

### Convention plugins

Literal, repository-contained included builds can supply convention plugins.
The adapter reads `gradlePlugin { plugins { ... } }` registrations using
`register("name")` or `create("name")` with literal `id` and
`implementationClass`, then looks for the registered classes under
`src/main` in the included build. It recognizes literal `add("configuration",
project(":module"))`, `"configuration"(project(":module"))` and
`configuration(project(":module"))` declarations inside `dependencies` blocks.
It follows literal `pluginManager.apply("id")` and `apply(plugin = "id")`
composition with cycle and depth guards. Modules apply these plugins through
`id("id")`, `apply(plugin = "id")`, or `alias(libs.plugins.name)` mapped through
`gradle/libs.versions.toml`.

`deps` JSON adds the optional `implicit_edges` array. Each entry keeps the
normal declaration fields and adds `implicit: true`, `plugin_id` and
`plugin_class` for the plugin that contains the declaration. `file` and `line`
point to the declaration in that class. Literal explicit edges retain their
shape in `edges`.

Symlinked or external included builds are refused. Recognized unsupported
constructs and unreadable convention inputs produce non-blocking warnings
with a file, field and line. Dynamic plugin logic, precompiled script plugins,
applied scripts and shared closures can leave declarations unobserved.

## Drift

`drift` reads Floorplan file-to-file imports and optionally Trail calls and
extends edges with known symbol endpoints. Each recorded graph reader enforces
its own schema and limits, including a 64 MiB file cap for each input.
The comparison assigns each recorded file to the longest matching non-root
Gradle directory or Trail scope on a path boundary. Unmatched files use the
directory preceding `/src/` in conventional
source layouts, then the root project if available. Observed-only directories
use colon-separated IDs derived from their paths. A module can appear in the
observed set through an indexed file or a Trail scope even with zero edges.
Files without an applicable directory and within-module links do not
contribute dependency evidence.

Each directed pair appears in one of `declared_and_used`, `declared_implicit`,
`declared_but_unused`, `used_but_undeclared`, or `call_only`. `declared_implicit`
contains observed pairs supplied entirely by convention plugins. A row retains its
declarations and groups its observations by layer, relation, provenance and
confidence. `evidence_count` is the sum of those observations. Floorplan
imports carry `inferred` provenance. Trail retains its adapter provenance
and original confidence label. `modules_only_declared` and
`modules_only_observed` report project IDs in only one source.

The comparison is pair-level. Each row includes a `tier`, numeric `rank`
(1 is strongest), and a `reasons` list. Undeclared pairs are ranked by evidence.

| Tier | Rank | Evidence |
| --- | ---: | --- |
| `import_backed` | 1 | At least one Floorplan file import from a non-test source path |
| `test_only` | 2 | Every evidence source has a `test`, `androidTest`, or `testFixtures` path segment |
| `call_only` | 3 | A non-test Trail call or extends edge without a non-test Floorplan import |

A test-path import paired with a production Trail call remains weak. Trail
call and extends observations can be name matches, so `call_only` pairs are
reported separately from `used_but_undeclared`.

`declared_but_unused` has two tiers. `unused_candidate` (rank 1) requires
an explicit production `implementation` or `api` declaration and zero
observations. Otherwise `build_time_configuration` (rank 3) covers implicit
dependencies and other configurations, including `baselineProfile`, `ksp`,
`kapt`, `annotationProcessor`, `runtimeOnly`, `compileOnly`, `lintChecks`,
`debugImplementation` and `releaseImplementation`.

## Output

The [CLI JSON contract](cli-json.md) defines the common envelope and exit
codes. Gradle uses `0` for a complete read, `1` for partial results or
candidate drift, and `2` for invalid arguments or unusable required inputs.
The `candidate dependency or module differences` warning requires an
`import_backed` or `unused_candidate` pair. Module-only differences are
advisory. Convention plugin warnings alone preserve exit `0` and `ok: true`.
Unsupported explicit declarations and unresolved references are warnings and
can yield partial results. A malformed or unreadable module build script
produces an error scoped to its project alongside the remaining declarations. Each diagnostic identifies
a file or command and field. JSON uses the
[deps](schemas/gradle-deps.schema.json) and
[drift](schemas/gradle-drift.schema.json) version 1 schemas. Drift JSON includes
every pair and a `summary` with counts by tier and counts for module-only differences. The text
report starts with those counts. Use `--verbose` to show the weak pair details.
