# Tool evaluation: Floorplan, Trail, Understand Anything

Evaluated 2026-11-21 by reading source and running the deterministic parts on copies of real repositories. Nothing was installed globally, no credentials were used, and no model was called. **VERIFIED** means observed in code or by running a command. **UNVERIFIED** means not tested.

## Decision

Use two engines with distinct jobs, consumed read-only through adapters, and skip the third.

| Tool | Role in État-major | Why |
| --- | --- | --- |
| **Floorplan** | Architecture layer: components, files, imports, endpoints, flows, blueprints | Cross-language, wide and cheap to build; its map is the best entry point for "what exists". |
| **Trail** | Symbol layer: functions, classes, call and extends edges with confidence labels | Floorplan has no call edges and no per-edge confidence. |
| **Understand Anything** | Skip as an indexer. Optional, manual, advisory prose only | Its graph is LLM-assembled, not reproducible and costs model quota; it duplicates Trail. |

Two engines are justified only because each does something the other demonstrably cannot (see the matrix). If either gap closes, drop one. État-major never merges the two graphs into one authoritative graph; it keeps each layer and its provenance and joins them by file path.

## Floorplan 0.11.0 (MIT)

Source: https://github.com/haydenschmitty/floorplan

**VERIFIED**
- MIT license. First commit 2026-10-28; 230 commits and 12 releases in about three weeks; one author wrote most commits. About 6,000 stars. Pre-1.0 and moving fast.
- Zero dependencies and no install hooks. The Node scripts run straight from a clone (`node skills/floorplan/scripts/*.mjs <root>`). It is a Claude Code and Codex skill; the scripts do the mechanical work and an LLM writes the architecture layer.
- Scan and build need no model and no key. On a 5-file Python repo: about 0.4 s. On a 271-file Kotlin, Python, Rust and shell repo (39,655 lines): 13 nodes and 547 import edges in about 1.3 s.
- Outputs are plain JSON with schema markers: `graph.json` (`floorplan/graph@1`), `architecture.json` (`floorplan/architecture@1`, documented in the repo's `schema.md`), `plan.json` (`floorplan/plan@1`, documented in `blueprint.md`), `recent-work.json`. Every script has a `--json` mode with stable exit codes and a documented unattended workflow.
- `graph.json` has files (path, language, line count, symbols as attributes, content hash), nodes (components), routes, links (import, http, external) and a health section. It is **not** a documented contract: the shape is implied by the code. It holds an absolute root path and the repo remote; strip both before sharing.
- A rebuild of an unchanged tree gives identical output apart from timestamps. A refresh after an edit, add and rename took about 0.5 s and reported counts.
- Node ids for components come from `architecture.json` and are stable across refreshes. File ids are paths, so a rename changes the id. Route ids are positional (`r:<index>`) and not stable.

**Needs a model (not run)**
- `architecture.json` (component labels, summaries, flows, tour), per-file descriptions and `recent-work.json`. Without them the map has directory-level components and files named automatically (`auto: true`). Cost is whatever the host agent session bills. The quality of an LLM-written map is **UNVERIFIED**.
- The viewer and its "Ask" bar (`serve.mjs`, which can call `claude -p` or `codex exec`) were never run. État-major does not use them.

**Blueprints (VERIFIED on a copy)**
- A blueprint is a separate graph. It contains only the planned files and cannot reference existing code, so a feature cannot be drawn on top of the current map. Planned files carry no `planned` flag.
- After a stub of a planned file was added, a refresh in blueprint mode ignored the code, and `--from-code` switched to a plain code map in which planned-only files read as deleted.
- The `f:<path>` ids are the same in both graphs, so a diff on them yields planned-only, built and existing. **That planned-versus-built overlay has to be computed by État-major's adapter.**

**Gaps**
- No call edges; symbols are attributes of a file, not nodes with ids. Regex-based, not compiler-grade. No per-edge confidence beyond an `inferred` flag on http links.
- Health checks (secrets, endpoint auth) did nothing useful on the samples.
- Multi-repository behaviour and `recent.mjs` output: **UNVERIFIED**.

## Trail 0.30.5 (MIT)

See [VISUALIZATION-ARCHITECTURE.md](VISUALIZATION-ARCHITECTURE.md) for the full notes. In short, **VERIFIED**: a deterministic tree-sitter graph (`wiring.json`, version 1). On this repo it produced 66 nodes (functions 48, classes 8, files 5, methods 5) and 167 edges (calls 82, contains 61, imports 17, extends 7), each edge with a confidence (`extracted` 132, `inferred` 35), in about 2 s. Ids are `path#symbol`. Pre-1.0, no documented schema-compatibility promise.

## Understand Anything 2.9.8 (MIT)

Source: https://github.com/Egonex-AI/Understand-Anything

**VERIFIED**
- A Claude Code plugin (also Codex and others). `/understand` is a long prompt that orchestrates about a dozen LLM subagents. About 93,000 stars; 442 commits since 2026-04-19.
- Its deterministic scripts (file scan, import map, per-file structure) ran in under a second on a copy of this repo: 47 functions, 8 classes, call names scoped to one file. They are intermediate steps, not a graph.
- The final graph (`.ua/knowledge-graph.json`: 27 node types, 38 edge types, weights 0 to 1, layers, tour) is **assembled by an LLM**. There is no command that produces it without a model. Cross-file `calls` edges are LLM-inferred, so node and edge sets differ between runs.
- Source is sent to whichever model the host agent uses.
- Path-based ids are stable.

**UNVERIFIED:** a full run and its token cost.

**Recommendation:** skip as an indexer. If summaries, tours or a domain view are wanted, run it manually and read `.ua/knowledge-graph.json` read-only, joined to Trail on `function:<path>:<name>`, labelled `ai-generated`.

## Capability matrix

| Capability | Floorplan | Trail | Understand Anything |
| --- | --- | --- | --- |
| Components and architecture layer | Yes (LLM-written, curated) | No | LLM-assigned layers |
| Files, imports across languages | Yes, regex | Imports per supported language | LLM-assembled |
| Function and class nodes with ids | No (symbols are file attributes) | Yes | LLM-assembled |
| Call edges | No | Yes, with confidence | LLM-inferred, numeric weight |
| HTTP endpoints and routes | Yes | No | No |
| Planned-software blueprints | Yes (greenfield only) | No | No |
| Recent-work highlighting | Yes | No | No |
| Deterministic and reproducible | Yes (mechanical layer) | Yes | No |
| Needs a model | For architecture layer and descriptions | No | For the graph itself |
| Prose summaries and tours | Some | No | Yes, its unique value |

## Integration design

État-major reads artifacts; it does not run the model-backed steps.

1. **Floorplan adapter.** Reads `graph.json` (and `plan.json`, `architecture.json`). Accepts only `floorplan/graph@1`; any other schema string fails with a clear error. Pin a Floorplan commit and parse a recorded fixture in CI. The adapter may invoke the deterministic `scan`, `build` and `refresh` scripts on a copy or worktree. It never runs the LLM steps, `serve.mjs` or the Ask bar. The architecture layer is produced by a human or by an agent the human started (in Codeman or Meute), then read as a local cache; a human may commit an approved `architecture.json` to Git.
2. **Trail adapter.** As described in the architecture document.
3. **Join.** Both layers are keyed by repository-relative file path, with a revision SHA. Floorplan `f:<path>` ids and Trail `path#symbol` ids share the path prefix.
4. **Metadata sidecar.** Feature, milestone and research links live in État-major's own files and point at `n:<component>` or `f:<path>` ids. Floorplan's own `annotations` are not used.
5. **Rename reconciler.** Because file ids are paths, a reconciler maps old paths to new ones between runs (Git rename detection) so links survive moves.
6. **Planned versus built overlay.** Diff the blueprint's `f:` ids against the current code map: planned-only, built, existing.
7. **Safety.** Strip the absolute root and remote from imported data; treat all text as untrusted when rendering.

## Open uncertainties

- Quality and stability of an LLM-written Floorplan architecture layer, and what it costs per refresh.
- Whether Floorplan's schema stays stable; there is no compatibility policy.
- Whether Trail's call edges can be reconciled with Floorplan's components cleanly on a multi-language repository.
- Floorplan multi-repository behaviour and the viewer.
