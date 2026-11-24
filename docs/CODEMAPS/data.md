<!-- Generated: 2026-11-23 | Files scanned: 47 | Token estimate: ~900 -->
# Data: no database, on-disk contracts

Git holds intent (Markdown + YAML frontmatter); recorded JSON/YAML are read-only inputs; no cache is authoritative. Reads go through `localfiles.read_text(path, MiB)` / `read_text_kib(path, KiB)` (dir-fd, regular files, size cap, no symlink following).

| Input | Loader (module.function) | Cap verified in code | Contract doc |
|-------|--------------------------|----------------------|--------------|
| Floorplan `graph.json` (+ architecture doc) | floorplan.load_graph, load_graph_recording (pin FLOORPLAN_COMMIT) | 64 MiB | contracts/floorplan-adapter.md |
| Trail `wiring.json` | trail.load_wiring, load_wiring_recording | 64 MiB | contracts/trail-adapter.md |
| `prs.json`, `releases.json` | evidence_records.load_prs, load_releases | 4 MiB; recorded-array checks | contracts/progress-evidence.md |
| local git repo | evidence_git.load_git (via renames._git_result) | git output 16 MiB | progress-evidence.md |
| Meute snapshot YAML | meute.load_meute, resolve_meute | 256 KiB; 256 report rows | contracts/meute-recording.md |
| Manual review YAML | manual_review.load_manual_review | 8 KiB | contracts/manual-review.md |
| Execution links YAML | execution_links (pydantic, per project) | 64 KiB; 256 rows | contracts/execution-links.md |
| Component model YAML | components.load_component_workspace/load_components | 1 MiB; 500 components, 1000 paths, id lengths 128/256 | contracts/components.md |
| Intent workspace (features, decisions, research, tasks, milestones, vision) | workspace.load_workspace; records.py, taskfile.py, planning.py parse files | 1 MiB per file; 2000 dir entries; 200 issues (unless validate_all) | contracts/task-file.md (+ task-file.schema.json), research-answer-format.md |
| Gradle settings/build scripts, version catalog | gradle.load_dependencies (gradle_settings/_parse/_plugins) | 256 KiB per script; depth 64; 5000-file probe; 1000 plugin entries; 32 composition depth | contracts/gradle-adapter.md |
| Pasted research answer | research_import.import_answer | read_text cap; writes new unreviewed artifact | research-answer-format.md |

## Outputs
- `--format json`: envelope from `cli_json.json_result`; schemas in `docs/contracts/schemas/*.schema.json` (trace, index, progress, decisions-list, workspace-validate, gradle-deps/drift, components-*); doc `contracts/cli-json.md`.
- Repo index shape: `contracts/repo-index.md` (`repo_index.RepoIndex`).
- Runner outputs (inside the supplied copy): Floorplan `floorplan/.cache/scan.json`, `floorplan/architecture.json`; Trail wiring via `trail_runner`.

## Other limits
- Understand: source excerpt 256 KiB, page 256 KiB, 25 rows per list page (docs/LIMITS.md; 64 MiB behavior unmeasured).
- Runners: Floorplan copy 25,000 entries, 64 MiB file limit, 1 MiB output, 60 s; Trail 100,000 tree entries, depth 64, 2 MiB output, 120 s.
- Stored task statuses only `draft|ready|blocked|done` (CLAUDE.md); other states derived.
- Fixtures: `tests/fixtures/`; examples: `docs/examples/*.json`; pins: `pins.toml`.
