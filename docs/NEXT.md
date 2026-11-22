# Handoff: current state and next tasks

Updated 2026-11-22. Keep this file under 60 lines; replace it, do not append. Rules are in `AGENTS.md` and `CLAUDE.md`.

## State
`main` has the design docs and a CLI over local and recorded data: trace, index (Floorplan architecture layer plus Trail symbol layer, joined by path), decisions, research brief/import (manual ChatGPT handoff), progress evidence from Git and recorded PR JSON, workspace validation, JSON output with schemas, and `gradle deps|drift`. No web UI, no live GitHub, Floorplan or Trail execution, no Codeman or Meute links. CI is green; the suite has about 800 tests at about 95% coverage.

## What the real-data proof-out established (details in `docs/FLOORPLAN-PROOF.md`)
- Floorplan's deterministic import links are useful; its model-written layer failed its accuracy target and blueprints are greenfield only. Use it as an optional provider of file-level import links, not as the source of truth for components.
- Trail's Kotlin `imports` edges do not resolve; its `calls` edges are name-matched and weak across modules. Trail also detects Gradle modules from `build.gradle.kts` and its output directory varies (`graft/` or `.trail/cache/`), so locate the file, do not assume the path.
- `gradle drift` on a real 33-module repo, after reading convention plugins and ranking by evidence: 102 declared-and-used, 37 implicit via plugins, 1 import-backed undeclared (hand-verified real), 4 unused candidates (hand-verified), the rest weak or test-only.

## Next tasks, in order
1. **Reviewed component model.** A Git-backed `components` file (id, label, module paths, owner, optional summary with `provenance`) with a loader and `etat-major components seed`, which proposes components from Gradle modules and Trail scopes. Done when a seeded file loads, a human-edited one is never overwritten, and every summary carries provenance.
**Subprocess exception for tasks 2 and 3 only:** each wrapper may exec exactly one external tool (`trail build`, or Floorplan's `scan`/`build`/`refresh` Node scripts) from one dedicated module, with a fixed argument list, no shell, a scrubbed environment (telemetry off, no credentials), a timeout, an output size cap, and only inside a throwaway copy or worktree supplied by the caller. Tests must use a fake executable; the real tool is run only by the maintainer or in the real-data smoke step. Anything else still follows the `AGENTS.md` ban.

2. **Trail runner wrapper.** Build Trail on a copy or worktree (telemetry off, never `trail init`), locate the output wherever it landed, check `meta.version`. Done when it works on a repo whose graph lands in `.trail/cache/` and on one that uses `graft/`.
3. **Floorplan runner wrapper.** Run only `scan`, `build` and `refresh` on a copy, pinned commit, no model steps, no viewer. Done when a refresh after a rename keeps component ids and reports the rename mapping.
4. **First read-only web screen** for the Understand view (needs a web dependency the maintainer must approve and install). Do not start before 1 to 3 are merged.
5. Real-data smoke script that runs every command on a real repository and compares counts with recorded expectations.

## Open questions
Quality and cost of a model-written component draft after the two misleading summaries are corrected; whether LikeC4 or Aalekh beat our own Git-backed model; Floorplan's `graph.json` has no stability promise (an open third-party issue has no reply); Codeman credential isolation before a second user.

## Local workflow (not in the repo)
The maintainer keeps a local runner that has Codex implement each unit in its own worktree, verifies with pytest and ruff, requires a separate reviewer's approval, and only then fast-forwards a local branch. It never pushes. Ask the maintainer for it; the specs for each unit live in its `units.sh`.
